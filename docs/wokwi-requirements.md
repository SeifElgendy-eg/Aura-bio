# Wokwi sensor layer: requirements

**Current focus: phase 1 — a working circuit.** An ESP32 and three custom chips, wired up, with the
sketch reading every value correctly and printing it in the message format. No network, no timeline, no
noise model yet; those are phase 2 (bottom of this page).

Numbers come from `contract/signals.yaml` (calibrated from real data, see `data/SOURCES.md`).

## 1. Parts

| Part | Role |
| --- | --- |
| ESP32 DevKit (Wokwi `board-esp32-devkit-c-v4`) | Reads the chips, builds messages |
| Custom chip **pulse** | Heart rate and HRV, plus an on/off line |
| Custom chip **co2** | Cabin CO₂ |
| Custom chip **analyzer** | Four lab values |

Custom chips: a `.chip.json` (pins + attributes) and a `.chip.c` each
([Wokwi Custom Chips API](https://docs.wokwi.com/chips-api/getting-started)). Attributes appear as
sliders in the simulator.

## 2. How each value reaches the ESP32

Phase 1 keeps it simple: **each value is an analog voltage (0–3.3 V)** that the chip sets from its
slider (`pin_dac_write`), and the ESP32 reads with `analogRead` (12-bit, 0–4095). Viral shedding and
the pulse sensor's on/off are digital pins.

Use **ADC1 pins only** (GPIO 32–39): ADC2 pins stop working on the ESP32 once WiFi is on, which phase 2
needs.

| Chip | Output pin → ESP32 pin | Signal | Value at 0 V | Value at 3.3 V | Slider default |
| --- | --- | --- | --- | --- | --- |
| pulse | `HR` → GPIO 34 | `resting_hr_bpm` | 30 | 130 | 60 |
| pulse | `HRV` → GPIO 35 | `rmssd_ms` | 0 | 200 | 55 |
| pulse | `ON` → GPIO 25 (digital) | sensor present | low = off | high = on | on |
| co2 | `CO2` → GPIO 32 | `cabin_co2_mmhg` | 0 | 10 | 2.2 |
| analyzer | `LYM` → GPIO 33 | `lymphocytes_per_ul` | 0 | 6000 | 2679 |
| analyzer | `IL6` → GPIO 36 | `il6_pg_ml` | 0 | 25 | 3.7 |
| analyzer | `NK` → GPIO 39 | `nk_activity_pct` | 0 | 150 | 100 |
| analyzer | `VIR` → GPIO 26 (digital) | `viral_pcr_positive` | low = 0 | high = 1 | 0 |

Both ends use the same `lo` and `hi` from the table (the values at 0 V and 3.3 V):

- **Chip** (slider value → voltage): `voltage = 3.3 * (value - lo) / (hi - lo)`
- **Sketch** (voltage → value): `value = lo + (hi - lo) * analogRead(pin) / 4095.0`

Ranges that don't start at 0 (heart rate starts at 30) give wrong readings if either side leaves out
`lo`: e.g. a chip outputting `3.3 * value / 130` for 60 bpm makes the sketch read 76 bpm.

Why these ranges: they cover normal values (defaults = the typical level in our data), every demo
scenario and every alert line in the plan:

- **Heart rate:** the deconditioning scenario is +12 bpm; the plan's red line is +20 over baseline.
- **HRV:** the sleep-debt scenario is −25%; the plan's red line is −35%.
- **CO₂:** the ISS cabin has ranged 1–9 mmHg; the plan's amber is 2.5–3 and red is above 3.
- **Lymphocytes:** they fell up to 48% after the Inspiration4 flight.
- **IL-6:** it rose up to 190% after the Inspiration4 flight.
- **NK activity:** ISS crew lost about 50% by flight day 90.

The chip sliders should use these same ranges, so what you set is what the ESP32 reads.

## 3. What the sketch does (phase 1)

Every 2 seconds (stand-in for "one simulated day" until phase 2):

1. Read all pins and convert to values (section 2).
2. If the pulse `ON` pin is low, skip `resting_hr_bpm` and `rmssd_ms` entirely (no message, not 0).
3. Print one JSON line per signal to Serial, in the contract format:

```json
{"crew_id":"cm1","ts":"2026-11-14T10:00:00Z","signal":"resting_hr_bpm","value":60.1,"source":"wokwi","provenance":"simulated"}
```

- `crew_id`: `cm1` for now (a `#define`).
- `ts`: fixed day-0 timestamp for now; phase 2 makes it advance.
- `value`: round to sensible precision (1 decimal for HR, RMSSD, IL-6, NK; 2 for CO₂; whole numbers for
  lymphocytes; 0 or 1 for viral).
- `source` is always `"wokwi"`, `provenance` always `"simulated"`.

Printing the exact message now means phase 2 only has to send the same lines over MQTT.

## 4. Done when

- [ ] The circuit runs in Wokwi (VS Code extension or wokwi.com) with the 3 chips wired as in section 2
- [ ] With sliders at their defaults, Serial shows 7 lines per cycle with values within ~1% of the defaults
- [ ] Moving each slider changes only its own value, across the full range
- [ ] Pulse `ON` off → the two pulse lines disappear; on → they come back
- [ ] Viral switch flips the value between 0 and 1
- [ ] Every printed line validates in Python: `Reading(**json.loads(line))` from `contract/schema.py`
- [ ] Project files committed under `firmware/` (`diagram.json`, `wokwi.toml`, sketch, chips)

## Phase 2 (later, not now)

Kept here so nothing is lost; to be detailed when phase 1 works.

- **MQTT:** publish each line to `aura/<crew_id>/<group>` (`vitals`, `cabin`, `labs`). Contract asks for
  QoS 1, but the usual Arduino library PubSubClient publishes QoS 0 only: pick another library or agree
  on QoS 0. Wokwi WiFi is `Wokwi-GUEST`; the local broker needs the Wokwi private gateway; public broker
  as fallback.
- **Timeline:** one message per *simulated day* (default 10 s per day), `ts` advancing from
  `2026-11-14T10:00:00Z`; labs only on days 0, 7, 14, …. Team decision: own day counter or a shared tick
  from the generator.
- **Realistic values:** personal level + day-to-day noise around the slider setting, using the spreads
  and persistence in `contract/signals.yaml` (e.g. CO₂ drifts slowly: persistence 0.87).
- **Scenarios:** sliders only, or scripted runs matching the generator's (team decision).
- **Living with the generator:** each signal for a given astronaut must come from one publisher only;
  the generator needs a `--skip-signals` option for that (data side, not built yet).
