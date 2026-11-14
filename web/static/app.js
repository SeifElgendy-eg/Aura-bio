/* AURA-Bio console. Every number, band and alert comes from the core service (core/app.py); this file only
   lays them out. Signal names are the contract's (contract/signals.yaml). */
'use strict';

// ---------- vocabulary ----------
const LANES = [
  { id: 'neuro', name: 'Neurocognitive', sub: 'Sleep, reaction, mood', systems: ['neurocognitive'] },
  { id: 'cardio', name: 'Cardiovascular', sub: 'HR, HRV, BP', systems: ['cardiovascular'] },
  { id: 'immune', name: 'Immune', sub: 'Weekly labs', systems: ['immune'] },
  { id: 'bone', name: 'Bone & muscle', sub: 'Exercise', systems: ['bone_muscle'] },
  { id: 'habitat', name: 'Habitat & radiation', sub: 'CO₂, dose', systems: ['environment', 'radiation'] },
  { id: 'metab', name: 'Metabolic', sub: 'No signal yet', systems: [] },
];
const NAMES = {
  sleep_duration_h: 'Sleep duration', sleep_efficiency_pct: 'Sleep efficiency', reaction_lapses_pct: 'Reaction-test lapses',
  mood_score: 'Mood', lymphocytes_per_ul: 'Lymphocytes', nk_activity_pct: 'NK cell activity', il6_pg_ml: 'IL-6',
  viral_pcr_positive: 'Viral PCR (EBV, CMV, VZV)', resting_hr_bpm: 'Resting heart rate', rmssd_ms: 'HRV (RMSSD)',
  bp_systolic_mmhg: 'Systolic blood pressure', exercise_completion_pct: 'Exercise completion',
  cabin_co2_mmhg: 'Cabin CO₂', dose_mgy: 'Daily radiation dose', cumulative_dose_msv: 'Dose to date',
};
const UNITS = { bpm: ' bpm', ms: ' ms', mmhg: ' mmHg', h: ' h', pct: '%', ul: ' /µL', ml: ' pg/mL', mgy: ' mGy', msv: ' mSv', score: '/10' };
const PRESET_NAMES = { station: 'ISS station', moon: 'Moon', mars_transit: 'Mars transit', mars_surface: 'Mars surface' };
const RANK = { unknown: 0, green: 1, stale: 2, amber: 3, red: 4 };
const WORD = { red: 'Red', amber: 'Amber', green: 'Within limits', stale: 'Data overdue', unknown: 'Not measured' };
const PVT_MS = 90000, LAPSE_MS = 355;  // plan 4.6; lapse cut-off = core's checkin.lapse_ms (Basner et al. 2011)

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const nameOf = (sig) => NAMES[sig] || sig;
const unitOf = (sig) => (sig === 'viral_pcr_positive' ? '' : UNITS[sig.split('_').pop()] ?? '');
const round = (v) => (v == null ? null : Math.abs(v) >= 100 ? Math.round(v) : Math.round(v * 10) / 10);
const fmt = (sig, v) => (v == null ? '—' : sig === 'viral_pcr_positive' ? (v ? 'Positive' : 'Negative') : `${round(v)}${unitOf(sig)}`);
const lower = (s) => (/^[A-Z][A-Z₂0-9]/.test(s) ? s : s.charAt(0).toLowerCase() + s.slice(1));
// a single-signal alert is named "<signal> red" by the core: show the signal's own name
const alertName = (n) => (n && n.endsWith(' red') && NAMES[n.slice(0, -4)] ? `${NAMES[n.slice(0, -4)]} red` : n);
const worst = (bands) => bands.reduce((w, b) => (RANK[b] > RANK[w] ? b : w), 'unknown');
const getJson = (url) => fetch(url).then((r) => (r.ok ? r.json() : null));

// ---------- state ----------
let crew = null;           // crew id shown
let status = null;         // /crew/<id>/status
let timeline = null;       // /crew/<id>/timeline
let mission = null;        // /mission
let range = 'all';
let linkUp = false;
let lastPush = null;
let lastDayTs = null;
const history = {};        // signal -> trend points, loaded for the signals view

// ---------- loading ----------
async function loadCrew() {
  const [st, tl] = await Promise.all([getJson(`/crew/${crew}/status`), getJson(`/crew/${crew}/timeline`)]);
  status = st;
  timeline = tl;
  lastDayTs = st && st.ts;
  for (const k in history) delete history[k];
}

async function init() {
  mission = await getJson('/mission');
  const ids = (await getJson('/crew')) || [];
  crew = sessionStorageGet('crew') || ids[0] || 'cm1';
  if (ids.length && !ids.includes(crew)) crew = ids[0];
  await loadCrew();
  linkUp = true;
  lastPush = new Date();
  connect();
  route();
  render();
}

function sessionStorageGet(k) { try { return sessionStorage.getItem(k); } catch { return null; } }
function sessionStorageSet(k, v) { try { sessionStorage.setItem(k, v); } catch { /* private mode */ } }

