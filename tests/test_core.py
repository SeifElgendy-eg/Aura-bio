from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from contract.schema import load_signals, load_thresholds
from core import app as core_app
from core.domain import band, match_patterns

T0 = datetime(2026, 11, 14, 10, tzinfo=timezone.utc)
BASE = 100.0  # baseline mean used for the relative rules


def value_for(rule, t, eps):
    """A value sitting eps past threshold t on the bad side."""
    sign = 1 if rule["direction"] == "above" else -1
    if rule["kind"] == "abs":
        return t + sign * eps
    return BASE + sign * (t + eps) * (BASE / 100 if rule["kind"] == "pct" else 1)


RULES = [(n, r) for n, rs in load_thresholds()["thresholds"].items() for r in (rs if isinstance(rs, list) else [rs])]


@pytest.mark.parametrize("name,rule", RULES)
def test_every_threshold_boundary(name, rule):  # NFR-5
    assert rule["basis"] in ("published", "proposed") and rule["citation"]  # NFR-13
    assert name in {s["name"] for s in load_signals()}
    for level in ("amber", "red"):
        if (t := rule.get(level)) is None:
            continue
        below = "green" if level == "amber" or "amber" not in rule else "amber"
        assert band(rule, value_for(rule, t, -0.01), BASE) == below
        assert band(rule, value_for(rule, t, 0.01), BASE) == level


def test_relative_rule_needs_baseline():
    assert band(load_thresholds()["thresholds"]["rmssd_ms"], 10.0, None) is None


def test_rule_list_takes_worst():
    lymph = load_thresholds()["thresholds"]["lymphocytes_per_ul"]
    assert band(lymph, 1100, 1300) == "green"
    assert band(lymph, 900, 1300) == "red"      # under 1000 even though only 31% below baseline
    assert band(lymph, 900, None) == "red"      # absolute rule works before a baseline exists
    assert band(lymph, 1500, 2600) == "red"     # 42% below baseline


PATTERNS = load_thresholds()["patterns"]


@pytest.mark.parametrize("p", PATTERNS, ids=lambda p: p["id"])
def test_every_pattern_boundary(p):  # NFR-5, NFR-13
    names = {s["name"] for s in load_signals()}
    assert set(p["signals"]) <= names and len(p["signals"]) >= 2
    assert p["basis"] in ("published", "proposed") and p["citation"] and p["response_system"] and p["response_crew"]

    need = p.get("min_band", {})
    days = p.get("days", 1)

    def fired(yesterday=None, **override):
        sig = {s: {"band": override.get(s, need.get(s, "amber")), "value": 1.0} for s in p["signals"]}
        return match_patterns(sig, [p], [yesterday or sig] * (days - 1))

    base = "red" if need else "amber"
    assert [a["level"] for a in fired()] == [base]
    assert [a["level"] for a in fired(**{p["signals"][0]: "red"})] == ["red"]
    for s in p["signals"]:
        for other in ("green", "stale", "unknown") + (("amber",) if need.get(s) == "red" else ()):
            assert fired(**{s: other}) == []
    if days > 1:  # must also have matched yesterday
        assert match_patterns({s: {"band": "red"} for s in p["signals"]}, [p], []) == []
        assert fired(yesterday={s: {"band": "green"} for s in p["signals"]}) == []


def test_broken_pattern_does_not_stop_others():  # NFR-2
    ok = {"id": "ok", "signals": ["a"]}
    assert [a["id"] for a in match_patterns({"a": {"band": "red"}}, [{"id": "bad", "signals": ["nope"]}, ok])] == ["ok"]


def replay(scenario, seed):
    """Run a simulated scenario through the store and status, day by day; return the patterns raised, in order."""
    import itertools

    import numpy as np

    from contract.schema import Reading
    from core.store import Store
    from generator.sim import SCENARIOS, make_profile, simulate, to_readings

    core_app.store = Store(":memory:")
    rng = np.random.default_rng(seed)
    sc = SCENARIOS[scenario]
    raised = []
    for _, msgs in itertools.groupby(to_readings("cm1", simulate(make_profile(rng), sc.days, rng, sc)),
                                     key=lambda m: m["ts"]):
        for m in msgs:
            core_app.store.add(Reading(**m))
        raised += [a["id"] for a in core_app.crew_status("cm1")["alerts"] if a["id"] not in raised]
    return raised


DEMO_SEED = 12  # an astronaut whose normal run raises nothing and each scenario raises only its own pattern


@pytest.mark.parametrize("scenario,expected", [("normal", []), ("co2_creep", ["co2_performance"]),
                                               ("sleep_debt", ["sleep_loss_impairment"]),
                                               ("deconditioning", ["cardio_deconditioning"])])
def test_demo_scenarios_raise_their_pattern(scenario, expected):  # NFR-5, plan 6.2: same alerts every run
    assert replay(scenario, DEMO_SEED) == expected


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AURA_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("AURA_MQTT_PORT", "1")  # nothing listens there; the service must start anyway
    with TestClient(core_app.app) as c:
        yield c


def post_day(client, day, **values):
    return client.post("/checkin", json={"crew_id": "cm1", "ts": (T0 + timedelta(days=day)).isoformat(),
                                         "values": values}).json()


def test_baseline_then_bands_and_stale(client):
    assert client.get("/crew/cm1/status").status_code == 404
    with client.websocket_connect("/ws") as ws:
        for d in range(14):
            post_day(client, d, resting_hr_bpm=60 + d % 2, cabin_co2_mmhg=2.0, sleep_duration_h=7.5)
            assert ws.receive_json()["baseline_ready"] is False
        post_day(client, 14, resting_hr_bpm=72, cabin_co2_mmhg=3.2, sleep_duration_h=7.5)
        s = ws.receive_json()
    assert s == client.get("/crew/cm1/status").json()
    assert s["baseline_ready"] and s["disclaimer"]
    assert s["signals"]["resting_hr_bpm"]["band"] == "amber"  # 72 vs baseline 60.5
    assert s["signals"]["resting_hr_bpm"]["provenance"] == "simulated"
    assert s["systems"] == {"cardiovascular": "amber", "neurocognitive": "green", "environment": "red",
                            "bone_muscle": "unknown", "radiation": "unknown", "immune": "unknown"}
    # pulse sensor stops: two days later heart rate is stale, never green (FR-8)
    post_day(client, 16, cabin_co2_mmhg=2.0)
    s = client.get("/crew/cm1/status").json()
    assert s["signals"]["resting_hr_bpm"]["band"] == "stale" and s["systems"]["cardiovascular"] == "stale"
    assert client.delete("/crew/cm1").status_code == 200 and client.get("/crew").json() == []


def test_bad_messages_are_rejected_without_stopping(client):  # FR-2, NFR-2
    good = '{"crew_id":"cm1","ts":"2026-11-14T10:00:00Z","signal":"cabin_co2_mmhg","value":2.7,' \
           '"source":"wokwi","provenance":"simulated"}'
    for bad in (b"not json", good.replace("cabin_co2_mmhg", "nope"), good.replace("2.7", '"x"'),
                good.replace("simulated", "made-up")):
        assert core_app.ingest(bad, "aura/cm1/cabin") is None
    assert post_day(client, 0, nope=1.0, mood_score=6)["rejected"] == ["nope"]
    assert core_app.ingest(good, "aura/cm1/cabin") is not None
    core_app.ingest(good, "aura/cm1/cabin")  # QoS 1 duplicate is stored once
    assert client.get("/health").json() == {"status": "ok", "mqtt_connected": False, "readings": 2, "rejects": 5}
