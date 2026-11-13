let telemetryData = null;
let currentMission = null;
let socket = null;
let trendChartInstance = null;
let activeSystemForModal = null;
let activeSignalForModal = null;

const systemCoords = {
  neuro: { x: 0.50, y: 0.065 },
  mucosal_immune: { x: 0.50, y: 0.170 },
  cardio: { x: 0.50, y: 0.275 },
  metabolic: { x: 0.50, y: 0.400 },
  musculoskeletal: { x: 0.43, y: 0.630 },
  environment: { x: 0.18, y: 0.180 },
};

const systemCircleLabels = {
  neuro: 'NEURO',
  cardio: 'CARDIO',
  mucosal_immune: 'IMMUNE',
  metabolic: 'METAB',
  musculoskeletal: 'SKEL',
  environment: 'ECLSS',
};

let currentFocusedOrganId = null;
let currentTopAlert = null;
let activeBiomarkerFilter = 'ALL';

// --- Core service adapter: the core (core/app.py) owns readings, baselines, bands and alerts; this maps its
// /crew/<id>/status onto the shape the UI below draws. Signal names are the contract's (contract/signals.yaml).
const CREW = 'cm1';
const SYSTEMS = [
  { id: 'neuro', name: 'Neurocognitive', icon: '🧠', description: 'Sleep, vigilance (reaction test) and mood',
    biomarkers: ['sleep_duration_h', 'sleep_efficiency_pct', 'reaction_lapses_pct', 'mood_score'] },
  { id: 'mucosal_immune', name: 'Immune', icon: '🛡️', description: 'Weekly labs: lymphocytes, NK activity, IL-6, viral PCR',
    biomarkers: ['lymphocytes_per_ul', 'nk_activity_pct', 'il6_pg_ml', 'viral_pcr_positive'] },
  { id: 'cardio', name: 'Cardiovascular', icon: '❤️', description: 'Resting heart rate, HRV and blood pressure',
    biomarkers: ['resting_hr_bpm', 'rmssd_ms', 'bp_systolic_mmhg'] },
  { id: 'metabolic', name: 'Metabolic & Nutrition', icon: '💧', description: 'No metabolic signal is measured yet',
    biomarkers: [] },
  { id: 'musculoskeletal', name: 'Musculoskeletal', icon: '🦴', description: 'Exercise countermeasure completion',
    biomarkers: ['exercise_completion_pct'] },
  { id: 'environment', name: 'Habitat & Radiation', icon: '🪐', description: 'Cabin CO₂, daily and cumulative radiation dose',
    biomarkers: ['cabin_co2_mmhg', 'dose_mgy', 'cumulative_dose_msv'] },
];
const ALL_BIOMARKER_ORDER = SYSTEMS.flatMap(x => x.biomarkers);
const SIGNAL_NAMES = {
  sleep_duration_h: 'Sleep Duration', sleep_efficiency_pct: 'Sleep Efficiency', reaction_lapses_pct: 'Reaction-Test Lapses',
  mood_score: 'Mood', lymphocytes_per_ul: 'Lymphocytes', nk_activity_pct: 'NK Cell Activity', il6_pg_ml: 'IL-6',
  viral_pcr_positive: 'Viral PCR (EBV/CMV/VZV)', resting_hr_bpm: 'Resting Heart Rate', rmssd_ms: 'HRV (RMSSD)',
  bp_systolic_mmhg: 'Systolic Blood Pressure', exercise_completion_pct: 'Exercise Completion',
  cabin_co2_mmhg: 'Cabin CO₂', dose_mgy: 'Daily Radiation Dose', cumulative_dose_msv: 'Cumulative Effective Dose',
};
const UNITS = { bpm: 'bpm', ms: 'ms', mmhg: 'mmHg', h: 'h', pct: '%', ul: '/µL', ml: 'pg/mL', mgy: 'mGy', msv: 'mSv',
  score: '/10', positive: '' };
const PRESET_NAMES = { station: 'ISS Low Earth Orbit', moon: 'Lunar Surface', mars_transit: 'Mars Transit',
  mars_surface: 'Mars Surface' };
let presetCatalog = {};
const signalHistory = {};  // signal -> [{time, value}], seeded from the trend endpoint, extended by live pushes

const round2 = v => (v == null || Number.isNaN(v) ? null : Math.round(v * 100) / 100);
const systemOfSignal = sig => (SYSTEMS.find(x => x.biomarkers.includes(sig)) || {}).id;

function boundsOf(sig, e) {
  const base = e.baseline_mean, sd = e.baseline_sd;
  const b = { baseline: round2(base), baseline_min: round2(base - sd), baseline_max: round2(base + sd),
    amber_low: null, amber_high: null, red_low: null, red_high: null,
    unit: UNITS[sig.split('_').pop()] ?? '', expected_interval_s: 86400 };
  for (const rule of [].concat(e.rule || [])) {
    const up = rule.direction === 'above';
    const at = t => (t == null ? null : rule.kind === 'abs' ? t : base == null ? null
      : rule.kind === 'delta' ? base + (up ? t : -t) : base * (1 + (up ? t : -t) / 100));
    for (const lvl of ['amber', 'red']) {
      const v = round2(at(rule[lvl]));
      if (v == null) continue;
      const key = `${lvl}_${up ? 'high' : 'low'}`;
      // several rules on one side: keep the one that triggers first
      b[key] = b[key] == null ? v : (up ? Math.min(b[key], v) : Math.max(b[key], v));
    }
  }
  return b;
}

function presetView(id, p) {
  const d = p.one_way_delay_s;
  return { id, name: PRESET_NAMES[id] || id, alert_wording: p.alert_wording,
    delay: d < 1 ? 'Real time' : d < 60 ? `${d} s` : `~${Math.round(d / 60)} min`,
    dose_rate: `${p.dose_mgy_day} mGy/day` };
}

function alertView(a) {
  const fired = a.fired || {};
  return {
    id: String(a.alert_id), crew_id: CREW, level: a.level, ts: a.started_ts,
    is_pattern: Boolean(a.id), active: a.active, acknowledged: Boolean(a.acknowledged_at),
    pattern_name: a.id ? a.name : `${SIGNAL_NAMES[a.signal] || a.signal} red`,
    signals_fired: Object.keys(fired),
    involved_systems: [...new Set(Object.keys(fired).map(systemOfSignal).filter(Boolean))],
    medical_reason: Object.entries(fired).map(([k, f]) => `${SIGNAL_NAMES[k] || k}: ${round2(f.value)} (${f.band})`)
      .join(' · ') + ((a.not_measured || []).length ? ` · not measured: ${a.not_measured.join(', ')}` : ''),
    citation: a.citation || [].concat(a.rule || []).map(r => r.citation).join('; '),
    is_published: a.basis ? a.basis === 'published' : true,
    response_crew: [a.response_crew || (a.response || {}).crew].filter(Boolean),
    response_medical: [a.response_system || (a.response || {}).system, a.action].filter(Boolean),
  };
}

function toTelemetry(status, overview) {
  const signals = (status && status.signals) || {};
  const biomarkers = {};
  for (const sig of ALL_BIOMARKER_ORDER) {
    const e = signals[sig] || {};
    const reading = e.value == null ? null : { crew_id: CREW, signal: sig, value: e.value, ts: e.ts,
      status: e.band, provenance: e.provenance, source: 'core' };
    const h = (signalHistory[sig] = signalHistory[sig] || []);
    if (reading && reading.ts && (!h.length || h[h.length - 1].ts !== reading.ts)) {
      h.push({ ts: reading.ts, time: reading.ts.slice(5, 10), value: reading.value });
      if (h.length > 60) h.shift();
    }
    biomarkers[sig] = { id: sig, name: SIGNAL_NAMES[sig] || sig, system_id: systemOfSignal(sig), reading,
      bounds: boundsOf(sig, e), history: h };
  }
  const m = status && status.mission;
  return {
    biomarkers, systems: SYSTEMS,
    // active first; resolved ones stay until acknowledged
    alerts: ((status && status.alerts) || []).map(alertView).sort((x, y) => y.active - x.active),
    mission: m ? presetView(m.name, m) : currentMission,
    presets: Object.fromEntries(Object.entries(presetCatalog).map(([id, p]) => [id, presetView(id, p)])),
    crew: (overview || []).map(c => ({ id: c.crew_id, name: c.crew_id.toUpperCase(), role: 'Crew member',
      status: c.worst, anomaly: c.anomaly_score || 0, alerts: c.alerts.length })),
    anomaly: status && status.anomaly, immune_risk: status && status.immune_risk,
    disclaimer: status && status.disclaimer,
  };
}

