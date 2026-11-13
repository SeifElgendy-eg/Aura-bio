import numpy as np

from contract.schema import Reading, model_signals
from generator.sim import BASELINE_DAYS, SCENARIOS, make_profile, simulate, to_readings
from model.dataset import WINDOW, normalise, windows


def _run(name, days=40):
    rng = np.random.default_rng(0)
    return simulate(make_profile(rng), days, rng, SCENARIOS[name])


def test_readings_match_contract():
    msgs = to_readings("cm1", _run("normal", 3))
    assert len(msgs) == 3 * len(model_signals())
    r = Reading(**msgs[0])
    assert r.topic().startswith("aura/cm1/")


def test_sleep_debt_reaches_target():
    df = _run("sleep_debt")
    assert df["sleep_duration_h"].iloc[-5:].mean() < 5.5
    assert abs(df["sleep_duration_h"].iloc[:BASELINE_DAYS].mean() - 7.2) < 1.0


def test_sensor_loss_drops_readings():
    df = _run("sensor_loss")
    on = SCENARIOS["sensor_loss"].onset_day
    assert df["resting_hr_bpm"].iloc[on:].isna().all()
    assert all(m["signal"] != "rmssd_ms" for m in to_readings("cm1", df.iloc[on:]))


def test_window_shape():
    w = windows(normalise(_run("normal")))
    assert w.shape == (40 - BASELINE_DAYS, WINDOW, len(model_signals()))
    assert np.isfinite(w).all()
