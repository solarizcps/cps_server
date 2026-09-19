(function (global) {
  'use strict';

  var planMap = null;
  var planTileLayer = null;
  var planMarkers = [];
  var planRouteLayer = null;
  var planSuggestedLayer = null;
  var planInitCount = 0;
  var lastPlanPayload = null;

  global.__atpPlanMapInits = 0;

  function esc(s) {
    if (s == null) return '';
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function isPlanMapVisible() {
    var box = document.getElementById('atp-plan-map-container');
    if (!box) return false;
    var st = window.getComputedStyle(box);
    return st.display !== 'none' && st.visibility !== 'hidden' && box.offsetWidth > 0 && box.offsetHeight > 0;
  }

  function baseIcon() {
    var svg = '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="40" viewBox="0 0 32 40">' +
      '<path d="M16 0C9 0 4 5 4 12c0 9 12 28 12 28s12-19 12-28C28 5 23 0 16 0z" fill="#1d4ed8" stroke="#fff" stroke-width="2"/>' +
      '<text x="16" y="16" text-anchor="middle" fill="#fff" font-size="10" font-weight="700">B</text></svg>';
    return L.divIcon({
      className: 'atp-plan-pin atp-plan-pin-base',
      html: svg,
      iconSize: [32, 40],
      iconAnchor: [16, 40],
      popupAnchor: [0, -38]
    });
  }

  function stopFill(stop) {
    var st = ((stop && stop.status) || '').toUpperCase();
    if (st === 'TAMAMLANDI') return '#16a34a';
    if (st === 'BASLADI') return '#2563eb';
    var pri = ((stop && stop.priority) || '').toUpperCase();
    if (pri === 'ACIL') return '#dc2626';
    return '#c8922a';
  }

  function stopIcon(orderNo, stop) {
    var n = esc(stop && (stop.display_order_no || stop.order_no) || orderNo);
    var fill = stopFill(stop);
    var acil = stop && ((stop.priority || '').toUpperCase() === 'ACIL')
      ? '<circle cx="24" cy="6" r="5" fill="#dc2626" stroke="#fff" stroke-width="1"/>' : '';
    var svg = '<svg xmlns="http://www.w3.org/2000/svg" width="30" height="38" viewBox="0 0 30 38">' +
      acil +
      '<circle cx="15" cy="15" r="13" fill="' + fill + '" stroke="#fff" stroke-width="2"/>' +
      '<text x="15" y="19" text-anchor="middle" fill="#fff" font-size="11" font-weight="700">' + n + '</text>' +
      '<path d="M15 28 L10 38 L20 38 Z" fill="' + fill + '" stroke="#fff" stroke-width="1"/></svg>';
    return L.divIcon({
      className: 'atp-plan-pin atp-plan-pin-stop',
      html: svg,
      iconSize: [30, 38],
      iconAnchor: [15, 38],
      popupAnchor: [0, -36]
    });
  }

  function endIcon() {
    var svg = '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="40" viewBox="0 0 32 40">' +
      '<path d="M16 0C9 0 4 5 4 12c0 9 12 28 12 28s12-19 12-28C28 5 23 0 16 0z" fill="#1d4ed8" stroke="#fff" stroke-width="2"/>' +
      '<text x="16" y="17" text-anchor="middle" fill="#fff" font-size="10" font-weight="700">↩</text></svg>';
    return L.divIcon({
      className: 'atp-plan-pin atp-plan-pin-base',
      html: svg,
      iconSize: [32, 40],
      iconAnchor: [16, 40],
      popupAnchor: [0, -38]
    });
  }

  function basePopupHtml(base) {
    return '<div class="atp-popup atp-plan-popup">' +
      '<strong>Başlangıç</strong>' +
      '<div>' + esc(base.base_name || '—') + '</div>' +
      '<div>' + esc(base.base_address || '—') + '</div>' +
      '</div>';
  }

  function safeMapsLink(lat, lng) {
    if (lat == null || lng == null) return '';
    var url = 'https://www.google.com/maps?q=' + encodeURIComponent(String(lat) + ',' + String(lng));
    return '<a href="' + url + '" target="_blank" rel="noopener noreferrer">Haritada Aç</a>';
  }

  function stopPopupHtml(stop) {
    var acilHtml = (stop.priority || '').toString().toUpperCase() === 'ACIL'
      ? '<div><span class="badge badge-red atp-acil-badge">ACİL</span></div>'
      : '';
    var mapLink = stop.has_coordinates ? safeMapsLink(stop.latitude, stop.longitude) : '';
    return '<div class="atp-popup atp-plan-popup">' +
      '<strong>' + esc(stop.display_order_no || stop.order_no) + ' · ' + esc(stop.company_name) + '</strong>' +
      acilHtml +
      '<div>İş: ' + esc(stop.job_title || '—') + '</div>' +
      '<div>Saat: ' + esc(stop.planned_time || '—') + '</div>' +
      '<div>Adres: ' + esc(stop.address_text || '—') + '</div>' +
      '<div>Durum: ' + esc(stop.status_label || stop.status || '—') + '</div>' +
      (mapLink ? '<div style="margin-top:6px">' + mapLink + '</div>' : '') +
      '</div>';
  }

  function updateMissingList(stops) {
    var el = document.getElementById('atpPlanMapMissingList');
    if (!el) return;
    var missing = (stops || []).filter(function (s) { return !s.has_coordinates; });
    if (!missing.length) {
      el.style.display = 'none';
      el.innerHTML = '';
      return;
    }
    el.style.display = '';
    var items = missing.map(function (s) {
      return '<li>' + esc(s.display_order_no || s.order_no) + '. ' + esc(s.company_name) + '</li>';
    }).join('');
    el.innerHTML = '<strong>Konumu eksik duraklar (' + missing.length + ')</strong><ul style="margin:6px 0 0;padding-left:18px">' + items + '</ul>';
  }

  function clearPlanMarkers() {
    if (!planMap) return;
    planMarkers.forEach(function (mk) { planMap.removeLayer(mk); });
    planMarkers = [];
  }

  function clearRouteLayers() {
    if (!planMap) return;
    if (planRouteLayer) {
      planMap.removeLayer(planRouteLayer);
      planRouteLayer = null;
    }
    if (planSuggestedLayer) {
      planMap.removeLayer(planSuggestedLayer);
      planSuggestedLayer = null;
    }
  }

  function setCurrentRouteGeometry(geometry) {
    if (!ensurePlanMap()) return;
    if (planRouteLayer) {
      if (planMap.hasLayer(planRouteLayer)) planMap.removeLayer(planRouteLayer);
      planRouteLayer = null;
    }
    if (!geometry || !geometry.length) return;
    var latlngs = geometry.map(function (p) { return [p[0], p[1]]; });
    planRouteLayer = L.polyline(latlngs, {
      color: '#1d4ed8',
      weight: 6,
      opacity: 0.92,
      lineJoin: 'round',
      lineCap: 'round'
    }).addTo(planMap);
    if (planRouteLayer.bringToFront) planRouteLayer.bringToFront();
    fitMapToContent(latlngs);
  }

  function setSuggestedRouteGeometry(geometry) {
    if (!ensurePlanMap()) return;
    if (planSuggestedLayer) {
      planMap.removeLayer(planSuggestedLayer);
      planSuggestedLayer = null;
    }
    if (!geometry || !geometry.length) return;
    var latlngs = geometry.map(function (p) { return [p[0], p[1]]; });
    planSuggestedLayer = L.polyline(latlngs, {
      color: '#16a34a',
      weight: 4,
      opacity: 0.75,
      dashArray: '8 6',
      lineJoin: 'round'
    }).addTo(planMap);
  }

  function clearSuggestedRouteGeometry() {
    if (!planMap || !planSuggestedLayer) return;
    planMap.removeLayer(planSuggestedLayer);
    planSuggestedLayer = null;
  }

  function syncPlanMapSize(cb) {
    if (!planMap) return;
    planMap.invalidateSize({ animate: false });
    if (typeof cb === 'function') {
      requestAnimationFrame(function () {
        planMap.invalidateSize({ animate: false });
        cb();
      });
    }
  }

  function fitMapToContent(extraLatLngs) {
    if (!planMap) return;
    var bounds = [];
    planMarkers.forEach(function (mk) { bounds.push(mk.getLatLng()); });
    (extraLatLngs || []).forEach(function (p) {
      if (p && p.length >= 2) bounds.push(L.latLng(p[0], p[1]));
    });
    if (!bounds.length) return;
    if (bounds.length === 1) {
      planMap.setView(bounds[0], 13, { animate: false });
      return;
    }
    planMap.fitBounds(L.latLngBounds(bounds).pad(0.12), { animate: false, maxZoom: 13 });
  }

  function ensurePlanMap() {
    if (planMap) return true;
    if (typeof L === 'undefined') return false;
    if (!isPlanMapVisible()) return false;
    var el = document.getElementById('atpPlanLeafletMap');
    if (!el) return false;
    if (el._leaflet_id && !planMap) {
      delete el._leaflet_id;
      el.innerHTML = '';
    }
    if (el._leaflet_id) return false;

    planMap = L.map(el, {
      zoomControl: true,
      attributionControl: true,
      preferCanvas: false
    }).setView([41.02, 29.05], 11);

    planTileLayer = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap contributors'
    });
    planTileLayer.addTo(planMap);

    planInitCount += 1;
    global.__atpPlanMapInits = planInitCount;

    planMap.whenReady(function () {
      syncPlanMapSize(function () {
        if (lastPlanPayload) renderPlanMap(lastPlanPayload);
      });
    });
    return true;
  }

  function updateCompleteness(completeness, base) {
    var el = document.getElementById('atpPlanMapCompleteness');
    if (!el || !completeness) return;
    var parts = [];
    if (completeness.total_stops > 0) {
      parts.push('Durak: ' + completeness.total_stops);
      parts.push('Konum Hazır: ' + completeness.ready);
      if (completeness.missing > 0) {
        parts.push('Konum Eksik: ' + completeness.missing);
      }
    }
    var html = parts.length ? parts.join(' · ') : '';
    if (!base || !base.has_coordinates) {
      html += (html ? '<br>' : '') +
        '<span class="atp-plan-base-warn">Başlangıç noktası tanımlanmamış.</span> ' +
        '<button type="button" class="atp-link-btn" id="atpBtnBaseFromCompleteness">Başlangıç Noktası Ekle</button>';
    }
    el.innerHTML = html;
    var btn = document.getElementById('atpBtnBaseFromCompleteness');
    if (btn) {
      btn.onclick = function () {
        if (global.AtpLocationModals && global.AtpLocationModals.openBaseModal) {
          global.AtpLocationModals.openBaseModal(base || {});
        }
      };
    }
  }

  function updateEmptyState(payload) {
    var emptyEl = document.getElementById('atpPlanMapEmpty');
    var mapEl = document.getElementById('atpPlanLeafletMap');
    if (!emptyEl) return;
    var stops = (payload && payload.stops) || [];
    var base = payload && payload.base;
    var hasMarkers = (base && base.has_coordinates) || stops.some(function (s) { return s.has_coordinates; });
    if (!stops.length && !(base && base.has_coordinates)) {
      emptyEl.style.display = '';
      emptyEl.querySelector('.atp-plan-empty-title').textContent = 'Plan item yok.';
      emptyEl.querySelector('.atp-plan-empty-sub').textContent = 'Seçili araç ve tarih için günlük plan boş.';
      if (mapEl) mapEl.style.display = 'none';
      return;
    }
    if (!hasMarkers) {
      emptyEl.style.display = '';
      emptyEl.querySelector('.atp-plan-empty-title').textContent = 'Haritada gösterilecek konum yok.';
      emptyEl.querySelector('.atp-plan-empty-sub').textContent = 'Duraklara veya başlangıç noktasına koordinat ekleyin.';
      if (mapEl) mapEl.style.display = 'none';
      return;
    }
    emptyEl.style.display = 'none';
    if (mapEl) mapEl.style.display = 'block';
  }

  function renderPlanMap(payload) {
    lastPlanPayload = payload || lastPlanPayload;
    if (!lastPlanPayload) return;
    updateEmptyState(lastPlanPayload);
    updateCompleteness(lastPlanPayload.completeness, lastPlanPayload.base);
    if (!ensurePlanMap()) return;
    clearPlanMarkers();

    var base = lastPlanPayload.base;
    if (base && base.has_coordinates && base.latitude != null && base.longitude != null) {
      var bmk = L.marker([base.latitude, base.longitude], { icon: baseIcon(), zIndexOffset: 1000 });
      bmk.bindPopup(basePopupHtml(base));
      bmk.addTo(planMap);
      planMarkers.push(bmk);
    }

    (lastPlanPayload.stops || []).forEach(function (stop) {
      if (!stop.has_coordinates || stop.latitude == null || stop.longitude == null) return;
      var mk = L.marker([stop.latitude, stop.longitude], {
        icon: stopIcon(stop.order_no, stop),
        zIndexOffset: 800 + (stop.order_no || 0)
      });
      mk._atpPlanItemId = stop.plan_item_id;
      mk.bindPopup(stopPopupHtml(stop));
      mk.addTo(planMap);
      planMarkers.push(mk);
    });

    if (base && base.has_coordinates && base.latitude != null && base.longitude != null) {
      var ep = [parseFloat(base.latitude) + 0.00012, parseFloat(base.longitude) + 0.00012];
      var emk = L.marker(ep, { icon: endIcon(), zIndexOffset: 950 });
      emk.bindPopup('<strong>Dönüş</strong><div>' + esc(base.base_name || 'Fabrika') + '</div>');
      emk.addTo(planMap);
      planMarkers.push(emk);
    }

    updateMissingList(lastPlanPayload.stops || []);

    var lastR = global.AtpRoute && global.AtpRoute.getLastRoute && global.AtpRoute.getLastRoute();
    var routeGeom = (lastR && lastR.current && lastR.current.geometry) || [];
    if (routeGeom.length) {
      if (!planRouteLayer || !planMap.hasLayer(planRouteLayer)) setCurrentRouteGeometry(routeGeom);
      else fitMapToContent(routeGeom);
    } else {
      fitMapToContent([]);
    }
  }

  function syncRouteFromLast() {
    var route = global.AtpRoute && global.AtpRoute.getLastRoute && global.AtpRoute.getLastRoute();
    if (route && route.current && route.current.geometry && route.current.geometry.length) {
      setCurrentRouteGeometry(route.current.geometry);
    }
  }

  function onPlanTabShown() {
    if (!isPlanMapVisible()) return;
    if (!planMap) ensurePlanMap();
    syncPlanMapSize(function () {
      if (lastPlanPayload) renderPlanMap(lastPlanPayload);
      syncRouteFromLast();
    });
  }

  var mapElHome = null;
  var fsExpandTrigger = null;
  var modalPortaled = false;

  function ensurePlanMapModalPortal() {
    var modal = document.getElementById('atpPlanMapFullscreenModal');
    if (!modal || modalPortaled) return;
    if (modal.parentElement !== document.body) {
      document.body.appendChild(modal);
    }
    modalPortaled = true;
  }

  function syncModalStopList() {
    var src = document.getElementById('atpStopListWrap');
    var dest = document.getElementById('atpPlanMapModalStopsList');
    if (!dest) return;
    if (src && src.innerHTML) {
      dest.innerHTML = src.innerHTML;
      return;
    }
    if (!lastPlanPayload || !lastPlanPayload.stops) {
      dest.innerHTML = '<div class="atp-v2-empty">Plan boş — aktif durak yok.</div>';
      return;
    }
    var base = (lastPlanPayload.base && lastPlanPayload.base.base_name) || 'Fabrika';
    var html = '<div class="factory-row"><span class="fl">🏭</span><span class="factory-label">Başlangıç: ' + esc(base) + '</span></div><div class="stop-list">';
    (lastPlanPayload.stops || []).forEach(function (stop) {
      var n = esc(stop.display_order_no || stop.order_no || '?');
      var st = (stop.status || '').toUpperCase();
      var done = st === 'TAMAMLANDI';
      var active = st === 'BASLADI';
      var acil = ((stop.priority || '').toUpperCase() === 'ACIL')
        ? ' <span class="badge badge-red atp-acil-badge">ACİL</span>' : '';
      var job = String(stop.job_title || '').trim();
      var co = String(stop.company_name || '').trim();
      var primary = esc(job || co || '—');
      var same = job && co && job.toLowerCase() === co.toLowerCase();
      var stack = '<div class="atp-task-co-block"><div class="atp-task-line1"><span class="atp-task-title">' + primary + '</span>' + acil + '</div>';
      if (co && !same) {
        stack += '<div class="atp-task-line2"><span class="atp-task-firma-ico">🏢</span><span class="atp-task-firma">Firma: ' + esc(co) + '</span></div>';
      }
      stack += '</div>';
      var numCls = 'stop-num' + (done ? ' done' : (active ? ' active' : ''));
      var cls = 'stop-item' + (done ? ' done' : (active ? ' active' : ''));
      html += '<div class="' + cls + '"><span class="' + numCls + '">' + n + '</span>' +
        '<div class="stop-main">' + stack + '</div>' +
        '<span class="badge badge-gray">' + esc(stop.status_label || stop.status || '—') + '</span></div>';
    });
    html += '</div><div class="factory-row" style="margin-top:4px"><span class="fl">🏭</span><span class="factory-label">Bitiş: Fabrika Dönüş — ' + esc(base) + '</span></div>';
    dest.innerHTML = html;
  }

  function openPlanMapFullscreen(ev) {
    if (ev) { ev.preventDefault(); ev.stopPropagation(); }
    ensurePlanMapModalPortal();
    var modal = document.getElementById('atpPlanMapFullscreenModal');
    var mapEl = document.getElementById('atpPlanLeafletMap');
    var fsHost = document.getElementById('atpPlanMapFullscreenLeaflet');
    var btn = document.getElementById('atpBtnPlanMapExpand');
    if (!modal || !mapEl || !fsHost || !lastPlanPayload) return;
    if (!ensurePlanMap()) return;
    fsExpandTrigger = btn || document.activeElement;
    syncModalStopList();
    if (!mapElHome) mapElHome = mapEl.parentElement;
    fsHost.appendChild(mapEl);
    modal.classList.add('is-open');
    modal.setAttribute('aria-hidden', 'false');
    document.body.classList.add('atp-plan-map-modal-open');
    requestAnimationFrame(function () {
      syncPlanMapSize(function () {
        requestAnimationFrame(function () {
          if (planMap) planMap.invalidateSize({ animate: false });
          fitMapToContent([]);
          syncRouteFromLast();
        });
      });
    });
    var closeBtn = document.getElementById('atpPlanMapFullscreenClose');
    if (closeBtn) closeBtn.focus();
  }

  function closePlanMapFullscreen() {
    var modal = document.getElementById('atpPlanMapFullscreenModal');
    var mapEl = document.getElementById('atpPlanLeafletMap');
    if (!modal) return;
    if (mapEl && mapElHome) mapElHome.appendChild(mapEl);
    modal.classList.remove('is-open');
    modal.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('atp-plan-map-modal-open');
    syncPlanMapSize(function () {
      fitMapToContent([]);
      syncRouteFromLast();
    });
    if (fsExpandTrigger && fsExpandTrigger.focus) fsExpandTrigger.focus();
  }

  function bindPlanMapFullscreen() {
    var btn = document.getElementById('atpBtnPlanMapExpand');
    if (btn) {
      btn.setAttribute('type', 'button');
      btn.addEventListener('click', openPlanMapFullscreen);
    }
    var closeBtn = document.getElementById('atpPlanMapFullscreenClose');
    var doneBtn = document.getElementById('atpPlanMapFullscreenDone');
    if (closeBtn) closeBtn.addEventListener('click', closePlanMapFullscreen);
    if (doneBtn) doneBtn.addEventListener('click', closePlanMapFullscreen);
    var modal = document.getElementById('atpPlanMapFullscreenModal');
    ensurePlanMapModalPortal();
    if (modal) {
      modal.addEventListener('click', function (ev) {
        if (ev.target === modal || ev.target.classList.contains('atp-plan-map-modal-backdrop')) {
          ev.stopPropagation();
        }
      });
    }
    document.addEventListener('keydown', function (ev) {
      if (ev.key === 'Escape') {
        var m = document.getElementById('atpPlanMapFullscreenModal');
        if (m && m.classList.contains('is-open')) {
          ev.preventDefault();
          closePlanMapFullscreen();
        }
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bindPlanMapFullscreen);
  } else {
    bindPlanMapFullscreen();
  }

  global.AtpPlanMap = {
    ensurePlanMap: ensurePlanMap,
    onPlanTabShown: onPlanTabShown,
    renderPlanMap: renderPlanMap,
    showRouteFallback: function (msg) {
      var el = document.getElementById('atpPlanMapRouteFallback');
      if (!el) return;
      if (msg) { el.style.display = ''; el.textContent = msg; }
      else { el.style.display = 'none'; el.textContent = ''; }
    },
    setCurrentRouteGeometry: setCurrentRouteGeometry,
    setSuggestedRouteGeometry: setSuggestedRouteGeometry,
    clearSuggestedRouteGeometry: clearSuggestedRouteGeometry,
    clearRouteLayers: clearRouteLayers,
    mapInstanceCount: function () { return planInitCount; },
    hasInstance: function () { return planMap !== null; },
    markerCount: function () { return planMarkers.length; },
    routeLayerCount: function () {
      var n = 0;
      if (planRouteLayer) n += 1;
      if (planSuggestedLayer) n += 1;
      return n;
    },
    hasCurrentRoute: function () { return planRouteLayer !== null; },
    hasSuggestedRoute: function () { return planSuggestedLayer !== null; },
    getMarkerRegistry: function () {
      var base = lastPlanPayload && lastPlanPayload.base;
      var stops = (lastPlanPayload && lastPlanPayload.stops) || [];
      var out = [];
      if (base && base.has_coordinates) {
        out.push({ kind: 'BASE', lat: base.latitude, lng: base.longitude, onMap: planMarkers.some(function (m) {
          var ll = m.getLatLng(); return base.latitude === ll.lat && base.longitude === ll.lng;
        }) });
      }
      stops.forEach(function (s) {
        if (!s.has_coordinates) return;
        out.push({ kind: 'stop', order_no: s.order_no, lat: s.latitude, lng: s.longitude,
          onMap: planMarkers.some(function (m) {
            var ll = m.getLatLng(); return s.latitude === ll.lat && s.longitude === ll.lng;
          }) });
      });
      return out;
    },
    getRouteDomPathCount: function () {
      var pane = document.querySelector('#atpPlanLeafletMap .leaflet-overlay-pane');
      return pane ? pane.querySelectorAll('path').length : 0;
    },
    getCurrentRoutePointCount: function () {
      return planRouteLayer && planRouteLayer.getLatLngs ? planRouteLayer.getLatLngs().length : 0;
    }
  };
})(window);