async function loadTelemetry(status) {
  const getJson = url => fetch(url).then(r => (r.ok ? r.json() : null));
  const [st, overview] = await Promise.all([status ? status : getJson(`/crew/${CREW}/status`), getJson('/crew/overview')]);
  telemetryData = toTelemetry(st, overview);
  if (telemetryData.mission) currentMission = telemetryData.mission;
}

async function seedHistory() {
  await Promise.all(ALL_BIOMARKER_ORDER.filter(s => s !== 'cumulative_dose_msv').map(async sig => {
    const r = await fetch(`/crew/${CREW}/signal/${sig}?days=30`);
    if (r.ok) signalHistory[sig] = (await r.json()).points.map(p => ({ ts: p.ts, time: p.ts.slice(5, 10), value: p.value }));
  }));
}

// --- Native Audio Telemetry Cues (Web Audio API - Ponytail standard zero-dependency) ---
let audioEnabled = true;
let audioCtx = null;
let lastAlertSoundTimestamp = 0;
let lastHighestAlertLevel = 'green';

function getAudioContext() {
  if (!audioCtx) {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (AudioContextClass) {
      audioCtx = new AudioContextClass();
    }
  }
  if (audioCtx && audioCtx.state === 'suspended') {
    audioCtx.resume();
  }
  return audioCtx;
}

function playCautionCue() {
  if (!audioEnabled) return;
  try {
    const ctx = getAudioContext();
    if (!ctx) return;
    const now = ctx.currentTime;
    const osc1 = ctx.createOscillator();
    const gain1 = ctx.createGain();
    osc1.frequency.setValueAtTime(520, now);
    gain1.gain.setValueAtTime(0.08, now);
    gain1.gain.exponentialRampToValueAtTime(0.001, now + 0.14);
    osc1.connect(gain1);
    gain1.connect(ctx.destination);
    osc1.start(now);
    osc1.stop(now + 0.14);

    const osc2 = ctx.createOscillator();
    const gain2 = ctx.createGain();
    osc2.frequency.setValueAtTime(659.25, now + 0.15);
    gain2.gain.setValueAtTime(0.08, now + 0.15);
    gain2.gain.exponentialRampToValueAtTime(0.001, now + 0.35);
    osc2.connect(gain2);
    gain2.connect(ctx.destination);
    osc2.start(now + 0.15);
    osc2.stop(now + 0.35);
  } catch (e) {}
}

function playWarningCue() {
  if (!audioEnabled) return;
  try {
    const ctx = getAudioContext();
    if (!ctx) return;
    const now = ctx.currentTime;
    [0, 0.13, 0.26].forEach((offset, idx) => {
      const freq = (idx === 1) ? 659.25 : 880;
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'triangle';
      osc.frequency.setValueAtTime(freq, now + offset);
      gain.gain.setValueAtTime(0.10, now + offset);
      gain.gain.exponentialRampToValueAtTime(0.001, now + offset + 0.11);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(now + offset);
      osc.stop(now + offset + 0.11);
    });
  } catch (e) {}
}

function playAckCue() {
  if (!audioEnabled) return;
  try {
    const ctx = getAudioContext();
    if (!ctx) return;
    const now = ctx.currentTime;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.frequency.setValueAtTime(1100, now);
    osc.frequency.exponentialRampToValueAtTime(450, now + 0.05);
    gain.gain.setValueAtTime(0.05, now);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.05);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start(now);
    osc.stop(now + 0.05);
  } catch (e) {}
}

function toggleAudio() {
  audioEnabled = !audioEnabled;
  const lbl = document.getElementById('audio-toggle-label');
  if (lbl) {
    lbl.textContent = audioEnabled ? '🔊 Audio Active' : '🔇 Audio Muted';
  }
  if (audioEnabled) {
    playAckCue();
  }
}

function checkAudioAlerts(alerts) {
  if (!audioEnabled || !alerts) return;
  const now = Date.now();
  let currentLevel = 'green';
  if (alerts.some(a => a.level === 'red')) {
    currentLevel = 'red';
  } else if (alerts.some(a => a.level === 'amber')) {
    currentLevel = 'amber';
  }

  const isEscalation = (currentLevel === 'red' && lastHighestAlertLevel !== 'red') ||
                       (currentLevel === 'amber' && lastHighestAlertLevel === 'green');
  const isRecurringNotice = (currentLevel !== 'green' && (now - lastAlertSoundTimestamp) > 9000);

  if (isEscalation || isRecurringNotice) {
    lastAlertSoundTimestamp = now;
    if (currentLevel === 'red') {
      playWarningCue();
    } else if (currentLevel === 'amber') {
      playCautionCue();
    }
  }
  lastHighestAlertLevel = currentLevel;
}

const organZoomConfig = {
  neuro: {
    origin: '50% 6.5%',
    scale: 2.5,
    shiftX: -14,
    img: '/static/images/organs/neuro_web.png',
    title: 'CEREBRAL CORTEX & CRANIAL AXIS',
    subtitle: 'Cerebral Cortex & Brainstem • Transparent Vector Visual',
    desc: 'Cerebral autoregulation, intracranial pressure balance, and psychomotor vigilance latency (PVT). Microgravity cephalad fluid shifts alter cranial venous return and vestibular equilibrium.',
  },
  mucosal_immune: {
    origin: '50% 17%',
    scale: 2.7,
    shiftX: -14,
    img: '/static/images/organs/mucosal_immune_web.png',
    title: 'CERVICAL LYMPHOID & SALIVARY AXIS',
    subtitle: 'Lymphatic Node & Reticular Architecture • Transparent Vector Visual',
    desc: 'Salivary Secretory Immunoglobulin A (sIgA) secretion and cervical lymphatic drainage. Sentinel indicator for mucosal barrier integrity and latent viral reactivation risk during deep space transit.',
  },
  cardio: {
    origin: '50% 27.5%',
    scale: 2.6,
    shiftX: -14,
    img: '/static/images/organs/cardio_web.png',
    title: 'MYOCARDIUM & CIRCULATORY AXIS',
    subtitle: 'Myocardium & Great Vessels • Transparent Vector Visual',
    desc: 'Autonomic vagal modulation, stroke volume, resting heart rate, and heart rate variability (rMSSD). Cephalad fluid redistribution causes acute central hypervolemia followed by baroreflex resetting.',
  },
  metabolic: {
    origin: '50% 40%',
    scale: 2.4,
    shiftX: -14,
    img: '/static/images/organs/metabolic_web.png',
    title: 'HEPATIC & GASTROINTESTINAL AXIS',
    subtitle: 'Gastrointestinal & Hepatic Tract • Transparent Vector Visual',
    desc: 'Fluid osmolar retention, hepatic glucose metabolism, gut microbiome permeability, and total astronaut body mass homeostasis in unweighted environments.',
  },
  musculoskeletal: {
    origin: '43% 63%',
    scale: 2.2,
    shiftX: -14,
    img: '/static/images/organs/musculoskeletal_web.png',
    title: 'SKELETAL DENSITY & LOCOMOTOR AXIS',
    subtitle: 'Complete Human Skeletal Frame • Transparent Anatomical Visual',
    desc: 'Cortical bone mineral density and osteoclast activity assessed via urinary N-telopeptide (NTX) crosslinks. Monitors effectiveness of daily high-intensity resistive exercise countermeasures.',
  },
  environment: {
    origin: '18% 18%',
    scale: 2.0,
    shiftX: -10,
    img: '/static/images/organs/eclss_mars_transit.png',
    title: 'ECLSS HABITAT & RADIATION SHIELDING',
    subtitle: 'Deep Space Transit Architecture • Transparent 3D Visual',
    desc: 'Cabin atmospheric partial pressure of CO2 (pCO2), ECLSS amine scrubber cycles, and cumulative galactic cosmic radiation (GCR) dosimeter exposures.',
  }
};