function connect() {
  const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`);
  ws.onopen = () => { linkUp = true; renderLive(); };
  ws.onmessage = async (e) => {
    const st = JSON.parse(e.data);
    lastPush = new Date();
    if (!st) return;
    if (st.crew_id !== crew) { if (view() === 'crew') renderCrew(); return; }
    status = st;
    if (st.ts !== lastDayTs) {  // a new simulated day: lanes and trends move
      lastDayTs = st.ts;
      timeline = await getJson(`/crew/${crew}/timeline`);
      for (const k in history) delete history[k];
    }
    render();
  };
  ws.onclose = () => { linkUp = false; renderLive(); setTimeout(connect, 3000); };
}

// ---------- derived facts ----------
function missionDay() { return timeline && timeline.days.length ? timeline.days[timeline.days.length - 1].day : null; }
function laneBand(systems, lane) {
  return lane.systems.length ? worst(lane.systems.map((s) => systems[s] || 'unknown')) : 'unknown';
}
function flagged() {
  return Object.entries(status.signals)
    .filter(([, e]) => e.value != null && RANK[e.band] >= RANK.stale)
    .sort((a, b) => RANK[b[1].band] - RANK[a[1].band]);
}
const liveAlerts = () => status.alerts.filter((a) => a.active && !a.acknowledged_at);
const toReview = () => status.alerts.filter((a) => !a.acknowledged_at);
function dayOf(ts) {
  if (!timeline || !ts) return null;
  return Math.floor((Date.parse(ts) - Date.parse(timeline.first_ts)) / 864e5) + 1;
}
function baselineDay() {
  const d = missionDay();
  return d != null && timeline && d <= timeline.baseline_days ? d : null;
}
function limitsOf(sig, e) {
  const out = [];
  for (const r of [].concat(e.rule || [])) {
    const base = e.baseline_mean;
    for (const lvl of ['amber', 'red']) {
      const t = r[lvl];
      if (t == null) continue;
      const up = r.direction === 'above';
      const v = r.kind === 'abs' ? t : base == null ? null
        : r.kind === 'delta' ? base + (up ? t : -t) : base * (1 + (up ? t : -t) / 100);
      out.push({ lvl, text: v == null ? `${lvl} ${up ? '+' : '−'}${t}${r.kind === 'pct' ? '%' : ''} from baseline`
        : `${lvl} ${up ? '>' : '<'} ${fmt(sig, v)}`, basis: r.basis, citation: r.citation });
    }
  }
  return out;
}

// ---------- status band (NFR-8) ----------
function headline() {
  if (!status) return { band: 'unknown', text: `No readings yet for ${String(crew).toUpperCase()}.`, soft: 'Open the mission panel to replay a scenario.' };
  const who = String(crew).toUpperCase();
  const top = flagged();
  const live = liveAlerts();
  const eps = (timeline ? timeline.episodes : []).filter((e) => e.pattern_id);
  const lastEp = eps.length ? eps.find((e) => e.pattern_id === eps[eps.length - 1].pattern_id) : null;  // onset of the latest pattern
  const band = worst([...top.map(([, e]) => e.band), ...live.map((a) => a.level)]);
  const act = mission ? `${mission.alert_wording}.` : '';
  const bday = baselineDay();
  if (bday && !top.length) {
    return { band: 'unknown', word: 'Baseline',
      text: `${who}: building your personal baseline, day ${bday} of ${timeline.baseline_days}.`,
      soft: 'Bands that compare you with yourself start after the baseline period.' };
  }
  if (!top.length && !live.length) {
    return { band: 'green', text: `${who}: every measured signal is within your personal limits.`,
      soft: lastEp ? `Last pattern: ${lower(lastEp.name)}, day ${lastEp.start_day}.` : '' };
  }
  if (live.length) {
    const a = live[0];
    return { band, text: `${who}: ${lower(a.name)} since day ${dayOf(a.started_ts)}${live.length > 1 ? `, plus ${live.length - 1} more alert${live.length > 2 ? 's' : ''}` : ''}.`, soft: act };
  }
  const [sig, e] = top[0];
  let what;
  if (e.band === 'stale') what = `${lower(nameOf(sig))} reading is overdue`;
  else if (e.baseline_mean != null) {
    what = `${lower(nameOf(sig))} ${fmt(sig, e.value)} is ${e.value < e.baseline_mean ? 'below' : 'above'} your ${fmt(sig, e.baseline_mean)} baseline`;
  } else what = `${lower(nameOf(sig))} ${fmt(sig, e.value)} is past its ${e.band} limit`;
  const after = lastEp ? `, after ${lower(lastEp.name)} from day ${lastEp.start_day}` : '';
  return { band, text: `${who}: ${what}${after}.`, soft: act };
}

function renderStatus() {
  const h = linkUp ? headline() : { band: 'offline', word: 'Offline',
    text: 'Connection to the core service lost.', soft: `Showing data from ${lastPush ? lastPush.toLocaleTimeString() : 'earlier'}; retrying.` };
  const b = $('s-band');
  b.className = `band ${h.band}`;
  b.textContent = h.word || WORD[h.band] || h.band;
  $('s-head').innerHTML = `${esc(h.text)}${h.soft ? ` <span class="soft">${esc(h.soft)}</span>` : ''}`;
  const n = status ? toReview().length : 0;
  const rv = $('s-review');
  rv.hidden = !n;
  rv.textContent = `Review ${n} alert${n === 1 ? '' : 's'}`;
}

function renderMeta() {
  $('m-crew').textContent = crew ? String(crew).toUpperCase() : '—';
  if (mission) {
    $('m-name').textContent = PRESET_NAMES[mission.name] || mission.name;
    const d = mission.one_way_delay_s;
    $('m-delay').textContent = d < 1 ? '0 s' : d < 60 ? `${d} s` : `${Math.round(d / 60)} min`;
  }
  $('m-day').textContent = missionDay() ?? '—';
  document.querySelectorAll('.crew-id').forEach((el) => { el.textContent = String(crew).toUpperCase(); });
}

function renderLive() {
  const el = $('live');
  el.className = `live${linkUp ? '' : ' lost'}`;
  el.textContent = linkUp ? `Live · updated ${lastPush ? lastPush.toLocaleTimeString() : ''}` : 'Connection lost · retrying';
  document.body.classList.toggle('link-lost', !linkUp);
  renderStatus();
}

// ---------- timeline (signature) ----------
function domain() {
  const last = missionDay() || 1;
  if (range === 'baseline') return [1, Math.max(timeline ? timeline.baseline_days : 14, 2)];
  if (range === 'last7') return [Math.max(1, last - 6), Math.max(last, 2)];
  return [1, Math.max(last, 2)];
}

function renderTimeline() {
  const box = $('lanes');
  $('tl-empty').hidden = !!(timeline && timeline.days.length);
  if (!timeline || !timeline.days.length) { box.innerHTML = ''; return; }
  const [d0, d1] = domain();
  const span = d1 - d0 + 1;
  const x = (day) => ((day - d0) / span) * 100;          // left edge of a day, in %
  const days = timeline.days.filter((d) => d.day >= d0 && d.day <= d1);
  const now = status ? status.systems : {};

  const lanesHtml = LANES.map((lane) => {
    const cur = laneBand(now, lane);
    if (!lane.systems.length) {
      return `<div class="lane"><div class="lane-label"><b>${lane.name}</b><small>${lane.sub}</small></div>
        <div class="track"><div class="not-measured">Not measured</div></div></div>`;
    }
    // consecutive days in one non-green band become one run
    const runs = [];
    for (const d of days) {
      const band = laneBand(d.systems, lane);
      const last = runs[runs.length - 1];
      if (!['amber', 'red', 'stale'].includes(band)) continue;
      if (last && last.band === band && last.to === d.day - 1) last.to = d.day; else runs.push({ band, from: d.day, to: d.day });
    }
    const runHtml = runs.map((r) => `<div class="run ${r.band}" style="left:${x(r.from)}%;width:${(r.to - r.from + 1) / span * 100}%"
      title="${WORD[r.band]} · day ${r.from}${r.to > r.from ? `–${r.to}` : ''}"></div>`).join('');
    return `<div class="lane"><div class="lane-label"><b>${lane.name}</b>
      <small><span class="now ${cur}">${WORD[cur]}</span> · ${lane.sub}</small></div>
      <div class="track">${runHtml}</div></div>`;
  }).join('');

  const tickEvery = span > 30 ? 5 : span > 10 ? 2 : 1;
  const ticks = [];
  for (let d = d0; d <= d1; d++) if (d === d0 || d % tickEvery === 0) ticks.push(`<span style="left:${x(d)}%">${d === d0 ? `D${d}` : d}</span>`);

  // overlay: baseline zone, today, and the brackets where systems moved together
  const laneIdx = (sys) => LANES.findIndex((l) => l.systems.includes(sys));
  const H = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--lane-h')) || 64;
  const bEnd = timeline.baseline_days;
  let over = '';
  if (d0 <= bEnd) over += `<div class="baseline-zone" style="left:0;width:${Math.min(x(bEnd + 1), 100)}%"><span>Personal baseline · days 1–${bEnd}</span></div>`;
  const today = missionDay();
  if (today >= d0 && today <= d1) over += `<div class="today" style="left:${x(today + 0.5)}%"><span>Day ${today} · today</span></div>`;
  const seen = {};
  for (const ep of timeline.episodes) {
    if (ep.start_day < d0 || ep.start_day > d1) continue;
    const idx = ep.systems.map(laneIdx).filter((i) => i >= 0);
    if (!idx.length) continue;
    const cx = x(ep.start_day + 0.5);
    if (!ep.pattern_id) {  // a single signal red by a published limit: a marker on its lane
      over += `<div class="marker" style="left:${cx}%;top:${(idx[0] + 0.5) * H}px" title="${esc(nameOf(ep.signal))} red · day ${ep.start_day}"></div>`;
      continue;
    }
    const top = (Math.min(...idx) + 0.5) * H, bottom = (Math.max(...idx) + 0.5) * H;
    const recur = seen[ep.pattern_id];
    seen[ep.pattern_id] = true;
    const dots = idx.map((i) => `<span class="dot ${ep.level}" style="top:${(i + 0.5) * H - top - 5.5}px"></span>`).join('');
    over += `<div class="bracket${recur ? ' recur' : ''}" style="left:${cx}%;top:${top}px;height:${Math.max(bottom - top, 1)}px">${dots}</div>`;
    const state = ep.active ? (ep.acknowledged ? 'active, acknowledged' : 'active') : ep.acknowledged ? 'resolved' : 'resolved, to review';
    const labelTop = recur ? top - 22 : top + Math.max((bottom - top) / 2 - 24, 8);
    const side = cx > 55 ? `right:${100 - cx + 0.6}%` : `left:${cx + 0.6}%`;
    over += recur
      ? `<button type="button" class="blabel recur" style="${side};top:${labelTop}px" data-alert="${ep.alert_id}">Again day ${ep.start_day}</button>`
      : `<button type="button" class="blabel" style="${side};top:${labelTop}px" data-alert="${ep.alert_id}">
          <b>${esc(ep.name)}</b><small>Day ${ep.start_day} · ${ep.systems.length} systems · ${state}</small></button>`;
  }
  box.innerHTML = `${lanesHtml}<div class="axis"><div></div><div class="ticks">${ticks.join('')}</div></div>
    <div class="overlay">${over}</div>`;
}

// ---------- what to do ----------
function renderTodo() {
  const list = $('todo');
  if (!status) { list.innerHTML = ''; $('todo-cite').textContent = ''; return; }
  const steps = [], seen = new Set(), cites = new Set();
  const add = (text, detail) => {
    const t = text.trim().replace(/\.$/, '');
    if (t && !seen.has(t)) { seen.add(t); steps.push({ t, detail }); }
  };
  const sentences = (s) => (s || '').split(/(?<=\.)\s+/);
  const live = liveAlerts();
  const top = flagged();
  if ((live.length || top.some(([, e]) => e.band !== 'stale')) && mission) {
    const d = mission.one_way_delay_s;
    add(mission.alert_wording, `${PRESET_NAMES[mission.name] || mission.name}: ${d < 1 ? 'real-time link to the ground' : `${d < 60 ? `${d} s` : `${Math.round(d / 60)} min`} one-way delay`}`);
  }
  for (const a of live) {
    const crewText = a.response_crew || (a.response || {}).crew;
    const why = Object.entries(a.fired || {}).map(([k, f]) => `${nameOf(k)} ${fmt(k, f.value)}`).join(' · ');
    sentences(crewText).forEach((s, i) => add(s, i ? '' : why));
    (a.citation || '').split(/;\s*/).forEach((c) => c && cites.add(c));
  }
  for (const [sig, e] of top) {
    if (e.band === 'stale') { add(`Check the ${lower(nameOf(sig))} sensor`, 'Its reading is overdue'); continue; }
    const detail = `${nameOf(sig)} ${fmt(sig, e.value)}${e.baseline_mean != null ? `, baseline ${fmt(sig, e.baseline_mean)}` : ''}`;
    sentences((e.response || {}).crew).forEach((s, i) => add(s, i ? '' : detail));
    for (const r of [].concat(e.rule || [])) (r.citation || '').split(/;\s*/).forEach((c) => c && cites.add(c));
  }
  if (!steps.length) add('Nothing outside your limits; keep your normal routine', 'Take today’s check-in if you have not yet');
  list.innerHTML = steps.slice(0, 5).map((s) => `<li><div>${esc(s.t)}${s.detail ? `<small>${esc(s.detail)}</small>` : ''}</div></li>`).join('');
  $('todo-cite').textContent = cites.size ? `Sources: ${[...cites].slice(0, 3).join('; ')}` : '';
}

// ---------- body map (FR-7) ----------
const FIGURE = {  // stylised outline; one part per system, the habitat drawn as the room around the body
  habitat: '<rect class="part" data-lane="habitat" x="4" y="4" width="112" height="192" rx="10"/>',
  neuro: '<circle class="part" data-lane="neuro" cx="60" cy="30" r="13"/>',
  immune: '<path class="part" data-lane="immune" d="M53 46h14v8H53z"/>',
  cardio: '<path class="part" data-lane="cardio" d="M42 58h36l3 40H39z"/>',
  metab: '<path class="part" data-lane="metab" d="M41 102h38l-2 26H43z"/>',
  bone: '<path class="part" data-lane="bone" d="M44 132h14l-2 56h-9zM62 132h14l-3 56h-9zM38 60l-10 50h7l9-42zM82 60l10 50h-7l-9-42z"/>',
};
function renderBody() {
  const sys = status ? status.systems : {};
  $('figure').innerHTML = Object.values(FIGURE).join('');
  const bands = {};
  for (const lane of LANES) bands[lane.id] = laneBand(sys, lane);
  document.querySelectorAll('#figure .part').forEach((p) => p.classList.add(bands[p.dataset.lane]));
  $('figure').setAttribute('aria-label', `Body map: ${LANES.map((l) => `${l.name} ${WORD[bands[l.id]].toLowerCase()}`).join(', ')}`);
  $('systems').innerHTML = LANES.map((l) => `<li><span>${l.name}</span><span class="now ${bands[l.id]}">${WORD[bands[l.id]]}</span></li>`).join('');
  if (!status) { $('scores').innerHTML = ''; return; }
  const a = status.anomaly || {};
  const ir = status.immune_risk || {};
  const dose = status.signals.cumulative_dose_msv;
  const perModel = Array.isArray(a.scores) ? a.scores.map((v, i) => `${['2-day model', 'EWMA'][i] || `model ${i + 1}`} ${round(v)}`)
    : Object.entries(a.scores || {}).map(([k, v]) => `${k} ${round(v)}`);
  $('scores').innerHTML = `
    <div><dt>Anomaly score</dt><dd>${a.available ? `<b>${round(a.score)}</b><small>alarm at 1 · ${esc(perModel.join(' · '))}</small>` : '<small>model unavailable</small>'}</dd></div>
    <div><dt>Immune risk</dt><dd>${ir.score == null ? '<small>waiting for lab baselines</small>' : `<b>${Math.round(ir.score)}</b>/100<small>placeholder weights</small>`}</dd></div>
    <div><dt>Dose to date</dt><dd>${dose && dose.value != null ? `<b>${round(dose.value)} mSv</b><small>${round(dose.pct_of_limit)}% of the 600 mSv career limit</small>` : '—'}</dd></div>`;
}

// ---------- alerts (FR-6) ----------
function alertHtml(a) {
  const fired = Object.entries(a.fired || {});
  const crewText = a.response_crew || (a.response || {}).crew || '';
  const sysText = a.response_system || (a.response || {}).system || '';
  const cites = a.citation || [].concat(a.rule || []).map((r) => r.citation).join('; ');
  const basis = a.basis || ([].concat(a.rule || []).some((r) => r.basis === 'published') ? 'published' : 'proposed');
  const state = a.active ? (a.acknowledged_at ? 'Active · acknowledged' : 'Active') : 'Resolved · to review';
  return `<article class="alert" id="alert-${a.alert_id}">
    <div class="alert-head"><span class="lvl ${a.level}">${a.level}</span><b>${esc(a.id ? a.name : `${nameOf(a.signal)} red`)}</b>
      <span class="state${a.active ? ' live' : ''}">${state}</span></div>
    <p class="sub">${a.id ? 'Cross-system pattern' : 'Single signal past a published limit'} · from day ${dayOf(a.started_ts) ?? '?'}${a.last_ts !== a.started_ts ? ` to day ${dayOf(a.last_ts)}` : ''}</p>
    <h4>Why this alert</h4>
    <p>${fired.map(([k, f]) => `${esc(nameOf(k))} ${esc(fmt(k, f.value))} (${f.band})`).join(' · ')}${(a.not_measured || []).length ? ` · not measured: ${esc(a.not_measured.join(', '))}` : ''}</p>
    ${crewText ? `<h4>Suggested response · crew</h4><p>${esc(crewText)}</p>` : ''}
    ${sysText ? `<h4>Suggested response · medical team</h4><p>${esc(sysText)}</p>` : ''}
    ${a.action ? `<h4>This mission</h4><p>${esc(a.action)}</p>` : ''}
    <p class="cite">Source: ${esc(cites)} · ${basis} threshold</p>
    ${a.acknowledged_at ? '' : `<div class="acts"><button type="button" data-ack="${a.alert_id}">Acknowledge</button></div>`}
  </article>`;
}
function openAlerts(focusId) {
  const list = status ? [...status.alerts].sort((x, y) => y.active - x.active || y.alert_id - x.alert_id) : [];
  // one card per alert kind; repeat episodes of the same pattern or signal are listed under it
  const groups = new Map();
  for (const a of list) {
    const k = a.id || `signal:${a.signal}`;
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(a);
  }
  $('da-list').innerHTML = list.length ? [...groups.values()].map(([first, ...rest]) => alertHtml(first) + rest.map((a) => `
    <div class="alert again" id="alert-${a.alert_id}"><p>Also from day ${dayOf(a.started_ts) ?? '?'}${a.last_ts !== a.started_ts ? ` to day ${dayOf(a.last_ts)}` : ''}
      · ${a.active ? 'active' : 'resolved'} · ${Object.entries(a.fired || {}).map(([k, f]) => `${esc(nameOf(k))} ${esc(fmt(k, f.value))}`).join(' · ')}</p>
      ${a.acknowledged_at ? '' : `<button type="button" data-ack="${a.alert_id}">Acknowledge</button>`}</div>`).join('')).join('')
    : '<p class="sub">No alerts to review.</p>';
  $('d-alerts').showModal();
  const el = focusId && $(`alert-${focusId}`);
  if (el) el.scrollIntoView({ block: 'start' });
}
async function acknowledge(id, btn) {
  btn.disabled = true;
  btn.textContent = 'Acknowledging…';
  const r = await fetch(`/alerts/${id}/ack`, { method: 'POST' }).catch(() => null);
  if (!r || !r.ok) { btn.disabled = false; btn.textContent = 'Not saved, try again'; return; }
  status = await getJson(`/crew/${crew}/status`);
  timeline = await getJson(`/crew/${crew}/timeline`);
  render();
  if ($('d-alerts').open) openAlerts();
}

// ---------- signals (FR-10, FR-11) ----------
async function loadHistory() {
  if (!status) return;
  const sigs = Object.keys(status.signals).filter((s) => s !== 'cumulative_dose_msv' && !history[s]);
  await Promise.all(sigs.map(async (s) => { history[s] = await getJson(`/crew/${crew}/signal/${s}?days=30`); }));
}
function spark(sig) {
  const h = history[sig];
  if (!h || h.points.length < 2) return '<span class="sub">—</span>';
  const v = h.points.map((p) => p.value);
  const lo = Math.min(...v, h.baseline_mean ?? Infinity), hi = Math.max(...v, h.baseline_mean ?? -Infinity);
  const y = (val) => 26 - ((val - lo) / (hi - lo || 1)) * 24;
  const d = v.map((val, i) => `${i ? 'L' : 'M'}${(i / (v.length - 1) * 118 + 1).toFixed(1)} ${y(val).toFixed(1)}`).join(' ');
  const base = h.baseline_mean != null ? `<path class="base" d="M1 ${y(h.baseline_mean)}H119"/>` : '';
  return `<svg class="spark" viewBox="0 0 120 28" aria-hidden="true">${base}<path d="${d}"/></svg>`;
}
async function renderSignals() {
  if (!status) { $('sig-rows').innerHTML = ''; return; }
  await loadHistory();
  const rows = [];
  for (const lane of LANES.filter((l) => l.systems.length)) {
    const sigs = Object.entries(status.signals).filter(([, e]) => lane.systems.includes(e.system));
    if (!sigs.length) continue;
    rows.push(`<tr class="group"><td colspan="6">${lane.name}</td></tr>`);
    for (const [sig, e] of sigs) {
      const lims = limitsOf(sig, e);
      const prov = e.provenance && e.provenance !== 'simulated' ? `<span class="tag">${esc(e.provenance)}</span>` : '';
      const baseTxt = e.baseline_mean != null ? fmt(sig, e.baseline_mean) : sig === 'cumulative_dose_msv' ? 'derived' : 'building';
      rows.push(`<tr>
        <td><button type="button" class="rowbtn" data-signal="${sig}">${esc(nameOf(sig))}</button>${prov}</td>
        <td>${esc(fmt(sig, e.value))}</td>
        <td>${esc(baseTxt)}</td>
        <td class="lim">${lims.length ? lims.map((l) => `${esc(l.text)}<span class="tag">${l.basis}</span>`).join('<br>') : 'no rule'}</td>
        <td><span class="now ${e.band}">${WORD[e.band]}</span></td>
        <td>${sig === 'cumulative_dose_msv' ? '' : spark(sig)}</td></tr>`);
    }
  }
  $('sig-rows').innerHTML = rows.join('');
}

let chart = null;
async function openSignal(sig) {
  const e = status.signals[sig];
  const h = await getJson(`/crew/${crew}/signal/${sig}?days=400`);
  $('ds-title').textContent = nameOf(sig);
  $('ds-sub').textContent = `Now ${fmt(sig, e.value)} · ${WORD[e.band]}${e.baseline_mean != null ? ` · your baseline ${fmt(sig, e.baseline_mean)} ± ${fmt(sig, e.baseline_sd)}` : ''}`;
  const lims = limitsOf(sig, e);
  $('ds-cite').textContent = lims.length ? `Limits: ${lims.map((l) => `${l.text} (${l.basis})`).join(' · ')}. Source: ${[...new Set(lims.map((l) => l.citation))].join('; ')}` : 'No limit rule for this signal.';
  $('d-signal').showModal();
  if (!window.Chart || !h) return;
  const pts = h.points.map((p) => ({ x: dayOf(p.ts), y: p.value }));
  const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const flat = (v) => pts.map((p) => ({ x: p.x, y: v }));
  const sets = [{ label: nameOf(sig), data: pts, borderColor: css('--ink'), borderWidth: 2, pointRadius: 0, tension: 0.2 }];
  if (h.baseline_mean != null) {
    sets.push({ label: 'Baseline + 1 SD', data: flat(h.baseline_mean + h.baseline_sd), borderWidth: 0, pointRadius: 0, fill: '+1', backgroundColor: 'rgba(230,225,213,0.08)' });
    sets.push({ label: 'Baseline − 1 SD', data: flat(h.baseline_mean - h.baseline_sd), borderWidth: 0, pointRadius: 0 });
    sets.push({ label: 'Your baseline', data: flat(h.baseline_mean), borderColor: css('--mute'), borderDash: [4, 4], borderWidth: 1, pointRadius: 0 });
  }
  for (const l of lims) {
    const m = l.text.match(/[<>] (-?[\d.]+)/);
    if (m) sets.push({ label: `${l.lvl} limit`, data: flat(parseFloat(m[1])), borderColor: l.lvl === 'red' ? css('--red') : css('--amber'), borderWidth: 1, pointRadius: 0 });
  }
  if (chart) chart.destroy();
  chart = new window.Chart($('ds-chart'), {
    type: 'line', data: { datasets: sets },
    options: { animation: false, maintainAspectRatio: false, parsing: false,
      scales: { x: { type: 'linear', title: { display: true, text: 'Mission day', color: css('--mute') }, ticks: { color: css('--mute') }, grid: { color: css('--rule') } },
        y: { ticks: { color: css('--mute') }, grid: { color: css('--rule') } } },
      plugins: { legend: { labels: { color: css('--mute'), filter: (i) => !i.text.includes('SD') } } } },
  });
}

// ---------- check-in (FR-12) ----------
const pvt = { running: false, go: false, t0: 0, end: 0, timer: null, trials: [] };
const touched = { mood: false, ex: false };
function pvtPress() {
  const btn = $('pvt');
  if (!pvt.running) {
    Object.assign(pvt, { running: true, go: false, trials: [], end: Date.now() + PVT_MS });
    $('pvt-big').textContent = 'Wait';
    $('pvt-state').textContent = 'Press when the panel turns light';
    btn.className = 'pvt wait';
    pvtSchedule();
  } else if (pvt.go) {
    const rt = Date.now() - pvt.t0;
    pvt.trials.push(rt);
    pvt.go = false;
    btn.className = 'pvt wait';
    $('pvt-big').textContent = `${rt} ms`;
    pvtStats();
    if (Date.now() >= pvt.end) pvtDone(); else pvtSchedule();
  } else {
    $('pvt-state').textContent = 'Too early: wait for the light';
  }
}
function pvtSchedule() {
  clearTimeout(pvt.timer);
  pvt.timer = setTimeout(() => {  // 1-4 s between stimuli, as in PVT-B
    pvt.go = true;
    pvt.t0 = Date.now();
    $('pvt').className = 'pvt go';
    $('pvt-big').textContent = 'Now';
    $('pvt-state').textContent = 'Press now';
  }, 1000 + Math.random() * 3000);
}
function pvtStats() {
  const n = pvt.trials.length;
  $('pvt-n').textContent = n;
  $('pvt-mean').textContent = n ? `${Math.round(pvt.trials.reduce((a, b) => a + b, 0) / n)} ms` : '—';
  $('pvt-lapses').textContent = pvt.trials.filter((t) => t >= LAPSE_MS).length;
  $('pvt-left').textContent = pvt.running ? `${Math.max(0, Math.ceil((pvt.end - Date.now()) / 1000))} s` : 'done';
}
function pvtDone() {
  clearTimeout(pvt.timer);
  pvt.running = false;
  $('pvt').className = 'pvt';
  $('pvt-big').textContent = 'Done';
  $('pvt-state').textContent = `${pvt.trials.length} trials recorded. Press to take it again.`;
  pvtStats();
}
async function sendCheckin(ev) {
  ev.preventDefault();
  const out = $('ci-result');
  const body = { crew_id: crew, values: {} };
  if (touched.mood) body.mood_answers = [parseFloat($('ci-mood').value)];
  // shortcut: 60 min of exercise = 100% completion (the console's old assumption); use the real prescription when known
  if (touched.ex) body.values.exercise_completion_pct = Math.min(100, (parseFloat($('ci-ex').value) / 60) * 100);
  if (pvt.trials.length) body.reaction_times_ms = pvt.trials;
  if (!body.mood_answers && !body.reaction_times_ms && !touched.ex) {
    out.className = 'result err';
    out.textContent = 'Nothing to send yet: take the reaction test or answer a question.';
    return;
  }
  const btn = $('ci-send');
  btn.disabled = true;
  btn.textContent = 'Sending…';
  try {
    const r = await fetch('/checkin', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    if (!r.ok) throw new Error(`the core answered ${r.status}`);
    const res = await r.json();
    out.className = 'result ok';
    out.textContent = `Sent for day ${missionDay() ?? '?'}: ${res.accepted.map(nameOf).join(', ')}.${res.rejected.length ? ` Not accepted: ${res.rejected.join(', ')}.` : ''}`;
  } catch (err) {
    out.className = 'result err';
    out.textContent = `Not sent (${err.message}). Your answers are kept; try again.`;
  } finally {
    btn.disabled = false;
    btn.textContent = 'Send check-in';
  }
}

// ---------- crew (FR-17) and ground reports (FR-16) ----------
async function renderCrew() {
  const cards = (await getJson('/crew/overview')) || [];
  $('crew').innerHTML = cards.length ? cards.map((c) => {
    const open = c.alerts.filter((a) => a.active).length, review = c.alerts.length - open;
    return `<li class="card"><div class="who"><b>${esc(c.crew_id.toUpperCase())}</b><span class="band ${c.worst}">${WORD[c.worst]}</span></div>
      <dl><div><dt>Alerts</dt><dd>${open} active · ${review} to review</dd></div>
      <div><dt>Anomaly score</dt><dd>${c.anomaly_score == null ? '—' : round(c.anomaly_score)}</dd></div>
      <div><dt>Immune risk</dt><dd>${c.immune_risk == null ? '—' : `${Math.round(c.immune_risk)}/100`}</dd></div>
      <div><dt>Last reading</dt><dd>${new Date(c.ts).toUTCString().slice(5, 22)} UTC</dd></div></dl>
      <button type="button" data-crew="${esc(c.crew_id)}"${c.crew_id === crew ? ' disabled' : ''}>${c.crew_id === crew ? 'Showing' : 'Open'}</button></li>`;
  }).join('') : '<li class="sub">No crew members yet.</li>';
}
async function renderReports() {
  const r = await getJson('/ground/reports');
  if (!r) return;
  const pend = r.pending.map((p) => `<li class="card"><span class="pending">On its way · arrives in ${Math.ceil(p.release_in_s / 60)} min</span>
    <span class="when">Report ${p.report_id} · ${esc(p.crew_id.toUpperCase())}</span></li>`);
  const done = [...r.released].reverse().map((p) => `<li class="card"><b>${esc(p.crew_id.toUpperCase())} · ${esc(alertName(p.alert))}</b>
    <span class="when">${esc(p.level)} · ${esc(PRESET_NAMES[p.mission] || p.mission)} · ${new Date(p.ts).toUTCString().slice(5, 22)} UTC</span></li>`);
  $('reports').innerHTML = [...pend, ...done].join('') || '<li class="sub">No reports sent yet.</li>';
}

// ---------- mission panel (FR-13, FR-9 demo) ----------
function openMission() {
  const p = mission.presets;
  $('dm-presets').innerHTML = Object.entries(p).map(([id, v]) => `<label class="preset"><input type="radio" name="preset" value="${id}"${id === mission.name ? ' checked' : ''}>
    <span><b>${esc(PRESET_NAMES[id] || id)}</b><small>Delay ${v.one_way_delay_s < 1 ? 'real time' : v.one_way_delay_s < 60 ? `${v.one_way_delay_s} s` : `${Math.round(v.one_way_delay_s / 60)} min`} · dose ${v.dose_mgy_day} mGy/day · alerts read “${esc(v.alert_wording)}”</small></span></label>`).join('');
  $('dm-result').textContent = '';
  $('d-mission').showModal();
}
async function setPreset(id) {
  const r = await fetch('/mission', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ preset: id }) });
  if (r.ok) { const m = await r.json(); mission = { ...mission, ...m }; render(); }
}
async function replay() {
  const out = $('dm-result');
  const r = await fetch(`/scenario/${$('dm-scenario').value}?crew_id=${encodeURIComponent(crew)}&speed=${$('dm-speed').value}`, { method: 'POST' }).catch(() => null);
  if (!r || !r.ok) { out.className = 'result err'; out.textContent = 'Scenario not started; is the core running?'; return; }
  const s = await r.json();
  out.className = 'result ok';
  out.textContent = `Replaying ${s.days} days at ${s.seconds_per_day} s per day.`;
  status = null; timeline = null;
  render();
}

// ---------- views ----------
const VIEWS = ['health', 'signals', 'checkin', 'crew', 'reports'];
const view = () => (VIEWS.includes(location.hash.slice(1)) ? location.hash.slice(1) : 'health');
function route() {
  const v = view();
  for (const id of VIEWS) $(`v-${id}`).hidden = id !== v;
  document.querySelectorAll('.tabs a').forEach((a) => (a.dataset.view === v ? a.setAttribute('aria-current', 'page') : a.removeAttribute('aria-current')));
  if (v === 'signals') renderSignals();
  if (v === 'crew') renderCrew();
  if (v === 'reports') renderReports();
}
function render() {
  renderMeta();
  renderLive();
  renderTimeline();
  renderTodo();
  renderBody();
  if (view() === 'signals') renderSignals();
}

// ---------- events ----------
document.addEventListener('click', (e) => {
  const t = e.target.closest('button, [data-alert]');
  if (!t) return;
  if (t.dataset.close !== undefined) t.closest('dialog').close();
  else if (t.dataset.alert) openAlerts(t.dataset.alert);
  else if (t.dataset.ack) acknowledge(t.dataset.ack, t);
  else if (t.dataset.signal) openSignal(t.dataset.signal);
  else if (t.dataset.range) {
    range = t.dataset.range;
    document.querySelectorAll('.seg button').forEach((b) => b.setAttribute('aria-pressed', b === t));
    renderTimeline();
  } else if (t.dataset.crew) {
    crew = t.dataset.crew;
    sessionStorageSet('crew', crew);
    loadCrew().then(() => { location.hash = '#health'; render(); });
  } else if (t.id === 's-review') openAlerts();
  else if (t.id === 'm-mission') openMission();
  else if (t.id === 'dm-replay') replay();
  else if (t.id === 'pvt') pvtPress();
});
document.addEventListener('change', (e) => { if (e.target.name === 'preset') setPreset(e.target.value); });
document.addEventListener('keydown', (e) => {  // Space works anywhere on the check-in view once the test runs
  if (e.code === 'Space' && pvt.running && view() === 'checkin' && e.target.id !== 'pvt') { e.preventDefault(); pvtPress(); }
});
$('ci-mood').addEventListener('input', (e) => { touched.mood = true; e.target.classList.add('touched'); $('ci-mood-out').textContent = `${e.target.value} / 10`; });
$('ci-ex').addEventListener('input', (e) => { touched.ex = true; e.target.classList.add('touched'); $('ci-ex-out').textContent = `${e.target.value} min`; });
$('ci-form').addEventListener('submit', sendCheckin);
setInterval(() => { if (pvt.running) pvtStats(); }, 500);
window.addEventListener('hashchange', route);
window.addEventListener('resize', renderTimeline);

init().catch(() => {
  linkUp = false;
  renderLive();
  setTimeout(() => location.reload(), 5000);
});
