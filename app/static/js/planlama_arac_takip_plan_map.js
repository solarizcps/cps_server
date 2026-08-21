(function (global) {
  'use strict';

  var planMap = null;
  var planTileLayer = null;
  var planMarkers = [];
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

  function stopIcon(orderNo) {
    var n = esc(orderNo);
    var svg = '<svg xmlns="http://www.w3.org/2000/svg" width="30" height="38" viewBox="0 0 30 38">' +
      '<circle cx="15" cy="15" r="13" fill="#c8922a" stroke="#fff" stroke-width="2"/>' +
      '<text x="15" y="19" text-anchor="middle" fill="#fff" font-size="11" font-weight="700">' + n + '</text>' +
      '<path d="M15 28 L10 38 L20 38 Z" fill="#c8922a" stroke="#fff" stroke-width="1"/></svg>';
    return L.divIcon({
      className: 'atp-plan-pin atp-plan-pin-stop',
      html: svg,
      iconSize: [30, 38],
      iconAnchor: [15, 38],
      popupAnchor: [0, -36]
    });
  }

  function basePopupHtml(base) {
    return '<div class="atp-popup atp-plan-popup">' +
      '<strong>Başlangıç</strong>' +
      '<div>' + esc(base.base_name || '—') + '</div>' +
      '<div>' + esc(base.base_address || '—') + '</div>' +
      '</div>';
  }

  function stopPopupHtml(stop) {
    return '<div class="atp-popup atp-plan-popup">' +
      '<strong>' + esc(stop.order_no) + ' · ' + esc(stop.company_name) + '</strong>' +
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

  function ensurePlanMap() {
    if (planMap) return true;
    if (typeof L === 'undefined') return false;
    if (!isPlanMapVisible()) return false;
    var el = document.getElementById('atpPlanLeafletMap');
    if (!el) return false;
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
    if (mapEl) mapEl.style.display = '';
  }

  function renderPlanMap(payload) {
    lastPlanPayload = payload || lastPlanPayload;
    if (!lastPlanPayload) return;
    updateEmptyState(lastPlanPayload);
    updateCompleteness(lastPlanPayload.completeness, lastPlanPayload.base);
    if (!ensurePlanMap()) return;
    clearPlanMarkers();

    var layers = [];
    var base = lastPlanPayload.base;
    if (base && base.has_coordinates && base.latitude != null && base.longitude != null) {
      var bmk = L.marker([base.latitude, base.longitude], { icon: baseIcon(), zIndexOffset: 1000 });
      bmk.bindPopup(basePopupHtml(base));
      bmk.addTo(planMap);
      planMarkers.push(bmk);
      layers.push(bmk);
    }

    (lastPlanPayload.stops || []).forEach(function (stop) {
      if (!stop.has_coordinates || stop.latitude == null || stop.longitude == null) return;
      var mk = L.marker([stop.latitude, stop.longitude], {
        icon: stopIcon(stop.order_no),
        zIndexOffset: 800 + (stop.order_no || 0)
      });
      mk.bindPopup(stopPopupHtml(stop));
      mk.addTo(planMap);
      planMarkers.push(mk);
      layers.push(mk);
    });

    if (layers.length === 1) {
      planMap.setView(layers[0].getLatLng(), 13, { animate: false });
    } else if (layers.length > 1) {
      planMap.fitBounds(L.featureGroup(layers).getBounds().pad(0.15), { animate: false, maxZoom: 13 });
    }
  }

  function onPlanTabShown() {
    if (!isPlanMapVisible()) return;
    if (!planMap) ensurePlanMap();
    syncPlanMapSize(function () {
      if (lastPlanPayload) renderPlanMap(lastPlanPayload);
    });
  }

  global.AtpPlanMap = {
    ensurePlanMap: ensurePlanMap,
    onPlanTabShown: onPlanTabShown,
    renderPlanMap: renderPlanMap,
    mapInstanceCount: function () { return planInitCount; },
    hasInstance: function () { return planMap !== null; },
    markerCount: function () { return planMarkers.length; }
  };
})(window);
