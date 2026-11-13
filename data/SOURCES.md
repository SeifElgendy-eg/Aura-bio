# Datasets (plan section 5)

`uv run python data/fetch.py [source ...]` downloads into `data/raw/<source>/` (git-ignored) and
writes `data/raw/MANIFEST.json` (URL, bytes, sha256 per file). Re-runs skip what is already there.
Nothing may hit a NASA server during the demo (NFR-7), so run this before the event.
Datasets on the official challenge page take precedence over this list.

| # | Source | What we fetch | Used for | Size | Status |
| --- | --- | --- | --- | --- | --- |
| 1 | [NASA OSDR Environmental Data App](https://visualization.osdr.nasa.gov/eda) | ISS cabin CO2, temp, humidity | `cabin_co2_mmhg` normal baseline (currently sim_mean 2.0) | ? | **Manual**: no documented API. Data Tables tab → Telemetry Table → download CSV into `data/raw/eda/`. Check the CO2 unit (page doesn't state it). |
| 2 | [NASA RadLab](https://visualization.osdr.nasa.gov/radlab/gui/data-api) | ISS DosTel1/DosTel2 absorbed dose rate (µGy/h) + dose-equivalent rate (µSv/h), 2022-01-01 → 2022-04-01, ~72 s cadence | Dose signal, station preset (aggregate to daily) | 13 MB | `fetch.py radlab` ✓ |
| 3 | Curiosity RAD (Hassler et al.) | Mars cruise 0.48 / surface 0.21 mGy/day | Mars presets | — | published values |
| 4 | [PhysioNet BIDSleep 1.0.1](https://physionet.org/content/bidsleep-dataset/1.0.1/) | `hr.csv` (~0.2 Hz HR) + `labels.mat` (EEG sleep stages, 30 s epochs), 47 adults, 253 nights. **Skips `motion.csv`** (that's most of the 6.4 GB zip) | Calibrate `sim_sd`/`person_sd` for HR & sleep; normal-night data | ~29 MB | `fetch.py bidsleep` ✓ (sha256-checked) |
| 5 | OSDR Inspiration4: [OSD-569](https://osdr.nasa.gov/bio/repo/data/studies/OSD-569), [OSD-575](https://osdr.nasa.gov/bio/repo/data/studies/OSD-575) | CBC (LSDS-7), CMP + serum immune/cardiovascular cytokine panels (LSDS-8). Skips RNA-seq | Analyzer signals, immune-risk anchors | 0.3 MB | `fetch.py inspiration4` ✓ |
| 6 | [NOAA SWPC](https://services.swpc.noaa.gov/json/goes/primary/) | GOES integral proton flux, rolling 7 days | Optional solar particle event | 1.7 MB | `fetch.py swpc` ✓ |

## Notes

- RadLab DosTel coverage ends mid-April 2022; earlier windows (2019–2021) also work if more history is needed.
- BIDSleep: cite the dataset and Song et al. (IEEE TBME 2025); split by subject, not night. Check its licence file in `data/raw/bidsleep/`.
- RadLab API syntax: `?spacecraft=ISS&instrument=DosTel&timestamp%3E=...&timestamp%3C...&<column>&format=csv`. Bare key = return column, `key=value` = filter.

## Gaps (simulated, labelled `provenance: simulated`)

Beat-to-beat in-flight HRV, reaction-test results, mood: no open astronaut data.