const eclssPresetConfig = {
  station: {
    img: '/static/images/organs/eclss_station.png',
    title: 'ISS ORBITAL HABITAT & ECLSS',
    subtitle: 'ISS Low Earth Orbit Configuration • NASA 3D Systems',
    desc: 'Monitors ISS Node 3 / Tranquility regenerative ECLSS, Oxygen Generation System (OGS), Sabatier carbon dioxide reduction, and Earth geomagnetically shielded radiative flux.',
  },
  moon: {
    img: '/static/images/organs/eclss_moon.png',
    title: 'LUNAR GATEWAY & ARTEMIS HABITAT',
    subtitle: 'Artemis Lunar Surface Habitat • NASA Architecture',
    desc: 'Monitors Lunar Surface Habitat ECLSS, airlock depressurization cycles, and passive regolith cosmic ray radiation shielding in the unshielded lunar environment.',
  },
  mars_transit: {
    img: '/static/images/organs/eclss_mars_transit.png',
    title: 'DEEP SPACE MARS TRANSIT ECLSS',
    subtitle: 'Deep Space Mars Transit Vehicle • NASA 1000-Day Architecture',
    desc: 'Cabin atmospheric partial pressure of CO2 (pCO2), amine scrubbers, closed-loop water recovery, and cumulative interplanetary galactic cosmic radiation (GCR) exposure.',
  },
  mars_surface: {
    img: '/static/images/organs/eclss_mars_surface.png',
    title: 'MARS SURFACE PRESSURIZED HABITAT',
    subtitle: 'Mars Surface Science & Habitat Platform • NASA Surface Systems',
    desc: 'Martian atmospheric CO2 capture, surface ECLSS scrubbers, regolith radiation attenuation, and pressurized surface habitat life-support systems.',
  },
};

function getEffectiveOrganConfig(sysId) {
  const base = organZoomConfig[sysId];
  if (!base) return null;
  if (sysId === 'environment') {
    const presetId = (currentMission && currentMission.id) || 'mars_transit';
    const presetCfg = eclssPresetConfig[presetId] || eclssPresetConfig.mars_transit;
    return {
      ...base,
      img: presetCfg.img,
      title: presetCfg.title,
      subtitle: presetCfg.subtitle,
      desc: presetCfg.desc,
    };
  }
  return base;
}

let pvtState = {
  isRunning: false,
  isWaiting: false,
  isStimulusActive: false,
  startTime: null,
  timer: null,
  trials: [],
  lapses: 0,
};

// --- Theme Management (Light / Dark Mode) ---
function initTheme() {
  const savedTheme = localStorage.getItem('aura-theme') || 'dark';
  applyTheme(savedTheme);
}

function toggleTheme() {
  const currentTheme = document.documentElement.getAttribute('data-theme') || 'dark';
  const newTheme = (currentTheme === 'dark') ? 'light' : 'dark';
  applyTheme(newTheme);
}

function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  localStorage.setItem('aura-theme', theme);
  
  const label = document.getElementById('theme-toggle-label');
  if (label) {
    label.textContent = (theme === 'dark') ? 'Light Mode' : 'Dark Mode';
  }

  // If a modal chart is currently rendered, redraw with updated axis/grid colors
  if (activeSignalForModal && trendChartInstance) {
    updateModalChart(activeSignalForModal);
  }
}

async function init() {
  initTheme();
  const grid = document.querySelector('.workbench-grid');
  if (grid && !grid.getAttribute('data-tablet-view')) {
    grid.setAttribute('data-tablet-view', 'anatomy');
  }
  try {
    const mission = await fetch('/mission').then(r => r.json());
    presetCatalog = mission.presets;
    currentMission = presetView(mission.name, mission);
    await seedHistory();
    await loadTelemetry();
    updateMissionHeader();
    renderHotspots();
    setupWebSocket();
    updateUI();
  } catch (err) {
    console.error('Failed to initialize telemetry bridge', err);
  }
}

function setupWebSocket() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  socket = new WebSocket(`${protocol}//${window.location.host}/ws`);

  socket.onmessage = async (event) => {
    const status = JSON.parse(event.data);
    if (!status || status.crew_id !== CREW) return;
    await loadTelemetry(status);
    updateMissionHeader();
    updateUI();
  };

  socket.onclose = () => {
    setTimeout(setupWebSocket, 3000);
  };
}

function updateMissionHeader() {
  if (!currentMission) return;
  document.getElementById('mission-name').textContent = currentMission.name.toUpperCase();
  document.getElementById('mission-delay').textContent = currentMission.delay;
  document.getElementById('mission-dose').textContent = currentMission.dose_rate;
}

function renderHotspots() {
  const container = document.getElementById('hotspots-container');
  container.innerHTML = '';

  if (!telemetryData || !telemetryData.systems) return;

  telemetryData.systems.forEach((sys) => {
    const coords = systemCoords[sys.id] || { x: sys.x, y: sys.y };
    const label = systemCircleLabels[sys.id] || sys.name.toUpperCase();

    const pin = document.createElement('button');
    pin.className = 'system-pin status-green';
    pin.id = `pin-${sys.id}`;
    pin.style.left = `${coords.x * 100}%`;
    pin.style.top = `${coords.y * 100}%`;
    pin.setAttribute('aria-label', `${sys.name} system status`);
    pin.title = `${sys.name} System`;
    pin.innerHTML = `
      <div class="reticle-circle-wrapper" aria-hidden="true">
        <svg class="reticle-svg" viewBox="0 0 56 56" width="56" height="56">
          <circle class="reticle-disc-bg" cx="28" cy="28" r="26.5" />
          <g class="reticle-rotator-outer" transform-origin="28 28">
            <circle class="reticle-outer-gaps" cx="28" cy="28" r="24.5" fill="none" />
          </g>
          <g class="reticle-rotator-inner" transform-origin="28 28">
            <circle class="reticle-inner-dots" cx="28" cy="28" r="18.5" fill="none" />
          </g>
          <text class="reticle-label-text" x="28" y="28">${label}</text>
        </svg>
      </div>
    `;
    pin.onclick = (e) => {
      e.stopPropagation();
      triggerCircleRotation(pin);
      focusOrgan(sys.id);
    };
    container.appendChild(pin);
  });
}

function triggerCircleRotation(pinEl) {
  if (!pinEl) return;
  const outer = pinEl.querySelector('.reticle-rotator-outer');
  const inner = pinEl.querySelector('.reticle-rotator-inner');
  const wrap = pinEl.querySelector('.reticle-circle-wrapper');

  [outer, inner, wrap].forEach(el => {
    if (el) {
      el.classList.remove('is-spinning');
      void el.offsetWidth; // force DOM reflow
      el.classList.add('is-spinning');
    }
  });
}

function updateUI() {
  if (!telemetryData) return;
  updateHotspotStatuses();
  renderAlerts();
  renderScores();
  updateUrgentHudBanner();
  checkAudioAlerts(liveAlerts(telemetryData.alerts));
  renderTelemetryList();
  renderConnectorLines();
  if (currentFocusedOrganId) {
    const focusedSys = telemetryData.systems.find(s => s.id === currentFocusedOrganId);
    if (focusedSys) {
      renderOrganDrawerTelemetry(focusedSys);
      renderOrganDrawerSubsystemNav(currentFocusedOrganId);
      if (currentFocusedOrganId === 'environment') {
        refreshOrganDrawerEnvironment();
      }
    }
  }
  if (activeSystemForModal && activeSignalForModal) {
    updateModalChart(activeSignalForModal);
  }
}

function updateHotspotStatuses() {
  if (!telemetryData || !telemetryData.systems) return;

  telemetryData.systems.forEach((sys) => {
    let worst = 'green';
    let hasAnyReading = false;

    sys.biomarkers.forEach((bId) => {
      const bio = telemetryData.biomarkers[bId];
      if (bio && bio.reading) {
        hasAnyReading = true;
        const status = bio.reading.status;
        if (status === 'red') worst = 'red';
        else if (status === 'amber' && worst !== 'red') worst = 'amber';
      }
    });

    if (!hasAnyReading && worst !== 'red' && worst !== 'amber') {
      worst = 'stale';
    }

    const pin = document.getElementById(`pin-${sys.id}`);
    if (pin) {
      const isFocused = (currentFocusedOrganId === sys.id);
      pin.className = `system-pin status-${worst}${isFocused ? ' is-active-focus' : ''}`;
    }
  });
}

// --- Risk scores (FR-14 anomaly model, FR-15 immune-risk score) ---
// shortcut: copy of the contract's model-signal order, only needed if the model returns lists instead of dicts
const MODEL_SIGNALS = ['resting_hr_bpm', 'rmssd_ms', 'bp_systolic_mmhg', 'sleep_duration_h', 'sleep_efficiency_pct',
  'reaction_lapses_pct', 'mood_score', 'cabin_co2_mmhg', 'exercise_completion_pct', 'dose_mgy'];
const asEntries = (x, names) => (Array.isArray(x) ? x.map((v, i) => [names[i] || `#${i + 1}`, v]) : Object.entries(x || {}));
const nameOf = sig => SIGNAL_NAMES[sig] || sig;

