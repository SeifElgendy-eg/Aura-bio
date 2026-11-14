# AURA-Bio — data & model

NASA Space Apps 2026 · astronaut health monitoring. See `CLAUDE.md` for layout and commands.

```bash
uv sync && uv run pytest -q
uv run python -m model.train
uv run uvicorn model.service:app --port 8001
uv run uvicorn core.app:app --port 8000      # backend; or everything: docker compose up --build
```

Container image for the model service (trains `artifacts/` first if missing):

```bash
deploy/model/build.sh
docker run --rm -p 8001:8001 --read-only --tmpfs /tmp aura-bio/model:local
```

See `deploy/model/README.md` for deployment details.
The root Compose model service uses the baked `aura-bio/model:local` image and no host artifact
mount. On a fresh clone, run `deploy/model/build.sh` first; it trains only when artifacts are
missing. See `docs/model-integration.md` for the staged version, model-down behavior, and the
no-arbitrary-tuning boundary.
