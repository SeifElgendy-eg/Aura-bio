/* Crew-wide notices are backend events, not frontend health judgments. */
'use strict';
window.AuraNotifications = (() => {
  let registration = null, subscription = null, config = null, cursor = 0, started = false, latest = null;
  const seen = new Set();
  const pending = [];
  let overflow = 0;
  const el = (id) => document.getElementById(id);
  function message(text) { el('notification-status').textContent = text; }
  function updateButton() {
    const button = el('notifications-toggle');
    button.textContent = subscription ? 'Disable crew notifications' : 'Enable crew notifications';
    button.setAttribute('aria-pressed', String(!!subscription));
  }
  function renderNotice() {
    latest = pending[0] || null;
    el('crew-notification').hidden = !latest;
    if (!latest) return;
    const count = pending.length + overflow;
    el('crew-notification-text').textContent = `${count} crew alert${count === 1 ? '' : 's'} · ${String(latest.crew_id).toUpperCase()}: ${latest.level === 'red' ? 'Red' : 'Amber'} ${latest.kind === 'escalated' ? 'escalation' : 'alert'} · ${latest.name}. For all crew · simulated data.${overflow ? ' More updates are available in Crew overview.' : ''}`;
  }
  function receive(event) {
    if (!event || !Number.isSafeInteger(event.id) || event.id < 1 || seen.has(event.id)) return;
    seen.add(event.id);
    if (seen.size > 100) seen.delete(seen.values().next().value);
    cursor = Math.max(cursor, event.id);
    pending.push(event);
    pending.sort((a, b) => Number(b.level === 'red') - Number(a.level === 'red') || b.id - a.id);
    if (pending.length > 20) { pending.pop(); overflow++; }
    renderNotice();
  }
  async function sync(initial = false) {
    try {
      const response = await fetch(`/notifications?after=${cursor}`);
      if (!response.ok) return;
      const data = await response.json();
      if (!initial) (data.notifications || []).forEach(receive);
      cursor = Math.max(cursor, Number(data.cursor) || 0);
    } catch { /* the connection banner already explains offline status */ }
  }
  async function save(method, value) {
    const response = await fetch('/notifications/subscriptions', {
      method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value.toJSON()),
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(typeof body.detail === 'string' ? body.detail : `server answered ${response.status}`);
    }
  }
  function decodeKey(value) {
    const padded = value.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - value.length % 4) % 4);
    return Uint8Array.from(atob(padded), (character) => character.charCodeAt(0));
  }
  async function toggle() {
    const button = el('notifications-toggle');
    button.disabled = true;
    try {
      if (subscription) {
        await save('DELETE', subscription);
        const removed = await subscription.unsubscribe();
        if (!removed) throw new Error('browser did not remove its subscription; retry');
        subscription = null;
        message('Browser push off. Crew alerts still appear while this console is connected.');
      } else {
        // Permission is requested only here, directly after the member's click.
        const permission = await Notification.requestPermission();
        if (permission !== 'granted') {
          message(permission === 'denied' ? 'Notifications blocked. Change this site’s browser permission to enable them.' : 'Permission not granted. Crew alerts still appear in this console.');
          return;
        }
        subscription = await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: decodeKey(config.public_key) });
        try { await save('POST', subscription); }
        catch (error) { await subscription.unsubscribe(); subscription = null; throw error; }
        message('Enabled on this device for all crew. Push needs internet and a running backend; delivery depends on browser/OS settings.');
      }
    } catch (error) { message(`Notifications not updated: ${error.message}. Retry when connected.`); }
    finally { button.disabled = false; updateButton(); }
  }
  async function init() {
    if (started) return;
    started = true;
    const button = el('notifications-toggle');
    button.addEventListener('click', toggle);
    el('crew-notification-dismiss').addEventListener('click', () => {
      pending.shift();
      if (!pending.length) overflow = 0;
      renderNotice();
      if (!latest) el('main')?.focus?.();
    });
    el('crew-notification-review').addEventListener('click', () => {
      if (latest) window.dispatchEvent(new CustomEvent('aura-review-crew', { detail: String(latest.crew_id) }));
    });
    await sync(true);
    if (!window.isSecureContext || !('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window)) {
      button.disabled = true;
      message('Browser push is unavailable here. Crew alerts still appear in this console while connected.');
      return;
    }
    try {
      const response = await fetch('/notifications/config');
      if (!response.ok) throw new Error('notification service unavailable');
      config = await response.json();
      if (!config.enabled || !config.public_key) throw new Error('server push is not configured');
      await navigator.serviceWorker.register('/notifications-sw.js', { scope: '/' });
      registration = await navigator.serviceWorker.ready;
      subscription = await registration.pushManager.getSubscription();
      if (subscription) await save('POST', subscription);
      updateButton();
      message(subscription ? 'Enabled on this device for all crew. Internet and a running backend are required.' : 'Opt in on each member’s device to receive all crew alerts, including when the console is in the background.');
    } catch (error) {
      button.disabled = true;
      message(`Browser push unavailable: ${error.message}. Reload to retry; connected crew alerts still work.`);
    }
  }
  return { init, receive, sync, decodeKey };
})();
