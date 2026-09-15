(function (global) {
  'use strict';

  var mainMap = null;
  var lastPayload = null;

  function esc(s) {
    if (s == null) return '';
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function readPayload() {
    var el = document.getElementById('atpDriverMapJson');
    if (!el) return null;
    try { return JSON.parse(el.textContent || '{}'); } catch (e) { return null; }
  }

  function markerColor(stop) {
    var st = (stop.durum || '').toUpperCase();
    if (st === 'TAMAMLANDI') return '#16a34a';
    if (st === 'BASLADI' || (stop.visit_state && stop.visit_state !== 'NONE')) return '#2563eb';
    if (stop.is_acil) return '#dc2626';
    return '#c8922a';
  }

  function stopIcon(stop) {
    var n = esc(stop.sira || stop.display_order_no || stop.order_no || '?');
    var fill = markerColor(stop);
    var acil = stop.is_acil ? '<circle cx="24" cy="6" r="5" fill="#dc2626" stroke="#fff" stroke-width="1"/>' : '';
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

  function baseIcon(label, color) {
    var svg = '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="40" viewBox="0 0 32 40">' +
      '<path d="M16 0C9 0 4 5 4 12c0 9 12 28 12 28s12-19 12-28C28 5 23 0 16 0z" fill="' + color + '" stroke="#fff" stroke-width="2"/>' +
      '<text x="16" y="17" text-anchor="middle" fill="#fff" font-size="10" font-weight="700">' + esc(label) + '</text></svg>';
    return L.divIcon({
      className: 'atp-plan-pin atp-plan-pin-base',
      html: svg,
      iconSize: [32, 40],
      iconAnchor: [16, 40],
      popupAnchor: [0, -38]
    });
  }

  function popupHtml(stop) {
    var acil = stop.is_acil ? '<div><span class="badge badge-red">ACİL</span></div>' : '';
    var safeLink = stop.safe_maps_url
      ? '<a href="' + esc(stop.safe_maps_url) + '" target="_blank" rel="noopener noreferrer">Haritada Aç</a>'
      : '';
    return '<div class="atp-popup atp-plan-popup">' +
      '<strong>' + esc(stop.sira) + '. ' + esc(stop.firma) + '</strong>' +
      acil +
      '<div>İş: ' + esc(stop.yapilacak_is) + '</div>' +
      '<div>Adres: ' + esc(stop.adres) + '</div>' +
      '<div>Öncelik: ' + esc(stop.priority_label || stop.oncelik) + '</div>' +
      '<div>Durum: ' + esc(stop.status_label || stop.durum) + '</div>' +
      (safeLink ? '<div style="margin-top:6px">' + safeLink + '</div>' : '') +
      '</div>';
  }

  function endOffset(lat, lng) {
    return [lat + 0.00012, lng + 0.00012];
  }

  function renderOn(mapInst, payload, markersOut) {
    if (!mapInst || !payload) return;
    markersOut.forEach(function (mk) { mapInst.removeLayer(mk); });
    markersOut.length = 0;
    var base = payload.base_start || payload.base;
    if (base && base.location_valid !== false && base.latitude != null && base.longitude != null) {
      var bmk = L.marker([base.latitude, base.longitude], { icon: baseIcon('B', '#1d4ed8'), zIndexOffset: 1000 });
      bmk.bindPopup('<strong>Başlangıç</strong><div>' + esc(base.name || base.base_name || 'Fabrika') + '</div>');
      bmk.addTo(mapInst);
      markersOut.push(bmk);
    }
    (payload.stops || []).forEach(function (stop) {
      if (!stop.location_valid && stop.location_valid !== undefined) return;
      if (stop.latitude == null || stop.longitude == null) return;
      var mk = L.marker([stop.latitude, stop.longitude], {
        icon: stopIcon(stop),
        zIndexOffset: 800 + (stop.sira || 0)
      });
      mk._atpPlanItemId = stop.plan_item_id;
      mk.bindPopup(popupHtml(stop));
      mk.addTo(mapInst);
      markersOut.push(mk);
    });
    var endBase = payload.base_end || base;
    if (endBase && endBase.latitude != null && endBase.longitude != null) {
      var ep = endOffset(parseFloat(endBase.latitude), parseFloat(endBase.longitude));
      var emk = L.marker(ep, { icon: baseIcon('↩', '#1d4ed8'), zIndexOffset: 950 });
      emk.bindPopup('<strong>Dönüş</strong><div>' + esc(endBase.name || 'Fabrika') + '</div>');
      emk.addTo(mapInst);
      markersOut.push(emk);
    }
    if (payload.route_geometry && payload.route_geometry.length && !payload.route_fallback) {
      L.polyline(payload.route_geometry.map(function (p) { return [p[0], p[1]]; }), {
        color: '#1d4ed8', weight: 5, opacity: 0.9
      }).addTo(mapInst);
    }
    var bounds = [];
    markersOut.forEach(function (mk) { bounds.push(mk.getLatLng()); });
    if (bounds.length === 1) mapInst.setView(bounds[0], 13);
    else if (bounds.length > 1) mapInst.fitBounds(L.latLngBounds(bounds).pad(0.12), { maxZoom: 13 });
  }

  function ensureMap(elId) {
    var el = document.getElementById(elId);
    if (!el || typeof L === 'undefined') return null;
    if (el._leaflet_id && el._leaflet_map) return el._leaflet_map;
    if (el._leaflet_id) {
      delete el._leaflet_id;
      el.innerHTML = '';
    }
    var m = L.map(el, { zoomControl: true }).setView([41.02, 29.05], 11);
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap'
    }).addTo(m);
    el._leaflet_map = m;
    return m;
  }

  function initMain() {
    lastPayload = readPayload();
    if (!lastPayload) return;
    mainMap = ensureMap('atpDriverLeafletMap');
    if (!mainMap) return;
    var markers = [];
    renderOn(mainMap, lastPayload, markers);
    mainMap.whenReady(function () {
      mainMap.invalidateSize({ animate: false });
      requestAnimationFrame(function () { mainMap.invalidateSize({ animate: false }); });
    });
  }

  document.addEventListener('DOMContentLoaded', initMain);

  global.AtpDriverMap = {
    getMarkerPlanItemIds: function () {
      if (!mainMap) return [];
      var ids = [];
      mainMap.eachLayer(function (layer) {
        if (layer._atpPlanItemId != null) ids.push(layer._atpPlanItemId);
      });
      return ids;
    },
    openFirstStopPopup: function () {
      if (!mainMap) return false;
      var target = null;
      mainMap.eachLayer(function (layer) {
        if (!target && layer._atpPlanItemId != null) target = layer;
      });
      if (target && target.openPopup) { target.openPopup(); return true; }
      return false;
    }
  };
})(window);
