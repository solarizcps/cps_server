(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  }
  root.AtpPlanMap = api.AtpPlanMap;
  root.__atpPlanMapPure = api.pure;
}(typeof globalThis !== 'undefined' ? globalThis : typeof window !== 'undefined' ? window : this, function () {
  'use strict';

  var planMap = null;
  var planTileLayer = null;
  var planMarkers = [];
  var planRouteLayer = null;
  var planSuggestedLayer = null;
  var planInitCount = 0;
  var lastPlanPayload = null;
  var routeContextKey = '';
  var routeContextSeq = 0;
  var lastDrawnCurrentSig = null;
  var lastDrawnSuggestedSig = null;

  var globalRef = typeof globalThis !== 'undefined' ? globalThis : typeof window !== 'undefined' ? window : this;
  globalRef.__atpPlanMapInits = 0;

  var EARTH_RADIUS_M = 6371000;
  var DENSE_POINT_MIN = 12;
  var MAX_SEGMENT_DENSE_M = 2500;
  var SHORT_ROUTE_MAX_M = 3000;
  var SPARSE_POINT_MAX = 8;
  var SPARSE_SEGMENT_REJECT_M = 10000;
  var SPARSE_TOTAL_REJECT_M = 15000;

  function haversineM(a, b) {
    var lat1 = Number(a[0]);
    var lng1 = Number(a[1]);
    var lat2 = Number(b[0]);
    var lng2 = Number(b[1]);
    if (!isFinite(lat1) || !isFinite(lng1) || !isFinite(lat2) || !isFinite(lng2)) return NaN;
    var rLat1 = lat1 * Math.PI / 180;
    var rLat2 = lat2 * Math.PI / 180;
    var dLat = (lat2 - lat1) * Math.PI / 180;
    var dLng = (lng2 - lng1) * Math.PI / 180;
    var h = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
      Math.cos(rLat1) * Math.cos(rLat2) * Math.sin(dLng / 2) * Math.sin(dLng / 2);
    return 2 * EARTH_RADIUS_M * Math.asin(Math.min(1, Math.sqrt(h)));
  }

  function normalizeValidLatLngs(geometry) {
    if (!Array.isArray(geometry)) return [];
    var out = [];
    for (var i = 0; i < geometry.length; i++) {
      var p = geometry[i];
      if (!Array.isArray(p) || p.length < 2) continue;
      var lat = Number(p[0]);
      var lng = Number(p[1]);
      if (!isFinite(lat) || !isFinite(lng)) continue;
      if (lat < -90 || lat > 90 || lng < -180 || lng > 180) continue;
      out.push([lat, lng]);
    }
    return out;
  }

  function geometrySignature(geometry) {
    var pts = normalizeValidLatLngs(geometry);
    if (!pts.length) return '';
    var first = pts[0];
    var last = pts[pts.length - 1];
    return pts.length + ':' + first[0] + ',' + first[1] + ':' + last[0] + ',' + last[1];
  }

  function isIdenticalRouteGeometry(a, b) {
    if (!a || !b) return false;
    return geometrySignature(a) === geometrySignature(b);
  }

  function routeGeometryMetrics(pts) {
    var totalM = 0;
    var maxM = 0;
    for (var i = 1; i < pts.length; i++) {
      var d = haversineM(pts[i - 1], pts[i]);
      if (!isFinite(d)) return null;
      totalM += d;
      if (d > maxM) maxM = d;
    }
    return { totalM: totalM, maxM: maxM, pointCount: pts.length };
  }

  function isDrawableRouteGeometry(geometry) {
    var pts = normalizeValidLatLngs(geometry);
    if (pts.length < 2) return false;
    var metrics = routeGeometryMetrics(pts);
    if (!metrics) return false;
    if (metrics.pointCount >= DENSE_POINT_MIN) return true;
    if (metrics.maxM <= MAX_SEGMENT_DENSE_M) return true;
    if (metrics.totalM <= SHORT_ROUTE_MAX_M) return true;
    if (metrics.pointCount <= SPARSE_POINT_MAX && metrics.maxM > SPARSE_SEGMENT_REJECT_M) return false;
    if (metrics.pointCount <= 6 && metrics.totalM > SPARSE_TOTAL_REJECT_M) return false;
    return metrics.pointCount >= 8;
  }

  function makeRouteContextKey(payload) {
    if (!payload) return '';
    return String(payload.vehicle_id || '') + '|' +
      String(payload.plan_date || payload.date || '') + '|' +
      String(payload.plan_id || '');
  }

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

  function removeLayerPair(layerRef) {
    if (!planMap || !layerRef) return;
    if (layerRef._halo && planMap.hasLayer(layerRef._halo)) {
      planMap.removeLayer(layerRef._halo);
    }
    if (planMap.hasLayer(layerRef)) {
      planMap.removeLayer(layerRef);
    }
    layerRef._halo = null;
  }

  function removeCurrentRouteLayer() {
    if (planRouteLayer) {
      removeLayerPair(planRouteLayer);
      planRouteLayer = null;
    }
    lastDrawnCurrentSig = null;
  }

  function removeSuggestedRouteLayer() {
    if (planSuggestedLayer) {
      removeLayerPair(planSuggestedLayer);
      planSuggestedLayer = null;
    }
    lastDrawnSuggestedSig = null;
  }

  function clearPlanMarkers() {
    if (!planMap) return;
    planMarkers.forEach(function (mk) { planMap.removeLayer(mk); });
    planMarkers = [];
  }

  function clearRouteLayers() {
    removeCurrentRouteLayer();
    removeSuggestedRouteLayer();
  }

  function setCurrentRouteGeometry(geometry, opts) {
    if (!ensurePlanMap()) return;
    opts = opts || {};
    if (opts.contextSeq != null && opts.contextSeq !== routeContextSeq) return;

    removeCurrentRouteLayer();

    if (!isDrawableRouteGeometry(geometry)) {
      fitMapToContent([]);
      return;
    }

    var sig = geometrySignature(geometry);
    var latlngs = normalizeValidLatLngs(geometry).map(function (p) { return [p[0], p[1]]; });
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
    lastDrawnCurrentSig = sig;
    if (planRouteLayer.bringToFront) planRouteLayer.bringToFront();
    fitMapToContent(latlngs);
  }

  function setSuggestedRouteGeometry(geometry, opts) {
    if (!ensurePlanMap()) return;
    opts = opts || {};
    if (opts.contextSeq != null && opts.contextSeq !== routeContextSeq) return;

    removeSuggestedRouteLayer();

    if (!isDrawableRouteGeometry(geometry)) return;

    var sig = geometrySignature(geometry);
    var curSig = opts.currentSignature != null ? opts.currentSignature : lastDrawnCurrentSig;
    if (curSig && sig === curSig) {
      lastDrawnSuggestedSig = sig;
      return;
    }
    var latlngs = normalizeValidLatLngs(geometry).map(function (p) { return [p[0], p[1]]; });
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
    lastDrawnSuggestedSig = sig;
    if (planSuggestedLayer.bringToFront) planSuggestedLayer.bringToFront();
  }

  function clearSuggestedRouteGeometry() {
    removeSuggestedRouteLayer();
  }

  function syncRouteFromLast(expectedSeq) {
    if (expectedSeq != null && expectedSeq !== routeContextSeq) return;
    var route = globalRef.AtpRoute && globalRef.AtpRoute.getLastRoute && globalRef.AtpRoute.getLastRoute();
    var geom = route && route.current && route.current.geometry;
    if (isDrawableRouteGeometry(geom)) {
      var sig = geometrySignature(geom);
      if (sig !== lastDrawnCurrentSig) {
        setCurrentRouteGeometry(geom, { contextSeq: expectedSeq != null ? expectedSeq : routeContextSeq });
      }
    } else {
      removeCurrentRouteLayer();
      fitMapToContent([]);
    }

    var curGeom = route && route.current && route.current.geometry;
    var cSig = isDrawableRouteGeometry(curGeom) ? geometrySignature(curGeom) : lastDrawnCurrentSig;
    var suggested = route && route.suggested && route.suggested.geometry;
    if (isDrawableRouteGeometry(suggested)) {
      var sSig = geometrySignature(suggested);
      if (cSig && sSig === cSig) {
        removeSuggestedRouteLayer();
        lastDrawnSuggestedSig = sSig;
      } else if (sSig !== lastDrawnSuggestedSig) {
        setSuggestedRouteGeometry(suggested, {
          contextSeq: expectedSeq != null ? expectedSeq : routeContextSeq,
          currentSignature: cSig
        });
      }
    } else {
      removeSuggestedRouteLayer();
    }
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
      var lastR = globalRef.AtpRoute && globalRef.AtpRoute.getLastRoute && globalRef.AtpRoute.getLastRoute();
      var g = lastR && lastR.current && lastR.current.geometry;
      if (isDrawableRouteGeometry(g)) {
        setCurrentRouteGeometry(g, { contextSeq: routeContextSeq });
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
    if (planRouteLayer && planMap.hasLayer(planRouteLayer) && planRouteLayer.getLatLngs) {
      planRouteLayer.getLatLngs().forEach(function (p) {
        bounds.push(L.latLng(p.lat, p.lng));
      });
    }
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
    globalRef.__atpPlanMapInits = planInitCount;

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
        if (globalRef.AtpLocationModals && globalRef.AtpLocationModals.openBaseModal) {
          globalRef.AtpLocationModals.openBaseModal(base || {});
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
    routeContextKey = makeRouteContextKey(lastPlanPayload);
    routeContextSeq += 1;
    var mySeq = routeContextSeq;

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

    syncRouteFromLast(mySeq);
  }

  function onPlanTabShown() {
    if (!isPlanMapVisible()) return;
    if (!planMap) ensurePlanMap();
    syncPlanMapSize(function () {
      if (lastPlanPayload) renderPlanMap(lastPlanPayload);
      else syncRouteFromLast(routeContextSeq);
    });
  }

  function countOrphanHalos() {
    if (!planMap || !planMap.__atpLayerRegistry) return 0;
    var linked = {};
    if (planRouteLayer && planRouteLayer._halo) linked[planRouteLayer._halo._atpId] = true;
    if (planSuggestedLayer && planSuggestedLayer._halo) linked[planSuggestedLayer._halo._atpId] = true;
    var orphans = 0;
    planMap.__atpLayerRegistry.forEach(function (layer) {
      if (layer._atpKind === 'halo' && planMap.hasLayer(layer) && !linked[layer._atpId]) orphans += 1;
    });
    return orphans;
  }

  var AtpPlanMap = {
    ensurePlanMap: ensurePlanMap,
    onPlanTabShown: onPlanTabShown,
    renderPlanMap: renderPlanMap,
    setCurrentRouteGeometry: setCurrentRouteGeometry,
    setSuggestedRouteGeometry: setSuggestedRouteGeometry,
    clearSuggestedRouteGeometry: clearSuggestedRouteGeometry,
    clearRouteLayers: clearRouteLayers,
    focusCurrentRoute: focusCurrentRoute,
    syncRouteFromLast: syncRouteFromLast,
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
      if (planRouteLayer && planMap && planMap.hasLayer(planRouteLayer)) n += 1;
      if (planSuggestedLayer && planMap && planMap.hasLayer(planSuggestedLayer)) n += 1;
      return n;
    },
    haloLayerCount: function () {
      var n = 0;
      if (planRouteLayer && planRouteLayer._halo && planMap && planMap.hasLayer(planRouteLayer._halo)) n += 1;
      if (planSuggestedLayer && planSuggestedLayer._halo && planMap && planMap.hasLayer(planSuggestedLayer._halo)) n += 1;
      return n;
    },
    orphanHaloCount: countOrphanHalos,
    hasCurrentRoute: function () {
      return !!(planRouteLayer && planMap && planMap.hasLayer(planRouteLayer));
    },
    hasSuggestedRoute: function () {
      return !!(planSuggestedLayer && planMap && planMap.hasLayer(planSuggestedLayer));
    },
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
    },
    getRouteContextKey: function () { return routeContextKey; },
    getRouteContextSeq: function () { return routeContextSeq; },
    _testLayerKinds: function () {
      if (!planMap || !planMap.__atpLayerRegistry) return [];
      var out = [];
      planMap.__atpLayerRegistry.forEach(function (layer) {
        if (!planMap.hasLayer(layer)) return;
        var opts = layer.opts || layer.options || {};
        out.push({
          kind: layer._atpKind || 'unknown',
          dashArray: opts.dashArray || null,
          color: opts.color || null,
        });
      });
      return out;
    },
    _testReset: function () {
      clearRouteLayers();
      clearPlanMarkers();
      planMap = null;
      planTileLayer = null;
      planInitCount = 0;
      lastPlanPayload = null;
      routeContextKey = '';
      routeContextSeq = 0;
      lastDrawnCurrentSig = null;
      lastDrawnSuggestedSig = null;
      globalRef.__atpPlanMapInits = 0;
      var el = document.getElementById('atpPlanLeafletMap');
      if (el) {
        delete el._leaflet_id;
        el.innerHTML = '';
      }
    }
  };

  return {
    AtpPlanMap: AtpPlanMap,
    pure: {
      haversineM: haversineM,
      normalizeValidLatLngs: normalizeValidLatLngs,
      geometrySignature: geometrySignature,
      isIdenticalRouteGeometry: isIdenticalRouteGeometry,
      isDrawableRouteGeometry: isDrawableRouteGeometry,
      makeRouteContextKey: makeRouteContextKey
    }
  };
}));
