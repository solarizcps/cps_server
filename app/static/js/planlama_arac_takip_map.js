(function (global) {
  'use strict';

  var STATUS_COLORS = {
    HAREKETLI: '#12b76a',
    ROLANTI: '#f79009',
    DURAN: '#f04438',
    PASIF: '#98a2b3',
    BILINMIYOR: '#667085'
  };

  var map = null;
  var tileLayer = null;
  var markerById = {};
  var lastVehicles = [];
  var lastSuccessAt = null;
  var initCount = 0;
  var pendingShow = false;

  global.__atpMapInits = 0;

  function esc(s) {
    if (s == null) return '';
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function isLiveMapVisible() {
    /* Check both the container and the map element itself */
    var box = document.getElementById('atp-live-map-container') ||
              document.getElementById('atpLeafletMap');
    if (!box) return false;
    var st = window.getComputedStyle(box);
    if (st.display === 'none' || st.visibility === 'hidden') return false;
    /* Also check that parent canli view is visible */
    var canliView = document.getElementById('atpCanliView');
    if (canliView) {
      var cvSt = window.getComputedStyle(canliView);
      if (cvSt.display === 'none') return false;
    }
    return true;
  }

  function markerIcon(status) {
    var color = STATUS_COLORS[status] || STATUS_COLORS.BILINMIYOR;
    var svg = '<svg xmlns="http://www.w3.org/2000/svg" width="28" height="36" viewBox="0 0 28 36">' +
      '<path d="M14 0C6.3 0 0 6.3 0 14c0 10.5 14 22 14 22s14-11.5 14-22C28 6.3 21.7 0 14 0z" fill="' + color + '" stroke="#fff" stroke-width="2"/>' +
      '<text x="14" y="17" text-anchor="middle" fill="#fff" font-size="11" font-weight="700">🚚</text></svg>';
    return L.divIcon({
      className: 'atp-leaflet-pin',
      html: svg,
      iconSize: [28, 36],
      iconAnchor: [14, 36],
      popupAnchor: [0, -34]
    });
  }

  function formatLastSeen(v) {
    var ts = v.last_seen_at || '';
    if (!ts) return '—';
    var m = ts.match(/(\d{2}:\d{2})/);
    return m ? m[1] : ts;
  }

  function locationText(v) {
    if (v.address) return v.address;
    if (v.latitude != null && v.longitude != null) {
      return v.latitude.toFixed(5) + ', ' + v.longitude.toFixed(5);
    }
    return '—';
  }

  function popupHtml(v) {
    var stale = v.is_stale_data ? '<span class="atp-popup-stale">Eski veri</span>' : '';
    return '<div class="atp-popup">' +
      '<strong>' + esc(v.plate_display || v.plate) + '</strong>' + stale +
      '<div>Durum: ' + esc(v.activity_status_label || '—') + '</div>' +
      '<div>Şoför: ' + esc(v.driver_name || '—') + '</div>' +
      '<div>Hız: ' + esc(v.speed_kmh != null ? v.speed_kmh : 0) + ' km/s</div>' +
      '<div>Son veri: ' + esc(formatLastSeen(v)) + '</div>' +
      '<div>Konum: ' + esc(locationText(v)) + '</div>' +
      (v.total_distance_km != null ? '<div>Toplam KM: ' + esc(v.total_distance_km) + ' km</div>' : '') +
      '</div>';
  }

  function setLastUpdate(date) {
    var el = document.getElementById('atpMapLastUpdate');
    if (!el || !date) return;
    var h = String(date.getHours()).padStart(2, '0');
    var m = String(date.getMinutes()).padStart(2, '0');
    var s = String(date.getSeconds()).padStart(2, '0');
    el.textContent = 'Son güncelleme: ' + h + ':' + m + ':' + s;
  }

  function setWarning(msg) {
    var el = document.getElementById('atpMapWarn');
    if (!el) return;
    el.textContent = msg || '';
    el.style.display = msg ? 'block' : 'none';
  }

  function setEmpty(show) {
    var el = document.getElementById('atpMapEmpty');
    if (el) el.style.display = show ? 'block' : 'none';
  }

  function syncMapSize(cb) {
    if (!map) return;
    map.invalidateSize({ animate: false });
    if (typeof cb === 'function') {
      requestAnimationFrame(function () {
        map.invalidateSize({ animate: false });
        cb();
      });
    }
  }

  function ensureLiveMap() {
    if (map) return true;
    if (typeof L === 'undefined') return false;
    if (!isLiveMapVisible()) {
      pendingShow = true;
      return false;
    }
    pendingShow = false;
    var el = document.getElementById('atpLeafletMap');
    if (!el) return false;

    map = L.map(el, {
      zoomControl: true,
      attributionControl: true,
      preferCanvas: false
    }).setView([41.02, 29.05], 11);

    tileLayer = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap contributors'
    });
    tileLayer.addTo(map);

    initCount += 1;
    global.__atpMapInits = initCount;

    var btn = document.getElementById('atpBtnFitAll');
    if (btn && !btn._atpBound) {
      btn._atpBound = true;
      btn.addEventListener('click', function () { fitAll(); });
    }

    map.whenReady(function () {
      syncMapSize(function () {
        if (lastVehicles.length) updateVehicleMarkers(lastVehicles);
      });
    });
    /* Extra invalidateSize after a short delay for cases where container
       size is still settling (tab animation, etc.) */
    setTimeout(function () {
      if (map) {
        map.invalidateSize({ animate: false });
        if (lastVehicles.length) updateVehicleMarkers(lastVehicles);
      }
    }, 300);
    return true;
  }

  function validVehicles(list) {
    return (list || []).filter(function (v) {
      return v.has_valid_location && v.latitude != null && v.longitude != null;
    });
  }

  function fitAll(animate) {
    if (!map) return;
    var layers = Object.keys(markerById).map(function (id) { return markerById[id]; });
    if (!layers.length) return;
    map.fitBounds(L.featureGroup(layers).getBounds().pad(0.12), {
      animate: animate !== false,
      maxZoom: 13
    });
  }

  function updateVehicleMarkers(vehicles) {
    if (!map) return 0;
    lastVehicles = vehicles || lastVehicles;
    var valid = validVehicles(lastVehicles);
    setEmpty(!valid.length);

    valid.forEach(function (v) {
      var latlng = [v.latitude, v.longitude];
      if (markerById[v.id]) {
        markerById[v.id].setLatLng(latlng);
        markerById[v.id].setIcon(markerIcon(v.activity_status));
        markerById[v.id].setPopupContent(popupHtml(v));
      } else {
        var mk = L.marker(latlng, {
          icon: markerIcon(v.activity_status),
          title: v.plate_display || v.plate,
          zIndexOffset: 500
        });
        mk.bindPopup(popupHtml(v));
        mk.addTo(map);
        markerById[v.id] = mk;
      }
    });

    var validIds = {};
    valid.forEach(function (v) { validIds[v.id] = true; });
    Object.keys(markerById).forEach(function (id) {
      if (!validIds[id]) {
        map.removeLayer(markerById[id]);
        delete markerById[id];
      }
    });

    if (valid.length === 1) {
      map.setView([valid[0].latitude, valid[0].longitude], 13, { animate: false });
    } else if (valid.length > 1) {
      fitAll(false);
    }
    return valid.length;
  }

  function focusVehicle(id) {
    if (!map) ensureLiveMap();
    if (!map || !markerById[id]) return false;
    map.flyTo(markerById[id].getLatLng(), Math.max(map.getZoom(), 14), { duration: 0.5 });
    markerById[id].openPopup();
    document.querySelectorAll('#atpVehicleList li[data-vehicle-id]').forEach(function (li) {
      li.classList.toggle('atp-veh-selected', li.getAttribute('data-vehicle-id') === String(id));
    });
    return true;
  }

  function onLiveTabShown() {
    if (!map) {
      /* Try immediately, then after short delay in case tab just became visible */
      if (!ensureLiveMap()) {
        setTimeout(function () {
          if (!map && ensureLiveMap() && lastVehicles.length) {
            updateVehicleMarkers(lastVehicles);
          }
        }, 100);
      }
      return;
    }
    /* Map exists — just resize and refresh markers */
    setTimeout(function () {
      if (map) {
        map.invalidateSize({ animate: false });
        updateVehicleMarkers(lastVehicles);
      }
    }, 50);
  }

  function refreshLiveVehicles(vehicles, opts) {
    opts = opts || {};
    if (vehicles && vehicles.length) {
      lastVehicles = vehicles;
      if (!opts.silent) setWarning('');
      if (opts.success) {
        lastSuccessAt = new Date();
        setLastUpdate(lastSuccessAt);
      }
      if (!map) {
        /* Map not initialized yet — try to init now */
        if (ensureLiveMap()) {
          updateVehicleMarkers(vehicles);
        } else {
          /* Will be picked up on next onLiveTabShown */
        }
      } else {
        updateVehicleMarkers(vehicles);
        if (isLiveMapVisible()) map.invalidateSize({ animate: false });
      }
      return validVehicles(vehicles).length;
    }
    if (opts.failed && lastSuccessAt) {
      setWarning('Canlı araç verisi güncellenemedi.');
      setLastUpdate(lastSuccessAt);
    }
    return 0;
  }

  global.AtpLiveMap = {
    ensureLiveMap: ensureLiveMap,
    onLiveTabShown: onLiveTabShown,
    focusVehicle: focusVehicle,
    fitAll: fitAll,
    refreshLiveVehicles: refreshLiveVehicles,
    updateVehicleMarkers: updateVehicleMarkers,
    validCount: function (list) { return validVehicles(list || lastVehicles).length; },
    markerCount: function () { return Object.keys(markerById).length; },
    mapInstanceCount: function () { return initCount; }
  };
})(window);
