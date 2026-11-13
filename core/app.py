"""Core service: MQTT ingest, REST and WebSocket (plan 3.5 API layer).
uvicorn core.app:app --port 8000
Env: AURA_DB (default core.db), AURA_MQTT_HOST (default localhost), AURA_MQTT_PORT (default 1883),
AURA_MODEL_URL (default http://localhost:8001).
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

import paho.mqtt.client as mqtt
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from contract.schema import Reading, load_limits, load_presets, load_signals, load_thresholds, model_signals
from core import domain, model_client
from core.store import Store

log = logging.getLogger("aura.core")
store: Store
mqtt_client: mqtt.Client
sockets: set[WebSocket] = set()
_status_lock = threading.Lock()  # one status at a time: a stale overlapping one could reopen a closed alert


def ingest(payload: bytes | str, topic: str | None = None) -> Reading | None:
    """Validate and store one message. A bad message is logged to `reject` and dropped (FR-2, NFR-2)."""
    try:
        r = Reading.model_validate_json(payload)
        if r.signal not in {s["name"] for s in load_signals()}:
            raise ValueError(f"unknown signal {r.signal!r}")
        if not math.isfinite(r.value):
            raise ValueError("value is not finite")
    except Exception as e:  # noqa: BLE001
        text = payload.decode(errors="replace") if isinstance(payload, bytes) else payload
        log.warning("rejected message on %s: %s", topic, e)
        store.reject(topic, text, str(e))
        return None
    store.add(r)
    return r


def mission() -> dict:
    if (row := store.mission()) is None:
        set_preset("station")
        row = store.mission()
    return {"name": row["preset"], "preset": load_presets()[row["preset"]], "limits": load_limits()}


def set_preset(name: str) -> None:
    p = load_presets()[name]
    store.set_mission(name, p["one_way_delay_s"], p["dose_mgy_day"])


def anomaly(crew_id: str, latest: dict, base: dict, now: datetime) -> dict:
    """FR-14: model score over up to 14 days of z-scores; optional, never blocks the rule alerts."""
    if not base:
        return {"available": False, "reason": "baseline not ready"}
    first = datetime.fromisoformat(store.span(crew_id)[0])
    n = min(14, (now - first).days + 1)
    snaps = [latest] + [store.latest(crew_id, (now - timedelta(days=k)).isoformat()) for k in range(1, n)]
    window = domain.model_window(snaps, base, model_signals())
    return model_client.score(crew_id, window)


def latest_ts(latest: dict) -> str:
    return max(r["ts"] for r in latest.values())


def baselines(crew_id: str, cfg: dict) -> dict[str, tuple[float, float]]:
    """Stored baselines; a signal's baseline is computed and saved once its window has passed (plan 3.6:
    "baseline ready?"). Daily signals use baseline_days, weekly labs lab_baseline_days so they get enough samples."""
    stored = store.baselines(crew_id)
    labs = {s["name"] for s in load_signals() if s.get("interval_days", 1) > 1}
    for days, wanted in ((cfg["baseline_days"], lambda n: n not in labs), (cfg["lab_baseline_days"], labs.__contains__)):
        window = store.baseline_window(crew_id, days)
        new = {n: b for n, v in window.items() if wanted(n) and n not in stored and (b := domain.baseline(v))}
        if new:
            store.save_baselines(crew_id, new, days)
            stored |= new
    return stored


def crew_status(crew_id: str) -> dict | None:
    with _status_lock:
        return _crew_status(crew_id)


def _crew_status(crew_id: str) -> dict | None:
    latest = store.latest(crew_id)
    if not latest:
        return None
    cfg = load_thresholds()
    now = datetime.fromisoformat(latest_ts(latest))
    history = [store.latest(crew_id, (now - timedelta(days=k)).isoformat())
               for k in range(1, domain.history_days(cfg) + 1)]
    base, m = baselines(crew_id, cfg), mission()
    s = domain.status(crew_id, latest, base, cfg, load_signals(), history, m,
                      store.total(crew_id, "dose_mgy"), anomaly(crew_id, latest, base, now))
    for alert_id, a in store.sync_alerts(crew_id, s["alerts"], s["ts"]):  # FR-16: each new alert goes to the ground
        store.queue_report(crew_id, alert_id, {
            "crew_id": crew_id, "ts": s["ts"], "alert": a["name"], "level": a["level"], "signals_fired": a["fired"],
            "systems": s["systems"], "mission": m["name"], "disclaimer": domain.DISCLAIMER},
            time.time(), m["preset"]["one_way_delay_s"])
    patterns = {p["id"]: p for p in cfg["patterns"]}
    signal_alert = {a["signal"]: a for a in s["alerts"] if a["id"] is None}
    s["alerts"] = [(patterns.get(r["pattern_id"]) or signal_alert.get(r["signal"]) or {
        "id": None, "signal": r["signal"], "name": f"{r['signal']} red", "rule": cfg["thresholds"].get(r["signal"]),
        "response": domain.with_response({"band": "red"}, r["signal"], cfg).get("response")}) | {
        "alert_id": r["id"], "level": r["level"], "fired": json.loads(r["signals_fired"]), "started_ts": r["ts"],
        "last_ts": r["last_ts"], "active": bool(r["active"]), "acknowledged_at": r["acknowledged_at"],
        "action": m["preset"]["alert_wording"]}  # FR-13: the same alert reads differently far from Earth
        for r in store.open_alerts(crew_id) if r["pattern_id"] is None or r["pattern_id"] in patterns]
    return s


async def broadcast(crew_id: str) -> None:
    msg = crew_status(crew_id)
    for ws in list(sockets):
        try:
            await ws.send_json(msg)
        except Exception:  # noqa: BLE001  a dead socket must not stop the others
            sockets.discard(ws)


def start_mqtt(loop: asyncio.AbstractEventLoop) -> mqtt.Client:
    # fixed id + clean_session=False: the broker keeps QoS 1 messages while the service restarts (NFR-3)
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="aura-core", clean_session=False)
    c.on_connect = lambda client, *_: client.subscribe("aura/+/+", qos=1)

    def on_message(_c, _u, m):
        try:
            if r := ingest(m.payload, m.topic):
                asyncio.run_coroutine_threadsafe(broadcast(r.crew_id), loop)
        except Exception:  # noqa: BLE001
            log.exception("ingest failed")

    c.on_message = on_message
    c.connect_async(os.environ.get("AURA_MQTT_HOST", "localhost"), int(os.environ.get("AURA_MQTT_PORT", 1883)))
    c.loop_start()  # reconnects by itself; the API starts even with no broker
    return c


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global store, mqtt_client
    store = Store(os.environ.get("AURA_DB", "core.db"))
    mqtt_client = start_mqtt(asyncio.get_running_loop())
    yield
    mqtt_client.loop_stop()


app = FastAPI(title="AURA-Bio core service", lifespan=lifespan)


class CheckIn(BaseModel):
    crew_id: str
    ts: datetime
    values: dict[str, float] = {}  # signal name -> value, e.g. {"exercise_completion_pct": 95}
    reaction_times_ms: list[float] | None = Field(None, min_length=1)  # raw reaction test, one per trial
    mood_answers: list[float] | None = Field(None, min_length=1)  # one per mood question, on the checkin mood_scale


class MissionChange(BaseModel):
    preset: str


@app.get("/health")
def health():
    return {"status": "ok", "mqtt_connected": mqtt_client.is_connected(),
            "readings": store.count(), "rejects": store.count("reject")}


@app.get("/crew")
def crew():
    return store.crews()


@app.get("/crew/overview")
def overview():
    """FR-17: one card per astronaut for the crew medical officer."""
    cards = []
    for crew_id in store.crews():
        s = crew_status(crew_id)
        cards.append({"crew_id": crew_id, "ts": s["ts"], "systems": s["systems"],
                      "worst": max(s["systems"].values(), key=domain.ORDER.index),
                      "alerts": [{"alert_id": a["alert_id"], "name": a["name"], "level": a["level"],
                                  "active": a["active"]} for a in s["alerts"]],
                      "anomaly_score": s["anomaly"].get("score"), "immune_risk": s["immune_risk"]["score"]})
    return cards


@app.post("/alerts/{alert_id}/ack")
async def ack(alert_id: int):
    if (crew_id := store.ack(alert_id)) is None:
        raise HTTPException(404, f"no alert {alert_id}")
    await broadcast(crew_id)
    return {"acknowledged": alert_id}


@app.get("/ground/reports")
def ground_reports():
    """FR-16: reports reach the ground only after the mission's one-way delay (wall-clock seconds)."""
    released, pending = store.reports(time.time())
    return {"released": released, "pending": pending}


