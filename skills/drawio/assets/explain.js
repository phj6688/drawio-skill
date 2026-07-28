/* explain.js: runtime for a generated diagram explainer.
   Reads three globals emitted by explain.py: TEXTS, ALSO, CFG. */
(function () {
  'use strict';
  var root = document.documentElement;
  var DGS = CFG.dgs, COMPS = CFG.comps, TABS = CFG.tabs;
  var scale = {}, fitted = {};
  DGS.forEach(function (d) { scale[d] = 1; });

  function $(sel, ctx) { return (ctx || document).querySelector(sel); }
  function $$(sel, ctx) { return [].slice.call((ctx || document).querySelectorAll(sel)); }
  function canvasOf(dg) { return $('.dgcanvas[data-dg="' + dg + '"]'); }
  function wrapOf(dg) { return $('.dgwrap[data-dg="' + dg + '"]'); }

  /* ---------------- theme ---------------- */
  $('#theme').addEventListener('click', function () {
    var cur = root.getAttribute('data-theme');
    if (!cur) cur = matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    root.setAttribute('data-theme', cur === 'dark' ? 'light' : 'dark');
  });

  /* ---------------- tabs + component picker ---------------- */
  function activeComp() {
    var on = $('.pill.on');
    return on ? on.dataset.comp : (COMPS[0] || null);
  }
  function currentTab() {
    var t = $('.tab[aria-selected="true"]');
    return t ? t.dataset.tab : TABS[0];
  }
  /* the diagram actually on screen, or null on the reference tab */
  function visibleDg() {
    var t = currentTab();
    if (t === '__ref') return null;
    if (t === '__comp') return activeComp();
    return t;
  }
  function showTab(name, skipHash) {
    if (TABS.indexOf(name) < 0) name = TABS[0];
    $$('.tab').forEach(function (t) {
      t.setAttribute('aria-selected', String(t.dataset.tab === name));
    });
    TABS.forEach(function (n) {
      var p = document.getElementById('panel-' + n);
      if (p) p.hidden = (n !== name);
    });
    var q = $('#q');
    q.hidden = (name !== '__ref');
    $('#hits').textContent = '';
    if (name !== '__ref') { q.value = ''; refSearch(); }
    try { localStorage.setItem('explain_tab', name); } catch (e) {}
    var dg = visibleDg();
    if (dg && !fitted[dg]) { fit(dg); fitted[dg] = true; }
    if (!skipHash) writeHash();
  }
  $$('.tab').forEach(function (t) {
    t.addEventListener('click', function () { showTab(t.dataset.tab); });
  });
  function showComp(key, skipHash) {
    $$('.pill').forEach(function (x) { x.classList.toggle('on', x.dataset.comp === key); });
    $$('.comp').forEach(function (b) { b.hidden = (b.dataset.comp !== key); });
    try { localStorage.setItem('explain_comp', key); } catch (e) {}
    if (!fitted[key]) { fit(key); fitted[key] = true; }
    if (!skipHash) writeHash();
  }
  $$('.pill').forEach(function (p) {
    p.addEventListener('click', function () { showComp(p.dataset.comp); });
  });

  /* ---------------- pan + zoom ---------------- */
  function applyScale(dg) {
    var c = canvasOf(dg); if (!c) return;
    c.style.transform = 'scale(' + scale[dg] + ')';
    var w = parseFloat(c.style.width), h = parseFloat(c.style.height);
    c.style.marginRight = (w * (scale[dg] - 1) + 22) + 'px';
    c.style.marginBottom = (h * (scale[dg] - 1) + 22) + 'px';
    var lbl = $('.zlvl[data-dg="' + dg + '"]');
    if (lbl) lbl.textContent = Math.round(scale[dg] * 100) + '%';
  }
  function setScale(dg, v, anchor) {
    var wrap = wrapOf(dg), old = scale[dg];
    v = Math.max(0.15, Math.min(4, v));
    if (!wrap || v === old) return;
    var ax = anchor ? anchor.x : wrap.clientWidth / 2;
    var ay = anchor ? anchor.y : wrap.clientHeight / 2;
    var cx = (wrap.scrollLeft + ax) / old, cy = (wrap.scrollTop + ay) / old;
    scale[dg] = v; applyScale(dg);
    wrap.scrollLeft = cx * v - ax; wrap.scrollTop = cy * v - ay;
  }
  function fit(dg) {
    var wrap = wrapOf(dg), c = canvasOf(dg);
    if (!wrap || !c || !wrap.clientWidth) return;
    var w = parseFloat(c.style.width), h = parseFloat(c.style.height);
    scale[dg] = Math.max(0.15, Math.min(1,
      Math.min((wrap.clientWidth - 54) / w, (wrap.clientHeight - 54) / h)));
    applyScale(dg);
    wrap.scrollLeft = 0; wrap.scrollTop = 0;
  }
  $$('.zb').forEach(function (b) {
    b.addEventListener('click', function () {
      var dg = b.dataset.dg, a = b.dataset.act;
      if (a === 'in') setScale(dg, scale[dg] * 1.25);
      else if (a === 'out') setScale(dg, scale[dg] / 1.25);
      else if (a === 'fit') fit(dg);
      else if (a === 'walk') walk(dg, +1);
      else { scale[dg] = 1; applyScale(dg); }
    });
  });
  $$('.dgwrap').forEach(function (wrap) {
    var dg = wrap.dataset.dg, down = false, sx, sy, sl, st;
    wrap.addEventListener('mousedown', function (e) {
      if (e.target.closest('.hot')) return;   // let the hotspot get the click
      down = true; sx = e.clientX; sy = e.clientY;
      sl = wrap.scrollLeft; st = wrap.scrollTop;
      wrap.classList.add('grabbing'); e.preventDefault();
    });
    window.addEventListener('mousemove', function (e) {
      if (!down) return;
      wrap.scrollLeft = sl - (e.clientX - sx);
      wrap.scrollTop = st - (e.clientY - sy);
    });
    window.addEventListener('mouseup', function () {
      down = false; wrap.classList.remove('grabbing');
    });
    wrap.addEventListener('wheel', function (e) {
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault();
      var r = wrap.getBoundingClientRect();
      setScale(dg, scale[dg] * (e.deltaY < 0 ? 1.12 : 1 / 1.12),
        { x: e.clientX - r.left, y: e.clientY - r.top });
    }, { passive: false });
    wrap.addEventListener('keydown', function (e) {
      var s = 90;
      if (e.key === 'ArrowLeft') { wrap.scrollLeft -= s; e.preventDefault(); }
      if (e.key === 'ArrowRight') { wrap.scrollLeft += s; e.preventDefault(); }
      if (e.key === 'ArrowUp') { wrap.scrollTop -= s; e.preventDefault(); }
      if (e.key === 'ArrowDown') { wrap.scrollTop += s; e.preventDefault(); }
      if (e.key === '+' || e.key === '=') { setScale(dg, scale[dg] * 1.25); e.preventDefault(); }
      if (e.key === '-') { setScale(dg, scale[dg] / 1.25); e.preventDefault(); }
      if (e.key === '0') { fit(dg); e.preventDefault(); }
    });
  });

  /* ---------------- popup ---------------- */
  function closeCard(dg) {
    var d = $('.detail[data-dg="' + dg + '"]'); if (!d) return;
    $('.dcard', d).hidden = true;
    $('.dhint', d).hidden = false;
    $$('.hot[data-dg="' + dg + '"].sel').forEach(function (h) { h.classList.remove('sel'); });
  }
  function openCard(btn, skipHash) {
    var dg = btn.dataset.dg, id = btn.dataset.id, t = TEXTS[id];
    if (!t) return;
    var d = $('.detail[data-dg="' + dg + '"]');
    $$('.hot[data-dg="' + dg + '"].sel').forEach(function (h) { h.classList.remove('sel'); });
    btn.classList.add('sel');
    $('.dhint', d).hidden = true;
    var card = $('.dcard', d); card.hidden = false;
    $('.dtitel', card).textContent = t.title || id.split('::')[1];
    function put(sel, v) {
      var el = $(sel, card);
      $('p', el).textContent = v || '';
      el.hidden = !v;
    }
    put('.dwhat', t.what); put('.dwhy', t.why); put('.dfact', t.fact);

    var alsoBox = $('.dalso', card), peers = ALSO[id] || [];
    if (peers.length) {
      var span = $('span', alsoBox); span.textContent = '';
      peers.forEach(function (p) {
        var a = document.createElement('a');
        a.textContent = p[0]; a.href = '#' + p[0] + '/' + p[1];
        a.addEventListener('click', function (e) { e.preventDefault(); goTo(p[0], p[1]); });
        span.appendChild(a);
      });
      alsoBox.hidden = false;
    } else alsoBox.hidden = true;

    var dd = $('.ddetail', card);
    if (t.detail) { dd.hidden = false; $('code', dd).textContent = t.detail; }
    else dd.hidden = true;

    d.scrollTop = 0;
    if (!skipHash) writeHash(id);
  }
  $$('.hot').forEach(function (b) {
    b.addEventListener('click', function (e) { e.stopPropagation(); openCard(b); });
  });
  $$('.dclose').forEach(function (b) {
    b.addEventListener('click', function () { closeCard(b.closest('.detail').dataset.dg); });
  });
  $$('.dcopy').forEach(function (b) {
    b.addEventListener('click', function () {
      var url = location.href;
      var done = function () {
        var old = b.textContent; b.textContent = CFG.ui.copied;
        setTimeout(function () { b.textContent = old; }, 1400);
      };
      if (navigator.clipboard) navigator.clipboard.writeText(url).then(done, done);
      else done();
    });
  });
  $$('.dgmark').forEach(function (cb) {
    var c = canvasOf(cb.dataset.dg);
    if (c) c.classList.add('marked');
    cb.addEventListener('change', function () { c.classList.toggle('marked', cb.checked); });
  });

  /* ---------------- walk: step through the boxes in reading order ---------- */
  function boxesOf(dg) {
    return $$('.hot[data-dg="' + dg + '"][data-leaf="1"]').sort(function (a, b) {
      var ay = parseFloat(a.style.top), by = parseFloat(b.style.top);
      if (Math.abs(ay - by) > 24) return ay - by;
      return parseFloat(a.style.left) - parseFloat(b.style.left);
    });
  }
  function walk(dg, dir) {
    var list = boxesOf(dg);
    if (!list.length) return;
    var cur = $('.hot[data-dg="' + dg + '"].sel');
    var i = cur ? list.indexOf(cur) : -1;
    i = (i + dir + list.length) % list.length;
    var next = list[i];
    openCard(next);
    next.scrollIntoView({ block: 'center', inline: 'center', behavior: 'smooth' });
  }

  /* ---------------- deep links: #diagram/element ---------------- */
  var muteHash = false;
  function writeHash(id) {
    var dg = visibleDg();
    if (muteHash) return;
    var h = '';
    if (id) h = id.replace('::', '/');
    else if (dg) h = dg;
    else h = '__ref';
    muteHash = true;
    try { history.replaceState(null, '', '#' + h); } finally { muteHash = false; }
  }
  function goTo(dg, eid) {
    var tab = COMPS.indexOf(dg) >= 0 ? '__comp' : dg;
    showTab(tab, true);
    if (tab === '__comp') showComp(dg, true);
    if (!eid) { writeHash(); return; }
    var btn = $('.hot[data-dg="' + dg + '"][data-id="' + dg + '::' + eid + '"]');
    if (btn) {
      openCard(btn, true);
      btn.scrollIntoView({ block: 'center', inline: 'center' });
      writeHash(dg + '::' + eid);
    }
  }
  function readHash() {
    var h = decodeURIComponent((location.hash || '').replace(/^#/, ''));
    if (!h) return false;
    var parts = h.split('/'), dg = parts[0], eid = parts[1];
    if (dg === '__ref' || dg === '__comp') { showTab(dg, true); return true; }
    if (DGS.indexOf(dg) < 0) return false;
    goTo(dg, eid);
    return true;
  }
  window.addEventListener('hashchange', function () { if (!muteHash) readHash(); });

  /* ---------------- diagram search ---------------- */
  function norm(s) {
    return (s || '').toLowerCase()
      .replace(/ä/g, 'ae').replace(/ö/g, 'oe').replace(/ü/g, 'ue').replace(/ß/g, 'ss');
  }
  $$('.dgsearch').forEach(function (inp) {
    inp.addEventListener('input', function () {
      var dg = inp.dataset.dg, term = norm(inp.value.trim());
      var list = $$('.hot[data-dg="' + dg + '"]');
      if (!term) { list.forEach(function (h) { h.classList.remove('dim', 'match'); }); return; }
      var first = null;
      list.forEach(function (h) {
        var t = TEXTS[h.dataset.id] || {};
        var ok = norm([t.title, t.what, t.why, t.fact].join(' ')).indexOf(term) > -1;
        h.classList.toggle('match', ok); h.classList.toggle('dim', !ok);
        if (ok && !first) first = h;
      });
      if (first) first.scrollIntoView({ block: 'center', inline: 'center' });
    });
  });

  /* ---------------- reference search ---------------- */
  var refUnits = $$('#panel-__ref .card, #panel-__ref .gi, #panel-__ref .tw tr, ' +
                    '#panel-__ref .flow, #panel-__ref .note');
  refUnits.forEach(function (u) { u.dataset.t = norm(u.textContent || '').replace(/\s+/g, ' '); });
  var refSections = $$('#panel-__ref section');
  function refSearch() {
    var q = $('#q'), none = $('#noresult'), raw = q.value.trim();
    if (!raw) {
      refUnits.forEach(function (u) { u.classList.remove('hide'); });
      refSections.forEach(function (s) { s.classList.remove('hide'); });
      if (none) none.classList.add('hide');
      $('#hits').textContent = ''; return;
    }
    var terms = norm(raw).split(/\s+/).filter(Boolean), n = 0;
    refUnits.forEach(function (u) {
      var ok = terms.every(function (t) { return u.dataset.t.indexOf(t) > -1; });
      u.classList.toggle('hide', !ok); if (ok) n++;
    });
    refSections.forEach(function (s) {
      var vis = s.querySelector('.card:not(.hide), .gi:not(.hide), tr:not(.hide), ' +
                                '.flow:not(.hide), .note:not(.hide)');
      var head = s.querySelector('h2');
      var hm = head && terms.every(function (t) { return norm(head.textContent).indexOf(t) > -1; });
      s.classList.toggle('hide', !vis && !hm);
      if (hm) {
        s.classList.remove('hide');
        $$('.card,.gi,tr,.flow,.note', s).forEach(function (u) { u.classList.remove('hide'); });
      }
    });
    $('#hits').textContent = n + ' ' + CFG.ui.hits;
    if (none) none.classList.toggle('hide', n > 0);
  }
  $('#q').addEventListener('input', refSearch);

  /* ---------------- keyboard ---------------- */
  document.addEventListener('keydown', function (e) {
    var typing = /^(INPUT|TEXTAREA)$/.test(document.activeElement.tagName);
    if (e.key === 'Escape') {
      if (typing) { document.activeElement.value = ''; refSearch(); document.activeElement.blur(); }
      else DGS.forEach(closeCard);
      return;
    }
    if (typing) return;
    var dg = visibleDg();
    if (e.key === '/') {
      var target = dg ? $('.dgsearch[data-dg="' + dg + '"]') : $('#q');
      if (target) { e.preventDefault(); target.focus(); target.select(); }
    }
    if (dg && (e.key === 'n' || e.key === 'N')) { e.preventDefault(); walk(dg, +1); }
    if (dg && (e.key === 'p' || e.key === 'P')) { e.preventDefault(); walk(dg, -1); }
  });

  /* ---------------- boot ---------------- */
  var startTab = TABS[0], startComp = null;
  try {
    startTab = localStorage.getItem('explain_tab') || TABS[0];
    startComp = localStorage.getItem('explain_comp');
  } catch (e) {}
  if (startComp && COMPS.indexOf(startComp) >= 0) showComp(startComp, true);
  showTab(startTab, true);
  DGS.forEach(applyScale);
  readHash();
  window.addEventListener('resize', function () {
    var dg = visibleDg(); if (dg) fit(dg);
  });
})();
