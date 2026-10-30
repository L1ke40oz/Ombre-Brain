/* 仅在 HTTPS（或本机 localhost）这类安全上下文注册 Service Worker；
   HTTP + 公网 IP 访问时浏览器不允许安装 PWA，这里什么也不做。 */
(function () {
  'use strict';
  if (!('serviceWorker' in navigator) || !window.isSecureContext) return;
  window.addEventListener('load', function () {
    navigator.serviceWorker.register('/sw.js', {scope: '/', updateViaCache: 'none'})
      .catch(function (error) { console.warn('Service Worker 注册失败', error); });
  }, {once: true});
})();
