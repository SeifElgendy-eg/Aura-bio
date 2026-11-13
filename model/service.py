"""Scoring service (separate container so a crash never stops rule alerts, NFR-4).
uvicorn model.service:app --port 8001

POST /score {"crew_id": "cm1", "window": {"<signal>": [z_day-4, ..., z_today], ...}}
  window values are baseline-normalised z-scores; missing signals are treated as baseline (0).
"""
from __future__ import annotations

import os
from pathlib import Path

import torch
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from model.autoencoder import errors, load

MODEL_PATH = Path(os.environ.get("AURA_MODEL_PATH", "artifacts/model.pt"))
app = FastAPI(title="AURA-Bio model service")
_state: dict = {}


def _model():
    if "m" not in _state:
        _state["m"], _state["thr"], _state["sig"] = load(MODEL_PATH)
    return _state["m"], _state["thr"], _state["sig"]


class ScoreRequest(BaseModel):
    crew_id: str
    window: dict[str, list[float]]


class ScoreResponse(BaseModel):
    crew_id: str
    score: float          # error / threshold; > 1 = outside 99% of normal days
    anomalous: bool
    contributions: dict[str, float]  # share of error per signal, sums to 1
    label: str = "research concept, not validated on crew data"


@app.get("/health")
def health():
    try:
        _model()
        return {"status": "ok"}
    except Exception as e:  # noqa: BLE001
        return {"status": "degraded", "error": str(e)}


@app.post("/score", response_model=ScoreResponse)
def score(req: ScoreRequest):
    m, thr, sig = _model()
    unknown = set(req.window) - set(sig)
    if unknown:
        raise HTTPException(422, f"unknown signals: {sorted(unknown)}")
    rows = []
    for s in sig:
        v = req.window.get(s, [0.0] * m.window)
        if len(v) != m.window:
            raise HTTPException(422, f"{s}: need {m.window} values, got {len(v)}")
        rows.append(v)
    x = torch.tensor(rows, dtype=torch.float32).T.unsqueeze(0)
    err, per_sig = errors(m, x)
    tot = float(per_sig.sum()) or 1.0
    sc = float(err) / thr
    return ScoreResponse(crew_id=req.crew_id, score=round(sc, 3), anomalous=sc > 1,
                         contributions={s: round(float(v) / tot, 3) for s, v in zip(sig, per_sig[0])})
