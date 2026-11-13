# AURA-Bio Wokwi Sensor Layer (Phase 1)

ESP32 DevKitC v4 (`board-esp32-devkit-c-v4`) + 3 custom Wokwi chips (`pulse`, `co2`, `analyzer`) printing one `Reading` JSON line per signal over Serial every 2 seconds.

No WiFi, MQTT, timeline, or noise yet (those belong to phase 2).

## Files

- `src/main.cpp` — ESP32 Arduino sketch reading ADC1 pins (`34`, `35`, `32`, `33`, `VP`/`36`, `VN`/`39`) and digital pins (`25`, `26`)
- `chips/{pulse,co2,analyzer}.chip.json` & `.chip.c` — custom Wokwi chips with interactive sliders
- `diagram.json` — circuit wiring with chip defaults
- `platformio.ini` & `wokwi.toml` — PlatformIO + Wokwi config
- `tools/validate_serial.py` — validates captured Serial lines against `contract/schema.py`

## Option A — Run locally (VS Code or Wokwi CLI)

1. **Build the firmware:**
   ```powershell
   & "$env:USERPROFILE\.platformio\penv\Scripts\pio.exe" run
   ```
2. **Compile the 3 custom chips to `.wasm`:**
   ```powershell
   $w = "$env:USERPROFILE\.wokwi\bin\wokwi-cli.exe"
   & $w chip compile -o chips/pulse.chip.wasm chips/pulse.chip.c
   & $w chip compile -o chips/co2.chip.wasm chips/co2.chip.c
   & $w chip compile -o chips/analyzer.chip.wasm chips/analyzer.chip.c
   ```
3. **Interactive in VS Code:**
   - Open `firmware/diagram.json`, press `F1`, and run **Wokwi: Start Simulator**.
   - Click each custom chip in the diagram to adjust its sliders and switches.
4. **Headless via Wokwi CLI** (requires `WOKWI_CLI_TOKEN`):
   ```powershell
   & "$env:USERPROFILE\.wokwi\bin\wokwi-cli.exe" . --timeout 10000 --serial-log-file unneeded/serial_capture.txt
   ```

## Option B — Run on wokwi.com

1. Open <https://wokwi.com> → **New Project** → **ESP32**.
2. Paste `src/main.cpp` into `sketch.ino`.
3. Replace `diagram.json` with `firmware/diagram.json`.
4. Add 6 new files via the editor menu (`pulse.chip.json`, `pulse.chip.c`, `co2.chip.json`, `co2.chip.c`, `analyzer.chip.json`, `analyzer.chip.c`). The browser compiles the `.chip.c` files automatically.
5. Click **Start the simulation**, click any chip to move its sliders, and copy Serial output into `firmware/unneeded/serial_capture.txt`.

## Validate Serial output

From the repo root:

```powershell
py firmware/tools/validate_serial.py firmware/unneeded/serial_capture.txt
py firmware/tools/validate_serial.py --expect-defaults firmware/unneeded/serial_capture.txt
```
