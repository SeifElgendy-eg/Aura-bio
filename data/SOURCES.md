# Datasets (plan section 5)

Download everything here before the event; record URL + date + licence per file. Raw files go in
`data/raw/<source>/` (git-ignored), derived files in `data/processed/`. Nothing may hit a NASA server
during the demo (NFR-7). Datasets on the official challenge page take precedence over this list.

| # | Source | Provides | Used for | Status |
|---|--------|----------|----------|--------|
| 1 | NASA Environmental Data Application (OSDR) | ISS cabin CO2, temp, humidity | `cabin_co2_mmhg` normal baseline (currently sim_mean 2.0) | TODO download |
| 2 | NASA RadLab | ISS dose & flux by detector | Dose signal, station preset | TODO download |
| 3 | Curiosity RAD (Hassler et al.) | Mars cruise 0.48 / surface 0.21 mGy/day | Mars presets | published values |
| 4 | PhysioNet BIDSleep | 253 nights Apple Watch HR + motion, 47 adults | Calibrate `sim_sd`/`person_sd` for HR & sleep; normal-night training data | TODO download |
| 5 | OSDR Inspiration4 | Blood count, metabolic, CV, cytokine panels | Analyzer signals, immune-risk anchors | confirm downloads |
| 6 | NOAA SWPC proton flux | Live 5-min proton flux JSON | Optional solar particle event | open, no key |

## Gaps (simulated, labelled `provenance: simulated`)
Beat-to-beat in-flight HRV, reaction-test results, mood: no open astronaut data.
