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


def evaluate(models: dict, n: int = 200, days: int = 40) -> None:
    """Per scenario, over n simulated astronauts: share flagged (score > 1) after onset, median day of
    first flag, and false alarms per normal day before onset. 'any' = any window, as /score reports."""
    onset = SCENARIOS["normal"].onset_day
    print(f"{n} astronauts per scenario, onset day {onset}: flagged % / median day after onset / false alarms per day before onset")
    for name in SCENARIOS:
        scores = {w: [] for w in models}
        for seed in range(1000, 1000 + n):
            _, z = scenario_run(name, n_days=days, seed=seed)
            for w, (m, thr) in models.items():
                scores[w].append(errors(m, torch.from_numpy(windows(z, w)))[0].numpy() / thr)
        scores["any"] = [np.max(per_w, axis=0) for per_w in zip(*(scores[w] for w in models))]
        cells = []
        for w, runs in scores.items():
            runs = np.array(runs)
            pre, post = runs[:, : onset - BASELINE_DAYS], runs[:, onset - BASELINE_DAYS :]
            first = np.array([np.argmax(r > 1) if (r > 1).any() else np.nan for r in post])
            hit = np.isfinite(first)
            med = f"{np.nanmedian(first):4.1f}" if hit.any() else "   -"
            cells.append(f"{w}{'d' if w != 'any' else ''}: {hit.mean() * 100:3.0f}% {med} {(pre > 1).mean() * 100:3.1f}%")
        print(f"{name:15s} " + " | ".join(cells))


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

    print()
    evaluate(models)


if __name__ == "__main__":
    main()