function scoreCard(title, value, level, gauge, lines) {
  return `
    <div class="score-card ${level}">
      <div class="score-card-title">${title}</div>
      <div class="score-value">${value}</div>
      ${gauge}
      ${lines.filter(Boolean).map(l => `<div class="score-note">${l}</div>`).join('')}
    </div>`;
}

function renderScores() {
  const el = document.getElementById('score-panel');
  if (!el || !telemetryData) return;
  const a = telemetryData.anomaly || {};
  const ir = telemetryData.immune_risk || {};

  let anomaly;
  if (!a.available) {
    anomaly = scoreCard('Anomaly (model)', '—', 'stale', '', [a.reason || 'model service unavailable']);
  } else {
    const raw = asEntries(a.scores, ['2-day autoencoder', 'EWMA']);
    const peak = Math.max(0, ...raw.map(([, v]) => v));
    // gauge 0..2, alarm line at 1: shows the rise even while the headline score is still 0
    const gauge = `<div class="score-bar" title="highest model score ${peak.toFixed(2)}; alarm at 1">
        <div class="score-bar-fill" style="width: ${Math.min(100, peak * 50)}%"></div>
        <div class="score-bar-mark"></div></div>`;
    const top = asEntries(a.contributions, MODEL_SIGNALS).sort((x, y) => y[1] - x[1]).slice(0, 3)
      .map(([k, v]) => `${nameOf(k)} ${Math.round(v * 100)}%`).join(', ');
    const drift = asEntries(a.drift, MODEL_SIGNALS).filter(([, v]) => v)
      .map(([k, v]) => `${nameOf(k)} ${v > 0 ? '↑' : '↓'}`).join(', ');
    anomaly = scoreCard('Anomaly (model)', (a.score ?? 0).toFixed(2), a.score >= 1 ? 'amber' : 'green', gauge, [
      raw.map(([k, v]) => `${k}: ${(+v).toFixed(2)}`).join(' · '),
      top && `Driven by: ${top}`,
      drift && `Drifting: ${drift}`,
      a.score >= 1 ? 'Unusual for this astronaut' : 'Within this astronaut\'s normal',
    ]);
  }

  const inputs = Object.entries(ir.inputs || {}).filter(([, z]) => z >= 0.05)
    .map(([k, z]) => `${nameOf(k)} ${z.toFixed(1)} SD`).join(', ');
  const immune = ir.score == null
    ? scoreCard('Immune risk', '—', 'stale', '', ['Waiting for lab baselines (first 28 days)'])
    : scoreCard('Immune risk', `${Math.round(ir.score)}<span class="score-unit">/100</span>`, 'neutral',
      `<div class="score-bar"><div class="score-bar-fill" style="width: ${ir.score}%"></div></div>`,
      [inputs && `Off baseline: ${inputs}`,
        (ir.not_measured || []).length && `Not measured: ${ir.not_measured.join(', ')}`,
        'Placeholder weights']);

  el.innerHTML = anomaly + immune;
}

// alerts that should still sound and fill the banner: active and not yet acknowledged
const liveAlerts = alerts => (alerts || []).filter(a => a.active && !a.acknowledged);

async function acknowledgeAlert(alertId) {
  playAckCue();
  await fetch(`/alerts/${alertId}/ack`, { method: 'POST' });  // the core pushes the new status over /ws
}

function alertStateChip(a) {
  if (!a.active) return '<span class="alert-state-chip">RESOLVED · AWAITING ACK</span>';
  if (a.acknowledged) return '<span class="alert-state-chip">ACKNOWLEDGED · STILL ACTIVE</span>';
  return '';
}

function renderAlerts() {
  const list = document.getElementById('alerts-list');
  const badge = document.getElementById('alerts-count-badge');
  const tabletPill = document.getElementById('tablet-alert-pill');
  const alerts = telemetryData ? telemetryData.alerts : [];

  if (tabletPill) {
    if (liveAlerts(alerts).length > 0) {
      tabletPill.textContent = liveAlerts(alerts).length;
      tabletPill.style.display = 'inline-flex';
    } else {
      tabletPill.style.display = 'none';
    }
  }

  if (!alerts || alerts.length === 0) {
    badge.textContent = 'NOMINAL';
    badge.className = 'panel-count-badge';
    badge.style.color = 'var(--color-status-green)';
    list.innerHTML = `
      <div class="pattern-card nominal">
        <div class="pattern-card-meta">
          <span style="color: var(--color-status-green); font-weight: 700; font-size: 14.5px;">● MULTI-SYSTEM HARMONY</span>
          <span style="color: var(--color-text-dim); font-size: 13.5px;">STEADY STATE</span>
        </div>
        <div class="pattern-card-title" style="font-size: 17px; margin: 4px 0;">All Systems Nominal</div>
        <details class="tablet-collapsible">
          <summary class="tablet-collapsible-summary">Show Telemetry Baseline Context</summary>
          <div class="collapsible-content">
            No multi-system signal divergence detected. Observed physiological variables are bounded within personal baseline envelopes across neurocognitive, cardiovascular, mucosal, metabolic, musculoskeletal, and ECLSS subsystems.
          </div>
        </details>
      </div>
    `;
    return;
  }

  const live = liveAlerts(alerts).length;
  const waiting = alerts.filter(a => !a.acknowledged).length - live;
  badge.textContent = [live && `${live} ACTIVE`, waiting && `${waiting} TO ACKNOWLEDGE`].filter(Boolean).join(' · ')
    || `${alerts.length} ACKNOWLEDGED`;
  badge.className = live ? 'panel-count-badge badge-urgent-pulse' : 'panel-count-badge';
  badge.style.color = live ? '' : 'var(--color-text-dim)';

  list.innerHTML = alerts.map((alert) => `
    <div class="pattern-card ${alert.level === 'red' ? 'level-red' : 'level-amber'}${alert.active ? '' : ' resolved'}">
      <div class="pattern-card-meta">
        <span class="urgent-indicator-chip ${alert.level}">
          ${alert.level === 'red' ? 'RED' : 'AMBER'} · ${alert.is_pattern ? 'CROSS-SYSTEM PATTERN' : 'SIGNAL ALERT'}
        </span>
        <span class="urgent-sys-chip">${alert.involved_systems.map(s => (systemCircleLabels[s] || s).toUpperCase()).join(' + ')}</span>
      </div>
      ${alertStateChip(alert)}
      <div class="pattern-card-title">${alert.pattern_name}</div>
      <div class="pattern-card-summary">${alert.medical_reason}</div>

      <button class="btn-control primary alert-protocol-btn" onclick="openProtocolModal('${alert.id}')">
        <span>What to do (${alert.response_crew.length + alert.response_medical.length} steps)</span>
        <span>→</span>
      </button>
      ${alert.acknowledged ? '' : `<button class="btn-control alert-ack-btn" onclick="acknowledgeAlert('${alert.id}')">Acknowledge</button>`}
    </div>
  `).join('');
}

function openProtocolModal(alertId) {
  if (!telemetryData || !telemetryData.alerts) return;
  const alert = telemetryData.alerts.find(a => a.id === alertId);
  if (!alert) return;

  const modal = document.getElementById('protocol-modal');
  const badge = document.getElementById('protocol-modal-badge');
  const title = document.getElementById('protocol-modal-title');
  const meta = document.getElementById('protocol-modal-meta');
  const reason = document.getElementById('protocol-modal-reason');
  const crewList = document.getElementById('protocol-crew-checklist');
  const medList = document.getElementById('protocol-medical-list');
  const citation = document.getElementById('protocol-modal-citation');

  if (badge) {
    badge.className = `urgent-indicator-chip ${alert.level}`;
    badge.textContent = `${alert.level.toUpperCase()} · ${alert.is_pattern ? 'CROSS-SYSTEM PATTERN' : 'SIGNAL ALERT'}`;
  }
  if (title) title.textContent = alert.pattern_name;

  if (meta) {
    const sysTags = alert.involved_systems.map(s => `
      <span class="protocol-meta-chip system">${(systemCircleLabels[s] || s).toUpperCase()} SUBSYSTEM</span>
    `).join('');
    const sigTags = alert.signals_fired.map(sig => {
      const bio = telemetryData.biomarkers ? telemetryData.biomarkers[sig] : null;
      const val = bio && bio.reading ? `${bio.reading.value.toFixed(1)} ${bio.bounds.unit}` : sig;
      return `<span class="protocol-meta-chip signal">${bio ? bio.name : sig} (${val})</span>`;
    }).join('');
    meta.innerHTML = `<div class="protocol-meta-group">${sysTags}${sigTags}</div>`;
  }

  if (reason) reason.textContent = alert.medical_reason;

  if (crewList) {
    crewList.innerHTML = alert.response_crew.map((act, i) => `
      <div class="protocol-checklist-item" onclick="toggleChecklistItem(this)">
        <div class="protocol-checkbox" aria-label="Step ${i + 1} checkbox"></div>
        <div class="protocol-step-body">
          <div class="protocol-step-num">ACTION STEP ${i + 1} OF ${alert.response_crew.length}</div>
          <div class="protocol-step-instruction">${act}</div>
        </div>
      </div>
    `).join('');
    updateChecklistCounter();
  }

  if (medList) {
    medList.innerHTML = alert.response_medical.map((inst, i) => `
      <div class="protocol-medical-item">
        <span class="protocol-medical-num">${i + 1}.</span>
        <span class="protocol-medical-text">${inst}</span>
      </div>
    `).join('');
  }

  if (citation) {
    citation.innerHTML = `
      <strong>Source:</strong> ${alert.citation} · <em>${alert.is_published ? 'published threshold' : 'proposed threshold (team research doc)'}</em>
    `;
  }

  modal.style.display = 'flex';
}

