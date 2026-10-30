/* 主页风铃导航：左上角挂钩点开后，一串吊牌像风铃一样落下。
   原有 .tab 按钮保留在 DOM 里负责切页逻辑，这里只做表现层并转发点击。 */
(function () {
  'use strict';
  var SVG = 'http://www.w3.org/2000/svg';
  var STORE = 'ob-chime-open';

  // 吊牌外形：路径都在 60×84 的画布里，顶部 0~18 留给丝带与吊环。
  function scallop(cx, cy, radius, bumps) {
    var d = '';
    for (var i = 0; i <= bumps; i++) {
      var a = -Math.PI / 2 + i * Math.PI * 2 / bumps;
      var x = (cx + radius * Math.cos(a)).toFixed(2), y = (cy + radius * Math.sin(a)).toFixed(2);
      d += i === 0 ? 'M' + x + ' ' + y : 'A' + (radius * Math.sin(Math.PI / bumps) * 1.08).toFixed(2) + ' ' + (radius * Math.sin(Math.PI / bumps) * 1.08).toFixed(2) + ' 0 0 1 ' + x + ' ' + y;
    }
    return d + 'Z';
  }
  var SHAPES = {
    arch: {top:18, iconY:50, d:'M12 32C12 23 20 18 30 18S48 23 48 32V76Q48 80 44 80H16Q12 80 12 76Z'},
    scallop: {top:28, iconY:51, d:scallop(30,51,22,14)},
    cameo: {top:26, iconY:50, d:'M30 26C39.5 26 47 36.7 47 50S39.5 74 30 74 13 63.3 13 50 20.5 26 30 26Z'},
    bookmark: {top:20, iconY:45, d:'M13 20H47V80L30 71 13 80Z'},
    heart: {top:35, iconY:50, d:'M30 78C18 68 11 59 11 46 11 37 17 31 23.5 31 27 31 29 33 30 35 31 33 33 31 36.5 31 43 31 49 37 49 46 49 59 42 68 30 78Z'}
  };
  var ICONS = {
    list: '<path d="M7 3.5h10V6H7zM8 6v2.5C6.5 9.5 6 11 6 13v5.5A2.5 2.5 0 0 0 8.5 21h7a2.5 2.5 0 0 0 2.5-2.5V13c0-2-.5-3.5-2-4.5V6"/><path d="M12 17.6c-1.8-1.2-2.8-2.2-2.8-3.4a1.4 1.4 0 0 1 2.8-.4 1.4 1.4 0 0 1 2.8.4c0 1.2-1 2.2-2.8 3.4z" class="ob-chime-fill"/>',
    breath: '<path d="M3 8h10a3 3 0 1 0-3-3M3 12.5h15a3 3 0 1 1-3 3M3 17h6"/>',
    network: '<path d="M5 6l7 5 5-7M12 11l7 4M12 11l-3 8 10-4"/><circle cx="5" cy="6" r="1.6" class="ob-chime-fill"/><circle cx="17" cy="4" r="1.3" class="ob-chime-fill"/><circle cx="19" cy="15" r="1.6" class="ob-chime-fill"/><circle cx="9" cy="19" r="1.3" class="ob-chime-fill"/><circle cx="12" cy="11" r="2"/>',
    plan: '<path d="M5 5h14v16H5zM8 3v4M12 3v4M16 3v4M8 11h8M8 14.5h8M8 18h5"/>',
    letters: '<path d="M3 6h18v13H3zM3 6.5l9 7 9-7"/><circle cx="12" cy="15.6" r="2.1" class="ob-chime-fill"/>',
    anchors: '<circle cx="12" cy="4.6" r="2.2"/><path d="M12 7v14M7.5 11h9M5 15c0 3.5 3 6 7 6s7-2.5 7-6"/>',
    'import': '<path d="M4 11l1.5 9h13L20 11M2.5 11h19M12 2v9.5M8.5 8L12 11.5 15.5 8"/>',
    logs: '<path d="M19 3C13 4 8.5 9 6.5 16.5L5 21M19 3c-1 5-4 9-9.5 11M9.6 10.4l3.2.5M7.9 13.9l3 .3"/>',
    self: '<circle cx="12" cy="8" r="3.6"/><path d="M5 20.5c.8-4 3.6-6.2 7-6.2s6.2 2.2 7 6.2"/>',
    settings: '<circle cx="8" cy="8" r="4.2"/><circle cx="8" cy="8" r="1.4" class="ob-chime-fill"/><path d="M11 11l9 9M15.8 15.8l2.2-2.2M18.4 18.4l2.2-2.2"/>'
  };
  var LOOK = {
    list:'arch', breath:'scallop', network:'cameo', plan:'arch', letters:'bookmark',
    anchors:'scallop', self:'scallop', 'import':'arch', logs:'cameo', settings:'heart'
  };

  function el(name, attrs, parent) {
    var node = document.createElementNS(SVG, name);
    Object.keys(attrs).forEach(function (key) { node.setAttribute(key, attrs[key]); });
    if (parent) parent.appendChild(node);
    return node;
  }

  function tagSvg(key) {
    var shape = SHAPES[LOOK[key]] || SHAPES.arch;
    var svg = el('svg', {viewBox:'0 0 60 84', 'aria-hidden':'true', focusable:'false', 'class':'ob-chime-svg'});
    el('path', {d:'M17 0L30 12.2 43 0M21 0L30 8.6 39 0', 'class':'ob-chime-ribbon'}, svg);
    el('circle', {cx:30, cy:14.6, r:3.2, 'class':'ob-chime-ring'}, svg);
    if (shape.top > 18.5) el('path', {d:'M30 17.8V' + shape.top, 'class':'ob-chime-ribbon'}, svg);
    el('path', {d:shape.d, 'class':'ob-chime-body'}, svg);
    el('path', {d:shape.d, 'class':'ob-chime-stitch', transform:'translate(30 ' + shape.iconY + ') scale(.84) translate(-30 -' + shape.iconY + ')'}, svg);
    var icon = el('g', {'class':'ob-chime-icon', transform:'translate(18 ' + (shape.iconY - 12) + ') scale(1)'}, svg);
    icon.innerHTML = ICONS[key] || '<circle cx="12" cy="12" r="4"/>';
    return svg;
  }

  function mount() {
    var nav = document.querySelector('nav.tabs');
    if (!nav || document.querySelector('.ob-chime')) return;
    var tabs = Array.from(nav.querySelectorAll('.tab[data-tab]'));
    if (!tabs.length) return;
    var reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
    var narrow = window.matchMedia('(max-width: 1100px)');
    document.body.classList.add('ob-journal');

    // 「Ombre Brain」左边换成蝴蝶结挂钩，一眼能看出可以点；风铃直接从它下面串下来。
    // 原品牌图标仍留在 DOM（其它脚本会更新它），只是隐藏。
    var header = document.querySelector('.header');
    var brand = header && header.querySelector('h1 .ob-logo');
    if (!header || !brand) return;
    var logo = document.createElement('img');
    logo.className = 'ob-chime-bow';
    logo.src = '/static/chime-hook.webp';
    logo.alt = '';
    logo.draggable = false;
    var toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'ob-chime-hook';
    toggle.setAttribute('aria-expanded', 'false');
    toggle.setAttribute('aria-controls', 'ob-chime-list');
    toggle.setAttribute('aria-label', '页面导航');
    toggle.title = '展开导航风铃';
    brand.parentNode.insertBefore(toggle, brand);
    toggle.appendChild(logo);
    brand.classList.add('ob-chime-brand-hidden');

    var root = document.createElement('nav');
    root.className = 'ob-chime';
    root.id = 'ob-chime';
    root.setAttribute('aria-label', '页面导航');
    var scrim = document.createElement('div');
    scrim.className = 'ob-chime-scrim';
    scrim.setAttribute('aria-hidden', 'true');

    var list = document.createElement('ul');
    list.className = 'ob-chime-list';
    list.id = 'ob-chime-list';
    list.hidden = true;

    // Breath 模拟没什么使用场景，它的位置换成左下角原来的「我」面板入口。
    var entries = tabs.filter(function (tab) { return tab.dataset.tab !== 'breath'; }).map(function (tab) {
      var spans = tab.querySelectorAll('span');
      return {key:tab.dataset.tab, tab:tab,
        zh:spans[0] ? spans[0].textContent.trim() : tab.dataset.tab,
        en:tab.querySelector('.tab-en') ? tab.querySelector('.tab-en').textContent.trim() : ''};
    });
    if (typeof window.openSelfPanel === 'function') {
      entries.splice(1, 0, {key:'self', zh:'我', en:'Me · You · Them', image:'breath',
        action:function () { window.openSelfPanel(); }});
    }

    var items = entries.map(function (entry, index) {
      var key = entry.key, tab = entry.tab, zh = entry.zh, en = entry.en;
      var li = document.createElement('li');
      li.className = 'ob-chime-item';
      var button = document.createElement('button');
      button.type = 'button';
      button.className = 'ob-chime-tag';
      button.dataset.chimeTab = key;
      button.setAttribute('aria-label', zh + (en ? ' ' + en : ''));
      var swing = document.createElement('span');
      swing.className = 'ob-chime-swing';
      // 瓷釉吊牌图（丝带已画在图上）；图片缺失时退回内置 SVG。
      var img = document.createElement('img');
      img.className = 'ob-chime-img';
      img.src = '/static/chime-' + (entry.image || key) + '.webp';
      img.alt = '';
      img.draggable = false;
      img.decoding = 'async';
      img.addEventListener('error', function onError() {
        img.removeEventListener('error', onError);
        img.replaceWith(tagSvg(key));
      });
      swing.appendChild(img);
      button.appendChild(swing);
      var label = document.createElement('span');
      label.className = 'ob-chime-label';
      label.setAttribute('aria-hidden', 'true');
      label.innerHTML = '<b></b><i></i>';
      label.firstChild.textContent = zh;
      label.lastChild.textContent = en;
      button.appendChild(label);
      button.addEventListener('click', function () {
        ring(swing, 1.6);
        if (entry.action) entry.action();
        else if (!tab.classList.contains('active')) tab.click();
        if (narrow.matches) setOpen(false, true);
      });
      button.addEventListener('mouseenter', function () { ring(swing, .7); });
      li.style.zIndex = String(entries.length - index + 1);
      li.appendChild(button);
      list.appendChild(li);
      return {li:li, button:button, swing:swing, tab:tab};
    });
    var tassel = document.createElement('li');
    tassel.className = 'ob-chime-tassel';
    tassel.setAttribute('aria-hidden', 'true');
    list.appendChild(tassel);
    root.appendChild(list);
    var defs = el('svg', {width:0, height:0, 'aria-hidden':'true', style:'position:absolute'});
    defs.innerHTML = '<defs><linearGradient id="ob-chime-paper" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ffffff"/><stop offset="1" stop-color="#e6e7f6"/></linearGradient>'
      + '<linearGradient id="ob-chime-paper-active" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#f1edfd"/><stop offset="1" stop-color="#d3cdef"/></linearGradient></defs>';
    root.appendChild(defs);
    header.appendChild(root);
    document.body.appendChild(scrim);

    // 头部在桌面端是 sticky，风铃挂在头部里随它固定；位置对齐图标正下方。
    function place() {
      var h = header.getBoundingClientRect(), l = logo.getBoundingClientRect();
      root.style.left = (l.left - h.left + l.width / 2 - root.offsetWidth / 2) + 'px';
      // 第一根丝带塞到蝴蝶结后面，整串像挂在它上面
      root.style.top = (l.bottom - h.top - 14) + 'px';
    }
    window.addEventListener('resize', place);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(place);
    place();

    function syncActive() {
      items.forEach(function (item) {
        var on = !!item.tab && item.tab.classList.contains('active');
        item.li.classList.toggle('is-active', on);
        if (on) item.button.setAttribute('aria-current', 'page');
        else item.button.removeAttribute('aria-current');
      });
    }
    new MutationObserver(syncActive).observe(nav, {subtree:true, attributes:true, attributeFilter:['class']});
    syncActive();

    function ring(node, strength) {
      if (reduced.matches || typeof node.animate !== 'function') return;
      var a = 9 * strength;
      node.animate([
        {transform:'rotate(0deg)'},
        {transform:'rotate(' + a + 'deg)', offset:.18},
        {transform:'rotate(' + (-a * .62) + 'deg)', offset:.42},
        {transform:'rotate(' + (a * .32) + 'deg)', offset:.66},
        {transform:'rotate(' + (-a * .12) + 'deg)', offset:.85},
        {transform:'rotate(0deg)'}
      ], {duration:900 + strength * 250, easing:'ease-out'});
    }

    var open = false;
    var running = [];
    function stopRunning() { running.forEach(function (a) { a.cancel(); }); running = []; }

    function setOpen(next, animate) {
      if (next === open) return;
      open = next;
      try { localStorage.setItem(STORE, open ? '1' : '0'); } catch (_) {}
      toggle.setAttribute('aria-expanded', String(open));
      toggle.title = open ? '收起导航风铃' : '展开导航风铃';
      root.classList.toggle('is-open', open);
      document.body.classList.toggle('ob-chime-open', open);
      if (open) place();
      stopRunning();
      var motion = animate && !reduced.matches && typeof list.animate === 'function';
      if (open) {
        list.hidden = false;
        if (!motion) return;
        items.concat([{li:tassel}]).forEach(function (item, i) {
          // 落下：带一点过冲回弹，随后整串像被风带过一样依次摆动。
          running.push(item.li.animate([
            {opacity:0, transform:'translateY(' + (-46 - i * 14) + 'px)'},
            {opacity:1, transform:'translateY(7px)', offset:.62},
            {transform:'translateY(-2px)', offset:.82},
            {opacity:1, transform:'translateY(0)'}
          ], {duration:520, delay:i * 38, easing:'cubic-bezier(.3,.7,.35,1)', fill:'backwards'}));
          if (item.swing) running.push(item.swing.animate([
            {transform:'rotate(' + (i % 2 ? -14 : 12) + 'deg)'},
            {transform:'rotate(' + (i % 2 ? 8 : -7) + 'deg)', offset:.35},
            {transform:'rotate(' + (i % 2 ? -3.5 : 3) + 'deg)', offset:.65},
            {transform:'rotate(0deg)'}
          ], {duration:1150, delay:i * 38 + 120, easing:'ease-out', fill:'backwards'}));
        });
      } else {
        if (!motion) { list.hidden = true; return; }
        var all = items.map(function (item) { return item.li; }).concat([tassel]);
        var last = null;
        all.forEach(function (li, i) {
          last = li.animate([
            {opacity:1, transform:'translateY(0)'},
            {opacity:0, transform:'translateY(' + (-30 - i * 12) + 'px)'}
          ], {duration:260, delay:(all.length - 1 - i) * 18, easing:'cubic-bezier(.5,0,.75,.4)', fill:'forwards'});
          running.push(last);
        });
        last.finished.then(function () {
          if (open) return;
          list.hidden = true;
          stopRunning();
        }).catch(function () {});
      }
    }

    toggle.addEventListener('click', function () {
      setOpen(!open, true);
      if (open && !reduced.matches && typeof logo.animate === 'function') {
        logo.animate([{transform:'rotate(0)'},{transform:'rotate(-12deg)',offset:.3},{transform:'rotate(6deg)',offset:.65},{transform:'rotate(0)'}], {duration:520, easing:'ease-out'});
      }
    });
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && open && (root.contains(document.activeElement) || document.activeElement === toggle)) {
        setOpen(false, true);
        toggle.focus();
      }
    });
    document.addEventListener('click', function (event) {
      if (open && narrow.matches && !root.contains(event.target) && !toggle.contains(event.target)) setOpen(false, true);
    });

    var remembered = null;
    try { remembered = localStorage.getItem(STORE); } catch (_) {}
    if (remembered !== '0' && !narrow.matches) {
      // 记住上次展开：等登录封面揭开后再落下，让风铃动画被看见。
      var cover = document.getElementById('auth-overlay');
      var drop = function () { setTimeout(function () { setOpen(true, true); }, 260); };
      if (cover && cover.style.display !== 'none') {
        var watch = new MutationObserver(function () {
          if (cover.style.display === 'none') { watch.disconnect(); drop(); }
        });
        watch.observe(cover, {attributes:true, attributeFilter:['style']});
      } else drop();
    }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount, {once:true});
  else mount();
})();
