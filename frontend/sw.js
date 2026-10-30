/* Only public, content-versioned artwork/fonts/engine are stored locally.
   Never cache HTML, credentials, /auth, /api, or memory attachments. */
'use strict';
const CACHE = 'ombre-public-art-v1';
self.addEventListener('install', event => event.waitUntil(self.skipWaiting()));
self.addEventListener('activate', event => event.waitUntil((async () => {
  const keys = await caches.keys();
  await Promise.all(keys.filter(key => key.startsWith('ombre-public-art-') && key !== CACHE).map(key => caches.delete(key)));
  await self.clients.claim();
})()));
self.addEventListener('fetch', event => {
  const req = event.request, url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== self.location.origin) return;
  if (req.mode === 'navigate') {
    event.respondWith(fetch(req).catch(() => new Response(
      '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Ombre Brain</title><body style="background:#f3f1fb;color:#49435f;font:18px/1.8 system-ui;padding:15vh 8vw"><h1>暂时无法连接</h1><p>连接网络后，重新打开记忆册。</p><button onclick="location.reload()">重试</button></body></html>',
      {status:503,headers:{'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store'}})));
    return;
  }
  if (!/^\/static\/[a-zA-Z0-9_-]+\.(?:webp|png|jpg|svg|woff2?|ttf)$/.test(url.pathname) && url.pathname !== '/static/galaxy-engine.js') return;
  if (!/^[a-f0-9]{16}$/.test(url.searchParams.get('v') || '')) return;
  event.respondWith((async () => {
    try {
      const cache = await caches.open(CACHE), hit = await cache.match(req);
      if (hit) return hit;
      const response = await fetch(req);
      if (response.ok && (response.headers.get('Cache-Control') || '').includes('immutable')) {
        try {
          await cache.put(req, response.clone());
          const keys = await cache.keys();
          await Promise.all(keys.slice(0, Math.max(0, keys.length - 100)).map(key => cache.delete(key)));
        } catch (_) { /* Storage limits must not prevent displaying an image. */ }
      }
      return response;
    } catch (_) { return fetch(req); }
  })());
});
