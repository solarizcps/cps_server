(function () {
  'use strict';

  var API = '/planlama/genel-plan/api/timeline';

  var state = {
    makineId: '',   // '' = tüm makineler
    period: 'bu_hafta',
    anchor: '',
    data: null,
    loading: false,
  };

  function $(id) { return document.getElementById(id); }

  function esc(s) {
    if (s == null || s === '') return '';
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function fmtDt(s) {
    if (!s) return '—';
    return String(s).replace('T', ' ').substring(0, 16);
  }

  function calismaModu(v) {
    return {GUNDUZ: 'Gündüz', GECE: 'Gece', GUNDUZ_GECE: 'Gündüz+Gece'}[v] || v || '—';
  }

  // -----------------------------------------------------------------------
  // Filter button state
  // -----------------------------------------------------------------------
  function setActiveMak(val) {
    var btns = document.querySelectorAll('.gp-mach-btn');
    for (var i = 0; i < btns.length; i++) {
      btns[i].classList.toggle('active', btns[i].dataset.mak === val);
    }
    state.makineId = val;
  }

  function setActivePeriod(val) {
    var btns = document.querySelectorAll('.gp-period-btn');
    for (var i = 0; i < btns.length; i++) {
      btns[i].classList.toggle('active', btns[i].dataset.period === val);
    }
    state.period = val;
  }

  // -----------------------------------------------------------------------
  // Fetch + render
  // -----------------------------------------------------------------------
  function load() {
    if (state.loading) return;
    state.loading = true;
    showLoading(true);
    hideError();

    var url = API + '?view=' + encodeURIComponent(state.period);
    if (state.makineId) url += '&makine_id=' + encodeURIComponent(state.makineId);
    if (state.anchor) url += '&anchor=' + encodeURIComponent(state.anchor);

    fetch(url, { credentials: 'include' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        state.loading = false;
        showLoading(false);
        if (!d.ok) {
          showError(d.hata || 'Veri alınamadı.');
          return;
        }
        state.data = d;
        render(d);
      })
      .catch(function (err) {
        state.loading = false;
        showLoading(false);
        showError('Bağlantı hatası: ' + (err.message || err));
      });
  }

  // -----------------------------------------------------------------------
  // Render
  // -----------------------------------------------------------------------
  function render(d) {
    // Period nav
    if ($('gpNavLabel')) $('gpNavLabel').textContent = (d.period && d.period.label) || '—';

    // Column headers
    renderHeader(d);

    // Resource rows
    renderRows(d);

    var hasPlan = d.plan_count > 0;
    var tl = $('gpTimeline');
    var em = $('gpEmpty');
    if (tl) tl.style.display = hasPlan ? '' : 'none';
    if (em) em.style.display = hasPlan ? 'none' : '';
  }

  function renderHeader(d) {
    var hdr = $('gpTimeHeader');
    if (!hdr) return;
    var cols = d.columns || [];
    var html = '';
    for (var i = 0; i < cols.length; i++) {
      var c = cols[i];
      var isWeekend = c.is_weekend ? ' gp-col-weekend' : '';
      html += '<div class="gp-col-hdr' + isWeekend + '" style="left:' + (c.left_pct || 0) + '%">'
        + '<span class="gp-col-day">' + esc(c.label || c.key) + '</span>'
        + (c.alt ? '<span class="gp-col-alt">' + esc(c.alt) + '</span>' : '')
        + '</div>';
    }
    hdr.innerHTML = html;
  }

  function renderRows(d) {
    var body = $('gpTimelineBody');
    if (!body) return;
    var rows = d.resource_rows || [];
    var plans = d.plans || [];
    var period = d.period || {};
    var winBas = period.bas ? new Date(period.bas.replace(' ', 'T')) : null;
    var winBit = period.bit ? new Date(period.bit.replace(' ', 'T')) : null;

    // Build plan index by resource_key
    var plansByKey = {};
    for (var i = 0; i < plans.length; i++) {
      var p = plans[i];
      var rk = p.resource_key;
      if (!plansByKey[rk]) plansByKey[rk] = [];
      plansByKey[rk].push(p);
    }

    var html = '';
    for (var ri = 0; ri < rows.length; ri++) {
      var row = rows[ri];
      var rPlans = plansByKey[row.resource_key] || [];
      html += '<div class="gp-row">';
      html += '<div class="gp-res-col"><span class="gp-res-label">'
        + esc(row.makine_kod) + ' / ' + esc(row.slot)
        + '</span><span class="gp-res-sub">' + esc(row.istasyon_sayisi) + ' ist.</span></div>';
      html += '<div class="gp-time-col gp-row-blocks">';

      // Weekend shading (only for bu_hafta/bu_ay)
      if (d.columns && d.view !== '3_ay') {
        for (var ci = 0; ci < d.columns.length; ci++) {
          var col = d.columns[ci];
          if (col.is_weekend) {
            html += '<div class="gp-weekend-shade" style="left:' + (col.left_pct || 0) + '%;width:' + (100 / d.columns.length) + '%"></div>';
          }
        }
      }

      // Plan blocks
      for (var pi = 0; pi < rPlans.length; pi++) {
        html += renderBlock(rPlans[pi]);
      }

      html += '</div></div>';
    }
    body.innerHTML = html;

    // Attach tooltip listeners
    var blocks = body.querySelectorAll('.gp-block');
    for (var bi = 0; bi < blocks.length; bi++) {
      attachBlockListeners(blocks[bi]);
    }
  }

  function renderBlock(p) {
    var blk = p.block || {};
    var left = blk.left_pct || 0;
    var width = blk.width_pct || 1;
    var dur = p.dur_hours ? Math.round(p.dur_hours) + 's' : '';
    var istStr = (p.istasyonlar || []).length
      ? 'İST' + p.istasyonlar[0] + (p.istasyonlar.length > 1 ? '–İST' + p.istasyonlar[p.istasyonlar.length - 1] : '')
      : '';

    var slotCls = 'gp-block-' + (p.slot || 'A').toLowerCase();
    var tipData = JSON.stringify({
      plan_id: p.plan_id,
      sip_no: p.sip_no,
      model: p.model,
      renk: p.renk,
      makine: p.makine_kod + ' / ' + p.slot,
      kalip: p.kalip_kod,
      istasyonlar: (p.istasyonlar || []).join(', '),
      baslangic: fmtDt(p.baslangic),
      bitis: fmtDt(p.bitis),
      cift: p.planlanacak_cift,
      calisma_modu: calismaModu(p.calisma_modu),
    });

    return '<div class="gp-block ' + slotCls + '"'
      + ' style="left:' + left + '%;width:' + width + '%"'
      + ' tabindex="0" role="button" aria-label="Plan ' + esc(p.sip_no) + '"'
      + ' data-tip=' + "'" + esc(tipData) + "'"
      + '>'
      + '<div class="gp-block-inner">'
      + '<span class="gp-block-sip">Sip: ' + esc(p.sip_no) + '</span>'
      + '<span class="gp-block-model">' + esc((p.model || '').substring(0, 14)) + '</span>'
      + '<span class="gp-block-ist">' + esc(istStr) + '</span>'
      + (p.kalip_kod ? '<span class="gp-block-kalip">' + esc(p.kalip_kod) + '</span>' : '')
      + '</div>'
      + '</div>';
  }

  // -----------------------------------------------------------------------
  // Tooltip
  // -----------------------------------------------------------------------
  var tooltipTarget = null;

  function attachBlockListeners(el) {
    el.addEventListener('mouseenter', function (e) { showTooltip(el, e); });
    el.addEventListener('focus', function (e) { showTooltip(el, e); });
    el.addEventListener('mouseleave', function () { hideTooltip(); });
    el.addEventListener('blur', function () { hideTooltip(); });
    el.addEventListener('click', function (e) { showTooltip(el, e); });
  }

  function showTooltip(el, e) {
    var tip = $('gpTooltip');
    if (!tip) return;
    var raw = el.getAttribute('data-tip') || '';
    var d = {};
    try { d = JSON.parse(raw); } catch (ex) {}

    tip.innerHTML = '<div class="gp-tip-row"><b>Plan #' + esc(d.plan_id) + '</b></div>'
      + '<div class="gp-tip-row">Sipariş: <b>' + esc(d.sip_no) + '</b></div>'
      + '<div class="gp-tip-row">Model: ' + esc(d.model) + '</div>'
      + '<div class="gp-tip-row">Renk: ' + esc(d.renk) + '</div>'
      + '<div class="gp-tip-row">Makine: <b>' + esc(d.makine) + '</b></div>'
      + '<div class="gp-tip-row">Kalıp: ' + esc(d.kalip) + '</div>'
      + '<div class="gp-tip-row">İstasyonlar: ' + esc(d.istasyonlar) + '</div>'
      + '<div class="gp-tip-row">Başlangıç: <b>' + esc(d.baslangic) + '</b></div>'
      + '<div class="gp-tip-row">Bitiş: <b>' + esc(d.bitis) + '</b></div>'
      + '<div class="gp-tip-row">Planlanan: ' + esc(d.cift) + ' çift</div>'
      + '<div class="gp-tip-row">Çalışma: ' + esc(d.calisma_modu) + '</div>';

    tip.style.display = '';
    positionTooltip(e);
    tooltipTarget = el;
  }

  function positionTooltip(e) {
    var tip = $('gpTooltip');
    if (!tip || !e) return;
    var x = (e.clientX || 0) + 12;
    var y = (e.clientY || 0) + 12;
    var tw = tip.offsetWidth || 220;
    var th = tip.offsetHeight || 180;
    if (x + tw > window.innerWidth - 8) x = (e.clientX || 0) - tw - 8;
    if (y + th > window.innerHeight - 8) y = (e.clientY || 0) - th - 8;
    tip.style.left = x + 'px';
    tip.style.top = y + 'px';
  }

  function hideTooltip() {
    var tip = $('gpTooltip');
    if (tip) tip.style.display = 'none';
    tooltipTarget = null;
  }

  document.addEventListener('mousemove', function (e) {
    if (tooltipTarget) positionTooltip(e);
  });

  // -----------------------------------------------------------------------
  // UI helpers
  // -----------------------------------------------------------------------
  function showLoading(v) {
    var el = $('gpLoading');
    if (el) el.style.display = v ? '' : 'none';
    var tl = $('gpTimeline');
    var em = $('gpEmpty');
    if (v) {
      if (tl) tl.style.display = 'none';
      if (em) em.style.display = 'none';
    }
  }

  function showError(msg) {
    var el = $('gpError');
    if (el) { el.textContent = msg; el.style.display = ''; }
  }

  function hideError() {
    var el = $('gpError');
    if (el) el.style.display = 'none';
  }

  // -----------------------------------------------------------------------
  // Init
  // -----------------------------------------------------------------------
  function init() {
    // Defaults
    setActiveMak('');
    setActivePeriod('bu_hafta');

    // Makine buttons
    var makBtns = document.querySelectorAll('.gp-mach-btn');
    for (var i = 0; i < makBtns.length; i++) {
      (function (btn) {
        btn.addEventListener('click', function () {
          setActiveMak(btn.dataset.mak);
          state.anchor = '';
          load();
        });
      })(makBtns[i]);
    }

    // Period buttons
    var pBtns = document.querySelectorAll('.gp-period-btn');
    for (var i = 0; i < pBtns.length; i++) {
      (function (btn) {
        btn.addEventListener('click', function () {
          setActivePeriod(btn.dataset.period);
          state.anchor = '';
          load();
        });
      })(pBtns[i]);
    }

    // Nav prev/next
    var navPrev = $('gpNavPrev');
    var navNext = $('gpNavNext');
    if (navPrev) navPrev.addEventListener('click', function () {
      var p = state.data && state.data.period;
      if (p && p.nav_prev) { state.anchor = p.nav_prev; load(); }
    });
    if (navNext) navNext.addEventListener('click', function () {
      var p = state.data && state.data.period;
      if (p && p.nav_next) { state.anchor = p.nav_next; load(); }
    });

    // Refresh
    var yenile = $('gpYenileBtn');
    if (yenile) yenile.addEventListener('click', function () { load(); });

    load();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
