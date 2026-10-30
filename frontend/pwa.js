/* Install support and a public-assets-only cache; sessions stay on the server. */
(function () {
  'use strict';
  if ('serviceWorker' in navigator && window.isSecureContext) {
    window.addEventListener('load', function () {
      navigator.serviceWorker.register('/sw.js', {scope:'/',updateViaCache:'none'})
        .catch(function (error) { console.warn('应用缓存暂不可用', error); });
    }, {once:true});
  }
  window.addEventListener('pageshow', function (event) {
    if (!event.persisted) return;
    document.documentElement.classList.add('auth-pending');
    var cover = document.getElementById('auth-overlay');
    if (cover) cover.style.display = 'flex';
    if (typeof checkAuth === 'function') checkAuth().then(function (ok) {
      if (ok) beginAuthenticatedDashboardSession();
    });
  });
  window.addEventListener('pagehide', function () {
    // Keep a BFCache snapshot from exposing the previous authenticated screen.
    document.documentElement.classList.add('auth-pending');
  });
})();
