/* PWA 安装所需的最小 Service Worker。
   只缓存带内容版本号的公开图片、字体和脚本；HTML、/auth、/api、记忆附件一律直连服务器，不进缓存。 */
'use strict';
const CACHE = 'ombre-static-v1';
const VERSIONED = /^\/static\/[A-Za-z0-9_-]+\.(?:webp|png|jpg|svg|woff2?|ttf|css|js)$/;

self.addEventListener('install', event => event.waitUntil(self.skipWaiting()));
self.addEventListener('activate', event => event.waitUntil((async () => {
  const keys = await caches.keys();
  await Promise.all(keys.filter(key => key.startsWith('ombre-static-') && key !== CACHE).map(key => caches.delete(key)));
  await self.clients.claim();
})()));

self.addEventListener('fetch', event => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== 'GET' || url.origin !== self.location.origin) return;
  if (request.mode === 'navigate') {
    event.respondWith(fetch(request).catch(() => new Response(
      '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Ombre Brain</title>'
      + '<body style="margin:0;background:#f3f1fb;color:#49435f;font:16px/1.8 serif;padding:18vh 9vw"><h1 style="font-weight:400">暂时无法连接</h1>'
      + '<p>连接网络后重新打开记忆册。</p><button onclick="location.reload()">重试</button></body></html>',
      {status: 503, headers: {'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store'}})));
    return;
  }
  if (!VERSIONED.test(url.pathname) || !/^[a-f0-9]{16}$/.test(url.searchParams.get('v') || '')) return;
  event.respondWith((async () => {
    const cache = await caches.open(CACHE);
    const hit = await cache.match(request);
    if (hit) return hit;
    const response = await fetch(request);
    if (response.ok && (response.headers.get('Cache-Control') || '').includes('immutable')) {
      try {
        await cache.put(request, response.clone());
        const keys = await cache.keys();
        await Promise.all(keys.slice(0, Math.max(0, keys.length - 120)).map(key => cache.delete(key)));
      } catch (_) { /* 存储空间不足不影响显示 */ }
    }
    return response;
  })());
});
