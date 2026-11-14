'use strict';
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));
// No fetch handler: this worker does not cache or intercept telemetry/game assets.
self.addEventListener('push', (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch { /* show a safe generic notice */ }
  const id = Number.isSafeInteger(data.event_id) ? data.event_id : 'update';
  event.waitUntil(self.registration.showNotification(String(data.title || 'AURA-Bio crew alert').slice(0, 128), {
    body: String(data.body || 'A crew alert needs review. Open the console. Simulated data.').slice(0, 240),
    tag: `aura-event-${id}`, renotify: false,
    data: { url: typeof data.url === 'string' ? data.url : '/#crew' },
  }));
});
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  let target;
  try { target = new URL(event.notification.data?.url || '/#crew', self.location.origin); }
  catch { target = new URL('/#crew', self.location.origin); }
  if (target.origin !== self.location.origin || target.pathname !== '/') target = new URL('/#crew', self.location.origin);
  event.waitUntil((async () => {
    const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    const consoleWindow = windows.find((client) => {
      const url = new URL(client.url);
      return url.origin === self.location.origin && url.pathname === '/';
    });
    if (consoleWindow) { await consoleWindow.navigate(target.href); return consoleWindow.focus(); }
    return self.clients.openWindow(target.href);
  })());
});
