# AURA-Bio Web Telemetry Console

Interactive astronaut physiological telemetry console for NASA Space Apps 2026.

## Overview
A lightweight, zero-dependency aeromedical monitoring web platform simulating real-time physiological telemetry, cross-system anomaly inference, and clinical emergency protocol execution.

## Key Features
- **Spatial Physiological Anatomy Map:** Anatomical astronaut silhouette with interactive concentric reticles across 6 subsystems (Neurocognitive, Mucosal Immune, Cardiovascular, Metabolic, Musculoskeletal, and ECLSS).
- **Dynamic Organ Zoom & Subsystem Carousel:** 1-tap organ detail inspection drawer with high-resolution anatomical vector visuals and quick-switch subsystem carousel.
- **Micro-Telemetry Sparklines:** Real-time sliding SVG sparklines calculated directly from physiological telemetry history, color-coded to status with dual-bound excursion markers.
- **Biomarker Subsystem Quick-Filters:** Filter telemetry by subsystem (`ALL`, `BREACHED`, `NEURO`, `CARDIO`, `IMMUNE`, `METAB`, `SKEL`, `ECLSS`).
- **Clinical Actions & Protocols Modal:** Central pop-up emergency protocol widget with interactive crew checklists, Houston CAPCOM guidance, and peer-reviewed scientific citations.
- **Aerospace Web Audio API Telemetry Cues:** Native zero-dependency sound synthesis for NASA Caution chimes (amber), emergency alarms (red), and tactile UI feedback.
- **Psychomotor Vigilance Task (PVT-90) & Daily Check-in:** Real-time micro-sleep lapse detection, reaction latency recording, and subjective readiness reporting.
- **Multi-Mission Environmental Profiles:** Pre-configured orbit telemetry presets for ISS LEO, Artemis Lunar Base, Mars Transit, and Mars Surface.

## Tech Stack
- **Backend:** FastAPI (Python 3.10+), Uvicorn, WebSockets, Pydantic
- **Frontend:** Pure HTML5, Modern CSS (Design Tokens, Responsive Flex/Grid, Native Glassmorphism), Vanilla JavaScript ES6+
- **Charting & Visuals:** Chart.js, Native Inline SVG Sparklines, Transparent Medical HUD Graphics

## Quickstart

```bash
cd web
pip install -r requirements.txt
uvicorn app:app --host 127.0.0.1 --port 8000 --reload
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) in any modern browser (desktop or handheld tablet).
