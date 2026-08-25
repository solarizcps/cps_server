/* ATP Route Decision Explainer Modal — v2
   Read-only: no DB write, no route apply.
   Memory-safe: Leaflet instance destroyed on close. */
(function (global) {
  'use strict';

  var _map = null;
  var _currentLayer = null;
  var _currentHalo = null;
  var _suggestedLayer = null;
  var _suggestedHalo = null;
  var _markers = [];

  /* ── helpers ── */
  function esc(s) {
    if (s == null) return '';
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }
  function el(id) { return document.getElementById(id); }

  /* ── priority badge ── */
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

  /* ── icon builders (same style as plan_map) ── */
  function makeBaseIcon(label, fill) {
    var color = fill || '#1d4ed8';
    var txt = esc(label || 'B');
    var svg = '<svg xmlns="http://www.w3.org/2000/svg" width="36" height="46" viewBox="0 0 36 46">' +
      '<filter id="expSh"><feDropShadow dx="0" dy="1" stdDeviation="2" flood-color="rgba(0,0,0,.4)"/></filter>' +
      '<g filter="url(#expSh)">' +
      '<path d="M18 0C10 0 4 6 4 14c0 10 14 32 14 32s14-22 14-32C32 6 26 0 18 0z" fill="' + color + '" stroke="#fff" stroke-width="2.5"/>' +
      '<text x="18" y="19" text-anchor="middle" fill="#fff" font-size="12" font-weight="800" dominant-baseline="middle">' + txt + '</text>' +
      '</g></svg>';
    return L.divIcon({
      className: 'atp-plan-pin',
      html: svg,
      iconSize: [36, 46],
      iconAnchor: [18, 46],
      popupAnchor: [0, -44]
    });
  }

  function makeStopIcon(orderNo) {
    var n = esc(orderNo != null ? orderNo : '?');
    var svg = '<svg xmlns="http://www.w3.org/2000/svg" width="34" height="44" viewBox="0 0 34 44">' +
      '<filter id="expSh2"><feDropShadow dx="0" dy="1" stdDeviation="2" flood-color="rgba(0,0,0,.35)"/></filter>' +
      '<g filter="url(#expSh2)">' +
      '<path d="M17 0C9.3 0 3 6.3 3 14c0 9.5 14 30 14 30S31 23.5 31 14C31 6.3 24.7 0 17 0z" fill="#d97706" stroke="#fff" stroke-width="2.5"/>' +
      '<text x="17" y="15" text-anchor="middle" fill="#fff" font-size="12" font-weight="800" dominant-baseline="middle">' + n + '</text>' +
      '</g></svg>';
    return L.divIcon({
      className: 'atp-plan-pin',
      html: svg,
      iconSize: [34, 44],
      iconAnchor: [17, 44],
      popupAnchor: [0, -42]
    });
  }

  /* ── destroy map ── */
  function destroyMap() {
    if (_map) {
      _map.remove();
      _map = null;
    }
    _currentLayer = null;
    _currentHalo = null;
    _suggestedLayer = null;
    _suggestedHalo = null;
    _markers = [];
    var mapEl = document.getElementById('atpExplainerMap');
    if (mapEl) {
      if (mapEl._leaflet_id) delete mapEl._leaflet_id;
      mapEl.innerHTML = '';
    }
  }

  /* ── draw map inside modal ── */
  function drawMap(route, planMapPayload) {
    destroyMap();
    var mapEl = document.getElementById('atpExplainerMap');
    if (!mapEl || typeof L === 'undefined') return;

    _map = L.map(mapEl, {
      zoomControl: true,
      attributionControl: false,
      preferCanvas: false
    }).setView([41.0, 29.0], 12);

    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19
    }).addTo(_map);

    var bounds = [];

    /* base start marker */
    var base = planMapPayload && planMapPayload.base;
    if (base && base.has_coordinates && base.latitude != null && base.longitude != null) {
      var bLat = parseFloat(base.latitude);
      var bLng = parseFloat(base.longitude);
      var startMk = L.marker([bLat, bLng], { icon: makeBaseIcon('B', '#1d4ed8'), zIndexOffset: 1000 });
      startMk.bindPopup('<strong>Başlangıç</strong><br>' + esc(base.base_name || '—'));
      startMk.addTo(_map);
      _markers.push(startMk);
      bounds.push([bLat, bLng]);

      /* base end marker (slight offset so it doesn't sit on start) */
      var endMk = L.marker([bLat + 0.00015, bLng + 0.00015], { icon: makeBaseIcon('\u21A9', '#0d6b60'), zIndexOffset: 950 });
      endMk.bindPopup('<strong>Bitiş: Fabrika Dönüş</strong><br>' + esc(base.base_name || '—'));
      endMk.addTo(_map);
      _markers.push(endMk);
    }

    /* stop markers from current plan payload */
    var stops = (planMapPayload && planMapPayload.stops) || [];
    stops.forEach(function (stop) {
      if (!stop.has_coordinates || stop.latitude == null || stop.longitude == null) return;
      var lat = parseFloat(stop.latitude);
      var lng = parseFloat(stop.longitude);
      var mk = L.marker([lat, lng], {
        icon: makeStopIcon(stop.order_no),
        zIndexOffset: 800 + (stop.order_no || 0)
      });
      mk.bindPopup(
        '<strong>' + esc(stop.order_no) + ' · ' + esc(stop.company_name) + '</strong>' +
        '<br>' + esc(stop.job_title || '—')
      );
      mk.addTo(_map);
      _markers.push(mk);
      bounds.push([lat, lng]);
    });

    /* current route polyline */
    var curGeom = (route && route.current && route.current.geometry) || [];
    if (curGeom.length >= 2) {
      var lls = curGeom.map(function (p) { return [p[0], p[1]]; });
      _currentHalo = L.polyline(lls, { color: '#fff', weight: 11, opacity: 0.5, interactive: false }).addTo(_map);
      _currentLayer = L.polyline(lls, { color: '#1d4ed8', weight: 7, opacity: 0.96, lineJoin: 'round', lineCap: 'round' }).addTo(_map);
      if (_currentLayer.bringToFront) _currentLayer.bringToFront();
      lls.forEach(function (p) { bounds.push(p); });
    }

    /* suggested route polyline (only if different) */
    var orderSame = route && route.order_same;
    var sugGeom = (route && route.suggested && route.suggested.geometry) || [];
    var sugLegend = el('atpExplainerLegendSug');
    if (!orderSame && sugGeom.length >= 2) {
      var sLls = sugGeom.map(function (p) { return [p[0], p[1]]; });
      _suggestedHalo = L.polyline(sLls, { color: '#fff', weight: 9, opacity: 0.4, interactive: false }).addTo(_map);
      _suggestedLayer = L.polyline(sLls, {
        color: '#16a34a', weight: 5, opacity: 0.88,
        dashArray: '10 6', lineJoin: 'round', lineCap: 'round'
      }).addTo(_map);
      if (_suggestedLayer.bringToFront) _suggestedLayer.bringToFront();
      if (sugLegend) sugLegend.style.display = '';
    } else {
      if (sugLegend) sugLegend.style.display = 'none';
    }

    /* fitBounds */
    if (bounds.length >= 2) {
      var boundsObj = L.latLngBounds(bounds);
      var span = Math.max(
        Math.abs(boundsObj.getNorth() - boundsObj.getSouth()),
        Math.abs(boundsObj.getEast() - boundsObj.getWest())
      );
      var pad = span < 0.01 ? 0.3 : 0.14;
      _map.fitBounds(boundsObj.pad(pad), { animate: false, maxZoom: 15, minZoom: 10 });
    } else if (bounds.length === 1) {
      _map.setView(bounds[0], 14, { animate: false });
    }

    setTimeout(function () { if (_map) _map.invalidateSize({ animate: false }); }, 120);
  }

  /* ── build order list HTML (with priority badges) ── */
  function buildOrderListHtml(stopList, base) {
    var baseName = (base && (base.base_name || base.base_address)) || 'Fabrika';
    var html = '<div class="atp-exp-row base">' +
      '<span style="font-size:18px;line-height:1">&#x1F3ED;</span>' +
      '<span class="atp-exp-name">Başlangıç: ' + esc(baseName) + '</span></div>';
    stopList.forEach(function (s) {
      var lockBadge = s.is_locked
        ? '<span class="atp-exp-lock" title="Kilitli">&#x1F512;</span>'
        : '';
      html += '<div class="atp-exp-row">' +
        '<span class="atp-exp-num">' + esc(s.order_no != null ? s.order_no : '—') + '</span>' +
        '<span class="atp-exp-name">' + esc(s.company_name || '—') + '</span>' +
        priBadge(s.priority || 'NORMAL') +
        lockBadge +
        '</div>';
    });
    html += '<div class="atp-exp-row base">' +
      '<span style="font-size:18px;line-height:1">&#x1F3ED;</span>' +
      '<span class="atp-exp-name">Bitiş: Fabrika Dönüş</span></div>';
    return html;
  }

  /* ── gain metric color class ── */
  function gainClass(route) {
    if (route.gain_negative) return 'gain-neg';
    if (route.gain_zero) return 'gain-zero';
    return 'gain';
  }

  /* ── populate modal content ── */
  function populateModal(route, planMapPayload) {
    if (!route) return;

    var orderSame = route.order_same;
    var base = planMapPayload && planMapPayload.base;

    /* Decision reason box */
    var reasonEl = el('atpExplainerDecisionReason');
    if (reasonEl) {
      reasonEl.textContent = route.decision_reason || '';
      var cls = 'atp-explainer-reason';
      if (orderSame || route.gain_zero) cls += ' optimal';
      else if (route.gain_negative && !route.has_priority_override) cls += ' warn';
      else if (route.gain_negative && route.has_priority_override) cls += ' priority-override';
      reasonEl.className = cls;
    }

    /* Priority banner */
    var bannerEl = el('atpExplainerPriorityBanner');
    if (bannerEl) {
      var pb = route.priority_banner || '';
      if (pb) {
        bannerEl.textContent = pb;
        bannerEl.style.display = '';
      } else {
        bannerEl.style.display = 'none';
      }
    }

    /* Current order */
    var curOrderEl = el('atpExplainerCurrentOrder');
    if (curOrderEl) {
      curOrderEl.innerHTML = buildOrderListHtml(route.current_stop_list || [], base);
    }

    /* Suggested order (hide section if same) */
    var sugSection = el('atpExplainerSugSection');
    var sugOrderEl = el('atpExplainerSugOrder');
    if (orderSame) {
      if (sugSection) sugSection.style.display = 'none';
    } else {
      if (sugSection) sugSection.style.display = '';
      if (sugOrderEl) {
        sugOrderEl.innerHTML = buildOrderListHtml(route.suggested_stop_list || [], base);
      }
    }

    /* Metrics */
    var metricsEl = el('atpExplainerMetrics');
    if (metricsEl) {
      var cur = route.current || {};
      var sug = route.suggested || {};
      var gain = route.gain || {};
      var gCls = 'atp-exp-metric ' + gainClass(route);
      var gainKm = gain.km;
      var gainTxt = (gainKm != null && gainKm !== '—') ? gainKm + ' km' : '—';
      metricsEl.innerHTML =
        '<div class="atp-exp-metric">' +
          '<div class="atp-exp-metric-label">Mevcut</div>' +
          '<div class="atp-exp-metric-val">' + esc(cur.km != null ? cur.km + ' km' : '—') + '</div>' +
          '<div class="atp-exp-metric-sub">' + esc(cur.duration_label || '—') + '</div></div>' +
        '<div class="atp-exp-metric">' +
          '<div class="atp-exp-metric-label">Önerilen</div>' +
          '<div class="atp-exp-metric-val">' + esc(sug.km != null ? sug.km + ' km' : '—') + '</div>' +
          '<div class="atp-exp-metric-sub">' + esc(sug.duration_label || '—') + '</div></div>' +
        '<div class="' + gCls + '">' +
          '<div class="atp-exp-metric-label">Kazanç</div>' +
          '<div class="atp-exp-metric-val">' + esc(gainTxt) + '</div>' +
          '<div class="atp-exp-metric-sub">' + esc(gain.duration_label || '—') + '</div></div>';
    }

    /* Apply disabled reason */
    var applyReasonEl = el('atpExplainerApplyReason');
    if (applyReasonEl) {
      var lbl = route.apply_disabled_reason_label || '';
      if (lbl) {
        applyReasonEl.textContent = '\uD83D\uDCCB ' + lbl;
        applyReasonEl.style.display = '';
      } else {
        applyReasonEl.style.display = 'none';
      }
    }

    /* Constraint labels */
    var constraintsEl = el('atpExplainerConstraints');
    if (constraintsEl) {
      var labels = route.constraint_labels || [];
      if (labels.length) {
        var linesHtml = labels.map(function (l) { return '<li>' + esc(l) + '</li>'; }).join('');
        constraintsEl.innerHTML = '\uD83D\uDD12 <strong>Kısıtlar:</strong><ul style="margin:4px 0 0 12px;padding:0">' + linesHtml + '</ul>';
        constraintsEl.style.display = '';
      } else {
        constraintsEl.style.display = 'none';
      }
    }

    /* Draw map after DOM settled */
    requestAnimationFrame(function () {
      drawMap(route, planMapPayload);
    });
  }

  /* ── open / close ── */
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

  /* ── wire close buttons ── */
  function bindClose() {
    ['atpRouteExplainerClose', 'atpRouteExplainerDismiss'].forEach(function (id) {
      var btn = el(id);
      if (btn) btn.addEventListener('click', closeModal);
    });
    var backdrop = el('atpRouteExplainerBackdrop');
    if (backdrop) {
      backdrop.addEventListener('click', function (e) {
        if (e.target === backdrop) closeModal();
      });
    }
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && el('atpRouteExplainerBackdrop') &&
          el('atpRouteExplainerBackdrop').classList.contains('open')) {
        closeModal();
      }
    });
  }

  /* ── wire explainer button from route.js hook ── */
  function bindExplainerButton(getLastRoute, getPlanMapPayload) {
    var btn = el('atpBtnRouteExplainer');
    if (!btn) return;
    btn.addEventListener('click', function () {
      var route = typeof getLastRoute === 'function' ? getLastRoute() : null;
      var payload = typeof getPlanMapPayload === 'function' ? getPlanMapPayload() : null;
      openModal(route, payload);
    });
  }

  /* ── update explainer button enabled state ── */
  function updateExplainerButton(route) {
    var btn = el('atpBtnRouteExplainer');
    if (!btn) return;
    btn.disabled = !route || !route.current || !route.current.geometry || !route.current.geometry.length;
  }

  bindClose();

  global.AtpRouteExplainer = {
    openModal: openModal,
    closeModal: closeModal,
    bindExplainerButton: bindExplainerButton,
    updateExplainerButton: updateExplainerButton
  };

})(window);
