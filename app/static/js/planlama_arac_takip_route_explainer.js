/* ATP Route Decision Explainer Modal — v4 (UI simplify)
   Read-only: no DB write, no route apply.
   All numbers from backend RouteResult + timeline — no frontend recalc. */
(function (global) {
  'use strict';

  /* ── Map state ── */
  var _map = null;
  var _currentLayer = null;
  var _currentHalo = null;
  var _suggestedLayer = null;
  var _suggestedHalo = null;
  var _markers = [];

  /* ── Selection state: 'current' | 'suggested' ── */
  var _selectedChoice = 'current';
  var _route = null;
  var _planMapPayload = null;

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
    _currentLayer = _currentHalo = _suggestedLayer = _suggestedHalo = null;
    _markers = [];
    var mapEl = el('atpExplainerMap');
    if (mapEl) { if (mapEl._leaflet_id) delete mapEl._leaflet_id; mapEl.innerHTML = ''; }
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

    var stops = (planMapPayload && planMapPayload.stops) || [];
    stops.forEach(function (stop) {
      if (!stop.has_coordinates || stop.latitude == null) return;
      var lat = parseFloat(stop.latitude), lng = parseFloat(stop.longitude);
      var mk = L.marker([lat, lng], { icon: makeStopIcon(stop.order_no), zIndexOffset: 800 + (stop.order_no || 0) });
      mk.bindPopup('<strong>' + esc(stop.order_no) + ' · ' + esc(stop.company_name) + '</strong><br>' + esc(stop.job_title || '—'));
      mk.addTo(_map); _markers.push(mk); bounds.push([lat, lng]);
    });

    var curGeom = (route && route.current && route.current.geometry) || [];
    if (curGeom.length >= 2) {
      var lls = curGeom.map(function (p) { return [p[0], p[1]]; });
      _currentHalo = L.polyline(lls, { color: '#fff', weight: 11, opacity: 0.5, interactive: false }).addTo(_map);
      _currentLayer = L.polyline(lls, { color: '#1d4ed8', weight: 7, opacity: 0.96, lineJoin: 'round', lineCap: 'round' }).addTo(_map);
      lls.forEach(function (p) { bounds.push(p); });
    }

    var orderSame = route && route.order_same;
    var sugGeom = (route && route.suggested && route.suggested.geometry) || [];
    var sugLegend = el('atpExplainerLegendSug');
    if (!orderSame && sugGeom.length >= 2) {
      var sLls = sugGeom.map(function (p) { return [p[0], p[1]]; });
      _suggestedHalo = L.polyline(sLls, { color: '#fff', weight: 9, opacity: 0.4, interactive: false }).addTo(_map);
      _suggestedLayer = L.polyline(sLls, { color: '#16a34a', weight: 5, opacity: 0.88, dashArray: '10 6', lineJoin: 'round', lineCap: 'round' }).addTo(_map);
      if (_suggestedLayer.bringToFront) _suggestedLayer.bringToFront();
      if (sugLegend) sugLegend.style.display = '';
    } else if (sugLegend) {
      sugLegend.style.display = 'none';
    }

    if (bounds.length >= 2) {
      _map.fitBounds(L.latLngBounds(bounds).pad(0.12), { animate: false, maxZoom: 12 });
    } else if (bounds.length === 1) {
      _map.setView(bounds[0], 11, { animate: false });
    }
    setTimeout(function () { if (_map) _map.invalidateSize({ animate: false }); }, 150);
  }

  /* highlight selected route on map */
  function updateMapHighlight(choice) {
    if (_currentLayer) {
      if (choice === 'current') {
        _currentLayer.setStyle({ opacity: 0.96, weight: 7 });
        if (_currentHalo) _currentHalo.setStyle({ opacity: 0.5 });
      } else {
        _currentLayer.setStyle({ opacity: 0.35, weight: 4 });
        if (_currentHalo) _currentHalo.setStyle({ opacity: 0.2 });
      }
    }
    if (_suggestedLayer) {
      if (choice === 'suggested') {
        _suggestedLayer.setStyle({ opacity: 0.96, weight: 6 });
        if (_suggestedHalo) _suggestedHalo.setStyle({ opacity: 0.5 });
      } else {
        _suggestedLayer.setStyle({ opacity: 0.45, weight: 4 });
        if (_suggestedHalo) _suggestedHalo.setStyle({ opacity: 0.2 });
      }
    }
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
      ['İşlem', summary.service_formula || '—'],
      ['Toplam plan', summary.total_minutes != null ? summary.total_minutes + ' dk' : '—'],
      ['Çıkış', summary.departure_time || '—'],
      ['Tahmini dönüş', summary.estimated_return_time || '—'],
    ];
    return rows.map(function (r) {
      return '<div class="atp-exp-sum-row"><span>' + esc(r[0]) + '</span><strong>' + esc(r[1]) + '</strong></div>';
    }).join('');
  }

  /* ── Diff badges ── */
  function buildDiffRow(cmp) {
    if (!cmp || !cmp.lines || !cmp.lines.length) return '';
    var badges = cmp.lines.map(function (line) {
      var cls = 'neutral';
      if (line.indexOf('daha kısa') !== -1) cls = 'positive';
      else if (line.indexOf('daha uzun') !== -1 || line.indexOf('daha geç') !== -1) cls = 'negative';
      else if (line.indexOf('Öncelik') !== -1 || line.indexOf('öncelik') !== -1) cls = 'info';
      return '<span class="atp-exp-diff-badge ' + cls + '">' + esc(line) + '</span>';
    });
    return badges.join('');
  }

  /* ── Leg cards HTML ── */
  function buildLegsHtml(breakdown) {
    if (!breakdown || !breakdown.legs || !breakdown.legs.length) {
      return '<p class="atp-exp-leg-empty">Ayak detayı yok (çıkış saati veya rota eksik).</p>';
    }
    var html = '';
    breakdown.legs.forEach(function (leg) {
      html += '<div class="atp-exp-leg-card' + (leg.is_return ? ' return' : '') + '">' +
        '<div class="atp-exp-leg-title">' + esc(leg.from_label) + ' → ' + esc(leg.to_label) + '</div>' +
        '<div class="atp-exp-leg-row">' +
        '<span>' + esc(leg.distance_km != null ? leg.distance_km + ' km' : '—') + '</span>' +
        '<span>' + esc(leg.travel_label || '—') + '</span>';
      if (!leg.is_return) {
        html += '<span>Varış <strong>' + esc(leg.arrival_time || '—') + '</strong></span>' +
          '<span>İşlem <strong>' + esc(leg.service_minutes != null ? leg.service_minutes + ' dk' : '—') + '</strong></span>' +
          '<span>Çıkış <strong>' + esc(leg.departure_time || '—') + '</strong></span>';
      } else {
        html += '<span>Tahmini dönüş <strong>' + esc(leg.arrival_time || '—') + '</strong></span>';
      }
      html += '</div></div>';
    });
    var f = breakdown.formula || {};
    var durLines = (f.duration_labels && f.duration_labels.lines) || [];
    html += '<div class="atp-exp-leg-formula">';
    if (durLines.length) {
      durLines.forEach(function (line) { html += '<div>' + esc(line) + '</div>'; });
    } else {
      html += '<div>Sürüş: <strong>' + esc(f.drive_minutes != null ? f.drive_minutes + ' dk' : '—') + '</strong></div>' +
        '<div>İşlem: <strong>' + esc(f.service_formula || '—') + '</strong></div>' +
        '<div>Toplam plan: <strong>' + esc(f.formula_text || '—') + '</strong></div>';
    }
    html += '<div>Tahmini dönüş: <strong>' + esc(f.estimated_return_time || '—') + '</strong></div>' +
      '</div>';
    return html;
  }

  /* ── Selection card toggle ── */
  function setSelection(choice) {
    _selectedChoice = choice;

    ['current', 'suggested'].forEach(function (c) {
      var card = el('atpExpCard' + (c === 'current' ? 'Current' : 'Suggested'));
      if (!card) return;
      card.classList.toggle('selected', c === choice);
      card.setAttribute('aria-pressed', String(c === choice));
    });

    /* Sync legs accordion content */
    var curLegs = el('atpExplainerCurrentLegs');
    var sugLegs = el('atpExplainerSugLegs');
    if (curLegs) curLegs.style.display = choice === 'current' ? '' : 'none';
    if (sugLegs) sugLegs.style.display = choice === 'suggested' ? '' : 'none';

    /* Sync footer buttons */
    var keepBtn  = el('atpExpFooterKeepCurrent');
    var applyBtn = el('atpExpFooterApplySuggested');
    if (keepBtn) {
      keepBtn.className = 'btn ' + (choice === 'current' ? 'btn-blue' : 'btn-outline');
    }
    if (applyBtn) {
      applyBtn.className = 'btn ' + (choice === 'suggested' ? 'btn-green' : 'btn-outline');
    }

    /* Map highlight */
    updateMapHighlight(choice);

    /* Map toggles */
    var tCur = el('atpExpToggleCurrent');
    var tSug = el('atpExpToggleSuggested');
    if (tCur) tCur.classList.toggle('active', choice === 'current');
    if (tSug) tSug.classList.toggle('active', choice === 'suggested');
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
      reasonEl.className = cls;
      if (decisionBar) decisionBar.style.display = txt ? '' : 'none';
    }

    /* Same order note */
    var sameNote = el('atpExplainerSameRouteNote');
    if (sameNote) {
      if (orderSame) {
        sameNote.textContent = 'Mevcut sıra zaten en uygun — sistem aynı sırayı öneriyor.';
        sameNote.style.display = '';
      } else {
        sameNote.style.display = 'none';
      }
    }

    /* Cards */
    var cardsEl = el('atpExpCards');
    if (cardsEl) cardsEl.style.display = orderSame ? 'none' : '';

    /* System badge visibility */
    var sysBadge = el('atpExpSystemBadge');
    if (sysBadge) sysBadge.style.display = orderSame ? 'none' : '';

    /* Current order + summary */
    var curOrderEl = el('atpExplainerCurrentOrder');
    if (curOrderEl) curOrderEl.innerHTML = buildOrderListHtml(route.current_stop_list || [], base);
    var curSumEl = el('atpExplainerCurrentSummary');
    if (curSumEl) curSumEl.innerHTML = buildCardSummaryHtml(route.current_summary);

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

    /* Leg panels */
    var curLegsEl = el('atpExplainerCurrentLegs');
    if (curLegsEl) curLegsEl.innerHTML = buildLegsHtml(route.current_breakdown);
    var sugLegsEl = el('atpExplainerSugLegs');
    if (sugLegsEl) sugLegsEl.innerHTML = buildLegsHtml(orderSame ? route.current_breakdown : route.suggested_breakdown);

    /* Footer buttons */
    var keepBtn  = el('atpExpFooterKeepCurrent');
    var applyBtn = el('atpExpFooterApplySuggested');
    if (orderSame) {
      if (keepBtn) { keepBtn.textContent = 'Mevcut Sırayla Devam Et'; keepBtn.className = 'btn btn-blue'; }
      if (applyBtn) applyBtn.style.display = 'none';
    } else {
      if (keepBtn) { keepBtn.textContent = 'Mevcut Sırayı Koru'; }
      if (applyBtn) applyBtn.style.display = '';
    }

    /* Map toggle buttons */
    var tSug = el('atpExpToggleSuggested');
    if (tSug) tSug.style.display = orderSame ? 'none' : '';

    /* Constraints */
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

    /* Legend */
    var sugLegend = el('atpExplainerLegendSug');
    if (sugLegend) sugLegend.style.display = orderSame ? 'none' : '';

    /* Default selection */
    setSelection('current');

    /* Map */
    requestAnimationFrame(function () { drawMap(route, planMapPayload); });
  }

  /* ── Open / close ── */
  function openModal(route, planMapPayload) {
    var backdrop = el('atpRouteExplainerBackdrop');
    var modal = el('atpRouteExplainerModal');
    if (!backdrop || !modal) return;
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

  function bindMapToggles() {
    ['current', 'suggested'].forEach(function (choice) {
      var btn = el('atpExpToggle' + (choice === 'current' ? 'Current' : 'Suggested'));
      if (!btn) return;
      btn.addEventListener('click', function () { setSelection(choice); });
    });
  }

  function bindFooterApply() {
    /* Mevcut Sırayı Koru — just close (no backend change) */
    var keepBtn = el('atpExpFooterKeepCurrent');
    if (keepBtn) {
      keepBtn.addEventListener('click', function () {
        setSelection('current');
        closeModal();
      });
    }

    /* Önerilen Sırayı Uygula — delegate to existing AtpRoute apply button */
    var applyBtn = el('atpExpFooterApplySuggested');
    if (applyBtn) {
      applyBtn.addEventListener('click', function () {
        setSelection('suggested');
        closeModal();
        /* Trigger existing apply button on main page */
        var mainApplyBtn = document.getElementById('atpBtnApplySuggestedOrder');
        if (mainApplyBtn && !mainApplyBtn.disabled) {
          mainApplyBtn.click();
        }
      });
    }
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

  /* ── Init ── */
  bindClose();
  bindCards();
  bindMapToggles();
  bindFooterApply();

  global.AtpRouteExplainer = {
    openModal: openModal,
    closeModal: closeModal,
    bindExplainerButton: bindExplainerButton,
    updateExplainerButton: updateExplainerButton,
  };

})(window);
