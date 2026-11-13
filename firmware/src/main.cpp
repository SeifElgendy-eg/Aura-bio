#include <Arduino.h>
#include <math.h>
#include <stdio.h>

#define CREW_ID   "cm1"
#define TS        "2026-11-14T10:00:00Z"
#define PERIOD_MS 2000

// Wokwi virtual ADCs use a fixed 5.0 V reference (docs.wokwi.com/chips-api/analog),
// while the custom chips output 0..3.3 V per docs/wokwi-requirements.md.
// Change ADC_VREF to 3.3f if flashing to physical ESP32 hardware.
#define ADC_VREF  5.0f
#define CHIP_VMAX 3.3f

#define PIN_PULSE_ON  25
#define PIN_VIRAL     26

struct AnalogSignal {
  const char *name;
  uint8_t pin;
  float lo;
  float hi;
  int decimals;
  bool requires_pulse;
};

static const AnalogSignal ANALOG_SIGNALS[] = {
  {"resting_hr_bpm",     34, 30.0f,   130.0f, 1, true},
  {"rmssd_ms",           35,  0.0f,   200.0f, 1, true},
  {"cabin_co2_mmhg",     32,  0.0f,    10.0f, 2, false},
  {"lymphocytes_per_ul", 33,  0.0f,  6000.0f, 0, false},
  {"il6_pg_ml",          36,  0.0f,    25.0f, 1, false},
  {"nk_activity_pct",    39,  0.0f,   150.0f, 1, false},
};

static void print_reading(const char *signal, float value, int decimals) {
  char line[256];
  snprintf(
      line,
      sizeof(line),
      "{\"crew_id\":\"%s\",\"ts\":\"%s\",\"signal\":\"%s\",\"value\":%.*f,\"source\":\"wokwi\",\"provenance\":\"simulated\"}",
      CREW_ID,
      TS,
      signal,
      decimals,
      value);
  Serial.println(line);
}

static float read_scaled(const AnalogSignal &sig) {
  int raw = analogRead(sig.pin);
  float voltage = ADC_VREF * (raw / 4095.0f);
  float val = sig.lo + (sig.hi - sig.lo) * (voltage / CHIP_VMAX);
  if (val < sig.lo) val = sig.lo;
  if (val > sig.hi) val = sig.hi;
  if (sig.decimals == 0) {
    val = roundf(val);
  }
  return val;
}

void setup() {
  Serial.begin(115200);
  analogReadResolution(12);
  pinMode(PIN_PULSE_ON, INPUT);
  pinMode(PIN_VIRAL, INPUT);
}

void loop() {
  bool pulse_on = (digitalRead(PIN_PULSE_ON) == HIGH);

  for (size_t i = 0; i < sizeof(ANALOG_SIGNALS) / sizeof(ANALOG_SIGNALS[0]); i++) {
    const AnalogSignal &sig = ANALOG_SIGNALS[i];
    if (sig.requires_pulse && !pulse_on) {
      continue;
    }
    print_reading(sig.name, read_scaled(sig), sig.decimals);
  }

  int viral = (digitalRead(PIN_VIRAL) == HIGH) ? 1 : 0;
  print_reading("viral_pcr_positive", (float)viral, 0);

  delay(PERIOD_MS);
}
