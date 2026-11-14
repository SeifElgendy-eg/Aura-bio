# Integration outcomes

- [x] Preserve the backend-served calm timeline console and existing 90-second reaction check-in; import only the newly published game bundle, not the retired main/frontend UI.
- [x] Store completed sessions for the selected crew using six known game IDs, UUID retries, bounded finite raw performance and mission time. Keep game records out of canonical health readings, alerts, baselines and anomaly scoring. Preserve game history during demo replay; delete it on explicit crew deletion.
- [x] Export once through the shared completion hook without changing game visuals, scoring or timing; namespace browser game databases per crew. Rebuild both runtime archives reproducibly from committed source.
- [x] Launch the hub from Check-in with visible saving consent/context, show recent raw sessions, and retain unsent results with visible manual retry. An actual browser Speed Click round saved through Python → JS → core; a round with the core stopped was retained for manual retry.

- [x] Connect saved capture/stdin/optional ESP32 serial to the existing contract MQTT topics with QoS 1 acknowledgements, seven Wokwi-contract signals, preserved crew/time/source/provenance, visible invalid/delivery failures and no retained health readings. Verify synthetic bridge transport, duplicates, WebSocket/timeline delivery, restart persistence and queued delivery; compile both firmware environments and all three custom chips.
- [x] Port the finalized anomaly model and separate baked deployment image without importing the model branch's old UI or changing calibrated values. Use shared blended first-14-calendar-day normalization only for model inputs, missing=0 and cap=8; leave persisted health baselines/rules/charts unchanged. The supplied build script created missing default seed-0 artifacts locally; no redesign/tuning or registry pull was performed.
- [x] Verify the exact combined broker/core/model stack: direct-container score parity, rule continuation during model failure and score recovery, six raw game contracts with idempotence/crew-time separation, health/model isolation, core/game persistence, replay-preserved games and explicit isolated crew deletion. Full merged regression: 148 passed, 1 local-artifact test skipped; standalone model runtime: 43 checks passed.

Hardware and game component PRs #1 and #2 remain open and unmerged. The combined branch contains both components and the finalized model port, preserving the backend console.

Not verified: real Wokwi execution (requires WOKWI_CLI_TOKEN), actual serial device capture/flashing/calibration, real crew/clinical validation, or production auth/TLS. The game runtime still needs its external Pygbag/CDN assets on first load; do not claim it is fully offline.
