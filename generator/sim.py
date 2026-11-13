"""Simulated crew data: per-astronaut baselines + AR(1) day-to-day noise + scenario effects.

Everything here is SIMULATED (provenance="simulated"); it is anchored to the research-doc findings,
not to real crew vitals (none are open). See data/SOURCES.md for the real datasets to anchor on.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from contract.schema import load_signals

BASELINE_DAYS = 14


@dataclass
class Effect:
    """Ramp a signal from onset over ramp_days. mode 'add': +value at full effect; 'mul': *(1+value);
    'set': move toward the absolute value."""
    mode: str
    value: float
    ramp_days: int = 5


@dataclass
class Scenario:
    name: str
    onset_day: int = BASELINE_DAYS + 7
    effects: dict[str, Effect] = field(default_factory=dict)
    drop_signals: list[str] = field(default_factory=list)  # stop publishing (sensor loss)


SCENARIOS: dict[str, Scenario] = {
    "normal": Scenario("normal"),
    "co2_creep": Scenario("co2_creep", effects={
        "cabin_co2_mmhg": Effect("set", 3.2, 8),
        "reaction_lapses_pct": Effect("mul", 0.25, 8),
        "mood_score": Effect("add", -0.8, 8),
    }),
    "sleep_debt": Scenario("sleep_debt", effects={
        "sleep_duration_h": Effect("add", -2.4, 5),  # same drop as plan 6.2 (7.2->4.8 h), from own baseline
        "sleep_efficiency_pct": Effect("add", -8, 5),
        "rmssd_ms": Effect("mul", -0.25, 5),
        "mood_score": Effect("add", -2.0, 5),
        "reaction_lapses_pct": Effect("mul", 0.2, 5),
    }),
    "deconditioning": Scenario("deconditioning", effects={
        "resting_hr_bpm": Effect("add", 12, 7),
        "exercise_completion_pct": Effect("set", 70, 7),
        "rmssd_ms": Effect("mul", -0.1, 7),
    }),
    "sensor_loss": Scenario("sensor_loss", drop_signals=["resting_hr_bpm", "rmssd_ms"]),
}


def make_profile(rng: np.random.Generator) -> dict[str, float]:
    """One astronaut's personal baseline means."""
    return {s["name"]: s["sim_mean"] + rng.normal(0, s["person_sd"]) for s in load_signals()}


def simulate(profile: dict[str, float], n_days: int, rng: np.random.Generator,
             scenario: Scenario | None = None, ar: float = 0.4) -> pd.DataFrame:
    """Daily values, one row per day, one column per signal (NaN where a sensor dropped out)."""
    scenario = scenario or SCENARIOS["normal"]
    cols = {}
    for s in load_signals():
        name, mean, sd = s["name"], profile[s["name"]], s["sim_sd"]
        eps = rng.normal(0, sd * np.sqrt(1 - ar**2), n_days)  # stationary AR(1) with std sd
        noise = np.zeros(n_days)
        noise[0] = rng.normal(0, sd)
        for t in range(1, n_days):
            noise[t] = ar * noise[t - 1] + eps[t]
        x = mean + noise
        eff = scenario.effects.get(name)
        if eff:
            ramp = np.clip((np.arange(n_days) - scenario.onset_day + 1) / eff.ramp_days, 0, 1)
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
