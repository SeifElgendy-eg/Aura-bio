# Integration outcomes

- [x] Preserve the backend-served calm timeline console and existing 90-second reaction check-in; import only the newly published game bundle, not the retired main/frontend UI.
- [x] Store completed sessions for the selected crew using six known game IDs, UUID retries, bounded finite raw performance and mission time. Keep game records out of canonical health readings, alerts, baselines and anomaly scoring. Preserve game history during demo replay; delete it on explicit crew deletion.
- [x] Export once through the shared completion hook without changing game visuals, scoring or timing; namespace browser game databases per crew. Rebuild both runtime archives reproducibly from committed source.
- [x] Launch the hub from Check-in with visible saving consent/context, show recent raw sessions, and retain unsent results with visible manual retry. An actual browser Speed Click round saved through Python → JS → core; a round with the core stopped was retained for manual retry.

Hardware integration is tracked separately in PR #1. Model integration is on a separate backend-based branch. The user's supplied `deploy/model/build.sh` path staged its seed-0 image locally; container health/API/restart checks passed. Core model-only scaling compatibility and the combined stack check are separate outcomes, not implied by game-save success.
