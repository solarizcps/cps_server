/* ATP Route Decision Explainer Modal — v11 (profile recommendation + legs UI fix)
   Google apply delegates to POST /api/route/apply with apply_source=google. */
(function (global) {
  'use strict';

  /* ── Map state ── */
  var _map = null;
  var _routeLayer = null;
  var _routeHalo = null;
  var _markers = [];

  /* ── Unified selection: profile + order ── */
  var _selectedOrder = 'current';   /* 'current' | 'suggested' */
  var _selectedProfile = 'fastest'; /* 'fastest' | 'toll_free' — Google mode only */
  var _route = null;
  var _planMapPayload = null;

  /* ── Google binding state ── */
  var _googleMode = false;
  var _googleDto = null;
  var _googleApplyInFlight = false;

  /* ── Apply hooks (injected from planlama_arac_takip.js) ── */
  var _applyHooks = {
    getVehicleId: null,
    getPlanDate: null,
    toast: null,
    reloadAfterApply: null,
  };

  /* ── Helpers ── */
  function esc(s) {
    if (s == null) return '';
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }
  function el(id) { return document.getElementById(id); }

  var PRI_CFG = {
    'ACIL':   { cls: 'pri-acil',   label: 'Acil' },
    'YUKSEK': { cls: 'pri-yuksek', label: 'Yüksek' },
    'NORMAL': { cls: 'pri-normal', label: 'Normal' },
    'DUSUK':  { cls: 'pri-dusuk',  label: 'Düşük' },
  };
  function priBadge(pri) {
    var cfg = PRI_CFG[pri] || PRI_CFG['NORMAL'];
    return '<span class="atp-exp-pri ' + cfg.cls + '">' + cfg.label + '</span>';
  }

  /* ── Map icons ── */
  function makeBaseIcon(label, fill) {
    var color = fill || '#1d4ed8';
    var txt = esc(label || 'B');
    var svg = '<svg xmlns="http://www.w3.org/2000/svg" width="36" height="46" viewBox="0 0 36 46">' +
      '<filter id="expSh"><feDropShadow dx="0" dy="1" stdDeviation="2" flood-color="rgba(0,0,0,.4)"/></filter>' +
      '<g filter="url(#expSh)">' +
      '<path d="M18 0C10 0 4 6 4 14c0 10 14 32 14 32s14-22 14-32C32 6 26 0 18 0z" fill="' + color + '" stroke="#fff" stroke-width="2.5"/>' +
      '<text x="18" y="19" text-anchor="middle" fill="#fff" font-size="12" font-weight="800" dominant-baseline="middle">' + txt + '</text>' +
      '</g></svg>';
    return L.divIcon({ className: 'atp-plan-pin', html: svg, iconSize: [36, 46], iconAnchor: [18, 46], popupAnchor: [0, -44] });
  }

  function makeStopIcon(orderNo) {
    var n = esc(orderNo != null ? orderNo : '?');
    var svg = '<svg xmlns="http://www.w3.org/2000/svg" width="34" height="44" viewBox="0 0 34 44">' +
      '<filter id="expSh2"><feDropShadow dx="0" dy="1" stdDeviation="2" flood-color="rgba(0,0,0,.35)"/></filter>' +
      '<g filter="url(#expSh2)">' +
      '<path d="M17 0C9.3 0 3 6.3 3 14c0 9.5 14 30 14 30S31 23.5 31 14C31 6.3 24.7 0 17 0z" fill="#d97706" stroke="#fff" stroke-width="2.5"/>' +
      '<text x="17" y="15" text-anchor="middle" fill="#fff" font-size="12" font-weight="800" dominant-baseline="middle">' + n + '</text>' +
      '</g></svg>';
    return L.divIcon({ className: 'atp-plan-pin', html: svg, iconSize: [34, 44], iconAnchor: [17, 44], popupAnchor: [0, -42] });
  }

  /* ── Map ── */
  function destroyMap() {
    if (_map) { _map.remove(); _map = null; }
    _routeLayer = _routeHalo = null;
    _markers = [];
    var mapEl = el('atpExplainerMap');
    if (mapEl) { if (mapEl._leaflet_id) delete mapEl._leaflet_id; mapEl.innerHTML = ''; }
  }

  function _activeProfileView(route) {
    if (!_googleMode || !route || !route.order_same || !route.profile_views) return null;
    return route.profile_views[_selectedProfile] || route.profile_views.fastest || null;
  }

  function _selectedGeometry(route) {
    if (!route) return [];
    var pv = _activeProfileView(route);
    if (pv && pv.geometry) return pv.geometry;
    var orderSame = !!route.order_same;
    if (_selectedOrder === 'suggested' && !orderSame) {
      return (route.suggested && route.suggested.geometry) || [];
    }
    return (route.current && route.current.geometry) || [];
  }

  function _selectedStopList(route) {
    if (!route) return [];
    var pv = _activeProfileView(route);
    if (pv && pv.stop_list) return pv.stop_list;
    var orderSame = !!route.order_same;
    if (_selectedOrder === 'suggested' && !orderSame) {
      return route.suggested_stop_list || [];
    }
    return route.current_stop_list || [];
  }

  function _selectedBreakdown(route) {
    if (!route) return { legs: [], formula: {} };
    var pv = _activeProfileView(route);
    if (pv && pv.breakdown) return pv.breakdown;
    var orderSame = !!route.order_same;
    if (_selectedOrder === 'suggested' && !orderSame) {
      return route.suggested_breakdown || { legs: [], formula: {} };
    }
    return route.current_breakdown || { legs: [], formula: {} };
  }

  function _selectedSummary(route) {
    if (!route) return null;
    var pv = _activeProfileView(route);
    if (pv && pv.summary) return pv.summary;
    var orderSame = !!route.order_same;
    if (_selectedOrder === 'suggested' && !orderSame) return route.suggested_summary;
    return route.current_summary;
  }

  function _routeLineColor() {
    return _selectedOrder === 'suggested' ? '#16a34a' : '#1d4ed8';
  }

  function drawMap(route, planMapPayload) {
    destroyMap();
    var mapEl = el('atpExplainerMap');
    if (!mapEl || typeof L === 'undefined') return;

    _map = L.map(mapEl, { zoomControl: true, attributionControl: false, preferCanvas: false })
      .setView([41.0, 29.0], 10);
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19 }).addTo(_map);

    var bounds = [];
    var base = planMapPayload && planMapPayload.base;
    if (base && base.has_coordinates && base.latitude != null && base.longitude != null) {
      var bLat = parseFloat(base.latitude), bLng = parseFloat(base.longitude);
      var startMk = L.marker([bLat, bLng], { icon: makeBaseIcon('B', '#1d4ed8'), zIndexOffset: 1000 });
      startMk.bindPopup('<strong>Başlangıç / Fabrika</strong><br>' + esc(base.base_name || '—'));
      startMk.addTo(_map); _markers.push(startMk); bounds.push([bLat, bLng]);
    }

    var stops = _selectedStopList(route);
    stops.forEach(function (stop) {
      if (!stop.has_coordinates || stop.latitude == null) return;
      var lat = parseFloat(stop.latitude), lng = parseFloat(stop.longitude);
      var mk = L.marker([lat, lng], { icon: makeStopIcon(stop.order_no), zIndexOffset: 800 + (stop.order_no || 0) });
      mk.bindPopup('<strong>' + esc(stop.order_no) + ' · ' + esc(stop.company_name) + '</strong><br>' + esc(stop.job_title || '—'));
      mk.addTo(_map); _markers.push(mk); bounds.push([lat, lng]);
    });

    var geom = _selectedGeometry(route);
    if (geom.length >= 2) {
      var lls = geom.map(function (p) { return [p[0], p[1]]; });
      var color = _routeLineColor();
      _routeHalo = L.polyline(lls, { color: '#fff', weight: 11, opacity: 0.55, interactive: false }).addTo(_map);
      _routeLayer = L.polyline(lls, { color: color, weight: 7, opacity: 0.96, lineJoin: 'round', lineCap: 'round' }).addTo(_map);
      lls.forEach(function (p) { bounds.push(p); });
    }

    if (bounds.length >= 2) {
      _map.fitBounds(L.latLngBounds(bounds).pad(0.12), { animate: false, maxZoom: 12 });
    } else if (bounds.length === 1) {
      _map.setView(bounds[0], 11, { animate: false });
    }
    setTimeout(function () { if (_map) _map.invalidateSize({ animate: false }); }, 150);
  }

  /* ── Order list HTML ── */
  function buildOrderListHtml(stopList, base) {
    var baseName = (base && (base.base_name || base.base_address)) || 'Fabrika';
    var html = '<div class="atp-exp-row base">' +
      '<span style="font-size:16px;line-height:1">&#x1F3ED;</span>' +
      '<span class="atp-exp-name">Başlangıç: ' + esc(baseName) + '</span></div>';
    stopList.forEach(function (s) {
      var lockBadge = s.is_locked ? '<span class="atp-exp-lock" title="Kilitli">&#x1F512;</span>' : '';
      html += '<div class="atp-exp-row">' +
        '<span class="atp-exp-num">' + esc(s.order_no != null ? s.order_no : '—') + '</span>' +
        '<span class="atp-exp-name">' + esc(s.company_name || '—') + '</span>' +
        priBadge(s.priority || 'NORMAL') + lockBadge + '</div>';
    });
    html += '<div class="atp-exp-row base">' +
      '<span style="font-size:16px;line-height:1">&#x1F3ED;</span>' +
      '<span class="atp-exp-name">Fabrikaya dönüş</span></div>';
    return html;
  }

  /* ── Card summary HTML ── */
  function buildCardSummaryHtml(summary) {
    if (!summary) return '';
    var rows = [
      ['Mesafe', summary.km != null ? summary.km + ' km' : '—'],
      ['Sürüş', summary.drive_label || '—'],
    ];
    if (summary.traffic_label) {
      rows.push(['Trafik gecikmesi', summary.traffic_label]);
    }
    rows.push(
      ['İşlem', summary.service_formula || '—'],
      ['Toplam plan', summary.total_minutes != null ? summary.total_minutes + ' dk' : '—'],
      ['Çıkış', summary.departure_time || '—'],
      ['Tahmini dönüş', summary.estimated_return_time || '—']
    );
    return rows.map(function (r) {
      return '<div class="atp-exp-sum-row"><span>' + esc(r[0]) + '</span><strong>' + esc(r[1]) + '</strong></div>';
    }).join('');
  }

  /* ── Google helpers (no new route math — display from API seconds/km) ── */
  function ceilMin(seconds) {
    var s = Number(seconds);
    if (!isFinite(s) || s <= 0) return 0;
    return Math.ceil(s / 60);
  }

  function formatDriveLabel(minutes) {
    var m = Math.max(0, parseInt(minutes, 10) || 0);
    if (m < 60) return m + ' dk';
    var h = Math.floor(m / 60), r = m % 60;
    return r ? (h + ' sa ' + r + ' dk') : (h + ' sa');
  }

  function formatTotalPlanHours(minutes) {
    var m = Math.max(0, parseInt(minutes, 10) || 0);
    if (m < 60) return m + ' dk';
    var h = Math.floor(m / 60);
    var r = m % 60;
    return h + ' sa ' + String(r).padStart(2, '0') + ' dk';
  }

  function formatKmTurkish(km) {
    if (km == null || !isFinite(Number(km))) return '—';
    return String(km).replace('.', ',') + ' km';
  }

  function buildStopSequenceShort(stopList) {
    return (stopList || []).map(function (s) { return shortStopName(s.company_name); }).join(' → ');
  }

  function buildDriveServiceSub(summary, stopCount, svcMin) {
    if (!summary) return '';
    var drive = summary.drive_label || '—';
    var svcTotal = (stopCount || 0) * (svcMin || 10);
    return drive + ' sürüş + ' + svcTotal + ' dk işlem';
  }

  function googleOrderTaskIds(order) {
    if (!_googleDto) return [];
    var side = order === 'suggested' ? _googleDto.suggested : _googleDto.current;
    return (side && side.order) ? side.order.map(String) : [];
  }

  function buildDecisionRowInner(choice, summary, stopList, showBadge) {
    var label = choice === 'suggested' ? 'B — CPS SIRA ÖNERİSİ' : 'A — MEVCUT SIRA';
    var badge = showBadge
      ? '<span class="atp-exp-decision-badge">CPS ÖNERİSİ</span>'
      : '';
    var stopCount = (stopList || []).length;
    var svcMin = (_googleDto && _googleDto.service_minutes_per_stop) || 10;
    return '<div class="atp-exp-decision-head"><span class="atp-exp-decision-label">' + esc(label) + '</span>' + badge + '</div>' +
      '<div class="atp-exp-decision-km">' + esc(formatKmTurkish(summary && summary.km)) + '</div>' +
      '<div class="atp-exp-decision-total">Toplam: ' + esc(formatTotalPlanHours(summary && summary.total_minutes)) + '</div>' +
      '<div class="atp-exp-decision-return">Dönüş: ' + esc((summary && summary.estimated_return_time) || '—') + '</div>' +
      '<div class="atp-exp-decision-seq">' + esc(buildStopSequenceShort(stopList)) + '</div>' +
      '<div class="atp-exp-decision-sub">' + esc(buildDriveServiceSub(summary, stopCount, svcMin)) + '</div>';
  }

  function buildCompactDecisionFootnote(dto, profile, route) {
    if (!dto) return '';
    if (!dto.order_changed) return 'Mevcut sıra zaten uygun';
    var curOpt = pickProfileOption(dto.current, profile);
    var sugOpt = pickProfileOption(dto.suggested, profile);
    if (!optionComplete(curOpt) || !optionComplete(sugOpt)) return route && route.decision_reason ? route.decision_reason : '';
    var dKm = Math.round(((sugOpt.distance_m - curOpt.distance_m) / 1000) * 10) / 10;
    var dReturnMin = ceilMin(sugOpt.total_plan_seconds) - ceilMin(curOpt.total_plan_seconds);
    var kmStr = String(Math.abs(dKm)).replace('.', ',');
    var parts = [];
    if (Math.abs(dKm) >= 0.1) {
      parts.push('B rotası ' + kmStr + ' km ' + (dKm < 0 ? 'daha kısa' : 'daha uzun'));
    }
    if (dReturnMin !== 0) {
      var timeClause = Math.abs(dReturnMin) + ' dk ' + (dReturnMin < 0 ? 'daha erken dönüyor' : 'daha geç dönüyor');
      if (parts.length) {
        parts[0] += '; ancak Google trafik hesabına göre ' + timeClause;
      } else {
        parts.push('Google trafik hesabına göre B rotası ' + timeClause);
      }
    }
    var sugStops = (route && route.suggested_stop_list) || buildStopListFromOption(sugOpt, _planMapPayload);
    var first = sugStops && sugStops[0];
    var priName = first ? shortStopName(first.company_name) : 'yüksek öncelikli durak';
    var highPri = first && ['YUKSEK', 'ACIL'].indexOf((first.priority || '').toUpperCase()) !== -1;
    var why = highPri
      ? (priName + ' yüksek öncelikli olduğu için CPS, B sırasını öneriyor.')
      : 'CPS, B sırasını öneriyor.';
    return parts.join('') + (parts.length ? '. ' : '') + why;
  }

  function buildConfirmDecisionDiff(dto, profile) {
    if (!dto || !dto.order_changed) return '—';
    var curOpt = pickProfileOption(dto.current, profile);
    var sugOpt = pickProfileOption(dto.suggested, profile);
    if (!optionComplete(curOpt) || !optionComplete(sugOpt)) return '—';
    var dKm = Math.round(((sugOpt.distance_m - curOpt.distance_m) / 1000) * 10) / 10;
    var dReturnMin = ceilMin(sugOpt.total_plan_seconds) - ceilMin(curOpt.total_plan_seconds);
    var bits = [];
    if (Math.abs(dKm) >= 0.1) {
      bits.push(String(Math.abs(dKm)).replace('.', ',') + ' km ' + (dKm < 0 ? 'daha kısa' : 'daha uzun'));
    }
    if (dReturnMin !== 0) {
      bits.push(Math.abs(dReturnMin) + ' dk ' + (dReturnMin < 0 ? 'daha erken' : 'daha geç'));
    }
    return bits.length ? bits.join('; ') : 'Fark yok';
  }

  function buildConfirmDecisionWhy(route) {
    var sugStops = route && route.suggested_stop_list;
    if (!sugStops || !sugStops.length) return 'Neden: CPS sıra önerisi';
    var first = sugStops[0];
    var priName = shortStopName(first.company_name);
    var highPri = ['YUKSEK', 'ACIL'].indexOf((first.priority || '').toUpperCase()) !== -1;
    return highPri ? ('Neden: ' + priName + ' yüksek öncelikli') : 'Neden: CPS sıra önerisi';
  }

  function updateDecisionSummary(route) {
    var box = el('atpExpDecisionSummary');
    var rowA = el('atpExpDecisionRowA');
    var rowB = el('atpExpDecisionRowB');
    var foot = el('atpExpDecisionFootnote');
    if (!box || !_googleMode || !route) {
      if (box) { box.style.display = 'none'; box.setAttribute('hidden', ''); }
      return;
    }
    if (route.order_same) {
      box.style.display = 'none';
      box.setAttribute('hidden', '');
      return;
    }
    box.style.display = '';
    box.removeAttribute('hidden');
    if (rowA) {
      rowA.className = 'atp-exp-decision-row' + (_selectedOrder === 'current' ? ' selected' : '');
      rowA.setAttribute('data-choice', 'current');
      rowA.innerHTML = buildDecisionRowInner('current', route.current_summary, route.current_stop_list, false);
    }
    if (rowB) {
      rowB.className = 'atp-exp-decision-row' + (_selectedOrder === 'suggested' ? ' selected' : '');
      rowB.setAttribute('data-choice', 'suggested');
      rowB.innerHTML = buildDecisionRowInner('suggested', route.suggested_summary, route.suggested_stop_list, true);
    }
    if (foot) {
      foot.textContent = buildCompactDecisionFootnote(_googleDto, _selectedProfile, route);
      foot.className = 'atp-exp-decision-footnote';
    }
    var decisionBar = el('atpExpDecisionBar');
    if (decisionBar) decisionBar.style.display = 'none';
  }

  function updateOrderSamePanels(route) {
    var panel = el('atpExpOrderSamePanel');
    var cards = el('atpExpProfileCards');
    var cardsEl = el('atpExpCards');
    var show = !!( _googleMode && route && route.order_same);
    if (panel) {
      panel.style.display = show ? '' : 'none';
      if (show) panel.removeAttribute('hidden');
      else panel.setAttribute('hidden', '');
    }
    if (cards) {
      cards.style.display = show ? '' : 'none';
      if (show) cards.removeAttribute('hidden');
      else cards.setAttribute('hidden', '');
    }
    if (cardsEl) cardsEl.style.display = (_googleMode && route && route.order_same) ? 'none' : (!_googleMode && route && route.order_same ? 'none' : '');
    if (show && panel) {
      var flowEl = el('atpExpOrderSameFlow');
      var recEl = el('atpExpProfileRecommendation');
      var base = _planMapPayload && _planMapPayload.base;
      var stops = route.current_stop_list || [];
      if (flowEl) flowEl.textContent = buildRouteFlowText(stops, base);
      var recText = route.profile_recommendation_text || '';
      if (recEl) {
        if (recText) {
          recEl.textContent = recText;
          recEl.style.display = '';
        } else {
          recEl.textContent = '';
          recEl.style.display = 'none';
        }
      }
    }
    if (show) updateProfileCards(route);
  }

  function updateProfileCards(route) {
    if (!_googleMode || !route || !route.order_same || !route.profile_views) return;
    var views = route.profile_views;
    [['atpExpProfileCardFast', 'fastest'], ['atpExpProfileCardFree', 'toll_free']].forEach(function (pair) {
      var card = el(pair[0]);
      if (!card) return;
      var prof = pair[1];
      var view = views[prof];
      var opt = view && view.option;
      var ok = optionComplete(opt);
      card.classList.toggle('selected', _selectedProfile === prof);
      card.classList.toggle('disabled', !ok);
      card.setAttribute('aria-pressed', String(_selectedProfile === prof));
      if (ok && _googleDto) {
        card.innerHTML = buildProfileCardInner(prof, opt, _googleDto, route.recommended_profile);
      } else {
        card.innerHTML = '<div class="atp-exp-profile-card-hdr">' +
          esc(prof === 'toll_free' ? 'ÜCRETLİ GEÇİŞİ AZALTAN' : 'EN HIZLI') + '</div>' +
          '<div class="atp-exp-profile-card-row">Hesaplanamadı</div>';
      }
    });
  }

  function profileApplyButtonLabel(profile) {
    return profile === 'toll_free' ? 'Ücretli Geçişi Azaltan Rotayı Kullan' : 'En Hızlı Rotayı Kullan';
  }

  function profileApplySuccessMessage(profile, stopList) {
    var seq = buildStopSequenceShort(stopList || []);
    if (profile === 'toll_free') {
      return 'Ücretli geçişi azaltan rota kullanıma alındı. Sıra değişmedi: ' + seq + '.';
    }
    return 'En Hızlı rota kullanıma alındı. Sıra değişmedi: ' + seq + '.';
  }

  function updateGoogleFooterButtons(route) {
    var keepBtn = el('atpExpFooterKeepCurrent');
    var applyBtn = el('atpExpFooterApplySuggested');
    var footnote = el('atpExpApplyFootnote');
    var pending = el('atpExpApplyPending');
    if (pending) pending.style.display = 'none';
    if (!keepBtn || !applyBtn) return;
    var orderSame = !!(route && route.order_same);
    keepBtn.style.display = orderSame ? 'none' : '';
    applyBtn.style.display = '';
    keepBtn.disabled = !!_googleApplyInFlight;
    applyBtn.disabled = !!_googleApplyInFlight;
    if (orderSame) {
      applyBtn.className = 'btn btn-green';
      applyBtn.textContent = profileApplyButtonLabel(_selectedProfile);
      if (footnote) { footnote.textContent = ''; footnote.style.display = 'none'; }
      return;
    }
    if (_selectedOrder === 'current') {
      keepBtn.className = 'btn btn-blue';
      keepBtn.textContent = 'Mevcut Sırayı Koru';
      applyBtn.className = 'btn btn-outline';
      applyBtn.textContent = 'B Sırasını Uygula';
    } else {
      keepBtn.className = 'btn btn-outline';
      keepBtn.textContent = 'Mevcut Sırayı Koru';
      applyBtn.className = 'btn btn-green';
      applyBtn.textContent = '✓ B Sırasını Uygula';
    }
    if (footnote) {
      if (route && !orderSame && route.suggested_stop_list && route.suggested_stop_list.length) {
        var parts = route.suggested_stop_list.map(function (s, i) {
          return (i + 1) + ' ' + shortStopName(s.company_name);
        });
        footnote.textContent = 'Seçilen sıra uygulanınca durak listesi ' + parts.join(', ') + ' olarak güncellenir.';
        footnote.style.display = '';
      } else {
        footnote.textContent = '';
        footnote.style.display = 'none';
      }
    }
  }

  function notify(msg) {
    if (typeof _applyHooks.toast === 'function') _applyHooks.toast(msg);
  }

  function openGoogleApplyConfirm() {
    if (!_route || !_googleDto) return;
    var profileOnly = !!_route.order_same;
    var backdrop = el('atpGoogleApplyConfirmBackdrop');
    var modal = el('atpGoogleApplyConfirmModal');
    if (!backdrop || !modal) return;
    var seqChange = el('atpGoogleApplySeqChange');
    var profOnlyBox = el('atpGoogleApplyProfileOnly');
    var orderNote = el('atpGoogleApplyOrderNote');
    var beforeEl = el('atpGoogleApplyBeforeSeq');
    var afterEl = el('atpGoogleApplyAfterSeq');
    var profEl = el('atpGoogleApplyProfile');
    var retEl = el('atpGoogleApplyReturn');
    var decHdr = el('atpGoogleApplyDecisionHdr');
    var decTitle = el('atpGoogleApplyDecisionTitle');
    var decMetrics = el('atpGoogleApplyDecisionMetrics');
    var decDiff = el('atpGoogleApplyDecisionDiff');
    var decWhy = el('atpGoogleApplyDecisionWhy');
    var confirmBtn = el('atpGoogleApplyConfirm');
    var sum = profileOnly ? _selectedSummary(_route) : (_route.suggested_summary || {});
    var stopList = profileOnly ? (_route.current_stop_list || []) : (_route.suggested_stop_list || []);
    if (seqChange) seqChange.style.display = profileOnly ? 'none' : '';
    if (profOnlyBox) {
      profOnlyBox.style.display = profileOnly ? '' : 'none';
      if (profileOnly) profOnlyBox.removeAttribute('hidden');
      else profOnlyBox.setAttribute('hidden', '');
    }
    if (profileOnly && orderNote) {
      orderNote.textContent = 'Sıra değişmeyecek: ' + buildStopSequenceShort(stopList);
    }
    if (beforeEl) beforeEl.textContent = buildStopSequenceShort(_route.current_stop_list).toUpperCase();
    if (afterEl) afterEl.textContent = buildStopSequenceShort(_route.suggested_stop_list).toUpperCase();
    if (profEl) profEl.textContent = profileDisplayLabel(_selectedProfile);
    if (retEl) retEl.textContent = (sum && sum.estimated_return_time) || '—';
    if (decHdr) decHdr.textContent = profileOnly ? 'UYGULANACAK ROTA' : 'UYGULANACAK KARAR';
    if (decTitle) {
      decTitle.textContent = profileOnly
        ? ('Profil: ' + profileDisplayLabel(_selectedProfile))
        : 'B — CPS Sıra Önerisi';
    }
    if (decMetrics) {
      decMetrics.textContent = formatKmTurkish(sum && sum.km) + ' · Toplam ' +
        formatTotalPlanHours(sum && sum.total_minutes) + ' · Dönüş ' + ((sum && sum.estimated_return_time) || '—');
    }
    if (decDiff) decDiff.style.display = profileOnly ? 'none' : '';
    if (decDiff && !profileOnly) decDiff.textContent = buildConfirmDecisionDiff(_googleDto, _selectedProfile);
    if (decWhy) decWhy.style.display = profileOnly ? 'none' : '';
    if (decWhy && !profileOnly) decWhy.textContent = buildConfirmDecisionWhy(_route);
    if (confirmBtn) {
      confirmBtn.textContent = profileOnly ? 'Onayla ve Rotayı Kullan' : 'Onayla ve B Sırasını Uygula';
    }
    backdrop.classList.add('open');
    backdrop.setAttribute('aria-hidden', 'false');
    modal.setAttribute('aria-hidden', 'false');
  }

  function closeGoogleApplyConfirm() {
    var backdrop = el('atpGoogleApplyConfirmBackdrop');
    var modal = el('atpGoogleApplyConfirmModal');
    if (backdrop) { backdrop.classList.remove('open'); backdrop.setAttribute('aria-hidden', 'true'); }
    if (modal) modal.setAttribute('aria-hidden', 'true');
  }

  function postGoogleApply() {
    if (_googleApplyInFlight || !_googleDto || !_route) return;
    var profileOnly = !!_route.order_same;
    var vid = typeof _applyHooks.getVehicleId === 'function' ? _applyHooks.getVehicleId() : null;
    var planDate = typeof _applyHooks.getPlanDate === 'function'
      ? _applyHooks.getPlanDate()
      : (global.ATP_PLAN_DATE || '');
    var taskIds = profileOnly
      ? googleOrderTaskIds('current')
      : googleOrderTaskIds('suggested');
    if (!vid || !planDate || !taskIds.length) {
      notify('Rota uygulanamadı: plan veya araç bilgisi eksik.');
      return;
    }
    var dep = (_googleDto.departure_time || '').trim();
    _googleApplyInFlight = true;
    updateGoogleFooterButtons(_route);
    closeGoogleApplyConfirm();
    fetch('/planlama/arac-takip/api/route/apply', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        date: planDate,
        vehicle_id: String(vid),
        task_ids: taskIds,
        apply_source: 'google',
        google_profile: _selectedProfile,
        departure_time: dep,
        keep_current_order: profileOnly,
        profile_only: profileOnly,
      }),
    })
      .then(function (r) { return r.json().then(function (j) { return { status: r.status, body: j }; }); })
      .then(function (res) {
        var j = res.body || {};
        if (!j.ok || res.status < 200 || res.status >= 300) {
          _googleApplyInFlight = false;
          updateGoogleFooterButtons(_route);
          notify('Rota uygulanamadı: ' + (j.error || j.message || ('HTTP ' + res.status)));
          return;
        }
        var stopList = profileOnly ? (_route.current_stop_list || []) : (_route.suggested_stop_list || []);
        var successMsg = profileOnly
          ? profileApplySuccessMessage(_selectedProfile, stopList)
          : ('Önerilen sıra uygulandı: ' + buildStopSequenceShort(stopList) + '.');
        var reloadFn = profileOnly && typeof _applyHooks.reloadAfterProfileApply === 'function'
          ? _applyHooks.reloadAfterProfileApply
          : _applyHooks.reloadAfterApply;
        if (typeof reloadFn !== 'function') {
          _googleApplyInFlight = false;
          closeModal();
          notify(successMsg);
          return;
        }
        var reloadArgs = profileOnly
          ? [String(vid), taskIds, _selectedProfile, (_selectedSummary(_route) || {}).estimated_return_time]
          : [String(vid), taskIds];
        return reloadFn.apply(null, reloadArgs).then(function (ok) {
          _googleApplyInFlight = false;
          closeModal();
          if (ok) notify(successMsg);
          else notify('Rota doğrulanamadı. Planı değişmiş kabul etmeyin.');
        });
      })
      .catch(function () {
        _googleApplyInFlight = false;
        updateGoogleFooterButtons(_route);
        notify('Rota uygulanamadı: ağ hatası.');
      });
  }

  function optionComplete(opt) {
    return !!(opt && opt.calculation_complete);
  }

  function pickProfileOption(side, profile) {
    if (!side) return null;
    return profile === 'toll_free' ? side.toll_free : side.fastest;
  }

  function profileAvailable(dto, profile) {
    if (!dto) return false;
    return optionComplete(pickProfileOption(dto.current, profile)) ||
      optionComplete(pickProfileOption(dto.suggested, profile));
  }

  function bothProfilesFailed(dto) {
    return !profileAvailable(dto, 'fastest') && !profileAvailable(dto, 'toll_free');
  }

  function defaultGoogleProfile(dto) {
    if (profileAvailable(dto, 'fastest')) return 'fastest';
    if (profileAvailable(dto, 'toll_free')) return 'toll_free';
    return 'fastest';
  }

  function parseHHMM(hhmm) {
    if (!hhmm || hhmm === '—') return null;
    var p = String(hhmm).trim().split(':');
    if (p.length < 2) return null;
    var h = parseInt(p[0], 10);
    var m = parseInt(p[1], 10);
    if (!isFinite(h) || !isFinite(m)) return null;
    return { h: h, m: m };
  }

  function addMinutesToHHMM(hhmm, minutes) {
    var t = parseHHMM(hhmm);
    if (!t) return '—';
    var total = t.h * 60 + t.m + (parseInt(minutes, 10) || 0);
    total = ((total % (24 * 60)) + (24 * 60)) % (24 * 60);
    var h = Math.floor(total / 60);
    var m = total % 60;
    return String(h).padStart(2, '0') + ':' + String(m).padStart(2, '0');
  }

  function legTollLine(tollPresent) {
    if (tollPresent === true) return 'Ücretli geçiş bildirildi';
    if (tollPresent === false) return 'Ücretli geçiş bildirilmedi';
    return 'Ücret bilgisi Google tarafından sağlanmadı';
  }

  function compareRecommendedProfile(fastOpt, freeOpt) {
    if (!optionComplete(fastOpt) && !optionComplete(freeOpt)) return null;
    if (!optionComplete(freeOpt)) return 'fastest';
    if (!optionComplete(fastOpt)) return 'toll_free';
    var fTotal = Number(fastOpt.total_plan_seconds) || 0;
    var tTotal = Number(freeOpt.total_plan_seconds) || 0;
    if (fTotal !== tTotal) return fTotal < tTotal ? 'fastest' : 'toll_free';
    var fDist = Number(fastOpt.distance_m) || 0;
    var tDist = Number(freeOpt.distance_m) || 0;
    return fDist <= tDist ? 'fastest' : 'toll_free';
  }

  function pickRecommendedProfile(dto) {
    if (!dto || dto.order_changed) return null;
    return compareRecommendedProfile(
      pickProfileOption(dto.current, 'fastest'),
      pickProfileOption(dto.current, 'toll_free'),
    );
  }

  function buildProfileRecommendationText(dto) {
    if (!dto || dto.order_changed) return '';
    var fastOpt = pickProfileOption(dto.current, 'fastest');
    var freeOpt = pickProfileOption(dto.current, 'toll_free');
    var rec = compareRecommendedProfile(fastOpt, freeOpt);
    if (!rec || !optionComplete(fastOpt) || !optionComplete(freeOpt)) return '';
    var winner = rec === 'fastest' ? fastOpt : freeOpt;
    var loser = rec === 'fastest' ? freeOpt : fastOpt;
    var winnerLabel = profileDisplayLabel(rec);
    var dKm = Math.round(((loser.distance_m - winner.distance_m) / 1000) * 10) / 10;
    var dReturnMin = ceilMin(loser.total_plan_seconds) - ceilMin(winner.total_plan_seconds);
    var parts = ['Öneri: ' + winnerLabel + '.'];
    var metrics = [];
    if (Math.abs(dKm) >= 0.1) {
      metrics.push(String(Math.abs(dKm)).replace('.', ',') + ' km daha kısa');
    }
    if (dReturnMin !== 0) {
      metrics.push(Math.abs(dReturnMin) + ' dk daha erken dönüyor');
    }
    if (metrics.length) {
      parts.push(metrics.join(' ve ') + '.');
    }
    if (rec === 'fastest') {
      parts.push('Diğer rota ücretli geçişleri azaltıyor ancak tamamen kaldırmıyor.');
    } else {
      parts.push('Diğer rota daha hızlı olabilir; bu profil ücretli geçişleri azaltmayı dener.');
    }
    return parts.join(' ');
  }

  function profileDisplayLabel(profile) {
    return profile === 'toll_free' ? 'Ücretli Geçişi Azaltan' : 'En Hızlı';
  }

  function orderDisplayLabel(order) {
    return order === 'suggested' ? 'B — Önerilen Sıra' : 'A — Mevcut Sıra';
  }

  function shortStopName(name) {
    if (!name) return '—';
    var s = String(name).replace(/\s+DEMO$/i, '').trim();
    return s || String(name);
  }

  function countLegTolls(opt) {
    if (!opt || !opt.legs || !opt.legs.length) return 0;
    var legs = opt.legs;
    var count = 0;
    for (var i = 0; i < legs.length - 1; i++) {
      if (legs[i].toll_present) count++;
    }
    return count;
  }

  function buildProfileTollMessage(profile, opt) {
    if (!optionComplete(opt)) return '';
    if (profile === 'toll_free') {
      if (opt.toll_present === false) {
        return 'Google bu rotada ücretli geçiş bildirmiyor.';
      }
      if (opt.toll_present === true) {
        var n = countLegTolls(opt);
        return 'Google ücretli yolları azaltan bir rota hesapladı; ancak ' + n +
          ' ayakta hâlâ ücretli geçiş bildiriyor. Fiyat bilgisi mevcut değil.';
      }
      return '';
    }
    if (opt.toll_present === true) {
      return 'Google bu rotada ücretli geçiş bildiriyor. Fiyat bilgisi mevcut değil.';
    }
    return '';
  }

  function profileCardHeaderLabel(profile, recommendedProfile) {
    var label = profile === 'toll_free' ? 'ÜCRETLİ GEÇİŞİ AZALTAN' : 'EN HIZLI';
    if (recommendedProfile === profile) {
      return label + ' <span class="atp-exp-profile-rec-badge">ÖNERİLEN</span>';
    }
    return label;
  }

  function buildProfileCardInner(profile, opt, dto, recommendedProfile) {
    var sum = optionToSummary(opt, dto);
    var tollMsg = buildProfileTollMessage(profile, opt);
    var html = '<div class="atp-exp-profile-card-hdr">' + profileCardHeaderLabel(profile, recommendedProfile) + '</div>' +
      '<div class="atp-exp-profile-card-km">' + esc(formatKmTurkish(sum.km)) + '</div>' +
      '<div class="atp-exp-profile-card-row"><span>Sürüş</span><strong>' + esc(sum.drive_label || '—') + '</strong></div>' +
      '<div class="atp-exp-profile-card-row"><span>İşlem</span><strong>' + esc(sum.service_formula || '—') + '</strong></div>' +
      '<div class="atp-exp-profile-card-row"><span>Toplam plan</span><strong>' + esc(formatTotalPlanHours(sum.total_minutes)) + '</strong></div>' +
      '<div class="atp-exp-profile-card-row"><span>Tahmini dönüş</span><strong>' + esc(sum.estimated_return_time || '—') + '</strong></div>';
    if (tollMsg) {
      html += '<div class="atp-exp-profile-card-toll">' + esc(tollMsg) + '</div>';
    }
    return html;
  }

  function buildProfileView(opt, dto, planMapPayload) {
    var stops = buildStopListFromOption(opt, planMapPayload);
    return {
      summary: optionToSummary(opt, dto),
      breakdown: optionToBreakdown(opt, dto, stops),
      geometry: decodePolyline(opt && opt.encoded_polyline),
      option: opt,
      stop_list: stops,
    };
  }

  function tollBadgeHtml(opt) {
    if (!optionComplete(opt)) return '';
    if (opt.toll_present === true) {
      return '<span class="atp-exp-toll-badge warn">Ücretli geçiş tespit edildi · fiyat bilgisi yok</span>';
    }
    if (opt.toll_present === false) {
      return '<span class="atp-exp-toll-badge ok">Ücretli geçiş tespit edilmedi</span>';
    }
    return '<span class="atp-exp-toll-badge neutral">Ücret bilgisi Google tarafından sağlanmadı</span>';
  }

  function buildRouteFlowText(stopList, base) {
    var baseLabel = 'Fabrika';
    var names = (stopList || []).map(function (s) { return shortStopName(s.company_name); });
    return [baseLabel].concat(names).concat([baseLabel]).join(' → ');
  }

  function buildReturnLegLine(breakdown, summary) {
    var legs = (breakdown && breakdown.legs) || [];
    if (!legs.length) return '';
    var last = legs[legs.length - 1];
    if (!last || !last.is_return) return '';
    var drive = last.travel_label || '—';
    var ret = (summary && summary.estimated_return_time) || last.arrival_time || '—';
    return 'Dönüş ayağı: ' + esc(last.from_label) + ' → ' + esc(last.to_label) + ' · ' + esc(drive) +
      (ret && ret !== '—' ? ' · Tahmini dönüş ' + esc(ret) : '');
  }

  function buildCpsPriorityReason(sugStops) {
    if (!sugStops || !sugStops.length) return 'CPS rota motoru B sırasını öneriyor.';
    var first = sugStops[0];
    var high = sugStops.filter(function (s) {
      var p = (s.priority || '').toUpperCase();
      return p === 'YUKSEK' || p === 'ACIL';
    });
    if (high.length && first && (high[0].id === first.id || high[0].company_name === first.company_name)) {
      return 'CPS, yüksek öncelikli ' + shortStopName(first.company_name) + ' durağını önce almak için B sırasını öneriyor.';
    }
    return 'CPS rota motoru B sırasını öneriyor.';
  }

  function dtoHasSlowerSuggested(dto, profile) {
    if (!dto || !dto.order_changed) return false;
    var curOpt = pickProfileOption(dto.current, profile);
    var sugOpt = pickProfileOption(dto.suggested, profile);
    if (!optionComplete(curOpt) || !optionComplete(sugOpt)) return false;
    return ceilMin(sugOpt.total_plan_seconds) > ceilMin(curOpt.total_plan_seconds);
  }

  function buildGoogleDecisionSummary(dto, profile) {
    if (!dto) return '';
    if (!dto.order_changed) return 'Mevcut sıra zaten uygun.';
    var curOpt = pickProfileOption(dto.current, profile);
    var sugOpt = pickProfileOption(dto.suggested, profile);
    if (!optionComplete(curOpt) || !optionComplete(sugOpt)) return 'Sıra önerisi: CPS rota motoru';
    var dKm = Math.round(((sugOpt.distance_m - curOpt.distance_m) / 1000) * 10) / 10;
    var dReturnMin = ceilMin(sugOpt.total_plan_seconds) - ceilMin(curOpt.total_plan_seconds);
    var cpsPart = buildCpsPriorityReason(buildStopListFromOption(sugOpt, _planMapPayload));
    var kmPart = '';
    if (Math.abs(dKm) >= 0.1) {
      var kmStr = String(Math.abs(dKm)).replace('.', ',');
      kmPart = ' B rotası ' + kmStr + ' km ' + (dKm < 0 ? 'daha kısa' : 'daha uzun');
    }
    var timePart = '';
    if (dReturnMin !== 0) {
      timePart = (kmPart ? '; ancak Google trafik hesabına göre' : ' Google trafik hesabına göre B rotası') +
        ' ' + Math.abs(dReturnMin) + ' dk ' + (dReturnMin < 0 ? 'daha erken dönüyor.' : 'daha geç dönüyor.');
    } else if (kmPart) {
      timePart = '.';
    }
    if (dReturnMin < 0 && dKm < 0) {
      return 'B rotası Google trafik hesabına göre ' + String(Math.abs(dKm)).replace('.', ',') +
        ' km daha kısa ve ' + Math.abs(dReturnMin) + ' dk daha erken dönüyor.';
    }
    return cpsPart + '.' + kmPart + timePart;
  }

  function updateMapSidePanel(route) {
    var cap = el('atpExpMapCaption');
    var flow = el('atpExpRouteFlow');
    var retLeg = el('atpExpReturnLeg');
    var legend = el('atpExpMapLegend');
    var profLabel = _googleMode ? profileDisplayLabel(_selectedProfile) : '';
    if (cap) {
      if (_googleMode && route && route.order_same) {
        cap.textContent = 'Haritada: ' + profLabel;
      } else {
        cap.textContent = 'Haritada: ' + orderDisplayLabel(_selectedOrder) +
          (profLabel ? ' · ' + profLabel : '');
      }
    }
    var stops = _selectedStopList(route);
    var base = _planMapPayload && _planMapPayload.base;
    if (flow) flow.textContent = buildRouteFlowText(stops, base);
    var bd = _selectedBreakdown(route);
    var sum = _selectedSummary(route);
    if (retLeg) {
      var line = buildReturnLegLine(bd, sum);
      retLeg.innerHTML = line;
      retLeg.style.display = line ? '' : 'none';
    }
    if (legend) legend.classList.toggle('atp-exp-map-legend-hidden', !!_googleMode);
  }

  function refreshSelectedView() {
    if (!_route) return;
    var legsPanel = el('atpExpLegsPanel');
    if (legsPanel) legsPanel.innerHTML = buildLegsHtml(_selectedBreakdown(_route));
    updateMapSidePanel(_route);
    requestAnimationFrame(function () { drawMap(_route, _planMapPayload); });
  }

  function decodePolyline(encoded) {
    if (!encoded || typeof encoded !== 'string') return [];
    var points = [];
    var index = 0, lat = 0, lng = 0, len = encoded.length;
    while (index < len) {
      var b, shift = 0, result = 0;
      do {
        b = encoded.charCodeAt(index++) - 63;
        result |= (b & 0x1f) << shift;
        shift += 5;
      } while (b >= 0x20 && index < len);
      lat += ((result & 1) ? ~(result >> 1) : (result >> 1));
      shift = 0; result = 0;
      do {
        b = encoded.charCodeAt(index++) - 63;
        result |= (b & 0x1f) << shift;
        shift += 5;
      } while (b >= 0x20 && index < len);
      lng += ((result & 1) ? ~(result >> 1) : (result >> 1));
      points.push([lat / 1e5, lng / 1e5]);
    }
    return points;
  }

  function lookupStopMeta(planMapPayload, stopId) {
    var stops = (planMapPayload && planMapPayload.stops) || [];
    var sid = String(stopId);
    for (var i = 0; i < stops.length; i++) {
      if (String(stops[i].id) === sid || String(stops[i].plan_item_id) === sid) return stops[i];
    }
    return null;
  }

  function buildStopListFromOption(opt, planMapPayload) {
    if (!opt) return [];
    var ids = opt.ordered_stop_ids || [];
    var names = opt.ordered_stop_names || [];
    return ids.map(function (id, i) {
      var meta = lookupStopMeta(planMapPayload, id) || {};
      return {
        id: String(id),
        order_no: i + 1,
        company_name: names[i] || meta.company_name || '—',
        priority: meta.priority || 'NORMAL',
        is_locked: !!meta.is_locked,
        has_coordinates: !!(meta.has_coordinates && meta.latitude != null),
        latitude: meta.latitude,
        longitude: meta.longitude,
        job_title: meta.job_title || '',
      };
    });
  }

  function incompleteSummary() {
    return {
      km: null,
      drive_label: 'Hesaplanamadı',
      traffic_label: '—',
      service_formula: '—',
      total_minutes: null,
      departure_time: '—',
      estimated_return_time: '—',
      error_code: true,
    };
  }

  function optionToSummary(opt, dto) {
    if (!optionComplete(opt)) return incompleteSummary();
    var svcMin = dto.service_minutes_per_stop || 10;
    var stopCount = dto.active_stop_count || (opt.ordered_stop_ids || []).length;
    var trafficMin = opt.traffic_delay_minutes_display;
    if (trafficMin == null) trafficMin = ceilMin(opt.traffic_delay_seconds || 0);
    return {
      km: opt.distance_km_display,
      drive_label: formatDriveLabel(opt.drive_minutes_display != null ? opt.drive_minutes_display : ceilMin(opt.drive_seconds)),
      traffic_label: trafficMin > 0 ? ('+' + formatDriveLabel(trafficMin)) : '0 dk',
      service_formula: stopCount + ' × ' + svcMin + ' dk',
      total_minutes: opt.total_plan_minutes_display != null ? opt.total_plan_minutes_display : ceilMin(opt.total_plan_seconds),
      departure_time: dto.departure_time || '—',
      estimated_return_time: opt.return_display || '—',
    };
  }

  function optionToBreakdown(opt, dto, stopList) {
    if (!optionComplete(opt) || !opt.legs || !opt.legs.length) {
      return { legs: [], formula: {} };
    }
    var names = (stopList || []).map(function (s) { return s.company_name || '—'; });
    var svcMin = dto.service_minutes_per_stop || 10;
    var depTime = dto.departure_time || '—';
    var elapsedMin = 0;
    var legs = opt.legs.map(function (lg, i) {
      var isReturn = i === opt.legs.length - 1;
      var fromLabel = i === 0 ? 'Fabrika' : (names[i - 1] || ('Durak ' + i));
      var toLabel = isReturn ? 'Fabrika' : (names[i] || ('Durak ' + (i + 1)));
      var driveMin = lg.drive_minutes_display != null
        ? lg.drive_minutes_display
        : ceilMin(lg.drive_seconds);
      var arrival = '—';
      var departureAfter = '—';
      if (depTime !== '—') {
        arrival = addMinutesToHHMM(depTime, elapsedMin + driveMin);
        if (!isReturn) {
          elapsedMin += driveMin + svcMin;
          departureAfter = addMinutesToHHMM(depTime, elapsedMin);
        } else {
          elapsedMin += driveMin;
          arrival = opt.return_display || arrival;
        }
      } else if (isReturn) {
        arrival = opt.return_display || '—';
      }
      return {
        from_label: fromLabel,
        to_label: toLabel,
        distance_km: lg.distance_km_display != null
          ? lg.distance_km_display
          : (lg.distance_m != null ? Math.round(lg.distance_m / 100) / 10 : null),
        travel_label: formatDriveLabel(driveMin),
        is_return: isReturn,
        arrival_time: arrival,
        departure_time: departureAfter,
        service_minutes: isReturn ? null : svcMin,
        toll_present: lg.toll_present,
        toll_label: legTollLine(lg.toll_present),
      };
    });
    return {
      legs: legs,
      formula: {
        drive_minutes: opt.drive_minutes_display,
        service_formula: (dto.active_stop_count || names.length) + ' × ' + svcMin + ' dk',
        formula_text: (opt.total_plan_minutes_display != null ? opt.total_plan_minutes_display + ' dk' : '—'),
        estimated_return_time: opt.return_display || '—',
      },
    };
  }

  function signedLabel(value, unit, shorterWord, longerWord) {
    if (value == null || !isFinite(value) || value === 0) return 'aynı';
    var abs = Math.abs(value);
    var word = value < 0 ? shorterWord : longerWord;
    return abs + ' ' + unit + ' ' + word;
  }

  function buildGoogleDiffLines(curOpt, sugOpt) {
    if (!optionComplete(curOpt) || !optionComplete(sugOpt)) return [];
    var dKm = Math.round(((sugOpt.distance_m - curOpt.distance_m) / 1000) * 10) / 10;
    var dDriveMin = ceilMin(sugOpt.drive_seconds) - ceilMin(curOpt.drive_seconds);
    var dReturnMin = ceilMin(sugOpt.total_plan_seconds) - ceilMin(curOpt.total_plan_seconds);
    var dTrafficMin = ceilMin(sugOpt.traffic_delay_seconds || 0) - ceilMin(curOpt.traffic_delay_seconds || 0);
    return [
      'Mesafe farkı: ' + signedLabel(dKm, 'km', 'daha kısa', 'daha uzun'),
      'Sürüş farkı: ' + signedLabel(dDriveMin, 'dk', 'daha kısa', 'daha uzun'),
      'Dönüş farkı: ' + signedLabel(dReturnMin, 'dk', 'daha erken', 'daha geç'),
      'Trafik etkisi: ' + signedLabel(dTrafficMin, 'dk', 'daha az', 'daha fazla'),
    ];
  }

  function mapGoogleDtoToRoute(dto, profile, planMapPayload) {
    profile = profile === 'toll_free' ? 'toll_free' : 'fastest';
    var curOpt = pickProfileOption(dto.current, profile);
    var sugOpt = pickProfileOption(dto.suggested, profile);
    var orderSame = !dto.order_changed;
    var curStops = buildStopListFromOption(curOpt, planMapPayload);
    var sugStops = buildStopListFromOption(sugOpt && !orderSame ? sugOpt : curOpt, planMapPayload);
    var curGeom = decodePolyline(curOpt && curOpt.encoded_polyline);
    var sugGeom = decodePolyline(sugOpt && sugOpt.encoded_polyline);
    var lines = orderSame ? [] : buildGoogleDiffLines(curOpt, sugOpt);
    var profileViews = null;
    if (orderSame) {
      profileViews = {
        fastest: buildProfileView(pickProfileOption(dto.current, 'fastest'), dto, planMapPayload),
        toll_free: buildProfileView(pickProfileOption(dto.current, 'toll_free'), dto, planMapPayload),
      };
    }
    var activeView = orderSame && profileViews ? profileViews[profile] : null;
    var recommendedProfile = orderSame ? pickRecommendedProfile(dto) : null;
    return {
      order_same: orderSame,
      decision_reason: orderSame && recommendedProfile
        ? buildProfileRecommendationText(dto)
        : buildGoogleDecisionSummary(dto, profile),
      recommended_profile: recommendedProfile,
      profile_recommendation_text: orderSame ? buildProfileRecommendationText(dto) : '',
      gain_zero: orderSame,
      has_priority_override: false,
      gain_negative: false,
      current_stop_list: curStops,
      suggested_stop_list: sugStops,
      current_summary: activeView ? activeView.summary : optionToSummary(curOpt, dto),
      suggested_summary: optionToSummary(orderSame ? curOpt : sugOpt, dto),
      gain_comparison: { lines: lines },
      current_breakdown: activeView ? activeView.breakdown : optionToBreakdown(curOpt, dto, curStops),
      suggested_breakdown: optionToBreakdown(orderSame ? curOpt : sugOpt, dto, sugStops),
      apply_disabled_reason_label: '',
      constraint_labels: [],
      source_info: {
        provider: 'Google Routes',
        profile: profile === 'toll_free' ? 'Ücretli Geçişi Azaltan' : 'En Hızlı',
        traffic: 'Trafik tahmini',
        service_minutes_per_stop: dto.service_minutes_per_stop || 10,
        leg_count: (curOpt && curOpt.legs) ? curOpt.legs.length : null,
        computed_at: '—',
      },
      current_option: activeView ? activeView.option : curOpt,
      suggested_option: orderSame ? (activeView ? activeView.option : curOpt) : sugOpt,
      profile_views: profileViews,
      current: { geometry: activeView ? activeView.geometry : curGeom },
      suggested: { geometry: sugGeom },
      google_maps_current: null,
      google_maps_suggested: null,
      gmaps_traffic_note: '',
    };
  }

  function setGoogleSourceVisible(on, dto) {
    var box = el('atpExpGoogleSource');
    var modal = el('atpRouteExplainerModal');
    if (modal) modal.classList.toggle('atp-exp-google-active', !!on);
    if (!box) return;
    box.style.display = on ? '' : 'none';
    if (on) box.removeAttribute('hidden');
    else box.setAttribute('hidden', '');
    var profTabs = el('atpExpGoogleProfiles');
    if (profTabs) {
      profTabs.style.display = (on && dto && dto.order_changed) ? '' : 'none';
    }
    var dep = el('atpExpGoogleDep');
    var svc = el('atpExpGoogleService');
    if (dep) dep.textContent = 'Çıkış: ' + ((dto && dto.departure_time) || '—');
    if (svc) {
      var mins = (dto && dto.service_minutes_per_stop) || 10;
      svc.textContent = 'Her durakta işlem: ' + mins + ' dk';
    }
    var pending = el('atpExpApplyPending');
    if (pending) pending.style.display = 'none';
  }

  function syncGoogleProfileButtons(dto, profile) {
    var fastBtn = el('atpExpProfileFast');
    var freeBtn = el('atpExpProfileFree');
    var fastOk = profileAvailable(dto, 'fastest');
    var freeOk = profileAvailable(dto, 'toll_free');
    if (fastBtn) {
      fastBtn.disabled = !fastOk;
      fastBtn.classList.toggle('active', profile === 'fastest');
      fastBtn.setAttribute('aria-selected', String(profile === 'fastest'));
    }
    if (freeBtn) {
      freeBtn.disabled = !freeOk;
      freeBtn.classList.toggle('active', profile === 'toll_free');
      freeBtn.setAttribute('aria-selected', String(profile === 'toll_free'));
    }
    var hint = el('atpExpProfileHint');
    if (hint) {
      if (profile === 'toll_free') {
        hint.textContent = 'Google ücretli geçişleri azaltmayı dener; tamamen kaldıracağını garanti etmez.';
        hint.style.display = '';
        hint.removeAttribute('hidden');
      } else {
        hint.textContent = '';
        hint.style.display = 'none';
        hint.setAttribute('hidden', '');
      }
    }
  }

  function disableApplyButtons(disabled) {
    var keepBtn = el('atpExpFooterKeepCurrent');
    var applyBtn = el('atpExpFooterApplySuggested');
    if (keepBtn) {
      keepBtn.disabled = !!disabled;
      if (disabled) keepBtn.setAttribute('aria-disabled', 'true');
      else keepBtn.removeAttribute('aria-disabled');
    }
    if (applyBtn) {
      applyBtn.disabled = !!disabled;
      if (disabled) applyBtn.setAttribute('aria-disabled', 'true');
      else applyBtn.removeAttribute('aria-disabled');
    }
  }

  function googleHttpErrorMessage(status, code) {
    var c = String(code || '').toUpperCase();
    if (c === 'GOOGLE_ROUTES_NOT_CONFIGURED' || status === 503) {
      return 'Google rota servisi yapılandırılmamış.';
    }
    if (c === 'AUTH' || status === 401 || status === 403) {
      return 'Google rota bağlantısı doğrulanamadı.';
    }
    if (c === 'RATE_LIMIT' || status === 429) {
      return 'Google rota kotası doldu. Daha sonra tekrar deneyin.';
    }
    if (c === 'NO_ACTIVE_STOPS') return 'Bu planda aktif durak yok.';
    if (c === 'MISSING_COORDINATES') return 'Aktif durakların koordinatı eksik.';
    if (c === 'PLAN_NOT_FOUND') return 'Plan bulunamadı.';
    if (c === 'VEHICLE_PLAN_MISMATCH') return 'Araç ile plan eşleşmiyor.';
    if (c === 'INVALID_REQUEST') return 'Geçersiz istek.';
    return 'Google rota hesabı tamamlanamadı.';
  }

  /* ── Diff badges ── */
  function buildDiffRow(cmp) {
    if (!cmp || !cmp.lines || !cmp.lines.length) return '';
    var badges = cmp.lines.map(function (line) {
      var cls = 'neutral';
      if (line.indexOf('daha kısa') !== -1 && line.indexOf('Mesafe') !== -1) cls = 'info';
      else if (line.indexOf('daha kısa') !== -1) cls = 'positive';
      else if (line.indexOf('daha uzun') !== -1 || line.indexOf('daha geç') !== -1) cls = 'negative';
      else if (line.indexOf('daha erken') !== -1) cls = 'positive';
      else if (line.indexOf('Öncelik') !== -1 || line.indexOf('öncelik') !== -1) cls = 'info';
      return '<span class="atp-exp-diff-badge ' + cls + '">' + esc(line) + '</span>';
    });
    return badges.join('');
  }

  /* ── Leg cards HTML ── */
  function buildLegKv(label, value) {
    return '<div class="atp-exp-leg-kv"><span>' + esc(label) + '</span><strong>' + esc(value) + '</strong></div>';
  }

  function buildLegsHtml(breakdown) {
    if (!breakdown || !breakdown.legs || !breakdown.legs.length) {
      return '<p class="atp-exp-leg-empty">Ayak detayı yok (çıkış saati veya rota eksik).</p>';
    }
    var html = '';
    breakdown.legs.forEach(function (leg) {
      html += '<div class="atp-exp-leg-card' + (leg.is_return ? ' return' : '') + '">' +
        '<div class="atp-exp-leg-title">' + esc(leg.from_label) + ' → ' + esc(leg.to_label) + '</div>' +
        '<div class="atp-exp-leg-grid">' +
        buildLegKv('Mesafe', leg.distance_km != null ? leg.distance_km + ' km' : '—') +
        buildLegKv('Sürüş süresi', leg.travel_label || '—');
      if (!leg.is_return) {
        html += buildLegKv('Tahmini varış', leg.arrival_time || '—') +
          buildLegKv('İşlem', leg.service_minutes != null ? leg.service_minutes + ' dk' : '—') +
          buildLegKv('Çıkış saati', leg.departure_time || '—');
      } else {
        html += buildLegKv('Tahmini dönüş', leg.arrival_time || '—');
      }
      html += '</div>' +
        '<div class="atp-exp-leg-toll-line">' + esc(leg.toll_label || legTollLine(leg.toll_present)) + '</div>' +
        '</div>';
    });
    var f = breakdown.formula || {};
    html += '<div class="atp-exp-leg-formula">' +
      '<div>Sürüş: <strong>' + esc(f.drive_minutes != null ? f.drive_minutes + ' dk' : '—') + '</strong></div>' +
      '<div>İşlem: <strong>' + esc(f.service_formula || '—') + '</strong></div>' +
      '<div>Toplam plan: <strong>' + esc(f.formula_text || '—') + '</strong></div>' +
      '<div>Tahmini dönüş: <strong>' + esc(f.estimated_return_time || '—') + '</strong></div>' +
      '</div>';
    return html;
  }

  /* ── Selection card toggle ── */
  function setSelection(choice) {
    _selectedOrder = choice;

    ['current', 'suggested'].forEach(function (c) {
      var card = el('atpExpCard' + (c === 'current' ? 'Current' : 'Suggested'));
      if (!card) return;
      card.classList.toggle('selected', c === choice);
      card.setAttribute('aria-pressed', String(c === choice));
    });

    var keepBtn  = el('atpExpFooterKeepCurrent');
    var applyBtn = el('atpExpFooterApplySuggested');
    if (keepBtn) {
      keepBtn.className = 'btn ' + (choice === 'current' ? 'btn-blue' : 'btn-outline');
    }
    if (applyBtn) {
      applyBtn.className = 'btn ' + (choice === 'suggested' ? 'btn-green' : 'btn-outline');
    }

    if (_googleMode) updateGoogleFooterButtons(_route);
    updateDecisionSummary(_route);
    refreshSelectedView();
  }

  /* ── Populate modal ── */
  function populateModal(route, planMapPayload) {
    if (!route) return;
    _route = route;
    _planMapPayload = planMapPayload;

    var orderSame = route.order_same;
    var base = planMapPayload && planMapPayload.base;

    /* Decision bar */
    var decisionBar = el('atpExpDecisionBar');
    var reasonEl = el('atpExplainerDecisionReason');
    if (reasonEl) {
      var txt = route.decision_reason || '';
      reasonEl.textContent = txt;
      var cls = 'atp-exp-decision-text';
      if (orderSame || route.gain_zero) cls += ' optimal';
      else if (route.has_priority_override) cls += ' priority-override';
      else if (route.gain_negative) cls += ' warn';
      else if (_googleMode && dtoHasSlowerSuggested(_googleDto, _selectedProfile)) cls += ' warn';
      reasonEl.className = cls;
      if (decisionBar) {
        if (_googleMode) decisionBar.style.display = 'none';
        else decisionBar.style.display = txt ? '' : 'none';
      }
    }

    /* Same order note */
    var sameNote = el('atpExplainerSameRouteNote');
    if (sameNote) {
      if (orderSame) {
        sameNote.textContent = _googleMode
          ? (route.profile_recommendation_text || 'Mevcut sıra CPS önerisiyle aynı — yol profili seçip uygulayabilirsiniz.')
          : 'Mevcut sıra zaten en uygun — sistem aynı sırayı öneriyor.';
        sameNote.style.display = '';
      } else {
        sameNote.style.display = 'none';
      }
    }

    /* Cards vs order-same profile layout */
    updateOrderSamePanels(route);

    /* System badge visibility */
    var sysBadge = el('atpExpSystemBadge');
    if (sysBadge) sysBadge.style.display = orderSame ? 'none' : '';

    /* Current order + summary */
    var curOrderEl = el('atpExplainerCurrentOrder');
    if (curOrderEl) curOrderEl.innerHTML = buildOrderListHtml(route.current_stop_list || [], base);
    var curSumEl = el('atpExplainerCurrentSummary');
    if (curSumEl) curSumEl.innerHTML = buildCardSummaryHtml(route.current_summary);
    var curToll = el('atpExpTollBadgeCurrent');
    if (curToll) {
      curToll.innerHTML = _googleMode && route.current_option ? tollBadgeHtml(route.current_option) : '';
    }

    /* Suggested order + summary */
    var sugOrderEl = el('atpExplainerSugOrder');
    if (sugOrderEl) {
      var sugList = orderSame ? (route.current_stop_list || []) : (route.suggested_stop_list || []);
      sugOrderEl.innerHTML = buildOrderListHtml(sugList, base);
    }
    var sugSumEl = el('atpExplainerSugSummary');
    if (sugSumEl) {
      var sugSum = orderSame ? route.current_summary : route.suggested_summary;
      sugSumEl.innerHTML = buildCardSummaryHtml(sugSum);
    }
    var sugToll = el('atpExpTollBadgeSuggested');
    if (sugToll) {
      var sugOptRef = orderSame ? route.current_option : route.suggested_option;
      sugToll.innerHTML = _googleMode && sugOptRef ? tollBadgeHtml(sugOptRef) : '';
    }

    /* Diff badges */
    var diffRow = el('atpExpDiffRow');
    if (diffRow) {
      if (!orderSame && route.gain_comparison) {
        diffRow.innerHTML = buildDiffRow(route.gain_comparison);
        diffRow.style.display = '';
      } else {
        diffRow.style.display = 'none';
      }
    }

    /* Leg panel — selected profile + order only */
    var legsPanel = el('atpExpLegsPanel');
    if (legsPanel) legsPanel.innerHTML = buildLegsHtml(_selectedBreakdown(route));

    /* Footer buttons */
    var keepBtn  = el('atpExpFooterKeepCurrent');
    var applyBtn = el('atpExpFooterApplySuggested');
    if (_googleMode) {
      updateGoogleFooterButtons(route);
      updateDecisionSummary(route);
    } else if (orderSame) {
      disableApplyButtons(false);
      if (keepBtn) { keepBtn.textContent = 'Mevcut Sırayla Devam Et'; keepBtn.className = 'btn btn-blue'; }
      if (applyBtn) applyBtn.style.display = 'none';
    } else {
      disableApplyButtons(false);
      if (keepBtn) { keepBtn.textContent = 'Mevcut Sırayı Koru'; }
      if (applyBtn) applyBtn.style.display = '';
    }

    /* Legend hidden in Google mode via updateMapSidePanel */
    var sugLegend = el('atpExplainerLegendSug');
    if (sugLegend) sugLegend.style.display = (!_googleMode && !orderSame) ? '' : 'none';

    var applyReasonEl = el('atpExplainerApplyReason');
    if (applyReasonEl) {
      var lbl = route.apply_disabled_reason_label || '';
      applyReasonEl.textContent = lbl ? '📋 ' + lbl : '';
      applyReasonEl.style.display = lbl ? '' : 'none';
    }
    var constraintsEl = el('atpExplainerConstraints');
    if (constraintsEl) {
      var labels = route.constraint_labels || [];
      if (labels.length) {
        constraintsEl.innerHTML = '🔒 <strong>Kısıtlar:</strong><ul style="margin:4px 0 0 12px;padding:0">' +
          labels.map(function (l) { return '<li>' + esc(l) + '</li>'; }).join('') + '</ul>';
        constraintsEl.style.display = '';
      } else {
        constraintsEl.style.display = 'none';
      }
    }

    /* Source info */
    var srcEl = el('atpExplainerSourceInfo');
    if (srcEl) {
      var si = route.source_info || {};
      srcEl.innerHTML =
        '<ul>' +
        '<li>Rota sağlayıcı: <strong>' + esc(si.provider || '—') + '</strong></li>' +
        '<li>Profil: <strong>' + esc(si.profile || '—') + '</strong></li>' +
        '<li>Trafik: <strong>' + esc(si.traffic || '—') + '</strong></li>' +
        '<li>Durak işlem süresi: <strong>' + esc(si.service_minutes_per_stop != null ? si.service_minutes_per_stop + ' dk' : '—') + '</strong></li>' +
        '<li>Rota ayağı: <strong>' + esc(si.leg_count != null ? si.leg_count : '—') + '</strong></li>' +
        '<li>Hesap zamanı: <strong>' + esc(si.computed_at || '—') + '</strong></li>' +
        '</ul>';
    }

    /* Google Maps links */
    var gmapsLinksEl = el('atpExpGmapsLinks');
    if (gmapsLinksEl) {
      var lHtml = '';
      if (route.google_maps_current) {
        lHtml += '<a class="atp-explainer-gmaps-link" href="' + esc(route.google_maps_current) + '" target="_blank" rel="noopener noreferrer">Mevcut rotayı Google Maps\'te kontrol et</a>';
      }
      if (!orderSame && route.google_maps_suggested) {
        lHtml += '<a class="atp-explainer-gmaps-link" href="' + esc(route.google_maps_suggested) + '" target="_blank" rel="noopener noreferrer">Önerilen rotayı Google Maps\'te kontrol et</a>';
      }
      gmapsLinksEl.innerHTML = lHtml;
    }
    var gmapsNote = el('atpExplainerGmapsNote');
    if (gmapsNote) gmapsNote.textContent = route.gmaps_traffic_note || '';

    /* Default selection + map */
    setSelection(_selectedOrder || 'current');
    updateMapSidePanel(route);
  }

  /* ── Open / close ── */
  function applyGoogleProfile(profile) {
    if (!_googleDto) return;
    if (!profileAvailable(_googleDto, profile)) return;
    _selectedProfile = profile;
    var mapped = mapGoogleDtoToRoute(_googleDto, profile, _planMapPayload);
    _route = mapped;
    populateModal(mapped, _planMapPayload);
    syncGoogleProfileButtons(_googleDto, profile);
    setGoogleSourceVisible(true, _googleDto);
  }

  function openGoogleModal(dto, planMapPayload) {
    if (!dto || bothProfilesFailed(dto)) return false;
    _googleMode = true;
    _googleDto = dto;
    _selectedProfile = defaultGoogleProfile(dto);
    _selectedOrder = dto.order_changed ? 'suggested' : 'current';
    _planMapPayload = planMapPayload || null;
    setGoogleSourceVisible(true, dto);
    applyGoogleProfile(_selectedProfile);
    var backdrop = el('atpRouteExplainerBackdrop');
    var modal = el('atpRouteExplainerModal');
    if (!backdrop || !modal) return false;
    backdrop.classList.add('open');
    backdrop.setAttribute('aria-hidden', 'false');
    modal.setAttribute('aria-hidden', 'false');
    return true;
  }

  function openModal(route, planMapPayload) {
    var backdrop = el('atpRouteExplainerBackdrop');
    var modal = el('atpRouteExplainerModal');
    if (!backdrop || !modal) return;
    _googleMode = false;
    _googleDto = null;
    _selectedOrder = 'current';
    setGoogleSourceVisible(false, null);
    disableApplyButtons(false);
    populateModal(route, planMapPayload);
    backdrop.classList.add('open');
    backdrop.setAttribute('aria-hidden', 'false');
    modal.setAttribute('aria-hidden', 'false');
  }

  function closeModal() {
    var backdrop = el('atpRouteExplainerBackdrop');
    var modal = el('atpRouteExplainerModal');
    if (backdrop) { backdrop.classList.remove('open'); backdrop.setAttribute('aria-hidden', 'true'); }
    if (modal) modal.setAttribute('aria-hidden', 'true');
    destroyMap();
  }

  /* ── Event binding ── */
  function bindClose() {
    ['atpRouteExplainerClose', 'atpRouteExplainerDismiss'].forEach(function (id) {
      var btn = el(id);
      if (btn) btn.addEventListener('click', closeModal);
    });
    var backdrop = el('atpRouteExplainerBackdrop');
    if (backdrop) {
      backdrop.addEventListener('click', function (e) { if (e.target === backdrop) closeModal(); });
    }
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && el('atpRouteExplainerBackdrop') &&
          el('atpRouteExplainerBackdrop').classList.contains('open')) closeModal();
    });
  }

  function bindCards() {
    ['current', 'suggested'].forEach(function (choice) {
      var card = el('atpExpCard' + (choice === 'current' ? 'Current' : 'Suggested'));
      if (!card) return;
      card.addEventListener('click', function () { setSelection(choice); });
      card.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSelection(choice); }
      });
    });
  }

  function bindFooterApply() {
    var keepBtn = el('atpExpFooterKeepCurrent');
    if (keepBtn) {
      keepBtn.addEventListener('click', function () {
        if (keepBtn.disabled) return;
        if (_googleMode) {
          setSelection('current');
          closeModal();
          return;
        }
        setSelection('current');
        closeModal();
      });
    }

    var applyBtn = el('atpExpFooterApplySuggested');
    if (applyBtn) {
      applyBtn.addEventListener('click', function () {
        if (applyBtn.disabled) return;
        if (_googleMode) {
          if (_route && _route.order_same) {
            openGoogleApplyConfirm();
            return;
          }
          setSelection('suggested');
          openGoogleApplyConfirm();
          return;
        }
        setSelection('suggested');
        closeModal();
        var mainApplyBtn = document.getElementById('atpBtnApplySuggestedOrder');
        if (mainApplyBtn && !mainApplyBtn.disabled) mainApplyBtn.click();
      });
    }
  }

  function bindDecisionSummaryRows() {
    var box = el('atpExpDecisionSummary');
    if (!box) return;
    box.addEventListener('click', function (e) {
      if (!_googleMode) return;
      var row = e.target.closest('.atp-exp-decision-row');
      if (!row || !box.contains(row)) return;
      var choice = row.getAttribute('data-choice') || 'current';
      setSelection(choice === 'suggested' ? 'suggested' : 'current');
    });
  }

  function bindGoogleApplyConfirm() {
    ['atpGoogleApplyConfirmClose', 'atpGoogleApplyCancel'].forEach(function (id) {
      var btn = el(id);
      if (btn) btn.addEventListener('click', closeGoogleApplyConfirm);
    });
    var backdrop = el('atpGoogleApplyConfirmBackdrop');
    if (backdrop) {
      backdrop.addEventListener('click', function (e) {
        if (e.target === backdrop) closeGoogleApplyConfirm();
      });
    }
    var confirmBtn = el('atpGoogleApplyConfirm');
    if (confirmBtn) confirmBtn.addEventListener('click', postGoogleApply);
  }

  function bindApplyHooks(hooks) {
    _applyHooks = Object.assign({}, _applyHooks, hooks || {});
  }

  function bindExplainerButton(getLastRoute, getPlanMapPayload) {
    var btn = el('atpBtnRouteExplainer');
    if (!btn) return;
    btn.addEventListener('click', function () {
      var route = typeof getLastRoute === 'function' ? getLastRoute() : null;
      var payload = typeof getPlanMapPayload === 'function' ? getPlanMapPayload() : null;
      openModal(route, payload);
    });
  }

  function updateExplainerButton(route) {
    var btn = el('atpBtnRouteExplainer');
    if (!btn) return;
    btn.disabled = !route || !route.current || !route.current.geometry || !route.current.geometry.length;
  }

  function bindProfileCards() {
    [['atpExpProfileCardFast', 'fastest'], ['atpExpProfileCardFree', 'toll_free']].forEach(function (pair) {
      var card = el(pair[0]);
      if (!card) return;
      function pick() {
        if (!_googleMode || card.classList.contains('disabled')) return;
        if (_selectedProfile === pair[1]) {
          refreshSelectedView();
          updateProfileCards(_route);
          updateGoogleFooterButtons(_route);
          return;
        }
        applyGoogleProfile(pair[1]);
      }
      card.addEventListener('click', pick);
      card.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(); }
      });
    });
  }

  function bindGoogleProfiles() {
    [['atpExpProfileFast', 'fastest'], ['atpExpProfileFree', 'toll_free']].forEach(function (pair) {
      var btn = el(pair[0]);
      if (!btn) return;
      btn.addEventListener('click', function () {
        if (!_googleMode || btn.disabled) return;
        applyGoogleProfile(pair[1]);
      });
    });
  }

  /* ── Init ── */
  bindClose();
  bindCards();
  bindFooterApply();
  bindGoogleProfiles();
  bindProfileCards();
  bindDecisionSummaryRows();
  bindGoogleApplyConfirm();

  global.AtpRouteExplainer = {
    openModal: openModal,
    openGoogleModal: openGoogleModal,
    closeModal: closeModal,
    bindExplainerButton: bindExplainerButton,
    bindApplyHooks: bindApplyHooks,
    updateExplainerButton: updateExplainerButton,
    mapGoogleDtoToRoute: mapGoogleDtoToRoute,
    decodePolyline: decodePolyline,
    bothProfilesFailed: bothProfilesFailed,
    profileAvailable: profileAvailable,
    defaultGoogleProfile: defaultGoogleProfile,
    googleHttpErrorMessage: googleHttpErrorMessage,
    formatDriveLabel: formatDriveLabel,
    formatTotalPlanHours: formatTotalPlanHours,
    formatKmTurkish: formatKmTurkish,
    buildStopSequenceShort: buildStopSequenceShort,
    buildCompactDecisionFootnote: buildCompactDecisionFootnote,
    buildGoogleDiffLines: buildGoogleDiffLines,
    buildProfileTollMessage: buildProfileTollMessage,
    profileApplyButtonLabel: profileApplyButtonLabel,
    buildProfileCardInner: buildProfileCardInner,
    pickProfileOption: pickProfileOption,
    pickRecommendedProfile: pickRecommendedProfile,
    buildProfileRecommendationText: buildProfileRecommendationText,
    compareRecommendedProfile: compareRecommendedProfile,
    legTollLine: legTollLine,
  };

})(window);
