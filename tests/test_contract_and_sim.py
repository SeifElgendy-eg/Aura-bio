import numpy as np

from contract.schema import Reading, model_signals
from generator.sim import BASELINE_DAYS, SCENARIOS, make_profile, simulate, to_readings
from model.dataset import normalise, windows


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
    base = df["sleep_duration_h"].iloc[:BASELINE_DAYS].mean()
    assert df["sleep_duration_h"].iloc[-10:].mean() < base - 1.8  # ~2.4 h below own baseline


def test_sensor_loss_drops_readings():
    df = _run("sensor_loss")
    on = SCENARIOS["sensor_loss"].onset_day
    assert df["resting_hr_bpm"].iloc[on:].isna().all()
    assert all(m["signal"] != "rmssd_ms" for m in to_readings("cm1", df.iloc[on:]))


def test_window_shape():
    for n in (2, 7, 14):
        w = windows(normalise(_run("normal")), n)
        assert w.shape == (40 - BASELINE_DAYS, n, len(model_signals()))
        assert np.isfinite(w).all()


def test_rmssd_never_negative():
    rng = np.random.default_rng(0)
    x = np.concatenate([simulate(make_profile(rng), 60, rng)["rmssd_ms"].to_numpy() for _ in range(300)])
    assert (x > 0).all()


def test_sleep_debt_lapses_follow_van_dongen():
    df = _run("sleep_debt", 60)
    on = SCENARIOS["sleep_debt"].onset_day
    base = df["reaction_lapses_pct"].iloc[:BASELINE_DAYS].mean()
    day14 = df["reaction_lapses_pct"].iloc[on + 11: on + 16].mean()  # around day 14 of restriction
    assert 8 < day14 - base < 20                                      # ~ +14 points
    assert df["reaction_lapses_pct"].iloc[-5:].mean() > day14         # keeps rising after day 14