function toggleChecklistItem(el) {
  el.classList.toggle('is-checked');
  updateChecklistCounter();
}

function updateChecklistCounter() {
  const container = document.getElementById('protocol-crew-checklist');
  const counter = document.getElementById('protocol-crew-counter');
  if (!container || !counter) return;
  const items = container.querySelectorAll('.protocol-checklist-item');
  const checked = container.querySelectorAll('.protocol-checklist-item.is-checked');
  counter.textContent = `${checked.length} / ${items.length} Completed`;
  if (checked.length === items.length && items.length > 0) {
    counter.style.color = 'var(--color-status-green)';
    counter.textContent = `✔ All ${items.length} Actions Completed`;
  } else {
    counter.style.color = 'var(--color-signal-primary)';
  }
}

// --- Urgent Situational Telemetry HUD Banner ---
function updateUrgentHudBanner() {
  const banner = document.getElementById('urgent-hud-banner');
  if (!banner || !telemetryData) return;
  const alerts = liveAlerts(telemetryData.alerts);

  if (alerts.length === 0) {
    banner.style.display = 'none';
    currentTopAlert = null;
    return;
  }

  // Priority: red alerts take precedence over amber
  const topAlert = alerts.find(a => a.level === 'red') || alerts[0];
  currentTopAlert = topAlert;

  const isRed = (topAlert.level === 'red');
  banner.className = `urgent-hud-banner ${isRed ? 'status-red' : 'status-amber'}`;
  banner.style.display = 'flex';

  const iconEl = document.getElementById('urgent-hud-icon');
  if (iconEl) iconEl.textContent = isRed ? '🚨' : '⚠️';

  const titleEl = document.getElementById('urgent-hud-title');
  if (titleEl) {
    titleEl.textContent = `${isRed ? 'RED' : 'AMBER'} ${topAlert.is_pattern ? 'PATTERN' : 'SIGNAL'}: ${topAlert.pattern_name.toUpperCase()}`;
  }

  const subEl = document.getElementById('urgent-hud-sub');
  if (subEl) {
    const sysNames = (topAlert.involved_systems || []).map(s => (systemCircleLabels[s] || s).toUpperCase()).join(' + ');
    subEl.textContent = `Affecting [${sysNames || 'Multi-System'}] • ${topAlert.medical_reason}`;
  }
}

function openUrgentProtocol() {
  playAckCue();
  if (currentTopAlert) {
    openProtocolModal(currentTopAlert.id);
  }
}

function focusUrgentSubsystem() {
  playAckCue();
  if (currentTopAlert && currentTopAlert.involved_systems && currentTopAlert.involved_systems.length > 0) {
    focusOrgan(currentTopAlert.involved_systems[0]);
  }
}

// --- Quick Subsystem Navigator inside Organ Inspection Drawer ---
function renderOrganDrawerSubsystemNav(activeSysId) {
  const nav = document.getElementById('organ-drawer-subsystem-nav');
  if (!nav || !telemetryData || !telemetryData.systems) return;

  const alerts = telemetryData.alerts || [];
  const systemDisplayLabels = {
    neuro: '🧠 Neuro',
    mucosal_immune: '🛡️ Immune',
    cardio: '❤️ Cardio',
    metabolic: '⚡ Metab',
    musculoskeletal: '🦴 Skel',
    environment: '🚀 ECLSS',
  };

  nav.innerHTML = telemetryData.systems.map(sys => {
    const isCurrent = (sys.id === activeSysId);
    const label = systemDisplayLabels[sys.id] || sys.name;

    let hasRed = false;
    let hasAmber = false;

    sys.biomarkers.forEach(bId => {
      const bio = telemetryData.biomarkers[bId];
      if (bio && bio.reading) {
        if (bio.reading.status === 'red') hasRed = true;
        if (bio.reading.status === 'amber') hasAmber = true;
      }
    });

    if (alerts.some(a => a.involved_systems && a.involved_systems.includes(sys.id))) {
      if (alerts.some(a => a.involved_systems.includes(sys.id) && a.level === 'red')) hasRed = true;
      else hasAmber = true;
    }

    let dotHtml = '';
    if (hasRed) {
      dotHtml = '<span class="drawer-subsys-dot red"></span>';
    } else if (hasAmber) {
      dotHtml = '<span class="drawer-subsys-dot amber"></span>';
    }

    return `
      <button class="drawer-subsys-pill ${isCurrent ? 'active' : ''}" onclick="focusOrgan('${sys.id}')">
        ${dotHtml}<span>${label}</span>
      </button>
    `;
  }).join('');
}

// --- Native SVG Micro-Telemetry Sparklines ---
function generateSparklineSvg(history, status = 'green') {
  if (!history || !Array.isArray(history) || history.length < 2) {
    return `
      <svg class="biomarker-sparkline" viewBox="0 0 70 24" aria-hidden="true">
        <line x1="2" y1="12" x2="68" y2="12" stroke="var(--color-border-subtle)" stroke-dasharray="3 3" stroke-width="1.5" />
      </svg>
    `;
  }

  const vals = history.map(h => (typeof h.value === 'number' ? h.value : 0));
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const range = (max - min) === 0 ? 1 : (max - min);

  const width = 70;
  const height = 24;
  const padX = 4;
  const padY = 4;
  const effW = width - (padX * 2);
  const effH = height - (padY * 2);

  const points = vals.map((v, i) => {
    const x = padX + (i / (vals.length - 1)) * effW;
    const y = (height - padY) - ((v - min) / range) * effH;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });

  const lastPt = points[points.length - 1].split(',');
  const lastX = lastPt[0];
  const lastY = lastPt[1];

  return `
    <svg class="biomarker-sparkline" viewBox="0 0 ${width} ${height}" aria-hidden="true">
      <polyline class="sparkline-line ${status}" points="${points.join(' ')}" />
      <circle class="sparkline-dot ${status}" cx="${lastX}" cy="${lastY}" />
    </svg>
  `;
}

// --- Biomarker Subsystem Quick-Filter Logic ---
function setBiomarkerFilter(category) {
  activeBiomarkerFilter = category;
  document.querySelectorAll('.filter-pill').forEach(btn => {
    btn.classList.toggle('active', btn.getAttribute('data-filter') === category);
  });
  playAckCue();
  renderTelemetryList();
}

