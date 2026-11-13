# AURA-Bio

Astronaut health monitoring for NASA Space Apps 2026 (48-h build, Nov 14–15). Scores each crew
member against their own baseline and alerts on cross-system patterns. The full plan is the team's
"AURA-Bio software plan" PDF; section refs below (e.g. "plan 4.3") point into it.

This repo currently holds the **data + model** workstream. Firmware (Wokwi), core service, and
Flutter app are other workstreams and may land here later as `firmware/`, `core/`, `app/`.

## Layout
- `contract/` — shared contract, changed only by team agreement. `signals.yaml` (names include
  units; `model: true` + order = autoencoder input vector), `schema.py` (`Reading` message, topics
  `aura/<crew_id>/<group>`).
- `generator/` — `sim.py` simulates per-astronaut baselines + AR(1) noise + scenario effects
  (plan 6.2: co2_creep, sleep_debt, deconditioning, sensor_loss); `publish.py` replays to MQTT.
- `model/` — `dataset.py` (baseline z-normalisation; windows of 2, 7, 14 days), `autoencoder.py` (dense AE; one model per window length),
  `train.py` (trains on normal days only, threshold = p99 normal error, saves `artifacts/model_{2,7,14}d.pt`), `service.py` (FastAPI
  `/score`, `/health`; separate container so rule alerts survive a model crash, NFR-4).
- `data/SOURCES.md` — dataset list; raw downloads in `data/raw/` (committed so clones work offline; regenerate with `data/fetch.py`).
- `artifacts/` — trained model (git-ignored; regenerate with `model.train`).

## Commands
Python is pinned <3.14 (torch); uv picks 3.12. Torch comes from the CPU wheel index.
If a foreign `VIRTUAL_ENV` is exported in your shell, `unset VIRTUAL_ENV` first.
- `uv sync` · `uv run pytest -q`
- `uv run python -m model.train` — trains the 3 models, prints score per scenario day and window
- `uv run python data/process.py` — raw data to `data/processed/`
- `uv run uvicorn model.service:app --port 8001`
- `uv run python -m generator.publish --scenario sleep_debt --crew cm1 --speed 10` (needs a broker on :1883)

## Rules
- All crew data is simulated and must carry `provenance: simulated`; never present it as real (NFR-11).
- Model output is a "research concept, not validated on crew data"; no diagnostic wording (NFR-10).
- Thresholds/patterns belong in config files, not code (NFR-12); cite source + published/proposed tag.
- `/score` takes baseline-normalised z-scores; the core service owns baselines.
