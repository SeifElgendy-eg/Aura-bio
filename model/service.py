"""Scoring service (separate container so a crash never stops rule alerts, NFR-4).
uvicorn model.service:app --port 8001

POST /score {"crew_id": "cm1", "window": {"<signal>": [z_oldest, ..., z_today], ...}}
  Values are baseline-normalised z-scores, one per day, up to 14 days. Each model (2, 7, 14 days)
  scores the most recent days it needs; a model is skipped while fewer days are available.
  Missing signals are treated as baseline (0).
"""
from __future__ import annotations

import os
from pathlib import Path

import torch
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from model.autoencoder import errors, load
from model.dataset import WINDOWS

ARTIFACTS = Path(os.environ.get("AURA_ARTIFACTS", "artifacts"))
app = FastAPI(title="AURA-Bio model service")
_models: dict = {}


def _load():
    if not _models:
        for w in WINDOWS:
            _models[w] = load(ARTIFACTS / f"model_{w}d.pt")
    return _models


class ScoreRequest(BaseModel):
    crew_id: str
    window: dict[str, list[float]]


class ScoreResponse(BaseModel):
    crew_id: str
    score: float                 # highest of the per-window scores; > 1 = outside 99% of normal
    anomalous: bool
    window_days: int             # which timescale gave the highest score
    scores: dict[str, float]     # per window, e.g. {"2d": 0.4, "7d": 1.3, "14d": 0.9}
    contributions: dict[str, float]  # share of error per signal in the top window, sums to 1
    label: str = "research concept, not validated on crew data"


@app.get("/health")
def health():
    try:
        _load()
        return {"status": "ok", "windows": list(WINDOWS)}
    except Exception as e:  # noqa: BLE001
        return {"status": "degraded", "error": str(e)}


@app.post("/score", response_model=ScoreResponse)
def score(req: ScoreRequest):
    models = _load()
    sig = next(iter(models.values()))[2]
    unknown = set(req.window) - set(sig)
    if unknown:
        raise HTTPException(422, f"unknown signals: {sorted(unknown)}")
    days = {len(v) for v in req.window.values()}
    if len(days) != 1:
        raise HTTPException(422, f"all signals need the same number of days, got {sorted(days)}")
    n = days.pop() if days else 0
    if n < min(WINDOWS):
        raise HTTPException(422, f"need at least {min(WINDOWS)} days, got {n}")
    x = torch.tensor([req.window.get(s, [0.0] * n) for s in sig], dtype=torch.float32).T  # (days, signals)

    results = {}
    for w, (m, thr, _) in models.items():
        if n >= w:
            err, per_sig = errors(m, x[-w:].unsqueeze(0))
            results[w] = (float(err) / thr, per_sig[0])
    top = max(results, key=lambda w: results[w][0])
    sc, per_sig = results[top]
    tot = float(per_sig.sum()) or 1.0
    return ScoreResponse(crew_id=req.crew_id, score=round(sc, 3), anomalous=sc > 1, window_days=top,
                         scores={f"{w}d": round(s, 3) for w, (s, _) in results.items()},
                         contributions={s: round(float(v) / tot, 3) for s, v in zip(sig, per_sig)})
