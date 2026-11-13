"""Shared message contract (plan 4.2). Core service, generator and Wokwi all emit this shape."""
from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

SIGNALS_YAML = Path(__file__).with_name("signals.yaml")
GROUPS = ("vitals", "cabin", "radiation", "labs")


class Reading(BaseModel):
    crew_id: str
    ts: datetime
    signal: str
    value: float
    source: Literal["wokwi", "generator", "app"]
    provenance: Literal["real", "replayed", "simulated"]

    def topic(self) -> str:
        return f"aura/{self.crew_id}/{signal_group(self.signal)}"


@lru_cache
def load_signals() -> list[dict]:
    return yaml.safe_load(SIGNALS_YAML.read_text())["signals"]


def model_signals() -> list[str]:
    """Ordered autoencoder input features."""
    return [s["name"] for s in load_signals() if s.get("model")]


def signal_group(name: str) -> str:
    return next(s["group"] for s in load_signals() if s["name"] == name)
