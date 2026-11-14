---
version: 1
slug: "web-static-index-html"
primary_target: "web/static/index.html"
related_targets: []
---

# Surface: AURA-Bio console (web/static/index.html)

Scope: the whole web console (every view: My health, Signals, Check-in, Crew overview, Ground reports, Mission panel, alert review, signal trend). Mode: Operate. Primary user: the astronaut; crew medical officer second. Judged on a projector and in recorded video.

Task: in five seconds, know the astronaut's status, what changed and what to do; then review alerts, open a signal's trend, take the daily check-in, switch crew, switch mission preset.

Constraints: status, bands, alerts and responses come from the core; nothing diagnostic; every value labelled with its provenance; limits tagged published or proposed; offline (vendored fonts and Chart.js); WCAG 2.2 AA.

## Direction contract

THESIS: Health as a mission timeline in mission days: one lane per body system, so systems drifting together line up vertically and the moment they moved together is drawn as a bracket. Refuses the category default of a KPI tile grid with separate charts and a glowing body hero.

OWN-WORLD: Flight-plan paper translated to a dark calm instrument: ground #0F1216, panel #1A1E24, ink #E6E1D5, ruled grid #2A2F37; colour only for status (amber #E0A33A, red #E5574F, green #3FB27F); one workhorse sans (Public Sans) with tabular numerals; 1px rules, 4-6px radii, no glows, no side stripes, no emoji.

STORY: The viewer reads the status sentence (band word, what drives it against the personal baseline, what changed and when, the preset's next action), sees on the timeline which systems moved and on which day, follows the numbered steps, and can acknowledge alerts or start the check-in.

FIRST VIEWPORT: Top bar with view tabs and crew, mission, delay, day. Full-width status band: band word chip, one-sentence headline, Review alerts and Start check-in. Main: timeline card (about 70% width) with six lanes over mission days, baseline days shaded, today marked, pattern brackets across lanes; right column: What to do (numbered steps with data lines and citation) and a body map card with the six systems and the two research scores. Footer: not-a-medical-device statement, baseline note, live/connection state.

FORM: Flight Plan Timeline, grounded candidate 1 of 7 (impeccable's pick, chosen by the user). seed:133797336be15447

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