function renderTelemetryList() {
  const container = document.getElementById('telemetry-list');
  const countBadge = document.getElementById('biomarker-count-badge');
  if (!container || !telemetryData || !telemetryData.biomarkers) return;

  let targetSignals = [];

  if (activeBiomarkerFilter === 'ALL') {
    targetSignals = ALL_BIOMARKER_ORDER.filter(id => telemetryData.biomarkers[id]);
    // Sort breached ones to the top
    targetSignals.sort((a, b) => {
      const bioA = telemetryData.biomarkers[a];
      const bioB = telemetryData.biomarkers[b];
      const weight = (bio) => {
        if (!bio || !bio.reading) return 3;
        if (bio.reading.status === 'red') return 0;
        if (bio.reading.status === 'amber') return 1;
        return 2;
      };
      return weight(bioA) - weight(bioB);
    });
    if (countBadge) {
      countBadge.textContent = `${targetSignals.length} MONITORED`;
      countBadge.style.color = 'var(--color-signal-primary)';
    }
  } else if (activeBiomarkerFilter === 'BREACHED') {
    targetSignals = ALL_BIOMARKER_ORDER.filter(id => {
      const bio = telemetryData.biomarkers[id];
      if (!bio) return false;
      if (!bio.reading) return true; // stale
      return (bio.reading.status === 'red' || bio.reading.status === 'amber');
    });
    if (countBadge) {
      countBadge.textContent = targetSignals.length > 0 ? `${targetSignals.length} BREACHED` : '0 BREACHED';
      countBadge.style.color = targetSignals.length > 0 ? 'var(--color-status-amber)' : 'var(--color-status-green)';
    }
  } else {
    const sys = telemetryData.systems.find(s => s.id === activeBiomarkerFilter);
    if (sys) {
      targetSignals = sys.biomarkers.filter(id => telemetryData.biomarkers[id]);
      if (countBadge) {
        countBadge.textContent = `${targetSignals.length} IN ${(systemCircleLabels[sys.id] || sys.name).toUpperCase()}`;
        countBadge.style.color = 'var(--color-signal-primary)';
      }
    } else {
      targetSignals = ALL_BIOMARKER_ORDER.filter(id => telemetryData.biomarkers[id]);
    }
  }

  if (targetSignals.length === 0) {
    if (activeBiomarkerFilter === 'BREACHED') {
      container.innerHTML = `
        <div class="filter-nominal-card">
          <div style="font-size: 24px; margin-bottom: 6px;">✔</div>
          <div style="font-size: 15px; font-weight: 700;">All 14 Biomarkers Within Personal Baseline</div>
          <div style="font-size: 13.5px; color: var(--color-text-muted); margin-top: 4px; font-weight: 400;">No parameter threshold excursions or sensor dropouts detected.</div>
        </div>
      `;
      return;
    }
  }

  let html = '';
  targetSignals.forEach((sigId) => {
    const bio = telemetryData.biomarkers[sigId];
    if (!bio) return;

    const rdg = bio.reading;
    const b = bio.bounds;

    if (!rdg) {
      const sparkline = generateSparklineSvg([], 'stale');
      html += `
        <div class="biomarker-row stale" style="opacity: 0.7;" onclick="openSystemForBiomarker('${sigId}')">
          <div class="biomarker-row-main">
            <div class="biomarker-info-title">${bio.name}</div>
            <div class="biomarker-info-bounds" style="color: var(--color-status-stale);">SENSOR TELEMETRY OVERDUE</div>
          </div>
          <div class="biomarker-row-sparkline" title="Offline - no telemetry history">
            ${sparkline}
          </div>
          <div class="biomarker-value-badge stale">STALE</div>
        </div>
      `;
    } else {
      const status = rdg.status;
      const isUrgent = (status === 'red' || status === 'amber');

      let boundsDesc = `Target: ${b.baseline} ${b.unit}`;
      if (b.amber_low !== null && b.amber_high !== null) {
        boundsDesc += ` · Band: [${b.amber_low} – ${b.amber_high}]`;
      } else if (b.amber_high !== null) {
        boundsDesc += ` · Upper: ${b.amber_high}`;
      } else if (b.amber_low !== null) {
        boundsDesc += ` · Lower: ${b.amber_low}`;
      }

      const sparkline = generateSparklineSvg(bio.history, status);

      html += `
        <div class="biomarker-row status-${status}${isUrgent ? ' urgent-row' : ''}" onclick="openSystemForBiomarker('${sigId}')">
          <div class="biomarker-row-main">
            <div class="biomarker-title-line">
              ${isUrgent ? `<span class="urgent-pip ${status}">●</span>` : ''}
              <span class="biomarker-info-title">${bio.name}</span>
            </div>
            <div class="biomarker-info-bounds">${boundsDesc}</div>
          </div>
          <div class="biomarker-row-sparkline" title="Micro-telemetry sparkline history">
            ${sparkline}
          </div>
          <div class="biomarker-value-badge ${status}">
            ${rdg.value.toFixed(1)} <span class="biomarker-unit">${b.unit}</span>
          </div>
        </div>
      `;
    }
  });

  container.innerHTML = html;
}

function openSystemForBiomarker(sigId) {
  if (!telemetryData) return;
  const sys = telemetryData.systems.find(s => s.biomarkers.includes(sigId));
  if (sys) {
    activeSignalForModal = sigId;
    focusOrgan(sys.id);
  }
}

function populateOrganDrawerDescription(descText) {
  const summaryEl = document.getElementById('organ-drawer-summary');
  const detailsEl = document.getElementById('organ-drawer-details');
  const descEl = document.getElementById('organ-drawer-desc');
  if (!summaryEl || !detailsEl || !descEl) return;

  const text = (descText || '').trim();
  const periodIdx = text.indexOf('. ');
  if (periodIdx !== -1) {
    summaryEl.textContent = text.substring(0, periodIdx + 1);
    descEl.textContent = text.substring(periodIdx + 2);
    detailsEl.style.display = 'block';
    detailsEl.open = false; // Collapsed by default for clean tablet readability
  } else {
    summaryEl.textContent = text;
    descEl.textContent = '';
    detailsEl.style.display = 'none';
  }
}

function focusOrgan(sysId) {
  if (!telemetryData || !telemetryData.systems) return;
  const sys = telemetryData.systems.find(s => s.id === sysId);
  const cfg = getEffectiveOrganConfig(sysId);
  if (!sys || !cfg) return;

  currentFocusedOrganId = sysId;

  // 1. Highlight active pin
  document.querySelectorAll('.system-pin').forEach(p => p.classList.remove('is-active-focus'));
  const pin = document.getElementById(`pin-${sysId}`);
  if (pin) {
    pin.classList.add('is-active-focus');
    triggerCircleRotation(pin);
  }

  // 2. Reposition / create targeting reticle on silhouette
  const stage = document.getElementById('map-stage');
  let reticle = document.getElementById('organ-reticle');
  if (!reticle) {
    reticle = document.createElement('div');
    reticle.id = 'organ-reticle';
    reticle.className = 'organ-target-reticle';
    stage.appendChild(reticle);
  }
  const coords = systemCoords[sysId] || { x: sys.x, y: sys.y };
  reticle.style.left = `${coords.x * 100}%`;
  reticle.style.top = `${coords.y * 100}%`;
  reticle.style.display = 'block';

  // 3. Smooth zoom to the organ with slight X offset for side drawer
  stage.style.transformOrigin = cfg.origin;
  const shift = cfg.shiftX || -12;
  stage.style.transform = `scale(${cfg.scale}) translateX(${shift}%)`;

  // 4. Reveal Reset Zoom button
  const resetBtn = document.getElementById('btn-reset-zoom');
  if (resetBtn) resetBtn.style.display = 'flex';

  // 5. Populate and reveal Organ Inspection Side Drawer
  const drawer = document.getElementById('organ-drawer');
  document.getElementById('organ-drawer-title').textContent = cfg.title;
  
  const imgEl = document.getElementById('organ-drawer-img');
  imgEl.src = cfg.img;
  imgEl.alt = `${sys.name} High-Resolution Web Visual`;
  imgEl.style.animation = 'none';
  void imgEl.offsetHeight; // retrigger CSS animation
  imgEl.style.animation = 'imageFadeIn 0.35s ease-out';

  document.getElementById('organ-drawer-caption').textContent = cfg.subtitle;
  populateOrganDrawerDescription(cfg.desc);

  renderOrganDrawerTelemetry(sys);
  renderOrganDrawerSubsystemNav(sysId);

  const chartBtn = document.getElementById('organ-drawer-chart-btn');
  if (chartBtn) {
    chartBtn.onclick = () => openSystemModal(sys);
  }

  drawer.style.display = 'flex';
}

function refreshOrganDrawerEnvironment() {
  if (currentFocusedOrganId !== 'environment') return;
  const cfg = getEffectiveOrganConfig('environment');
  if (!cfg) return;

  const titleEl = document.getElementById('organ-drawer-title');
  const imgEl = document.getElementById('organ-drawer-img');
  const captionEl = document.getElementById('organ-drawer-caption');

  if (titleEl) titleEl.textContent = cfg.title;
  if (imgEl && !imgEl.src.endsWith(cfg.img)) {
    imgEl.src = cfg.img;
    imgEl.style.animation = 'none';
    void imgEl.offsetHeight;
    imgEl.style.animation = 'imageFadeIn 0.35s ease-out';
  }
  if (captionEl) captionEl.textContent = cfg.subtitle;
  populateOrganDrawerDescription(cfg.desc);
}

