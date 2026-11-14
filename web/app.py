import asyncio
import json
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional, Union
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(
    title="AURA-Bio Core (FastAPI + HTML/CSS/JS)",
    description="Astronaut Health Monitoring System with Backend-Driven Upper & Lower Threshold Bounds",
    version="2.3.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

LUNAR_HUB_DIR = BASE_DIR / "static" / "lunar-arcade-hub"
if LUNAR_HUB_DIR.is_dir():
    app.mount(
        "/lunar-arcade-hub",
        StaticFiles(directory=str(LUNAR_HUB_DIR), html=True),
        name="lunar-arcade-hub",
    )

# --- Pydantic Data Models (plan.pdf Section 4.2 & Bounds Specification) ---

class ThresholdBand(BaseModel):
    """
    Model for Upper and Lower physiological limits computed by the backend model.
    None indicates an unbounded direction (e.g. CO2 has no amber_low).
    """
    baseline: float
    baseline_min: float
    baseline_max: float
    amber_low: Optional[float] = None
    amber_high: Optional[float] = None
    red_low: Optional[float] = None
    red_high: Optional[float] = None
    unit: str
    expected_interval_s: int

class SensorReading(BaseModel):
    crew_id: str = "cm1"
    ts: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    signal: str
    value: float
    source: str = "generator"
    provenance: str = "simulated"
    # Status dynamically evaluated by backend model against dual bounds
    status: str = "green"  # green, amber, red, stale

class BiomarkerTelemetry(BaseModel):
    id: str
    name: str
    system_id: str
    reading: Optional[SensorReading]
    bounds: ThresholdBand
    history: List[Dict[str, Any]]

class CheckinPayload(BaseModel):
    crew_id: str = "cm1"
    ts: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    pvt_mean_reaction_time_ms: float
    pvt_lapses: int
    pvt_false_starts: int
    mood_score: float
    stress_score: float
    hydration_ml: float
    exercise_minutes: float

class PatternAlert(BaseModel):
    id: str
    crew_id: str
    pattern_name: str
    level: str  # amber or red
    signals_fired: List[str]
    involved_systems: List[str]
    medical_reason: str
    citation: str
    is_published: bool
    response_crew: List[str]
    response_medical: List[str]
    ts: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

class TelemetryIngestItem(BaseModel):
    signal: str
    value: float
    crew_id: str = "cm1"
    source: str = "external_api"
    provenance: str = "live"
    ts: Optional[str] = None

# --- Backend Model: Physiological Bounds Definition ---

model_threshold_registry: Dict[str, ThresholdBand] = {
    # 1. Neurocognitive
    "pvt_lapses": ThresholdBand(
        baseline=1.0, baseline_min=0.5, baseline_max=1.5,
        amber_low=None, amber_high=3.0,
        red_low=None, red_high=5.0,
        unit="lapses", expected_interval_s=86400
    ),
    "sleep_hours": ThresholdBand(
        baseline=7.4, baseline_min=7.0, baseline_max=8.0,
        amber_low=6.0, amber_high=9.5,
        red_low=5.0, red_high=11.0,
        unit="hrs", expected_interval_s=86400
    ),
    "mood_score": ThresholdBand(
        baseline=8.5, baseline_min=7.5, baseline_max=9.5,
        amber_low=5.0, amber_high=None,
        red_low=3.0, red_high=None,
        unit="/10", expected_interval_s=86400
    ),

    # 2. Cardiovascular (Two-Sided: Bradycardia / Tachycardia / Hypotension / Hypertension)
    "resting_hr": ThresholdBand(
        baseline=62.0, baseline_min=58.0, baseline_max=66.0,
        amber_low=48.0, amber_high=74.0,
        red_low=40.0, red_high=85.0,
        unit="bpm", expected_interval_s=10
    ),
    "rmssd_ms": ThresholdBand(
        baseline=48.0, baseline_min=42.0, baseline_max=54.0,
        amber_low=36.0, amber_high=70.0,
        red_low=28.0, red_high=85.0,
        unit="ms", expected_interval_s=10
    ),
    "bp_systolic": ThresholdBand(
        baseline=118.0, baseline_min=110.0, baseline_max=126.0,
        amber_low=95.0, amber_high=140.0,
        red_low=85.0, red_high=160.0,
        unit="mmHg", expected_interval_s=86400
    ),

    # 3. Mucosal & Immune (plan.pdf notes sIgA trigger is two-sided: rises or suppresses in flight)
    "salivary_siga": ThresholdBand(
        baseline=180.0, baseline_min=155.0, baseline_max=205.0,
        amber_low=130.0, amber_high=230.0,
        red_low=100.0, red_high=260.0,
        unit="µg/mL", expected_interval_s=86400
    ),
    "nk_activity": ThresholdBand(
        baseline=38.0, baseline_min=34.0, baseline_max=42.0,
        amber_low=28.0, amber_high=None,
        red_low=20.0, red_high=None,
        unit="% lysis", expected_interval_s=86400
    ),

    # 4. Metabolic & Nutrition (Dehydration vs Overhydration, Mass Wasting)
    "hydration_fluid_ml": ThresholdBand(
        baseline=2500.0, baseline_min=2300.0, baseline_max=2700.0,
        amber_low=1900.0, amber_high=3500.0,
        red_low=1500.0, red_high=4200.0,
        unit="mL", expected_interval_s=86400
    ),
    "body_mass_loss": ThresholdBand(
        baseline=0.0, baseline_min=-0.5, baseline_max=0.5,
        amber_low=-2.0, amber_high=2.0,
        red_low=-4.0, red_high=5.0,
        unit="% loss", expected_interval_s=86400
    ),

    # 5. Musculoskeletal
    "exercise_completion": ThresholdBand(
        baseline=100.0, baseline_min=95.0, baseline_max=105.0,
        amber_low=75.0, amber_high=None,
        red_low=60.0, red_high=None,
        unit="%", expected_interval_s=86400
    ),
    "ntx_resorption": ThresholdBand(
        baseline=35.0, baseline_min=30.0, baseline_max=40.0,
        amber_low=None, amber_high=55.0,
        red_low=None, red_high=75.0,
        unit="nM BCE", expected_interval_s=86400
    ),

    # 6. Habitat & Environment
    "cabin_co2_mmhg": ThresholdBand(
        baseline=2.0, baseline_min=1.8, baseline_max=2.2,
        amber_low=None, amber_high=2.8,
        red_low=None, red_high=3.2,
        unit="mmHg", expected_interval_s=5
    ),
    "cumulative_dose_mgy": ThresholdBand(
        baseline=0.45, baseline_min=0.40, baseline_max=0.50,
        amber_low=None, amber_high=0.85,
        red_low=None, red_high=1.2,
        unit="mGy", expected_interval_s=3600
    ),
}

systems_catalog = [
    {
        "id": "neuro",
        "name": "Neurocognitive",
        "icon": "🧠",
        "x": 0.50,
        "y": 0.065,
        "description": "Cognitive vigilance, sleep architecture, stress & mental fatigue",
        "biomarkers": ["pvt_lapses", "sleep_hours", "mood_score"],
    },
    {
        "id": "mucosal_immune",
        "name": "Mucosal & Immune",
        "icon": "🛡️",
        "x": 0.50,
        "y": 0.170,
        "description": "Salivary sIgA, lymphocyte counts, NK cytotoxicity & cytokines",
        "biomarkers": ["salivary_siga", "nk_activity"],
    },
    {
        "id": "cardio",
        "name": "Cardiovascular",
        "icon": "❤️",
        "x": 0.50,
        "y": 0.275,
        "description": "Cardiac workload, autonomic tone, blood pressure & pulse",
        "biomarkers": ["resting_hr", "rmssd_ms", "bp_systolic"],
    },
    {
        "id": "metabolic",
        "name": "Metabolic & Nutrition",
        "icon": "💧",
        "x": 0.50,
        "y": 0.400,
        "description": "Fluid balance, energy homeostasis, glucose & body composition",
        "biomarkers": ["hydration_fluid_ml", "body_mass_loss"],
    },
    {
        "id": "musculoskeletal",
        "name": "Musculoskeletal",
        "icon": "🦴",
        "x": 0.43,
        "y": 0.630,
        "description": "Bone mineral turnover, muscle atrophy & countermeasure compliance",
        "biomarkers": ["exercise_completion", "ntx_resorption"],
    },
    {
        "id": "environment",
        "name": "Habitat & CO₂",
        "icon": "🪐",
        "x": 0.18,
        "y": 0.180,
        "description": "Cabin atmospheric CO₂, ambient pressure & cumulative radiation",
        "biomarkers": ["cabin_co2_mmhg", "cumulative_dose_mgy"],
    },
]

biomarker_names = {
    "pvt_lapses": "PVT Reaction Lapses",
    "sleep_hours": "Sleep Duration",
    "mood_score": "Mood Index",
    "resting_hr": "Resting Heart Rate",
    "rmssd_ms": "HRV (RMSSD)",
    "bp_systolic": "Systolic Blood Pressure",
    "salivary_siga": "Salivary sIgA",
    "nk_activity": "NK Cell Cytotoxicity",
    "hydration_fluid_ml": "Daily Hydration Fluid",
    "body_mass_loss": "Body Mass Delta",
    "exercise_completion": "Exercise Target Completed",
    "ntx_resorption": "Urinary NTX (Bone Resorption)",
    "cabin_co2_mmhg": "Cabin CO₂ Pressure",
    "cumulative_dose_mgy": "Cumulative Radiation Dose",
}

# --- State Store ---

current_readings: Dict[str, SensorReading] = {}
history_store: Dict[str, List[Dict[str, Any]]] = {}

def evaluate_reading_status(signal_id: str, value: float) -> str:
    """Backend evaluation of whether reading breaches upper or lower bounds."""
    b = model_threshold_registry.get(signal_id)
    if not b:
        return "green"

    # Red Thresholds (Critical Upper or Lower)
    if b.red_high is not None and value >= b.red_high:
        return "red"
    if b.red_low is not None and value <= b.red_low:
        return "red"

    # Amber Thresholds (Warning Upper or Lower)
    if b.amber_high is not None and value >= b.amber_high:
        return "amber"
    if b.amber_low is not None and value <= b.amber_low:
        return "amber"

    return "green"

# Initialize nominal state
for sig_id, band in model_threshold_registry.items():
    current_readings[sig_id] = SensorReading(
        crew_id="cm1",
        signal=sig_id,
        value=band.baseline,
        source="system",
        provenance="simulated",
        status="green",
    )
    # Generate 10 nominal history points bounded by personal baseline
    spread = (band.baseline_max - band.baseline_min) / 2.0
    history_store[sig_id] = [
        {"time": f"-{10-i}m", "value": round(band.baseline + (random.random() - 0.5) * spread, 2)}
        for i in range(10)
    ]

active_alerts: List[PatternAlert] = []
checkin_records: List[CheckinPayload] = []

mission_presets = {
    "station": {
        "id": "station",
        "name": "ISS Low Earth Orbit",
        "delay": "< 0.3s (Real-time)",
        "dose_rate": "0.35 mGy/day",
        "alert_wording": "Alert Ground Flight Surgeon directly via Space-to-Ground 1",
    },
    "moon": {
        "id": "moon",
        "name": "Lunar Gateway / Artemis Base",
        "delay": "1.3s",
        "dose_rate": "0.40 mGy/day",
        "alert_wording": "Transmit telemetry packet to Houston CAPCOM",
    },
    "mars_transit": {
        "id": "mars_transit",
        "name": "Deep Space Mars Transit",
        "delay": "14m 00s",
        "dose_rate": "0.48 mGy/day",
        "alert_wording": "Autonomous triage: Execute onboard mitigation protocol; telemetry queued for delayed transmission",
    },
    "mars_surface": {
        "id": "mars_surface",
        "name": "Mars Surface Habitat",
        "delay": "8m 30s",
        "dose_rate": "0.21 mGy/day",
        "alert_wording": "Autonomous triage: Execute surface habitat protocol; report queued for delayed sync",
    },
}

current_preset_id = "mars_transit"

crew_members = [
    {"id": "cm1", "name": "Cmdr. Alex Vance", "role": "Mission Commander", "status": "amber", "anomaly": 0.72, "alerts": 1},
    {"id": "cm2", "name": "Dr. Elena Rostova", "role": "Crew Medical Officer", "status": "green", "anomaly": 0.18, "alerts": 0},
    {"id": "cm3", "name": "Lt. Mark Watney", "role": "Flight Engineer", "status": "green", "anomaly": 0.24, "alerts": 0},
    {"id": "cm4", "name": "Dr. Samantha Wu", "role": "Payload Specialist", "status": "green", "anomaly": 0.15, "alerts": 0},
]

# --- Cross-System Pattern Evaluation Engine ---

def evaluate_patterns():
    global active_alerts
    alerts = []

    co2 = current_readings.get("cabin_co2_mmhg")
    pvt = current_readings.get("pvt_lapses")

    if co2 and pvt and co2.status in ["amber", "red"] and pvt.status in ["amber", "red"]:
        is_red = (co2.status == "red" or pvt.status == "red")
        alerts.append(
            PatternAlert(
                id="alert_co2_neuro",
                crew_id="cm1",
                pattern_name="CO₂-Associated Neurocognitive Impairment",
                level="red" if is_red else "amber",
                signals_fired=["cabin_co2_mmhg", "pvt_lapses"],
                involved_systems=["environment", "neuro"],
                medical_reason="Elevated ambient CO₂ pressure exceeding upper threshold impairs executive decision speed and cognitive vigilance.",
                citation="Law et al., NASA TM-2014, Spaceflight CO₂ Thresholds",
                is_published=True,
                response_crew=[
                    "Check ECLSS CO₂ scrubber canister flow rate",
                    "Don emergency O2 mask if headache or visual tunnel persists",
                    "Verify secondary cabin ventilation ducting",
                ],
                response_medical=[
                    "Perform neurological symptom triage and visual check",
                    "Queue telemetry event for next ground transmission window",
                ],
            )
        )

    sleep = current_readings.get("sleep_hours")
    hrv = current_readings.get("rmssd_ms")
    siga = current_readings.get("salivary_siga")

    # Autonomic-Immune Exhaustion: sleep breached lower bound, HRV breached lower bound, sIgA breached lower OR upper bound
    if sleep and hrv and siga and sleep.status in ["amber", "red"] and hrv.status in ["amber", "red"] and siga.status in ["amber", "red"]:
        alerts.append(
            PatternAlert(
                id="alert_sleep_immune",
                crew_id="cm1",
                pattern_name="Autonomic-Immune Exhaustion Triad",
                level="red",
                signals_fired=["sleep_hours", "rmssd_ms", "salivary_siga"],
                involved_systems=["neuro", "cardio", "mucosal_immune"],
                medical_reason="Chronic sleep restriction driving sympathetic overactivity, vagal withdrawal, and mucosal sIgA dysregulation.",
                citation="Crucian et al., Frontiers in Immunology 2018",
                is_published=True,
                response_crew=[
                    "Mandate 60-minute sleep hygiene schedule block before duty",
                    "Restrict scheduled EVA spacewalk activities",
                    "Replenish oral electrolytes and micronutrients",
                ],
                response_medical=[
                    "Review actigraphy and polysomnography telemetry",
                    "Consider sleep countermeasure intervention",
                ],
            )
        )

    hr = current_readings.get("resting_hr")
    ex = current_readings.get("exercise_completion")
    if hr and ex and hr.status in ["amber", "red"] and ex.status in ["amber", "red"]:
        alerts.append(
            PatternAlert(
                id="alert_cardio_deconditioning",
                crew_id="cm1",
                pattern_name="Cardiovascular Deconditioning & Exercise Non-Compliance",
                level="amber",
                signals_fired=["resting_hr", "exercise_completion"],
                involved_systems=["cardio", "musculoskeletal"],
                medical_reason="Resting heart rate out-of-bounds combined with countermeasure deficit indicates autonomic deconditioning and stroke volume shift.",
                citation="Hargens et al., Journal of Applied Physiology 2013",
                is_published=True,
                response_crew=[
                    "Increase resistive flywheel exercise intensity to 85% VO2 max",
                    "Consume 500 mL electrolyte loading solution prior to scheduled shifts",
                ],
                response_medical=[
                    "Queue 12-lead resting ECG at next downlink window",
                    "Review lower body negative pressure (LBNP) protocol compliance",
                ],
            )
        )

    active_alerts = alerts
    crew_members[0]["status"] = "red" if any(a.level == "red" for a in alerts) else ("amber" if alerts else "green")
    crew_members[0]["alerts"] = len(alerts)

# --- WebSocket Broadcast Manager ---

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in list(self.active_connections):
            try:
                await connection.send_text(json.dumps(message))
            except Exception:
                pass

manager = ConnectionManager()

# --- Helper Payload Generator ---

def build_telemetry_payload():
    """Compiles the full telemetry packet with backend-driven bounds and status."""
    evaluate_patterns()
    biomarkers_dict = {}
    for sig_id, band in model_threshold_registry.items():
        rdg = current_readings.get(sig_id)
        biomarkers_dict[sig_id] = {
            "id": sig_id,
            "name": biomarker_names.get(sig_id, sig_id),
            "reading": rdg.model_dump() if rdg else None,
            "bounds": band.model_dump(),
            "history": history_store.get(sig_id, []),
        }

    return {
        "biomarkers": biomarkers_dict,
        "systems": systems_catalog,
        "alerts": [a.model_dump() for a in active_alerts],
        "mission": mission_presets[current_preset_id],
        "presets": mission_presets,
        "crew": crew_members,
    }

# --- Routes ---

@app.get("/")
def serve_index():
    return FileResponse(str(BASE_DIR / "static" / "index.html"))

@app.get("/health")
def health():
    return {"status": "ok", "service": "aura-bio-fastapi", "timestamp": datetime.now(timezone.utc).isoformat()}

@app.get("/api/telemetry")
def get_telemetry():
    return build_telemetry_payload()

@app.post("/api/telemetry/ingest")
async def ingest_external_telemetry(payload: Union[List[TelemetryIngestItem], TelemetryIngestItem]):
    """
    Ingestion endpoint for external backend APIs, telemetry bridges, or medical devices.
    Accepts single or batch sensor readings, evaluates dual-sided bounds,
    updates pattern detection, and broadcasts live over WebSocket to all clients.
    """
    items = payload if isinstance(payload, list) else [payload]
    now_iso = datetime.now(timezone.utc).isoformat()

    for r in items:
        status = evaluate_reading_status(r.signal, r.value)
        ts_val = r.ts or now_iso
        current_readings[r.signal] = SensorReading(
            crew_id=r.crew_id,
            signal=r.signal,
            value=r.value,
            source=r.source,
            provenance=r.provenance,
            status=status,
            ts=ts_val
        )
        if r.signal not in history_store:
            history_store[r.signal] = []
        history_store[r.signal].append({"time": "now", "value": r.value})
        if len(history_store[r.signal]) > 60:
            history_store[r.signal] = history_store[r.signal][-60:]

    full_payload = build_telemetry_payload()
    await manager.broadcast({
        "type": "telemetry_update",
        **full_payload,
    })
    return {
        "status": "ok",
        "ingested_count": len(items),
        "active_alerts": len(active_alerts),
        "timestamp": now_iso
    }

@app.post("/api/mission/preset/{preset_id}")
async def set_mission_preset(preset_id: str):
    global current_preset_id
    if preset_id in mission_presets:
        current_preset_id = preset_id
        await manager.broadcast({
            "type": "telemetry_update",
            **build_telemetry_payload(),
        })
        return {"status": "ok", "preset": mission_presets[current_preset_id]}
    return {"status": "error", "message": "Unknown preset"}

@app.post("/api/scenario/{scenario_id}")
async def trigger_scenario(scenario_id: str):
    if scenario_id == "co2_creep":
        val_co2 = 3.3
        val_pvt = 4.0
        current_readings["cabin_co2_mmhg"] = SensorReading(
            crew_id="cm1", signal="cabin_co2_mmhg", value=val_co2, status=evaluate_reading_status("cabin_co2_mmhg", val_co2)
        )
        current_readings["pvt_lapses"] = SensorReading(
            crew_id="cm1", signal="pvt_lapses", value=val_pvt, status=evaluate_reading_status("pvt_lapses", val_pvt)
        )
        history_store["cabin_co2_mmhg"].append({"time": "now", "value": val_co2})
        history_store["pvt_lapses"].append({"time": "now", "value": val_pvt})

    elif scenario_id == "sleep_debt":
        val_sleep = 4.8
        val_hrv = 26.0
        val_siga = 95.0
        current_readings["sleep_hours"] = SensorReading(
            crew_id="cm1", signal="sleep_hours", value=val_sleep, status=evaluate_reading_status("sleep_hours", val_sleep)
        )
        current_readings["rmssd_ms"] = SensorReading(
            crew_id="cm1", signal="rmssd_ms", value=val_hrv, status=evaluate_reading_status("rmssd_ms", val_hrv)
        )
        current_readings["salivary_siga"] = SensorReading(
            crew_id="cm1", signal="salivary_siga", value=val_siga, status=evaluate_reading_status("salivary_siga", val_siga)
        )
        history_store["sleep_hours"].append({"time": "now", "value": val_sleep})
        history_store["rmssd_ms"].append({"time": "now", "value": val_hrv})
        history_store["salivary_siga"].append({"time": "now", "value": val_siga})

    elif scenario_id == "deconditioning":
        val_hr = 78.0
        val_ex = 70.0
        current_readings["resting_hr"] = SensorReading(
            crew_id="cm1", signal="resting_hr", value=val_hr, status=evaluate_reading_status("resting_hr", val_hr)
        )
        current_readings["exercise_completion"] = SensorReading(
            crew_id="cm1", signal="exercise_completion", value=val_ex, status=evaluate_reading_status("exercise_completion", val_ex)
        )
        history_store["resting_hr"].append({"time": "now", "value": val_hr})
        history_store["exercise_completion"].append({"time": "now", "value": val_ex})

    elif scenario_id == "bradycardia":
        # Demonstrates lower bound red violation for Heart Rate (resting HR < 40 bpm)
        val_hr = 38.0
        current_readings["resting_hr"] = SensorReading(
            crew_id="cm1", signal="resting_hr", value=val_hr, status=evaluate_reading_status("resting_hr", val_hr)
        )
        history_store["resting_hr"].append({"time": "now", "value": val_hr})

    elif scenario_id == "siga_spike":
        # Demonstrates upper bound amber violation for Salivary sIgA (> 230 ug/mL)
        val_siga = 245.0
        current_readings["salivary_siga"] = SensorReading(
            crew_id="cm1", signal="salivary_siga", value=val_siga, status=evaluate_reading_status("salivary_siga", val_siga)
        )
        history_store["salivary_siga"].append({"time": "now", "value": val_siga})

    elif scenario_id == "sensor_loss":
        del current_readings["resting_hr"]
        del current_readings["rmssd_ms"]

    elif scenario_id == "reset":
        for sig_id, band in model_threshold_registry.items():
            base = band.baseline
            current_readings[sig_id] = SensorReading(
                crew_id="cm1", signal=sig_id, value=base, source="system", provenance="simulated", status="green"
            )
            history_store[sig_id].append({"time": "now", "value": base})

    await manager.broadcast({
        "type": "telemetry_update",
        **build_telemetry_payload(),
    })
    return {"status": "ok", "scenario": scenario_id, "active_alerts": len(active_alerts)}

@app.post("/api/checkin")
async def post_checkin(checkin: CheckinPayload):
    checkin_records.append(checkin)
    pvt_val = float(checkin.pvt_lapses)
    mood_val = checkin.mood_score
    hydr_val = checkin.hydration_ml
    ex_val = min(100.0, (checkin.exercise_minutes / 60.0) * 100)

    current_readings["pvt_lapses"] = SensorReading(
        crew_id=checkin.crew_id, signal="pvt_lapses", value=pvt_val, source="app", provenance="simulated",
        status=evaluate_reading_status("pvt_lapses", pvt_val)
    )
    current_readings["mood_score"] = SensorReading(
        crew_id=checkin.crew_id, signal="mood_score", value=mood_val, source="app", provenance="simulated",
        status=evaluate_reading_status("mood_score", mood_val)
    )
    current_readings["hydration_fluid_ml"] = SensorReading(
        crew_id=checkin.crew_id, signal="hydration_fluid_ml", value=hydr_val, source="app", provenance="simulated",
        status=evaluate_reading_status("hydration_fluid_ml", hydr_val)
    )
    current_readings["exercise_completion"] = SensorReading(
        crew_id=checkin.crew_id, signal="exercise_completion", value=ex_val, source="app", provenance="simulated",
        status=evaluate_reading_status("exercise_completion", ex_val)
    )

    history_store["pvt_lapses"].append({"time": "now", "value": pvt_val})
    history_store["mood_score"].append({"time": "now", "value": mood_val})
    history_store["hydration_fluid_ml"].append({"time": "now", "value": hydr_val})
    history_store["exercise_completion"].append({"time": "now", "value": ex_val})

    await manager.broadcast({
        "type": "telemetry_update",
        **build_telemetry_payload(),
    })
    return {"status": "saved", "count": len(checkin_records)}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    await websocket.send_text(json.dumps({
        "type": "telemetry_update",
        **build_telemetry_payload(),
    }))
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
