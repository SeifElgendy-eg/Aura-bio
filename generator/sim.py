"""Simulated crew data: per-astronaut baselines + AR(1) day-to-day noise + scenario effects.

Everything here is SIMULATED (provenance="simulated"); it is anchored to the research-doc findings,
not to real crew vitals (none are open). See data/SOURCES.md for the real datasets to anchor on.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from contract.schema import load_presets, load_signals

BASELINE_DAYS = 14


@dataclass
class Effect:
    """Ramp a signal from onset over ramp_days. mode 'add': +value at full effect; 'mul': *(1+value);
    'set': move toward the absolute value. Default ramp is linear, then flat after ramp_days.
    With power set, the ramp is (days since onset / ramp_days) ** power and keeps growing past
    ramp_days (Van Dongen et al. 2003 fit y = beta * t^theta)."""
    mode: str
    value: float
    ramp_days: int = 5
    power: float | None = None


@dataclass
class Scenario:
    name: str
    onset_day: int = BASELINE_DAYS + 7
    effects: dict[str, Effect] = field(default_factory=dict)
    drop_signals: list[str] = field(default_factory=list)  # stop publishing (sensor loss)


SCENARIOS: dict[str, Scenario] = {
    "normal": Scenario("normal"),
    "co2_creep": Scenario("co2_creep", effects={
        "cabin_co2_mmhg": Effect("add", 1.2, 8),  # plan 6.2 size (2.0->3.2), from the cabin's own level
        "reaction_lapses_pct": Effect("mul", 0.25, 8),
        "mood_score": Effect("add", -0.8, 8),
    }),
    "sleep_debt": Scenario("sleep_debt", effects={
        "sleep_duration_h": Effect("add", -2.4, 5),  # same drop as plan 6.2 (7.2->4.8 h), from own baseline
        "sleep_efficiency_pct": Effect("add", -8, 5),
        "rmssd_ms": Effect("mul", -0.25, 5),
        # Van Dongen et al. 2003 (SLEEP 26:117), 4 h time-in-bed group (~3.8 h sleep, matching
        # 6.25 - 2.4 h): PVT lapses +~14 per 10-min test at day 14 (Fig 1A) ~ +14 percentage points
        # of trials, curve t^0.78, extrapolated past day 14. Sleepiness ~1 point on the 7-point SSS
        # (~1.7 on our 0-10 scale), curve t^0.24 -- sleepiness used as a proxy for mood.
        "mood_score": Effect("add", -1.7, 14, power=0.24),
        "reaction_lapses_pct": Effect("add", 14, 14, power=0.78),
    }),
    "deconditioning": Scenario("deconditioning", effects={
        "resting_hr_bpm": Effect("add", 12, 7),
        "exercise_completion_pct": Effect("set", 70, 7),
        "rmssd_ms": Effect("mul", -0.1, 7),
    }),
    "sensor_loss": Scenario("sensor_loss", drop_signals=["resting_hr_bpm", "rmssd_ms"]),
}


def make_profile(rng: np.random.Generator, preset: str = "station") -> dict[str, float]:
    """One astronaut's personal baseline means. Dose is scaled to the mission preset's level, keeping
    each astronaut's own offset (personal dosimeter), so crew differ independently of each other."""
    p = load_presets()[preset]
    prof = {}
    for s in load_signals():
        mean, spread = s["sim_mean"], s["person_sd"]
        if s["name"] == "dose_mgy":
            scale = p["dose_mgy_day"] / mean
            mean, spread = mean * scale, spread * scale
        prof[s["name"]] = mean + rng.normal(0, spread)
    return prof


def simulate(profile: dict[str, float], n_days: int, rng: np.random.Generator,
             scenario: Scenario | None = None) -> pd.DataFrame:
    """Daily values, one row per day, one column per signal (NaN where a sensor dropped out)."""
    scenario = scenario or SCENARIOS["normal"]
    cols = {}
    for s in load_signals():
        name, mean, sd, ar = s["name"], profile[s["name"]], s["sim_sd"], s.get("ar", 0.4)
        eps = rng.normal(0, sd * np.sqrt(1 - ar**2), n_days)  # stationary AR(1) with std sd
        noise = np.zeros(n_days)
        noise[0] = rng.normal(0, sd)
        for t in range(1, n_days):
            noise[t] = ar * noise[t - 1] + eps[t]
        # log: true -> variation is multiplicative with a fixed relative size (sim_sd / sim_mean),
        # so it scales with each astronaut's or preset's level and never goes negative
        x = mean * np.exp(noise / s["sim_mean"]) if s.get("log") else mean + noise
        eff = scenario.effects.get(name)
        if eff:
            t = np.clip(np.arange(n_days) - scenario.onset_day + 1, 0, None) / eff.ramp_days
            ramp = t ** eff.power if eff.power else np.clip(t, 0, 1)
            if eff.mode == "add":
                x = x + ramp * eff.value
            elif eff.mode == "mul":
                x = x * (1 + ramp * eff.value)
            elif eff.mode == "set":
                x = x + ramp * (eff.value - mean)
        if name in scenario.drop_signals:
            x[scenario.onset_day:] = np.nan
        cols[name] = x
    return pd.DataFrame(cols)


def to_readings(crew_id: str, df: pd.DataFrame, start: str = "2026-11-14T10:00:00+00:00",
                provenance: str = "simulated") -> list[dict]:
    """Daily frame -> contract messages (JSON-ready), skipping NaN (dropped sensors)."""
    by_name = {s["name"]: s for s in load_signals()}
    ts0 = pd.Timestamp(start)
    out = []
    for day, row in df.iterrows():
        ts = (ts0 + pd.Timedelta(days=int(day))).isoformat().replace("+00:00", "Z")
        for name, v in row.items():
            if pd.notna(v):
                out.append({"crew_id": crew_id, "ts": ts, "signal": name, "value": round(float(v), 3),
                            "source": by_name[name]["source"], "provenance": provenance})
    return out
