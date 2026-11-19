const C = 'safar-v9';
self.addEventListener('install', e => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', e => {
  const u = new URL(e.request.url);
  if (e.request.method === 'GET' && u.origin === self.location.origin &&
      (u.pathname.startsWith('/img/') || u.pathname.startsWith('/emoji/'))) {
    e.respondWith(caches.open(C).then(async c => {
      const m = await c.match(e.request);
      if (m) return m;
      const r = await fetch(e.request);
      if (r.ok) c.put(e.request, r.clone());
      return r;
    }).catch(() => fetch(e.request)));
  }
});
