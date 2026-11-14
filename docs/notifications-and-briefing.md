# Crew notifications and lightweight briefing

Open the console and choose **Enable crew notifications** on each member’s device. Browser permission is requested only after that click. Every enrolled device receives the same crew alert regardless of the crew selected in its console. **Disable crew notifications** removes that device’s subscription. Connected consoles also show a crew-wide notice without browser-push permission; Review affected crew opens the relevant member, and Dismiss notice advances the bounded, red-first queue.

A stimulus is a **new backend alert episode or an amber-to-red escalation**. Repeated readings in the same episode do not generate new notices. This feature does not reinterpret every game flash or telemetry sample as a stimulus, change any threshold or model, or bypass the mission’s Earth-report delay.

## Briefing download

Choose **Ground reports → Download crew briefing · under 50 kB**, or request `GET /briefing`. This generates a UTF-8 `.txt` attachment directly from backend values, without an LLM. The maximum is **49,999 bytes**, strictly below decimal 50 kB even with Unicode content.

The briefing includes generation UTC, mission/delay, crew summary, urgency-first alerts, available reasons and fired values, cited crew responses, model/research context, and released/pending ground-report counts. Large inputs produce explicit omission counts and bounded previews, never a broken UTF-8 file. Pending report payloads, push endpoints, subscription keys and VAPID secrets are excluded. The response is `text/plain; charset=utf-8`, an attachment, and `Cache-Control: no-store`.

## Deployment and API

Install the repository’s locked dependencies with `uv sync`. Run one core worker with the existing SQLite database. Push is enabled by default; `AURA_NOTIFICATIONS=0` disables provider delivery while connected-console notices still work. `AURA_VAPID_SUBJECT` can override the default project HTTPS contact URL. A private VAPID PEM is generated beside `AURA_DB`, chmod 0600 and Git-ignored; preserve it with the database when moving hosts so existing subscriptions keep working. Never publish it.

`GET /notifications/config` exposes only enabled state and the public application key. `POST` and `DELETE /notifications/subscriptions` accept native `PushSubscription.toJSON()` objects. Enrollment is device-wide, capped at 200 devices, and validates trusted HTTPS browser-provider endpoints and P-256/auth keys. Public-demo enrollment requires a same-host browser origin and JSON content type, with the existing 64 KiB streamed request cap. All other protected mutations retain their admin boundary.

`GET /notifications?after=<cursor>` exposes at most 100 recent secret-free events for reconnect recovery. The updated console uses `/ws?notifications=1` to receive typed `{type:"notification",notification:...}` frames before its selected-crew filter. Legacy `/ws` stays status-only. The root-scope worker is served at `/notifications-sw.js`, does not intercept fetches, and accepts notification navigation only to the same-origin console. Games’ offline caches and saved results are unchanged.

Delivery uses bounded concurrency/timeouts and one transient retry. Expired 404/410 endpoints are pruned, and provider failure does not stop telemetry ingest. Historical events are drained on backend startup rather than broadcast as fresh alerts. This is best-effort browser push, not a durable delivery/acknowledgment system or a safety-certified alert channel.

## Verification and limits

The temporary HTTPS demo served the notification configuration, active root-scope service worker and briefing attachment successfully. A real public WSS test used two independent connections with different crew-view query parameters; both received event 1 for `demo_co2_creep`. The visible console stayed on `demo_normal` with its own status intact and displayed the other crew’s notice. Browser enrollment origin validation was exercised without registering a fake device. Dark/light renders showed the controls and banner without horizontal overflow at the inspected viewport.

The downloaded sample at 2026-11-14T08:35:13Z is **4,608 bytes**; Content-Length matches, UTF-8 decodes, and the download filename is `aura-bio-briefing.txt`. Unit/integration coverage includes new/escalated episode deduplication, all-enrolled-device fanout, real payload encryption with mocked provider transport, expiry pruning, bounded retries, subscription origin/key validation, Unicode/large-input briefing caps, root-worker headers, notification opt-in/out, queueing, click safety and unchanged status-only WebSocket behavior.

Actual mobile/OS push receipt has **not** been verified: the test browser remained at permission `default`. Each recipient must explicitly allow notifications. Internet, a live backend and browser/OS/provider settings affect background delivery; a fully terminated browser is not guaranteed to receive it. The public URL is still temporary and may stop when the sandbox sleeps. No paid hosting or Render resources were created, and no fresh Docker build was attempted during this update. All crew data remains simulated; AURA-Bio is not a medical device.

Browser platform references: [MDN Push API](https://developer.mozilla.org/en-US/docs/Web/API/Push_API) and [MDN PushManager.subscribe](https://developer.mozilla.org/en-US/docs/Web/API/PushManager/subscribe).

The final regression also exposed a race in the existing free-demo supervisor test: its fake readiness command returned before a child’s PID file was written, allowing immediate fake-core exit to kill it first. The fixture now waits boundedly for both fake children before exercising cleanup. The deployed supervisor script was not changed.

Final complete repository regression: **201 passed, 1 existing local-artifact skip, 1 existing Starlette/httpx deprecation warning**, in 143.18 seconds. Notification UI/worker checks and the original status-only mission/check-in WebSocket assertions passed; those legacy assertions were not weakened or replaced.
