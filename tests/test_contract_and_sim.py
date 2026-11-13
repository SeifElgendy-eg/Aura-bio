import numpy as np

from contract.schema import Reading, load_signals, model_signals
from generator.sim import BASELINE_DAYS, SCENARIOS, make_profile, simulate, to_readings
from model.dataset import normalise, windows


def _run(name, days=40):
    rng = np.random.default_rng(0)
    return simulate(make_profile(rng), days, rng, SCENARIOS[name])


def test_readings_match_contract():
    msgs = to_readings("cm1", _run("normal", 3))
    daily = [s for s in load_signals() if "interval_days" not in s]
    weekly = [s for s in load_signals() if "interval_days" in s]
    assert len(msgs) == 3 * len(daily) + len(weekly)  # weekly labs only on day 0
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


def test_dose_follows_preset_and_differs_per_astronaut():
    from contract.schema import load_presets
    for preset, p in load_presets().items():
        rng = np.random.default_rng(1)
        levels = [simulate(make_profile(rng, preset), 60, rng)["dose_mgy"].mean() for _ in range(200)]
        assert abs(np.mean(levels) - p["dose_mgy_day"]) / p["dose_mgy_day"] < 0.03, preset
        assert np.std(levels) > 0.05 * p["dose_mgy_day"], preset   # each astronaut has own level
    rng = np.random.default_rng(2)
    assert (simulate(make_profile(rng, "mars_transit"), 60, rng)["dose_mgy"] > 0).all()


def test_labs_weekly_and_plausible():
    df = _run("normal", 60)
    lab = df["lymphocytes_per_ul"]
    assert lab.notna().sum() == 9 and lab.dropna().index.tolist()[:2] == [0, 7]
    assert (lab.dropna() > 0).all() and (df["il6_pg_ml"].dropna() > 0).all()
    assert set(df["viral_pcr_positive"].dropna().unique()) <= {0.0, 1.0}
    assert all(s not in model_signals() for s in ["lymphocytes_per_ul", "il6_pg_ml"])