function renderOrganDrawerTelemetry(sys) {
  const container = document.getElementById('organ-drawer-telemetry');
  if (!container || !telemetryData || !telemetryData.biomarkers) return;

  container.innerHTML = sys.biomarkers.map(bId => {
    const bio = telemetryData.biomarkers[bId];
    if (!bio) return '';
    const rdg = bio.reading;
    const b = bio.bounds;

    const status = rdg ? rdg.status : 'stale';
    const isUrgent = (status === 'red' || status === 'amber');
    const valText = rdg ? `${rdg.value.toFixed(1)}` : 'OFFLINE';

    let boundsDesc = `Nominal: ${b.baseline} ${b.unit}`;
    if (b.amber_low !== null && b.amber_high !== null) {
      boundsDesc = `Band: [${b.amber_low} – ${b.amber_high}]`;
    } else if (b.amber_high !== null) {
      boundsDesc = `Upper limit: ${b.amber_high} ${b.unit}`;
    } else if (b.amber_low !== null) {
      boundsDesc = `Lower limit: ${b.amber_low} ${b.unit}`;
    }

    return `
      <div class="biomarker-row status-${status}${isUrgent ? ' urgent-row' : ''}" style="padding: 10px 12px; cursor: pointer;" onclick="openSystemBiomarkerChart('${bId}')">
        <div>
          <div class="biomarker-title-line">
            ${isUrgent ? `<span class="urgent-pip ${status}">●</span>` : ''}
            <span class="biomarker-info-title" style="font-size: 14.5px;">${bio.name}</span>
          </div>
          <div class="biomarker-info-bounds" style="font-size: 12px;">${boundsDesc}</div>
        </div>
        <div class="biomarker-value-badge ${status}" style="font-size: 15px; padding: 4px 10px;">
          ${valText} <span class="biomarker-unit">${b.unit}</span>
        </div>
      </div>
    `;
  }).join('');
}

// --- Tablet Navigation & Layout Control ---
let currentTabletView = 'anatomy';

function switchTabletView(view) {
  currentTabletView = view;
  const grid = document.querySelector('.workbench-grid');
  const btnAnatomy = document.getElementById('tab-btn-anatomy');
  const btnTelemetry = document.getElementById('tab-btn-telemetry');
  
  if (grid) {
    grid.setAttribute('data-tablet-view', view);
  }
  if (btnAnatomy && btnTelemetry) {
    if (view === 'anatomy') {
      btnAnatomy.classList.add('active');
      btnTelemetry.classList.remove('active');
    } else {
      btnTelemetry.classList.add('active');
      btnAnatomy.classList.remove('active');
    }
  }
}

function toggleDisclaimer() {
  const strip = document.getElementById('disclaimer-strip');
  if (strip) {
    strip.classList.toggle('minimized');
  }
}

function openSystemBiomarkerChart(bId) {
  activeSignalForModal = bId;
  if (currentFocusedOrganId) {
    const sys = telemetryData.systems.find(s => s.id === currentFocusedOrganId);
    if (sys) openSystemModal(sys);
  }
}

function resetBodyZoom() {
  const stage = document.getElementById('map-stage');
  if (stage) {
    stage.style.transform = 'none';
    stage.style.transformOrigin = '50% 50%';
  }

  const reticle = document.getElementById('organ-reticle');
  if (reticle) reticle.style.display = 'none';

  document.querySelectorAll('.system-pin').forEach(p => p.classList.remove('is-active-focus'));

  const resetBtn = document.getElementById('btn-reset-zoom');
  if (resetBtn) resetBtn.style.display = 'none';

  const drawer = document.getElementById('organ-drawer');
  if (drawer) drawer.style.display = 'none';

  currentFocusedOrganId = null;
}

function closeOrganDrawer() {
  resetBodyZoom();
}

function renderConnectorLines() {
  const svg = document.getElementById('connector-svg');
  if (svg) svg.innerHTML = '';
}

function openSystemModal(sys) {
  activeSystemForModal = sys;
  if (!activeSignalForModal || !sys.biomarkers.includes(activeSignalForModal)) {
    activeSignalForModal = sys.biomarkers[0];
  }

  document.getElementById('modal-system-title').textContent = `${sys.name.toUpperCase()} SYSTEM`;
  document.getElementById('modal-system-desc').textContent = sys.description;

  const tabsContainer = document.getElementById('modal-biomarker-tabs');
  tabsContainer.innerHTML = sys.biomarkers.map((bId) => {
    const bio = telemetryData.biomarkers[bId];
    const isSelected = (bId === activeSignalForModal);
    return `
      <button class="tab-btn ${isSelected ? 'active' : ''}" onclick="selectBiomarkerTab('${bId}')">
        ${bio.name}
      </button>
    `;
  }).join('');

  const content = document.getElementById('modal-biomarkers-content');
  content.innerHTML = sys.biomarkers.map((bId) => {
    const bio = telemetryData.biomarkers[bId];
    const rdg = bio?.reading;
    const b = bio.bounds;

    let limitsStr = `Target: ${b.baseline} [${b.baseline_min}–${b.baseline_max}]`;
    if (b.amber_low !== null) limitsStr += ` · Lower Amber: <${b.amber_low}`;
    if (b.amber_high !== null) limitsStr += ` · Upper Amber: >${b.amber_high}`;
    if (b.red_low !== null) limitsStr += ` · Lower Red: <${b.red_low}`;
    if (b.red_high !== null) limitsStr += ` · Upper Red: >${b.red_high}`;

    const status = rdg?.status || 'green';
    const valStr = rdg ? rdg.value.toFixed(1) : '--';

    return `
      <div class="biomarker-row" onclick="selectBiomarkerTab('${bId}')">
        <div>
          <div class="biomarker-info-title">${bio.name}</div>
          <div class="biomarker-info-bounds">${limitsStr}</div>
        </div>
        <div class="biomarker-value-badge ${status}">
          ${valStr} ${b.unit}
        </div>
      </div>
    `;
  }).join('');

  updateModalChart(activeSignalForModal);
  document.getElementById('system-modal').style.display = 'flex';
}

function selectBiomarkerTab(bId) {
  activeSignalForModal = bId;
  openSystemModal(activeSystemForModal);
}

function updateModalChart(sigId) {
  const bio = telemetryData?.biomarkers[sigId];
  if (!bio) return;

  const b = bio.bounds;
  const history = bio.history || [];
  const labels = history.map(h => h.time);
  const values = history.map(h => h.value);

  document.getElementById('chart-signal-title').textContent = `${bio.name} (${b.unit})`;
  
  let boundsText = `Personal Baseline: ${b.baseline} ${b.unit} [${b.baseline_min} – ${b.baseline_max}]`;
  document.getElementById('chart-bounds-legend').textContent = boundsText;

  const statusBadge = document.getElementById('chart-status-badge');
  const currentStatus = bio.reading?.status || 'green';
  statusBadge.textContent = currentStatus.toUpperCase();
  statusBadge.className = `biomarker-value-badge ${currentStatus}`;

  const currentTheme = document.documentElement.getAttribute('data-theme') || 'dark';
  const gridColor = (currentTheme === 'dark') ? '#1C2638' : '#E2E8F0';
  const tickColor = (currentTheme === 'dark') ? '#64748B' : '#475569';
  const primaryLineColor = (currentTheme === 'dark') ? '#38BDF8' : '#0284C7';
  const primaryFillColor = (currentTheme === 'dark') ? 'rgba(56, 189, 248, 0.08)' : 'rgba(2, 132, 199, 0.08)';

  const ctx = document.getElementById('trendChart').getContext('2d');
  if (trendChartInstance) {
    trendChartInstance.destroy();
  }

  const datasets = [
    {
      label: `${bio.name}`,
      data: values,
      borderColor: primaryLineColor,
      backgroundColor: primaryFillColor,
      fill: true,
      tension: 0.25,
      borderWidth: 2,
      pointRadius: 3,
      pointBackgroundColor: primaryLineColor,
    },
    {
      label: 'Baseline Target',
      data: labels.map(() => b.baseline),
      borderColor: (currentTheme === 'dark') ? 'rgba(148, 163, 184, 0.5)' : 'rgba(71, 85, 105, 0.5)',
      borderDash: [4, 4],
      borderWidth: 1.2,
      pointRadius: 0,
      fill: false,
    },
  ];

  if (b.amber_high !== null) {
    datasets.push({
      label: 'Upper Amber Threshold',
      data: labels.map(() => b.amber_high),
      borderColor: '#F59E0B',
      borderDash: [5, 4],
      borderWidth: 1.4,
      pointRadius: 0,
      fill: false,
    });
  }
  if (b.red_high !== null) {
    datasets.push({
      label: 'Upper Red Critical',
      data: labels.map(() => b.red_high),
      borderColor: '#EF4444',
      borderWidth: 1.6,
      pointRadius: 0,
      fill: false,
    });
  }

  if (b.amber_low !== null) {
    datasets.push({
      label: 'Lower Amber Threshold',
      data: labels.map(() => b.amber_low),
      borderColor: '#F59E0B',
      borderDash: [5, 4],
      borderWidth: 1.4,
      pointRadius: 0,
      fill: false,
    });
  }
  if (b.red_low !== null) {
    datasets.push({
      label: 'Lower Red Critical',
      data: labels.map(() => b.red_low),
      borderColor: '#EF4444',
      borderWidth: 1.6,
      pointRadius: 0,
      fill: false,
    });
  }

  trendChartInstance = new Chart(ctx, {
    type: 'line',
    data: {
      labels: labels,
      datasets: datasets,
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          labels: {
            color: tickColor,
            font: { size: 13, weight: '600', family: 'Inter, sans-serif' },
            boxWidth: 14,
            padding: 12,
          },
        },
      },
      scales: {
        x: {
          grid: { color: gridColor },
          ticks: { color: tickColor, font: { size: 13, weight: '500' } },
        },
        y: {
          grid: { color: gridColor },
          ticks: { color: tickColor, font: { size: 13, weight: '600' } },
        },
      },
    },
  });
}