@app.get("/crew/{crew_id}/status")
def get_status(crew_id: str):
    if (s := crew_status(crew_id)) is None:
        raise HTTPException(404, f"no readings for {crew_id}")
    return s


@app.delete("/crew/{crew_id}")
def reset_crew(crew_id: str):
    """Demo only: wipe a crew member's readings before replaying another scenario."""
    store.clear(crew_id)
    return {"cleared": crew_id}


@app.get("/crew/{crew_id}/signal/{signal}")
def trend(crew_id: str, signal: str, days: int = 30):
    """FR-11: readings of one signal over the last `days` days, with the baseline band and thresholds."""
    if signal not in {s["name"] for s in load_signals()}:
        raise HTTPException(404, f"unknown signal {signal}")
    cfg = load_thresholds()
    _, last = store.span(crew_id)
    if last is None:
        raise HTTPException(404, f"no readings for {crew_id}")
    since = (datetime.fromisoformat(last) - timedelta(days=days)).isoformat()
    base = baselines(crew_id, cfg).get(signal)
    return {"crew_id": crew_id, "signal": signal, "points": store.series(crew_id, signal, since),
            "baseline_mean": base and base[0], "baseline_sd": base and base[1],
            "rule": cfg["thresholds"].get(signal)}


@app.get("/mission")
def get_mission():
    m = mission()
    return {"name": m["name"], **m["preset"], "presets": list(load_presets())}


@app.put("/mission")
async def set_mission(m: MissionChange):
    """FR-13: switch preset (demo mission panel); every crew member's status is pushed again."""
    if m.preset not in load_presets():
        raise HTTPException(422, f"unknown preset {m.preset}; choose from {list(load_presets())}")
    set_preset(m.preset)
    for crew_id in store.crews():
        await broadcast(crew_id)
    return get_mission()


@app.post("/checkin")
async def checkin(c: CheckIn):
    try:
        scored = domain.score_checkin(c.reaction_times_ms, c.mood_answers, load_thresholds())
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    ok = {}
    for signal, value in (c.values | scored).items():
        r = Reading.model_construct(crew_id=c.crew_id, ts=c.ts, signal=signal, value=value,
                                    source="app", provenance="simulated")
        ok[signal] = ingest(r.model_dump_json(), "checkin") is not None
    await broadcast(c.crew_id)
    return {"accepted": [s for s, v in ok.items() if v], "rejected": [s for s, v in ok.items() if not v]}


@app.websocket("/ws")
async def ws_status(ws: WebSocket):
    """Pushes a crew member's full status after every reading stored for them."""
    await ws.accept()
    sockets.add(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        sockets.discard(ws)
