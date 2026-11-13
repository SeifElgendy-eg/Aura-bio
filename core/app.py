"""Core service: MQTT ingest, REST and WebSocket (plan 3.5 API layer).
uvicorn core.app:app --port 8000
Env: AURA_DB (default core.db), AURA_MQTT_HOST (default localhost), AURA_MQTT_PORT (default 1883).
"""
from __future__ import annotations

import asyncio
import logging
import math
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

import paho.mqtt.client as mqtt
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from contract.schema import Reading, load_signals, load_thresholds
from core import domain
from core.store import Store

log = logging.getLogger("aura.core")
store: Store
mqtt_client: mqtt.Client
sockets: set[WebSocket] = set()


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


def crew_status(crew_id: str) -> dict | None:
    latest = store.latest(crew_id)
    if not latest:
        return None
    cfg = load_thresholds()
    now = max(datetime.fromisoformat(r["ts"]) for r in latest.values())
    history = [store.latest(crew_id, (now - timedelta(days=k)).isoformat())
               for k in range(1, domain.history_days(cfg) + 1)]
    return domain.status(crew_id, latest, store.baselines(crew_id, cfg["baseline_days"]), cfg, load_signals(), history)


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
    values: dict[str, float]  # signal name -> value, e.g. {"mood_score": 6, "reaction_lapses_pct": 8}


@app.get("/health")
def health():
    return {"status": "ok", "mqtt_connected": mqtt_client.is_connected(),
            "readings": store.count(), "rejects": store.count("reject")}


@app.get("/crew")
def crew():
    return store.crews()


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


@app.post("/checkin")
async def checkin(c: CheckIn):
    ok = {}
    for signal, value in c.values.items():
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
