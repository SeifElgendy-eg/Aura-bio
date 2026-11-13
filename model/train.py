"""python -m model.train  -> artifacts/model.pt, then prints per-scenario score traces."""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import torch

from contract.schema import model_signals
from generator.sim import BASELINE_DAYS, SCENARIOS
from model.autoencoder import WindowAE, errors, save
from model.dataset import WINDOW, build_normal, scenario_run

ARTIFACT = Path("artifacts/model.pt")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--crew", type=int, default=300)
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--quantile", type=float, default=0.99)
    a = ap.parse_args()
    torch.manual_seed(0)

    sig = model_signals()
    train = torch.from_numpy(build_normal(a.crew, a.days, seed=1))
    val = torch.from_numpy(build_normal(60, a.days, seed=2))
    model = WindowAE(WINDOW, len(sig))
    opt = torch.optim.Adam(model.parameters(), lr=1e-3)
    loader = torch.utils.data.DataLoader(train, batch_size=256, shuffle=True)
    for ep in range(a.epochs):
        model.train()
        for xb in loader:
            loss = ((model(xb) - xb) ** 2).mean()
            opt.zero_grad(); loss.backward(); opt.step()
        if ep % 10 == 0 or ep == a.epochs - 1:
            model.eval()
            print(f"epoch {ep:3d}  train {loss.item():.4f}  val {errors(model, val)[0].mean():.4f}")

    model.eval()
    threshold = float(np.quantile(errors(model, val)[0].numpy(), a.quantile))
    save(ARTIFACT, model, threshold, sig)
    print(f"saved {ARTIFACT}  threshold(p{a.quantile*100:.0f} normal)={threshold:.4f}\n")

    onset = SCENARIOS["co2_creep"].onset_day
    print(f"score = error/threshold per day from day {BASELINE_DAYS} (onset day {onset} = '|')")
    for name in SCENARIOS:
        _, w = scenario_run(name, seed=11)
        s = errors(model, torch.from_numpy(w))[0].numpy() / threshold
        cells = [("|" if BASELINE_DAYS + i == onset else "") + f"{v:.1f}" for i, v in enumerate(s)]
        print(f"{name:15s} " + " ".join(cells))


if __name__ == "__main__":
    main()