function handlePvtClick() {
  const arena = document.getElementById('pvt-arena');
  const prompt = document.getElementById('pvt-prompt');
  const sub = document.getElementById('pvt-sub');

  if (!pvtState.isRunning) {
    pvtState.isRunning = true;
    pvtState.trials = [];
    pvtState.lapses = 0;
    prompt.textContent = 'Awaiting visual stimulus...';
    sub.textContent = 'Trial 1 of 5';
    scheduleNextPvtStimulus();
  } else if (pvtState.isWaiting && !pvtState.isStimulusActive) {
    prompt.textContent = 'Premature response! Wait for signal';
    clearTimeout(pvtState.timer);
    scheduleNextPvtStimulus();
  } else if (pvtState.isStimulusActive) {
    const elapsed = Date.now() - pvtState.startTime;
    pvtState.trials.push(elapsed);
    if (elapsed > 500) pvtState.lapses++;

    pvtState.isStimulusActive = false;
    arena.classList.remove('active-stimulus');

    const meanRt = Math.round(pvtState.trials.reduce((a, b) => a + b, 0) / pvtState.trials.length);
    document.getElementById('pvt-trials-count').textContent = `${pvtState.trials.length}/5`;
    document.getElementById('pvt-mean-rt').textContent = `${meanRt} ms`;
    document.getElementById('pvt-lapses-count').textContent = pvtState.lapses;

    if (pvtState.trials.length >= 5) {
      pvtState.isRunning = false;
      prompt.textContent = 'Block Complete. Tap to Retest';
      sub.textContent = `Completed 5 trials · Mean: ${meanRt}ms · Lapses: ${pvtState.lapses}`;
    } else {
      prompt.textContent = 'Awaiting visual stimulus...';
      sub.textContent = `Trial ${pvtState.trials.length + 1} of 5`;
      scheduleNextPvtStimulus();
    }
  }
}

function scheduleNextPvtStimulus() {
  pvtState.isWaiting = true;
  pvtState.isStimulusActive = false;
  const delayMs = 1500 + Math.random() * 3000;

  pvtState.timer = setTimeout(() => {
    pvtState.isStimulusActive = true;
    pvtState.startTime = Date.now();
    const arena = document.getElementById('pvt-arena');
    arena.classList.add('active-stimulus');
    document.getElementById('pvt-prompt').textContent = 'ENGAGE RESPONSE';
  }, delayMs);
}

function openCrewModal() {
  playAckCue();
  const container = document.getElementById('crew-list-container');
  const crew = telemetryData?.crew || [];

  container.innerHTML = crew.map((c) => {
    return `
      <div class="biomarker-row" style="padding: 14px; min-height: 58px;">
        <div>
          <div class="biomarker-info-title" style="font-size: 16.5px;">${c.name}</div>
          <div class="biomarker-info-bounds" style="font-size: 14px; margin-top: 3px;">${c.role} · Drift index: ${(c.anomaly * 100).toFixed(0)}%</div>
        </div>
        <div style="text-align: right;">
          <span class="biomarker-value-badge ${c.status}" style="font-size: 15px; padding: 4px 10px;">${c.status.toUpperCase()}</span>
          <div style="font-size: 13px; color: var(--color-text-dim); margin-top: 3px;">${c.alerts} active ${c.alerts === 1 ? 'alert' : 'alerts'}</div>
        </div>
      </div>
    `;
  }).join('');

  document.getElementById('crew-modal').style.display = 'flex';
}

function openMissionModal() {
  playAckCue();
  const container = document.getElementById('presets-list-container');
  const presets = telemetryData?.presets || {};

  container.innerHTML = Object.values(presets).map((p) => {
    const isCurrent = currentMission && currentMission.name === p.name;
    return `
      <div class="biomarker-row" style="padding: 14px; min-height: 60px; cursor: pointer; ${isCurrent ? 'border-color: var(--color-signal-primary);' : ''}" onclick="selectMissionPreset('${p.id}')">
        <div>
          <div class="biomarker-info-title" style="font-size: 16.5px; color: ${isCurrent ? 'var(--color-signal-primary)' : 'var(--color-text-bright)'};">${p.name}</div>
          <div class="biomarker-info-bounds" style="font-size: 14px; margin-top: 2px;">Latency: ${p.delay} · Radiative flux: ${p.dose_rate}</div>
          <div style="font-size: 13.5px; color: var(--color-text-muted); margin-top: 4px;">${p.alert_wording}</div>
        </div>
        <button class="btn-control ${isCurrent ? 'primary' : ''}" style="min-height: 44px; font-size: 14px; font-weight: 700; padding: 8px 16px;">${isCurrent ? 'ACTIVE' : 'SELECT'}</button>
      </div>
    `;
  }).join('');

  document.getElementById('mission-modal').style.display = 'flex';
}

async function selectMissionPreset(presetId) {
  playAckCue();
  try {
    const res = await fetch('/mission', { method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ preset: presetId }) });
    const data = await res.json();
    if (res.ok) {
      currentMission = presetView(data.name, data);
      updateMissionHeader();
      if (currentFocusedOrganId === 'environment') {
        refreshOrganDrawerEnvironment();
      }
    }
    document.getElementById('mission-modal').style.display = 'none';
  } catch (err) {
    console.error('Failed to update mission preset', err);
  }
}

async function triggerScenario(id) {
  playAckCue();
  try {
    for (const k in signalHistory) delete signalHistory[k];  // the core wipes the crew member's readings too
    await fetch(`/scenario/${id}`, { method: 'POST' });
  } catch (err) {
    console.error('Failed to trigger scenario', err);
  }
}

function openCheckinModal() {
  playAckCue();
  document.getElementById('checkin-modal').style.display = 'flex';
}

function closeModal(event, modalId) {
  if (event.target.id === modalId) {
    playAckCue();
    document.getElementById(modalId).style.display = 'none';
    if (modalId === 'system-modal') {
      activeSystemForModal = null;
      activeSignalForModal = null;
    }
  }
}

async function submitCheckin(e) {
  e.preventDefault();
  const mood = parseFloat(document.getElementById('inp-mood').value);
  const exercise = parseFloat(document.getElementById('inp-exercise').value);

  // the core counts lapses (>= 355 ms, PVT-B) and scores mood; no ts = the crew member's current simulated day.
  // Hydration has no signal in the contract, so it is not sent.
  const payload = {
    crew_id: CREW,
    mood_answers: [mood],
    // shortcut: 60 min of exercise = 100% completion, the console's old assumption; use the real prescription when known
    values: { exercise_completion_pct: Math.min(100, (exercise / 60) * 100) },
  };
  if (pvtState.trials.length) payload.reaction_times_ms = pvtState.trials;

  await fetch('/checkin', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

  document.getElementById('checkin-modal').style.display = 'none';
}

window.addEventListener('resize', renderConnectorLines);
window.addEventListener('DOMContentLoaded', init);
