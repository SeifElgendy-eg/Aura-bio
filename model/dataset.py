"""Training data for the autoencoder: windows of baseline-normalised daily signals.

Normalisation is per astronaut: z = (x - baseline_mean) / baseline_sd over the first BASELINE_DAYS.
The core service does the same with its stored Baseline rows, then calls /score.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from contract.schema import model_signals
from generator.sim import BASELINE_DAYS, SCENARIOS, Scenario, make_profile, simulate

WINDOWS = (2, 7, 14)  # days; one autoencoder per window length (short-term vs slow drift)


def baseline_stats(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    base = df.iloc[:BASELINE_DAYS]
    sd = base.std().replace(0, np.nan).fillna(1e-3).clip(lower=1e-3)
    return base.mean(), sd


def normalise(df: pd.DataFrame) -> pd.DataFrame:
    mean, sd = baseline_stats(df)
    z = (df - mean) / sd
    return z[model_signals()].fillna(0.0)  # missing (stale) -> baseline; core marks it stale separately


def windows(z: pd.DataFrame, w: int, start: int = BASELINE_DAYS) -> np.ndarray:
    """(n_windows, w, n_signals): one window ending on each day from `start` on."""
    arr = z.to_numpy(dtype=np.float32)
    return np.stack([arr[t - w + 1 : t + 1] for t in range(max(start, w - 1), len(arr))])


def normal_frames(n_crew: int, n_days: int, seed: int) -> list[pd.DataFrame]:
    """Baseline-normalised normal days, one frame per simulated astronaut."""
    rng = np.random.default_rng(seed)
    return [normalise(simulate(make_profile(rng), n_days, rng)) for _ in range(n_crew)]


def scenario_run(scenario: Scenario | str, n_days: int = 40, seed: int = 0) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Raw daily frame and its baseline-normalised version."""
    sc = SCENARIOS[scenario] if isinstance(scenario, str) else scenario
    rng = np.random.default_rng(seed)
    df = simulate(make_profile(rng), n_days, rng, sc)
    return df, normalise(df)
