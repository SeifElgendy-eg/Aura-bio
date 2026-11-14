# AURA-Bio — data & model

NASA Space Apps 2026 · astronaut health monitoring. See `CLAUDE.md` for layout and commands.

```bash
uv sync && uv run pytest -q
uv run python -m model.train
uv run uvicorn model.service:app --port 8001
```

Container image for the model service (trains `artifacts/` first if missing):

```bash
deploy/model/build.sh
docker run --rm -p 8001:8001 --read-only --tmpfs /tmp aura-bio/model:local
```

See `deploy/model/README.md` for deployment details.
