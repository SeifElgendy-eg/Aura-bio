# AURA-Bio console design

The console remains a calm operating instrument, served by the existing FastAPI core with vanilla HTML/CSS/JS. Public Sans and every required console asset are local. This refinement implements the requested interactive web-sourced silhouette, urgency colors, larger type, progressive disclosure and light mode; it does not replace the backend, timeline or games.

## Astronaut operating priorities

Keep status, current crew, mission day, ground delay, connection state and next onboard actions visible. Use static red and amber alarms with written levels, never flashing animation or color alone. Alerts retain their backend reason, cited crew response, medical-team response, mission wording and acknowledgment. Resolved and acknowledged episodes recede; acknowledgment does not mean resolution. Long explanations and citations use native Show more sections. Nonmedical, simulated-data and game-save/offline statements remain visible.

The body selector and onboard-action column lead into a full-width mission timeline. Each of six regions has an equivalent named button and Enter/Space operation. The SVG is clipped to the public-domain Wikimedia human silhouette; habitat/radiation is a frame around the body, not an organ. Region mappings are symbolic selectors. Immune function is body-wide; bone/muscle currently uses exercise completion, not direct bone measurements. Metabolic remains not measured. No region implies anatomical diagnosis.

## Tokens and type

Dark is the default for low-light mission use: ground `#0f1216`, panel `#1a1e24`, ink `#e6e1d5`; red `#e5574f`, amber `#e0a33a`, green `#3fb27f`. Light mode is an explicit display choice for brighter ambient conditions: ground `#f1f2ef`, panel `#ffffff`, ink `#182321`, red `#ba302b`, amber `#976000`, green `#18744b`. Each theme has separate high-contrast status-text colors, muted ink, rules, focus and chart-baseline fill. Store only the local theme preference, with denied-storage fallback. Theme the charts and native controls as well as panels.

Body text is 17px, primary controls 16px with at least 44px height, explanatory copy 15–16px, fine-print and compact status labels 14–15px, section headings 19–20px, status headline 25px. Retain tabular numerals, restrained 1px rules, compact radii and no glow/film-HUD decoration. System state is color plus words; unknown is dotted and overdue is hatched/dashed. The backend supplies all bands, limits and responses.

## Disclosure and interruptions

Critical alert reason and crew response remain outside disclosure. Action evidence, medical response, sources, model scores and detailed signal limits may collapse. Preserve focus on system controls during telemetry updates and preserve open signal-limit disclosures. A visible connection-lost headline marks the remaining colors as last-known readings; do not desaturate away alarm urgency. Keep the canonical 90-second reaction test and its 355ms cutoff unchanged.

## Evidence boundary

Keyboard/browser checks and rendered dark/light review are engineering checks, not astronaut usability, flight certification, clinical validation or full assistive-technology testing. No new threshold, model calibration or measurement is introduced. Asset source and exact original checksum are in `web/static/images/SOURCES.md`.
