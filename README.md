# AURA-Bio — data & model

NASA Space Apps 2026 · astronaut health monitoring. See `CLAUDE.md` for layout and commands.

```bash
uv sync && uv run pytest -q
uv run python -m model.train
uv run uvicorn model.service:app --port 8001
```
