"""python -m model.train  -> artifacts/model_{2,7,14}d.pt, then prints per-scenario score traces."""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import torch

from contract.schema import model_signals
from generator.sim import BASELINE_DAYS, SCENARIOS
from model.autoencoder import WindowAE, errors, save
from model.dataset import WINDOWS, normal_frames, scenario_run, windows

ARTIFACTS = Path("artifacts")


def artifact(w: int) -> Path:
    return ARTIFACTS / f"model_{w}d.pt"


def train_one(w: int, train_z: list, val_z: list, epochs: int, quantile: float) -> tuple[WindowAE, float]:
    torch.manual_seed(0)
    train = torch.from_numpy(np.concatenate([windows(z, w) for z in train_z]))
    val = torch.from_numpy(np.concatenate([windows(z, w) for z in val_z]))
    model = WindowAE(w, train.shape[2])
    opt = torch.optim.Adam(model.parameters(), lr=1e-3)
    loader = torch.utils.data.DataLoader(train, batch_size=256, shuffle=True)
    for ep in range(epochs):
        model.train()
        for xb in loader:
            loss = ((model(xb) - xb) ** 2).mean()
            opt.zero_grad(); loss.backward(); opt.step()
    model.eval()
    val_err = errors(model, val)[0].numpy()
    threshold = float(np.quantile(val_err, quantile))
    print(f"{w:2d}-day: train {loss.item():.3f}  val {val_err.mean():.3f}  threshold(p{quantile*100:.0f})={threshold:.3f}")
    return model, threshold


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--crew", type=int, default=300)
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--quantile", type=float, default=0.99)
    a = ap.parse_args()

    sig = model_signals()
    train_z, val_z = normal_frames(a.crew, a.days, seed=1), normal_frames(60, a.days, seed=2)
    models = {}
    for w in WINDOWS:
        models[w] = train_one(w, train_z, val_z, a.epochs, a.quantile)
        save(artifact(w), models[w][0], models[w][1], sig)

    onset = SCENARIOS["co2_creep"].onset_day
    print(f"\nscore = error/threshold per day from day {BASELINE_DAYS} (onset day {onset} = '|'); >1 = anomalous")
    for name in SCENARIOS:
        _, z = scenario_run(name, seed=11)
        for w, (m, thr) in models.items():
            s = errors(m, torch.from_numpy(windows(z, w)))[0].numpy() / thr
            cells = [("|" if BASELINE_DAYS + i == onset else "") + f"{v:.1f}" for i, v in enumerate(s)]
            print(f"{name:15s}{w:3d}d " + " ".join(cells))


if __name__ == "__main__":
    main()
