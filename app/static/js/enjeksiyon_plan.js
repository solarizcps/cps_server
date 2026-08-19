(function () {
  'use strict';

  var API_KAP = '/planlama/uretim-plan/api/enj-kapasite';
  var API_CAL = '/planlama/enjeksiyon-plan/api/calendar';

  var state = {
    kod: 'M1',
    period: 'bugun',
    anchor: '',
    payload: null,
    calPayload: null,
    loading: false,
    selectedPlan: null,
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

  function qsParams() {
    var p = new URLSearchParams(window.location.search);
    return {
      tarih: p.get('tarih') || '',
      vardiya: p.get('vardiya') || '',
      anchor: p.get('anchor') || '',
    };
  }

  function todayIso() {
    var d = new Date();
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  }

  function machineByKod(kod) {
    var list = (state.payload && state.payload.machines) || [];
    for (var i = 0; i < list.length; i++) {
      if (list[i].makine_kod === kod || list[i].code === kod) return list[i];
    }
    return null;
  }

  function fmtDtShort(s) {
    if (!s) return '—';
    return String(s).substring(0, 16);
  }

  function planPayload(block) {
    return {
      plan_id: block.plan_id,
      model: block.model,
      renk: block.renk,
      siparis_no: block.siparis_no,
      makine_kod: block.makine_kod,
      kalip: block.kalip,
      kalip_adedi: block.kalip_adedi,
      slot: block.slot,
      istasyonlar: block.istasyonlar,
      plan_baslangic: block.plan_baslangic,
      plan_bitis: block.plan_bitis,
      guncel_tahmini_bitis: block.guncel_tahmini_bitis,
      sapma_durum: block.sapma_durum,
      sapma_gosterim: block.sapma_gosterim,
      tur_basi_cift: block.tur_basi_cift,
      planlanan_cift: block.planlanan_cift,
      calisma_modu: block.calisma_modu,
      hafta_sonu_calisma: block.hafta_sonu_calisma,
      confidence: block.confidence,
    };
  }

  function calismaModuLabel(v) {
    return { GUNDUZ: 'Gündüz', GECE: 'Gece', GUNDUZ_GECE: 'Gündüz + Gece' }[v] || v || '—';
  }

  function haftaSonuLabel(v) {
    return v === 'EVET' ? 'Çalışma Var' : 'Çalışma Yok';
  }

  /* ── BUGÜN ── */

  function cellClass(side, slot) {
    var durum = (side.durum || '').toUpperCase();
    if (durum === 'SETUP') return 'ep-cell-setup ep-cell-' + slot.toLowerCase();
    if (durum === 'ARIZA') return 'ep-cell-ariza ep-cell-' + slot.toLowerCase();
    if (parseInt(side.aktif, 10) === 1) return 'ep-cell-dolu ep-cell-' + slot.toLowerCase();
    return 'ep-cell-bos ep-cell-' + slot.toLowerCase();
  }

  function cellLabel(side) {
    if (side.slot_label) return side.slot_label;
    var durum = (side.durum || '').toUpperCase();
    if (durum === 'SETUP') return 'SETUP';
    if (durum === 'ARIZA') return 'ARIZA';
    if (durum === 'KAPALI') return 'KAPALI';
    return parseInt(side.aktif, 10) === 1 ? 'DOLU' : 'BOŞ';
  }

  function renderCell(side, slot) {
    var label = cellLabel(side);
    var cls = cellClass(side, slot);
    var html = '<div class="ep-cell ' + cls + '">';
    html += '<span class="ep-cell-tag ep-cell-tag-' + slot.toLowerCase() + '">' + esc(slot) + '</span>';
    html += '<span class="ep-cell-body">';
    if (parseInt(side.aktif, 10) === 1 && side.kalip_kod) {
      html += '<span class="ep-cell-kalip">' + esc(side.kalip_kod) + '</span>';
      if (side.renk) html += ' <span class="ep-cell-renk">' + esc(side.renk) + '</span>';
    } else if (label === 'BOŞ') {
      html += '<span class="ep-cell-hint">BOŞ / PLANLANABİLİR</span>';
    } else {
      html += '<span class="ep-cell-renk">' + esc(label) + '</span>';
    }
    html += '</span></div>';
    return html;
  }

  function renderSummary(m) {
    var ist = m.istasyon_sayisi || m.stations || 0;
    var yuva = m.toplam_yuva || (ist * 2);
    var a = m.A || {};
    var b = m.B || {};
    var html = '<div class="ep-sum-compact">';
    html += '<div class="ep-sum-line ep-sum-headline">' + esc(m.makine_kod) + ' — ' + ist + ' İSTASYON / ' + yuva + ' YUVA';
    if (m.snapshot_tarih) {
      html += ' <span class="ep-sum-badge">' + esc(m.snapshot_tarih) + ' · ' + esc(m.snapshot_vardiya || '') + '</span>';
    }
    html += '</div>';
    html += '<div class="ep-sum-line ep-sum-side-a"><span class="ep-sum-label">A TARAFI</span> ';
    html += '<span class="ep-sum-count">' + (a.dolu || 0) + '/' + ist + ' DOLU · ' + (a.bos || 0) + ' BOŞ</span></div>';
    html += '<div class="ep-sum-line ep-sum-side-b"><span class="ep-sum-label">B TARAFI</span> ';
    html += '<span class="ep-sum-count">' + (b.dolu || 0) + '/' + ist + ' DOLU · ' + (b.bos || 0) + ' BOŞ</span></div>';
    html += '</div>';
    $('epSummary').innerHTML = html;
  }

  function renderGrid(m) {
    var body = $('epGridBody');
    var grid = m.grid || [];
    var rows = '';
    for (var i = 0; i < grid.length; i++) {
      var g = grid[i];
      rows += '<tr class="ep-grid-row"><td class="ep-col-ist-cell">İST' + esc(g.istasyon_no) + '</td>';
      rows += '<td class="ep-td-a">' + renderCell(g.A || {}, 'A') + '</td>';
      rows += '<td class="ep-td-b">' + renderCell(g.B || {}, 'B') + '</td></tr>';
    }
    body.innerHTML = rows || '<tr><td colspan="3">Grid verisi yok</td></tr>';
  }

  function renderRefs(m) {
    var refs = m.references || [];
    var body = $('epRefsBody');
    if (!refs.length) {
      body.innerHTML = '<div class="ep-ref-item">Bu makine için 90g referans kaydı yok.</div>';
      return;
    }
    var html = '';
    for (var i = 0; i < refs.length; i++) {
      var r = refs[i];
      html += '<div class="ep-ref-item"><div class="ep-ref-title">' + esc(m.makine_kod) + ' / ' + esc(r.slot) +
        ' · ' + esc(r.vardiya).toUpperCase() + ' · aktif göz: ' + esc(r.aktif_goz_sayisi) +
        '<span class="ep-ref-tag">' + esc(r.etiket || 'Gecmis Referans') + '</span></div>';
      html += 'n: ' + esc(r.sample_count) + ' · median: ' + esc(r.median_tur_vardiya) + '</div>';
    }
    body.innerHTML = html;
  }

  function renderBugun() {
    var m = machineByKod(state.kod);
    if (!m) {
      $('epError').style.display = 'block';
      $('epError').textContent = state.kod + ' makinesi bulunamadı.';
      return;
    }
    $('epError').style.display = 'none';
    renderSummary(m);
    renderGrid(m);
    renderRefs(m);
    $('epPlansBody').className = 'ep-plan-empty';
    $('epPlansBody').textContent = 'Henüz yayınlanmış enjeksiyon planı yok.';
  }

  /* ── TAKVİM ── */

  function fmtDtCompact(s) {
    if (!s) return '—';
    var p = String(s).replace('T', ' ').slice(0, 16);
    var d = p.split(' ');
    if (d.length !== 2) return p;
    var dp = d[0].split('-');
    if (dp.length !== 3) return p;
    return dp[2] + '.' + dp[1] + ' ' + d[1].slice(0, 5);
  }

  function clearPlanPanel() {
    state.selectedPlan = null;
    var val = $('epCalSelValue');
    var exp = $('epCalDetailExpand');
    if (val) val.textContent = '—';
    if (exp) {
      exp.style.display = 'none';
      exp.innerHTML = '';
    }
    document.querySelectorAll('.ep-cal-block-selected').forEach(function (n) {
      n.classList.remove('ep-cal-block-selected');
    });
  }

  function renderCalSidebar() {
    var el = $('epCalSidebarSummary');
    if (!el) return;
    var m = machineByKod(state.kod);
    if (!m) {
      el.innerHTML = '<span class="ep-cal-mach-title">' + esc(state.kod) + '</span>';
      return;
    }
    var ist = m.istasyon_sayisi || 8;
    var a = m.A || {};
    var b = m.B || {};
    el.innerHTML =
      '<span class="ep-cal-mach-title">' + esc(m.makine_kod) + ' — ' + ist + ' İSTASYON / ' + (ist * 2) + ' YUVA</span>' +
      '<span class="ep-cal-mach-ab">' +
      '<span class="ep-sum-side-a">A: ' + (a.dolu || 0) + '/' + ist + ' DOLU · ' + (a.bos || 0) + ' BOŞ</span>' +
      '<span class="ep-sum-side-b">B: ' + (b.dolu || 0) + '/' + ist + ' DOLU · ' + (b.bos || 0) + ' BOŞ</span>' +
      '</span>';
  }

  function selectPlanPanel(p) {
    if (!p) {
      clearPlanPanel();
      return;
    }
    state.selectedPlan = p;
    var val = $('epCalSelValue');
    var exp = $('epCalDetailExpand');
    var istStr = (p.istasyonlar || []).length
      ? 'İST' + p.istasyonlar.join('–') : '—';
    var shortLabel = (p.siparis_no || '—') + ' · ' + (p.model || '—');
    if (val) val.textContent = shortLabel;
    if (exp) {
      var hs = p.hafta_sonu_calisma === 'EVET' ? 'Var' : 'Yok';
      var mod = calismaModuLabel(p.calisma_modu).replace(' + ', '+');
      exp.innerHTML =
        '<div class="ep-cal-detail-line1">' +
        esc(p.siparis_no || '—') + ' · ' + esc(p.model || '—') + ' · ' +
        esc(p.makine_kod || state.kod) + '/' + esc(p.slot || '—') + ' · ' + esc(istStr) +
        '</div>' +
        '<div class="ep-cal-detail-line2">' +
        fmtDtCompact(p.plan_baslangic) + ' → ' + fmtDtCompact(p.plan_bitis) +
        ' · ' + esc(mod) + ' · HS ' + hs +
        ' · Conf ' + esc(p.confidence || '—') +
        '</div>';
      exp.style.display = 'block';
    }
    document.querySelectorAll('.ep-cal-block-selected').forEach(function (n) {
      n.classList.remove('ep-cal-block-selected');
    });
    document.querySelectorAll('.ep-cal-block').forEach(function (n) {
      try {
        var d = JSON.parse(n.getAttribute('data-plan'));
        if (d.plan_id === p.plan_id && d.slot === p.slot) n.classList.add('ep-cal-block-selected');
      } catch (e) { /* ignore */ }
    });
  }

  function showTooltip(e, p) {
    var tip = $('epCalTooltip');
    if (!tip || !p) return;
    var html = '<strong>' + esc(p.model) + '</strong><br>' +
      'Orijinal: ' + fmtDtShort(p.plan_bitis) + '<br>';
    if (p.guncel_tahmini_bitis) html += 'Güncel: ' + fmtDtShort(p.guncel_tahmini_bitis) + '<br>';
    if (p.sapma_gosterim) html += esc(p.sapma_gosterim);
    tip.innerHTML = html;
    tip.style.display = 'block';
    tip.style.left = Math.min(e.clientX + 12, window.innerWidth - 240) + 'px';
    tip.style.top = (e.clientY + 12) + 'px';
  }

  function hideTooltip() {
    var tip = $('epCalTooltip');
    if (tip) tip.style.display = 'none';
  }

  function renderPlanBlock(block, view) {
    var b = block.block || {};
    var slot = (block.slot || 'A').toUpperCase();
    var cls = 'ep-cal-block ep-cal-block-' + slot.toLowerCase();
    if (block.continuation) cls += ' ep-cal-block-cont';
    if (block.sapma_durum === 'ERKEN') cls += ' ep-cal-block-erken';
    if (block.sapma_durum === 'GECIKIYOR') cls += ' ep-cal-block-gec';

    var style = 'left:' + (b.left_pct || 0) + '%;width:' + (b.width_pct || 5) + '%;';
    var payload = planPayload(block);
    var html = '<div class="' + cls + '" style="' + style + '" data-plan=\'' + esc(JSON.stringify(payload)) + '\'>';

    if (block.show_label !== false && !block.continuation) {
      if (view === '3_ay' || view === 'bu_ay') {
        html += '<span class="ep-cal-block-model">' + esc(block.model || '—') + '</span>';
        html += '<span class="ep-cal-block-kalip">' + esc(block.kalip_adedi || '') + ' kalıp</span>';
        html += '<span class="ep-cal-block-bitis">' + fmtDtShort(block.plan_baslangic) + ' – ' + fmtDtShort(block.plan_bitis) + '</span>';
      } else {
        html += '<span class="ep-cal-block-model">' + esc(block.model || '—') + '</span>';
        html += '<span class="ep-cal-block-kalip">' + esc(block.kalip_adedi || '') + ' Kalıp</span>';
        if (block.siparis_no) html += '<span class="ep-cal-block-sip">' + esc(block.siparis_no) + '</span>';
        html += '<span class="ep-cal-block-bitis">' + fmtDtShort(block.plan_baslangic) + ' – ' + fmtDtShort(block.plan_bitis) + '</span>';
        if (block.sapma_gosterim) {
          html += '<span class="ep-cal-block-sapma">' + esc(block.sapma_gosterim) + '</span>';
        }
      }
    }

    if (block.live_marker_pct != null && block.guncel_tahmini_bitis) {
      var mk = block.live_marker_pct - (b.left_pct || 0);
      html += '<div class="ep-cal-live-marker ep-cal-live-marker-' + slot.toLowerCase() +
        '" style="left:' + mk + '%" title="Güncel tahmin"></div>';
    }

    html += '</div>';
    return html;
  }

  function renderRowLabel(row, prevRow) {
    if (row.side_only) {
      return '<span class="ep-cal-side-label ep-cal-side-label-' + (row.slot || 'A').toLowerCase() + '">' +
        esc(row.label) + '</span>';
    }
    var showIst = !prevRow || prevRow.istasyon_no !== row.istasyon_no;
    var slot = (row.slot || 'A').toUpperCase();
    var html = '';
    if (showIst) {
      html += '<span class="ep-cal-ist">İST' + esc(row.istasyon_no) + '</span>';
    } else {
      html += '<span class="ep-cal-ist ep-cal-ist-empty"></span>';
    }
    html += '<span class="ep-cal-slot ep-cal-slot-' + slot.toLowerCase() + '">' + esc(slot) + '</span>';
    return html;
  }

  function renderCalendarHeader(d) {
    var cols = d.columns || [];
    var view = d.view;
    var html = '<div class="ep-cal-header">';
    html += '<div class="ep-cal-row-label ep-cal-corner">İSTASYON · TARAF</div>';
    html += '<div class="ep-cal-timeline-head">';
    for (var c = 0; c < cols.length; c++) {
      html += '<div class="ep-cal-col-head"><span class="ep-cal-col-main">' + esc(cols[c].label) + '</span>';
      if (cols[c].alt) html += '<span class="ep-cal-col-sub">' + esc(cols[c].alt) + '</span>';
      html += '</div>';
    }
    html += '</div></div>';

    if (view === 'bu_hafta') {
      html += '<div class="ep-cal-hour-header">';
      html += '<div class="ep-cal-row-label ep-cal-corner"></div>';
      html += '<div class="ep-cal-hour-row">';
      for (var hc = 0; hc < cols.length; hc++) {
        html += '<div class="ep-cal-hour-col">';
        ['07', '12', '17', '00'].forEach(function (h) {
          html += '<span class="ep-cal-hour-cell">' + h + '</span>';
        });
        html += '</div>';
      }
      html += '</div></div>';
    }
    return html;
  }

  function renderCalendar() {
    var d = state.calPayload;
    if (!d || !d.ok) {
      $('epError').style.display = 'block';
      $('epError').textContent = (d && d.hata) || 'Takvim yüklenemedi';
      return;
    }
    $('epError').style.display = 'none';
    $('epCalLabel').textContent = (d.period && d.period.label) || '—';
    state.anchor = (d.period && d.period.anchor) || state.anchor;
    renderCalSidebar();
    if (!state.selectedPlan) clearPlanPanel();

    var emptyEl = $('epCalEmpty');
    var gridEl = $('epCalGrid');
    if (d.empty) {
      emptyEl.style.display = 'block';
      emptyEl.textContent = d.empty_message || 'Bu dönemde yayınlanmış enjeksiyon planı yok.';
      gridEl.innerHTML = renderCalendarSkeleton(d, true);
      return;
    }
    emptyEl.style.display = 'none';
    gridEl.innerHTML = renderCalendarSkeleton(d, false);
    bindPlanClicks();
  }

  function renderCalendarSkeleton(d, emptyOnly) {
    var view = d.view;
    var rows = d.rows || [];
    var html = renderCalendarHeader(d);

    for (var r = 0; r < rows.length; r++) {
      var row = rows[r];
      var prevRow = r > 0 ? rows[r - 1] : null;
      var blocks = emptyOnly ? [] : ((d.row_blocks && d.row_blocks[row.key]) || []);
      var innerCls = 'ep-cal-timeline-inner';
      if (!blocks.length && !emptyOnly) innerCls += ' ep-cal-empty-row';
      var rowCls = 'ep-cal-row ep-cal-row-' + (row.slot || 'A').toLowerCase();

      html += '<div class="' + rowCls + '">';
      html += '<div class="ep-cal-row-label">' + renderRowLabel(row, prevRow) + '</div>';
      html += '<div class="ep-cal-timeline">';
      html += '<div class="' + innerCls + '">';

      var zones = d.disabled_zones || [];
      for (var z = 0; z < zones.length; z++) {
        var zn = zones[z];
        html += '<div class="ep-cal-disabled" style="left:' + zn.left_pct + '%;width:' + zn.width_pct + '%">';
        if ((zn.width_pct || 0) > 6) {
          html += '<span class="ep-cal-disabled-label">✕<br>ÇALIŞMA YOK<br>(Hafta Sonu)</span>';
        }
        html += '</div>';
      }

      for (var b = 0; b < blocks.length; b++) {
        html += renderPlanBlock(blocks[b], view);
      }

      if (!blocks.length && !emptyOnly && view === 'bu_hafta') {
        html += '<span class="ep-cal-row-hint">BOŞ / PLANLANABİLİR</span>';
      }

      html += '</div></div></div>';
    }
    return html;
  }

  function bindPlanClicks() {
    var blocks = document.querySelectorAll('.ep-cal-block');
    for (var i = 0; i < blocks.length; i++) {
      (function (el) {
        el.addEventListener('click', function (e) {
          e.stopPropagation();
          try {
            selectPlanPanel(JSON.parse(el.getAttribute('data-plan')));
          } catch (err) { /* ignore */ }
        });
        el.addEventListener('mouseenter', function (e) {
          try { showTooltip(e, JSON.parse(el.getAttribute('data-plan'))); } catch (err) { /* ignore */ }
        });
        el.addEventListener('mousemove', function (e) {
          try { showTooltip(e, JSON.parse(el.getAttribute('data-plan'))); } catch (err) { /* ignore */ }
        });
        el.addEventListener('mouseleave', hideTooltip);
      })(blocks[i]);
    }
  }

  function showView() {
    var isBugun = state.period === 'bugun';
    $('epBugunView').style.display = isBugun ? 'block' : 'none';
    $('epCalendarView').style.display = isBugun ? 'none' : 'block';
    $('epBuguneDon').style.display = isBugun ? 'none' : 'inline-block';
  }

  function loadKapasite() {
    state.loading = true;
    $('epLoading').style.display = 'block';
    $('epBugunView').style.display = 'none';
    $('epCalendarView').style.display = 'none';

    var url = API_KAP + '?days=90';
    var qp = qsParams();
    if (qp.tarih) url += '&tarih=' + encodeURIComponent(qp.tarih);
    if (qp.vardiya) url += '&vardiya=' + encodeURIComponent(qp.vardiya);

    fetch(url, { credentials: 'include' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        state.payload = d;
        if (state.period === 'bugun') {
          state.loading = false;
          $('epLoading').style.display = 'none';
          showView();
          if (d.ok) renderBugun();
          else {
            $('epError').style.display = 'block';
            $('epError').textContent = d.mesaj || 'Veri yüklenemedi';
          }
        } else {
          loadCalendar();
        }
      })
      .catch(function (e) {
        state.loading = false;
        $('epError').style.display = 'block';
        $('epError').textContent = String(e);
        $('epLoading').style.display = 'none';
      });
  }

  function loadCalendar() {
    if (!state.anchor) state.anchor = todayIso();
    var url = API_CAL + '?makine_kod=' + encodeURIComponent(state.kod) +
      '&view=' + encodeURIComponent(state.period) +
      '&anchor=' + encodeURIComponent(state.anchor) +
      '&live=1';

    fetch(url, { credentials: 'include' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        state.loading = false;
        state.calPayload = d;
        $('epLoading').style.display = 'none';
        showView();
        renderCalendar();
      })
      .catch(function (e) {
        state.loading = false;
        $('epError').style.display = 'block';
        $('epError').textContent = String(e);
        $('epLoading').style.display = 'none';
      });
  }

  function loadData() {
    if (state.loading) return;
    $('epError').style.display = 'none';
    var qp = qsParams();
    if (qp.anchor && state.period !== 'bugun') state.anchor = qp.anchor;
    loadKapasite();
  }

  function bindMachines() {
    var btns = document.querySelectorAll('#epMachines .ep-mach');
    for (var i = 0; i < btns.length; i++) {
      btns[i].addEventListener('click', function () {
        var kod = this.getAttribute('data-kod');
        if (!kod || kod === state.kod) return;
        state.kod = kod;
        clearPlanPanel();
        document.querySelectorAll('#epMachines .ep-mach').forEach(function (b) { b.classList.remove('active'); });
        this.classList.add('active');
        loadData();
      });
    }
  }

  function bindPeriods() {
    var btns = document.querySelectorAll('#epPeriods .ep-period');
    for (var i = 0; i < btns.length; i++) {
      btns[i].addEventListener('click', function () {
        var p = this.getAttribute('data-period');
        if (!p || p === state.period) return;
        state.period = p;
        clearPlanPanel();
        if (p !== 'bugun') {
          var qp = qsParams();
          state.anchor = qp.anchor || todayIso();
        }
        document.querySelectorAll('#epPeriods .ep-period').forEach(function (b) { b.classList.remove('active'); });
        this.classList.add('active');
        loadData();
      });
    }
  }

  function bindNav() {
    $('epCalPrev').addEventListener('click', function () {
      var p = state.calPayload && state.calPayload.period;
      if (p && p.nav_prev) { state.anchor = p.nav_prev; loadCalendar(); }
    });
    $('epCalNext').addEventListener('click', function () {
      var p = state.calPayload && state.calPayload.period;
      if (p && p.nav_next) { state.anchor = p.nav_next; loadCalendar(); }
    });
    $('epBuguneDon').addEventListener('click', function () {
      state.period = 'bugun';
      state.anchor = todayIso();
      document.querySelectorAll('#epPeriods .ep-period').forEach(function (b) {
        b.classList.toggle('active', b.getAttribute('data-period') === 'bugun');
      });
      loadData();
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    bindMachines();
    bindPeriods();
    bindNav();
    $('epYenileBtn').addEventListener('click', loadData);
    loadData();
  });
})();
