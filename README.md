# AURA-Bio — data & model

NASA Space Apps 2026 · astronaut health monitoring. See `CLAUDE.md` for layout and commands.

```bash
uv sync && uv run pytest -q
uv run python -m model.train
uv run uvicorn model.service:app --port 8001
uv run uvicorn core.app:app --port 8000      # backend; or everything: docker compose up --build
```

For Wokwi/ESP32 Serial → the existing MQTT bus → core → web console, see
[`hardware/README.md`](hardware/README.md). Start just `broker core` to connect hardware without trained model artifacts.
