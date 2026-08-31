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

  function baseIcon(label, fill, strokeColor) {
    var txt = esc(label || 'B');
    var color = fill || '#1d4ed8';
    var stroke = strokeColor || '#fff';
    /* 36×46 — slightly larger for visibility; white drop-shadow halo */
    var svg = '<svg xmlns="http://www.w3.org/2000/svg" width="36" height="46" viewBox="0 0 36 46">' +
      '<filter id="sh"><feDropShadow dx="0" dy="1" stdDeviation="2" flood-color="rgba(0,0,0,.45)"/></filter>' +
      '<g filter="url(#sh)">' +
      '<path d="M18 0C10 0 4 6 4 14c0 10 14 32 14 32s14-22 14-32C32 6 26 0 18 0z" fill="' + color + '" stroke="' + stroke + '" stroke-width="2.5"/>' +
      '<text x="18" y="18" text-anchor="middle" fill="#fff" font-size="12" font-weight="800" dominant-baseline="middle">' + txt + '</text>' +
      '</g></svg>';
    return L.divIcon({
      className: 'atp-plan-pin atp-plan-pin-base',
      html: svg,
      iconSize: [36, 46],
      iconAnchor: [18, 46],
      popupAnchor: [0, -44]
    });
  }

  function baseStartIcon() {
    return baseIcon('B', '#1d4ed8');
  }

  function baseEndIcon() {
    return baseIcon('\u21A9', '#0d6b60');
  }

  function stopIcon(orderNo) {
    var n = esc(orderNo != null ? orderNo : '?');
    /* 34×44 amber pin with white number, drop-shadow */
    var svg = '<svg xmlns="http://www.w3.org/2000/svg" width="34" height="44" viewBox="0 0 34 44">' +
      '<filter id="sh2"><feDropShadow dx="0" dy="1" stdDeviation="2" flood-color="rgba(0,0,0,.40)"/></filter>' +
      '<g filter="url(#sh2)">' +
      '<path d="M17 0C9.3 0 3 6.3 3 14c0 9.5 14 30 14 30S31 23.5 31 14C31 6.3 24.7 0 17 0z" fill="#d97706" stroke="#fff" stroke-width="2.5"/>' +
      '<text x="17" y="15" text-anchor="middle" fill="#fff" font-size="12" font-weight="800" dominant-baseline="middle">' + n + '</text>' +
      '</g></svg>';
    return L.divIcon({
      className: 'atp-plan-pin atp-plan-pin-stop',
      html: svg,
      iconSize: [34, 44],
      iconAnchor: [17, 44],
      popupAnchor: [0, -42]
    });
  }

  function basePopupHtml(base, title) {
    return '<div class="atp-popup atp-plan-popup">' +
      '<strong>' + esc(title || 'Başlangıç') + '</strong>' +
      '<div>' + esc(base.base_name || '—') + '</div>' +
      '<div>' + esc(base.base_address || '—') + '</div>' +
      '</div>';
  }

  function stopPopupHtml(stop) {
    var pinLabel = stop.display_order_no != null && stop.display_order_no !== ''
      ? stop.display_order_no
      : stop.order_no;
    return '<div class="atp-popup atp-plan-popup">' +
      '<strong>' + esc(pinLabel) + ' · ' + esc(stop.company_name) + '</strong>' +
      '<div>İş: ' + esc(stop.job_title || '—') + '</div>' +
      '<div>Saat: ' + esc(stop.planned_time || '—') + '</div>' +
      '<div>Adres: ' + esc(stop.address_text || '—') + '</div>' +
      '<div>Konum: ' + esc(stop.location_source_label || '—') + '</div>' +
      '</div>';
  }

  function clearPlanMarkers() {
    if (!planMap) return;
    planMarkers.forEach(function (mk) { planMap.removeLayer(mk); });
    planMarkers = [];
  }

  function clearRouteLayers() {
    if (!planMap) return;
    if (planRouteLayer) {
      if (planRouteLayer._halo && planMap.hasLayer(planRouteLayer._halo)) planMap.removeLayer(planRouteLayer._halo);
      planMap.removeLayer(planRouteLayer);
      planRouteLayer = null;
    }
    if (planSuggestedLayer) {
      if (planSuggestedLayer._halo && planMap.hasLayer(planSuggestedLayer._halo)) planMap.removeLayer(planSuggestedLayer._halo);
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
    /* white halo layer underneath for contrast against map tiles */
    var halo = L.polyline(latlngs, {
      color: '#fff',
      weight: 11,
      opacity: 0.55,
      lineJoin: 'round',
      lineCap: 'round',
      interactive: false
    }).addTo(planMap);
    planRouteLayer = L.polyline(latlngs, {
      color: '#1d4ed8',
      weight: 7,
      opacity: 0.96,
      lineJoin: 'round',
      lineCap: 'round'
    }).addTo(planMap);
    planRouteLayer._halo = halo;
    if (planRouteLayer.bringToFront) planRouteLayer.bringToFront();
    fitMapToContent(latlngs);
  }

  function setSuggestedRouteGeometry(geometry) {
    if (!ensurePlanMap()) return;
    if (planSuggestedLayer) {
      if (planSuggestedLayer._halo && planMap.hasLayer(planSuggestedLayer._halo)) {
        planMap.removeLayer(planSuggestedLayer._halo);
      }
      planMap.removeLayer(planSuggestedLayer);
      planSuggestedLayer = null;
    }
    if (!geometry || !geometry.length) return;
    var latlngs = geometry.map(function (p) { return [p[0], p[1]]; });
    var sHalo = L.polyline(latlngs, {
      color: '#fff',
      weight: 9,
      opacity: 0.45,
      lineJoin: 'round',
      interactive: false
    }).addTo(planMap);
    planSuggestedLayer = L.polyline(latlngs, {
      color: '#16a34a',
      weight: 5,
      opacity: 0.88,
      dashArray: '10 6',
      lineJoin: 'round',
      lineCap: 'round'
    }).addTo(planMap);
    planSuggestedLayer._halo = sHalo;
    if (planSuggestedLayer.bringToFront) planSuggestedLayer.bringToFront();
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

  function addPlanMarker(marker, kind) {
    marker._atpKind = kind;
    marker.addTo(planMap);
    planMarkers.push(marker);
  }

  function focusCurrentRoute() {
    if (!ensurePlanMap()) return false;
    var geomLatLngs = null;
    if (planRouteLayer && planRouteLayer.getLatLngs) {
      var ll = planRouteLayer.getLatLngs();
      if (ll && ll.length) geomLatLngs = ll.map(function (p) { return [p.lat, p.lng]; });
    }
    if (!geomLatLngs || !geomLatLngs.length) {
      var lastR = global.AtpRoute && global.AtpRoute.getLastRoute && global.AtpRoute.getLastRoute();
      var g = lastR && lastR.current && lastR.current.geometry;
      if (g && g.length) {
        setCurrentRouteGeometry(g);
        return true;
      }
    } else {
      fitMapToContent(geomLatLngs);
      syncPlanMapSize();
      return true;
    }
    if (planMarkers.length) {
      fitMapToContent([]);
      syncPlanMapSize();
      return true;
    }
    return false;
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
    /* clamp padding: tight routes need less zoom-out; enforce sensible min/max */
    var boundsObj = L.latLngBounds(bounds);
    var span = Math.max(
      Math.abs(boundsObj.getNorth() - boundsObj.getSouth()),
      Math.abs(boundsObj.getEast() - boundsObj.getWest())
    );
    var pad = span < 0.01 ? 0.25 : 0.12;
    planMap.fitBounds(boundsObj.pad(pad), { animate: false, maxZoom: 15, minZoom: 10 });
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
      var bmk = L.marker([base.latitude, base.longitude], { icon: baseStartIcon(), zIndexOffset: 1000 });
      bmk.bindPopup(basePopupHtml(base, 'Başlangıç'));
      addPlanMarker(bmk, 'base_start');
      var endLat = base.latitude + 0.00012;
      var endLng = base.longitude + 0.00012;
      var endMk = L.marker([endLat, endLng], { icon: baseEndIcon(), zIndexOffset: 950 });
      endMk.bindPopup(basePopupHtml(base, 'Bitiş: Fabrika Dönüş'));
      addPlanMarker(endMk, 'base_end');
    }

    (lastPlanPayload.stops || []).forEach(function (stop) {
      if (!stop.has_coordinates || stop.latitude == null || stop.longitude == null) return;
      /* Pin label: display_order_no (1-based active sequential) with canonical order_no fallback */
      var pinLabel = stop.display_order_no != null && stop.display_order_no !== ''
        ? stop.display_order_no
        : stop.order_no;
      var mk = L.marker([stop.latitude, stop.longitude], {
        icon: stopIcon(pinLabel),
        zIndexOffset: 800 + (stop.order_no || 0)
      });
      mk.bindPopup(stopPopupHtml(stop));
      addPlanMarker(mk, 'stop');
    });

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

  global.AtpPlanMap = {
    ensurePlanMap: ensurePlanMap,
    onPlanTabShown: onPlanTabShown,
    renderPlanMap: renderPlanMap,
    setCurrentRouteGeometry: setCurrentRouteGeometry,
    setSuggestedRouteGeometry: setSuggestedRouteGeometry,
    clearSuggestedRouteGeometry: clearSuggestedRouteGeometry,
    clearRouteLayers: clearRouteLayers,
    focusCurrentRoute: focusCurrentRoute,
    mapInstanceCount: function () { return planInitCount; },
    hasInstance: function () { return planMap !== null; },
    markerCount: function () { return planMarkers.length; },
    markerBreakdown: function () {
      var out = { base_start: 0, base_end: 0, stop: 0, total: planMarkers.length };
      planMarkers.forEach(function (mk) {
        var k = mk._atpKind || 'unknown';
        if (out[k] != null) out[k] += 1;
      });
      return out;
    },
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
