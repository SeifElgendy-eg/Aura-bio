'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('web/static/app.js', 'utf8');
const elements = {};
const element = (id) => elements[id] ||= { children: [], innerHTML: '', hidden: false, textContent: '',
  querySelectorAll: () => [], focus: () => {}, setAttribute: () => {} };
const parts = ['neuro', 'cardio', 'immune', 'bone', 'habitat', 'metab'].map((id) => ({ dataset: { lane: id }, attrs: {}, setAttribute(k, v) { this.attrs[k] = v; } }));
const buttons = parts.map((p) => ({ dataset: p.dataset, word: {}, attrs: {}, setAttribute(k, v) { this.attrs[k] = v; }, querySelector() { return this.word; } }));
const context = { document: { getElementById: element, addEventListener: () => {}, activeElement: {},
  querySelectorAll: (s) => s === '#figure .part' ? parts : s === '#systems button' ? buttons : [] },
  location: { hash: '' }, fetch: () => { throw new Error('network not expected'); }, console };
vm.runInNewContext(source.slice(0, source.indexOf('// ---------- events ----------')) + `
globalThis.UI = { LANES, laneBand, renderBody, renderTodo, renderAlarms, alertHtml, headline, openAlerts, renderSignals,
 set(st, lane = null) { for (const sig of Object.keys(st.signals)) history[sig] = {points:[]}; status = st; selectedLane = lane; crew = 'cm2'; timeline = { first_ts: '2026-11-14T10:00:00Z', baseline_days: 14, days: [{day:35}], episodes: [] }; } };`, context);
const ui = context.UI;
const habitat = ui.LANES.find((l) => l.id === 'habitat');
assert.equal(ui.laneBand({environment: 'green', radiation: 'unknown'}, habitat), 'unknown');
assert.equal(ui.laneBand({environment: 'green', radiation: 'stale'}, habitat), 'stale');
assert.equal(ui.laneBand({environment: 'amber', radiation: 'red'}, habitat), 'red');
assert.equal(ui.laneBand({}, ui.LANES.find((l) => l.id === 'metab')), 'unknown');
const makeAlert = (id, level, active, ack = null) => ({ alert_id: id, id: 'pattern', name: '<Sleep loss>', level, active, acknowledged_at: ack,
 started_ts: '2026-12-18T10:00:00Z', last_ts: '2026-12-18T10:00:00Z', fired: {sleep_duration_h: {value:4, band:'red'}},
 response_crew: 'Follow onboard protocol.', response_system: 'Review with medical team.', citation: 'Example source', basis: 'proposed' });
const st = { systems: { neurocognitive: 'red', cardiovascular: 'stale', immune: 'amber', bone_muscle: 'green', environment: 'green', radiation: 'unknown' },
 signals: { sleep_duration_h: {system:'neurocognitive', value:4, band:'red', baseline_mean:7, provenance:'simulated', ts:'2026-12-18T10:00:00Z', rule:{kind:'abs', direction:'below', red:5, basis:'published', citation:'Sleep source'}} },
 alerts: [makeAlert(1,'amber',true), makeAlert(2,'red',true), makeAlert(3,'red',false)] };
ui.set(st, 'neuro');
element('figure').innerHTML = 'stable svg nodes';
ui.renderBody();
assert.equal(element('figure').innerHTML, 'stable svg nodes', 'live updates retain SVG/focus nodes');
assert.match(parts[0].attrs.class, /red/);
assert.match(parts[1].attrs.class, /stale/);
assert.match(parts[4].attrs.class, /unknown/);
assert.match(parts[5].attrs.class, /unknown/);
assert.match(parts[0].attrs['aria-label'], /Red/);
assert.equal(parts[0].attrs['aria-pressed'], 'true');
assert.match(element('system-content').innerHTML, /simulated/);
assert.match(element('system-content').innerHTML, /Show more · limits/);
assert.match(element('system-content').innerHTML, /Baseline 7 h/);
ui.renderAlarms();
assert(element('alarms').innerHTML.indexOf('data-alert="2"') < element('alarms').innerHTML.indexOf('data-alert="1"'), 'higher urgency sorts first');
assert.match(element('alarms').innerHTML, /resolved, to review/);
const html = ui.alertHtml(st.alerts[1]);
assert.match(html, /alert red active/);
assert.match(html, /&lt;Sleep loss&gt;/);
assert(html.indexOf('Follow onboard protocol.') < html.indexOf('<details'), 'crew response remains visible');
assert.match(html, /Show more · medical response and sources/);
assert.match(html, /Review with medical team/);
assert.match(html, /Example source/);
assert.match(ui.alertHtml(makeAlert(4,'red',false,'now')), /Resolved · acknowledged/);
ui.set({systems:{}, signals:{sleep_duration_h:{value:null,band:'unknown'}}, alerts:[]}, 'metab');
assert.equal(ui.headline().band, 'unknown');
ui.renderTodo();
assert.match(element('todo').innerHTML, /Check the sensor feed/);
assert.doesNotMatch(element('todo').innerHTML, /normal routine/);
ui.renderBody();
assert.match(element('system-content').innerHTML, /No metabolic readings/);
ui.set({systems:{}, signals:{sleep_duration_h:{value:4,band:'unknown'}}, alerts:[]});
assert.equal(ui.headline().band, 'unknown', 'unclassified readings do not imply normal');
ui.set({systems:{}, signals:{sleep_duration_h:{value:null,band:'stale'}}, alerts:[]});
assert.equal(ui.headline().band, 'stale', 'overdue readings do not need a value to remain overdue');
ui.set(st);
const dialog = element('d-alerts'); dialog.open = true; dialog.contains = () => false;
ui.openAlerts();
assert.match(element('da-list').innerHTML, /Active/);
const resolved = {...st, alerts:[makeAlert(2,'red',false)]};
ui.set(resolved); ui.openAlerts();
assert.match(element('da-list').innerHTML, /Resolved · to review/);
assert.match(source, /if \(\$\('d-alerts'\)\.open\) openAlerts\(\)/, 'render refreshes an open alert dialog');
ui.set(st);
ui.renderSignals().then(() => assert.match(element('sig-rows').innerHTML, /class="tag">simulated/));
// Both persistence and storage denial must leave an operable preference switch.
const themeSource = fs.readFileSync('web/static/theme.js','utf8');
for (const denied of [false, true]) {
  const listeners = {}, toggle = {setAttribute(k,v){this[k]=v;}, addEventListener(k,fn){listeners[k]=fn;}};
  const doc = {documentElement:{dataset:{}}, getElementById:() => toggle, addEventListener(k,fn){listeners[k]=fn;}, dispatchEvent:() => {}};
  let saved = 'light';
  const storage = {getItem(){if(denied) throw Error(); return saved;}, setItem(k,v){if(denied) throw Error(); saved=v;}};
  vm.runInNewContext(themeSource, {document:doc, localStorage:storage, Event:function(){}});
  assert.equal(doc.documentElement.dataset.theme, denied ? 'dark' : 'light');
  listeners.DOMContentLoaded(); listeners.click();
  assert.equal(doc.documentElement.dataset.theme, denied ? 'light' : 'dark');
  assert.equal(toggle['aria-pressed'], denied ? 'true' : 'false');
}
console.log('Console UI checks passed: backend band mapping, unknown/stale, urgency, disclosure, focus-node retention and theme storage.');
