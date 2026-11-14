# Lunar Arcade Hub — Pygbag WebAssembly build

This directory is the browser build of Lunar Arcade Hub, produced with
Pygbag 0.9.3. It is served by the Aura-Bio FastAPI app at:

`/lunar-arcade-hub/`

It is also available under `/static/lunar-arcade-hub/index.html`. Open the
clean URL above, then click the Pygbag start overlay once to unlock audio.
Progress is stored in the browser's localStorage.

Rebuild from the Lunar Arcade Hub project with:

```bash
./webapp/build_game.sh
cp -a webapp/static/game/. ../Aura-bio/web/static/lunar-arcade-hub/
```

The archive contains only runtime files. The Pygbag runtime is downloaded from
its CDN on first launch.
