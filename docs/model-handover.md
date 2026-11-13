# Model handover

For whoever takes over the anomaly model. The data side (datasets, simulator, scenarios,
validation) is finished. Data questions go to the data owner; see "Rules" below.

## Get running

```bash
unset VIRTUAL_ENV            # if your shell exports one
uv sync
uv run pytest -q             # 23 tests, ~10 s
uv run python -m model.train # trains 3 models, then prints detection per scenario
uv run uvicorn model.service:app --port 8001
```

Read first: `CLAUDE.md`, plan sections 4.3 (model), 5.3 (simulator values and validation),
6.2 (scenarios) and 6.3 (current model performance).

## What exists

| File                   | Does                                                                                                                         |
| ---------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| `model/dataset.py`     | Per-astronaut z-scores against their first 14 days; windows of 2, 7, 14 days                                                 |
| `model/autoencoder.py` | Dense autoencoder (flatten → 32 → 6 → 32), one per window length                                                             |
| `model/train.py`       | Trains on normal days only; alarm threshold = 99th percentile of normal error; `evaluate()` runs 200 astronauts per scenario |
| `model/service.py`     | FastAPI `/score`, `/health`. Score > 1 = anomalous. Returns per-signal contributions                                         |
| `generator/sim.py`     | The simulator and the 7 scenarios. Your training data comes from here                                                        |

## Where the model stands (plan 6.3)

| Scenario              | Flagged (any window)                         | Median days to flag |
| --------------------- | -------------------------------------------- | ------------------- |
| Normal (false alarms) | 1.5% of days, 19% of astronauts over 20 days | —                   |
| Sleep debt            | 64%                                          | 6                   |
| Deconditioning        | 84%                                          | 6                   |
| Solar particle event  | 97%                                          | same day            |
| CO₂ creep             | 32% (barely above normal)                    | —                   |
| Immune                | 18% (= normal)                               | —                   |
| Sensor loss           | 14% (= normal)                               | —                   |

Retraining on new random data moves these by 10–20 points; compare changes over several seeds.

The 7- and 14-day windows are weak. **First thing to try: robust scaling** (median and a spread
that ignores outliers, instead of mean and SD over the 14 baseline days).

## What you must know about the data

1. **Normal days have few links between signals.** Sleep duration and sleep efficiency vary together
   (r 0.59, real BIDSleep data), and mood follows last night's sleep (Jones 2022 Table 1). Everything else
   is independent (a bad night does not raise the next day's heart rate or lapses), so multi-signal scenarios are easier to spot than in real life. Treat detection rates as
   optimistic.
2. **Inputs: 10 daily signals**, in the order of `model: true` in `contract/signals.yaml`. Weekly lab
   values (lymphocytes, IL-6, NK, viral shedding) are _not_ inputs; rules and the immune-risk score
   handle them.
3. **Scaling is shared with the core service.** The core service owns the baselines and sends z-scores
   to `/score`. If you change the scaling (e.g. robust scaling), the core service must change the same
   way, or live scores won't match training.
4. **Heavy tails and drift.** Reaction lapses have rare very high days; exercise and sleep efficiency
   sit just under 100% with a long tail down; cabin CO₂ drifts slowly (persistence 0.87), so a 14-day
   baseline often misses its current level.
5. **How much to trust each input:**

   | Trust                | Signals                                                                                          |
   | -------------------- | ------------------------------------------------------------------------------------------------ |
   | Real data, validated | Resting HR, sleep duration, sleep efficiency, cabin CO₂, dose                                    |
   | From papers          | HRV, systolic BP, lapse level, mood level                                                        |
   | Assumptions          | Mood day-to-day spread, all exercise values, persistence 0.4 for HRV, BP, lapses, mood, exercise |

6. **What the model should catch:** sleep debt, deconditioning, solar event. **Not:** CO₂ creep (inside
   natural drift; rules catch it), immune (lab values aren't inputs), sensor loss (stale marking).
   Don't tune toward those three; you would be fitting noise.
7. **Deconditioning sizes are the plan's proposal**, not published (HR +12 bpm over 21 days, exercise
   70%, HRV −10%).
8. **Missing values** are filled with 0 (= baseline); the core service marks them stale separately.
9. **Replay** (`generator.publish --replay`) feeds real ISS CO₂ and dose for cm1/cm2. Check false alarms
   on replayed runs too: real data has glitches the simulator doesn't.

## Rules

- **Don't change `contract/signals.yaml` values to improve model numbers.** They are calibrated to real
  data; `tests/test_validation.py` fails if a spread moves > 15%. Any data change goes to the data owner.
- Adding, removing or reordering a model input changes the shared contract: team agreement needed.
- Thresholds and patterns go in config files, not code (NFR-12).
- Keep evaluation honest: seeds 1 (train) and 2 (threshold) are used; `evaluate()` uses 1000+. Use a
  separate seed range for tuning, not the evaluation seeds.
