/**
 * ATP GPS Geçmişi — read-only trail viewer (V3 layout).
 * window.AtpGpsHistory
 */
(function (global) {
  'use strict';

  var API_BASE = '/planlama/arac-takip/api';
  var _map = null;
  var _layerGroup = null;
  var _data = null;
  var _playTimer = null;
  var _playIdx = 0;
  var _playSpeed = 1;
  var _marker = null;
  var _openPlanId = null;
  var _returnTab = 'gecmis';

  function qs(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function fmtTime(ts) {
    if (!ts) return '—';
    var m = String(ts).match(/(\d{2}):(\d{2})/);
    return m ? (m[1] + ':' + m[2]) : ts;
  }

  function destroyMap() {
    if (_playTimer) { clearInterval(_playTimer); _playTimer = null; }
    if (_map) {
      try { _map.remove(); } catch (e) { /* ignore */ }
      _map = null;
    }
    _layerGroup = null;
    _marker = null;
  }

  function ensureMap() {
    var el = qs('atpGpsHistoryMap');
    if (!el || typeof L === 'undefined') return null;
    destroyMap();
    _map = L.map(el, { zoomControl: true, attributionControl: true });
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap',
    }).addTo(_map);
    _layerGroup = L.layerGroup().addTo(_map);
    return _map;
  }

  function latLngFromPoint(p) {
    return [p.latitude, p.longitude];
  }

  function drawLayers(d) {
    if (!_map || !_layerGroup) return;
    _layerGroup.clearLayers();
    var bounds = [];

    var rg = d.route_geometry;
    if (rg && rg.coordinates && rg.coordinates.length) {
      var planLatLngs;
      if (rg.type === 'LineString') {
        planLatLngs = rg.coordinates.map(function (c) { return [c[1], c[0]]; });
      } else if (rg.type === 'MultiLineString') {
        planLatLngs = (rg.coordinates[0] || []).map(function (c) { return [c[1], c[0]]; });
      }
      if (planLatLngs && planLatLngs.length) {
        L.polyline(planLatLngs, { color: '#1976d2', weight: 4, opacity: 0.85 }).addTo(_layerGroup);
        planLatLngs.forEach(function (ll) { bounds.push(ll); });
      }
    }

    var ag = d.actual_trail_geometry;
    if (ag && ag.coordinates) {
      (ag.coordinates || []).forEach(function (line, idx) {
        if (!line || line.length < 2) return;
        var latlngs = line.map(function (c) { return [c[1], c[0]]; });
        var isGapSeg = d.gap_segments && d.gap_segments.some(function (g) {
          return g.after_point_index != null && g.segment_index === idx + 1;
        });
        L.polyline(latlngs, {
          color: isGapSeg ? '#f97316' : '#16a34a',
          weight: 4,
          opacity: 0.9,
          dashArray: isGapSeg ? '8 6' : null,
        }).addTo(_layerGroup);
        latlngs.forEach(function (ll) { bounds.push(ll); });
      });
    } else if (d.gps_points && d.gps_points.length) {
      var pts = d.gps_points.map(latLngFromPoint);
      L.polyline(pts, { color: '#16a34a', weight: 4, opacity: 0.9 }).addTo(_layerGroup);
      pts.forEach(function (ll) { bounds.push(ll); });
    }

    (d.deviations || []).forEach(function (dev) {
      /* deviation episodes highlighted via timeline; map uses red segment overlay if points known */
    });

    if (bounds.length) {
      _map.fitBounds(bounds, { padding: [24, 24] });
    } else {
      _map.setView([41.01, 28.95], 10);
    }

    if (d.gps_points && d.gps_points.length) {
      var first = d.gps_points[0];
      _marker = L.circleMarker(latLngFromPoint(first), {
        radius: 7, color: '#111', fillColor: '#fbbf24', fillOpacity: 1, weight: 2,
      }).addTo(_layerGroup);
      _playIdx = 0;
    }
  }

  function renderKpi(kpi) {
    kpi = kpi || {};
    var set = function (id, val) {
      var el = qs(id);
      if (el) el.textContent = val;
    };
    set('atpGpsKpiActualKm', (kpi.actual_distance_km != null ? kpi.actual_distance_km + ' km' : '—'));
    set('atpGpsKpiPlanKm', (kpi.planned_distance_km != null ? kpi.planned_distance_km + ' km' : '—'));
    set('atpGpsKpiDevCount', kpi.deviation_count != null ? String(kpi.deviation_count) : '0');
    set('atpGpsKpiDevMin', (kpi.deviation_duration_min != null ? kpi.deviation_duration_min + ' dk' : '—'));
    set('atpGpsKpiDwell', (kpi.stop_dwell_min != null ? kpi.stop_dwell_min + ' dk' : '—'));
    set('atpGpsKpiQuality', kpi.gps_quality_label || '—');
  }

  function timelineClass(type) {
    var t = (type || '').toUpperCase();
    if (t.indexOf('SAPMA') >= 0 || t.indexOf('ROTA_SAPMA') >= 0) return 'tl-err';
    if (t.indexOf('GECIKME') >= 0 || t.indexOf('BEKLI') >= 0) return 'tl-warn';
    if (t.indexOf('VARIL') >= 0 || t.indexOf('DONDU') >= 0 || t.indexOf('GIRIS') >= 0) return 'tl-ok';
    return 'tl-info';
  }

  function renderTimeline(events) {
    var ul = qs('atpGpsTimeline');
    if (!ul) return;
    if (!events || !events.length) {
      ul.innerHTML = '<li class="tl-info"><span class="tl-t">—</span><span class="tl-dot"></span><div>Olay kaydı yok</div></li>';
      return;
    }
    ul.innerHTML = events.map(function (ev) {
      var cls = timelineClass(ev.type);
      return '<li class="' + cls + '">' +
        '<span class="tl-t">' + esc(ev.time_display || fmtTime(ev.time)) + '</span>' +
        '<span class="tl-dot"></span>' +
        '<div><div>' + esc(ev.title || ev.type) + '</div>' +
        (ev.message ? '<div class="tl-sub">' + esc(ev.message) + '</div>' : '') +
        '</div></li>';
    }).join('');
  }

  function renderVehicleSummary(d) {
    var block = qs('atpGpsVehicleBlock');
    if (!block) return;
    var st = d.status || {};
    var badgeCls = st.severity === 'warn' ? 'badge-orange' : (st.severity === 'ok' ? 'badge-green' : 'badge-gray');
    block.innerHTML =
      '<div class="vcard ' + (st.severity === 'warn' ? 'warn' : '') + '">' +
        '<div class="vcard-inner" style="grid-template-columns:1fr;padding:10px 12px">' +
          '<div class="vcard-plate-row">' +
            '<div class="vcard-plate">' + esc(d.plate) + '</div>' +
            '<span class="badge ' + badgeCls + '">' + esc(st.label || '—') + '</span>' +
          '</div>' +
          '<div class="vcard-driver">' + esc(d.driver) + ' · Filom #' + esc(d.vehicle_external_id) + '</div>' +
          '<div class="vcard-detail-row" style="margin-top:8px"><span class="icon">📅</span><span>Plan: <strong>' + esc(d.plan_date) + '</strong></span></div>' +
          '<div class="vcard-detail-row"><span class="icon">🕐</span><span>Pencere: <strong>' + esc(fmtTime(d.window_start)) + ' – ' + esc(fmtTime(d.window_end)) + '</strong></span></div>' +
        '</div></div>';

    var qEl = qs('atpGpsQualityNote');
    if (qEl) {
      var kpi = d.kpi || {};
      if (kpi.gap_count > 0) {
        qEl.style.display = '';
        qEl.innerHTML = '<strong>Veri kalitesi:</strong> ' + esc(kpi.gps_quality_label || '') +
          ' · ' + kpi.gap_count + ' GPS boşluğu. Stale noktalar sapma hesabına katılmaz.';
      } else if (!d.has_gps_history) {
        qEl.style.display = '';
        qEl.textContent = 'Bu plan için GPS geçmişi kaydı bulunamadı.';
      } else {
        qEl.style.display = 'none';
      }
    }
  }

  function renderMeta(d) {
    var sideHdr = qs('atpGpsSideHdr');
    if (sideHdr) sideHdr.textContent = 'Araç Özeti · ' + (d.plan_date || '');
    var chips = qs('atpGpsFilterChips');
    if (chips) {
      var n = (d.gps_points || []).length;
      var gaps = (d.gap_segments || []).length;
      chips.innerHTML =
        '<span class="chip">' + n + ' GPS noktası</span>' +
        (gaps ? ('<span class="chip chip-warn">' + gaps + ' veri boşluğu</span>') : '');
    }
    var dateInp = qs('atpGpsFilterDate');
    if (dateInp && d.plan_date) dateInp.value = d.plan_date;
    var vehSel = qs('atpGpsFilterVehicle');
    if (vehSel) vehSel.innerHTML = '<option>' + esc(d.plate) + '</option>';
  }

  function setupPlayback(d) {
    var slider = qs('atpGpsPlaySlider');
    var pts = d.gps_points || [];
    if (!slider) return;
    slider.min = 0;
    slider.max = Math.max(0, pts.length - 1);
    slider.value = 0;
    slider.oninput = function () {
      _playIdx = parseInt(slider.value, 10) || 0;
      updatePlaybackUi(d);
    };
    qs('atpGpsBtnPlay').onclick = function () {
      if (_playTimer) { stopPlayback(); return; }
      startPlayback(d);
    };
    qs('atpGpsBtnStop').onclick = stopPlayback;
    document.querySelectorAll('#atpPanelGpsHistory .speed-btn').forEach(function (btn) {
      btn.onclick = function () {
        document.querySelectorAll('#atpPanelGpsHistory .speed-btn').forEach(function (b) {
          b.classList.remove('active');
        });
        btn.classList.add('active');
        _playSpeed = parseInt(btn.getAttribute('data-speed'), 10) || 1;
      };
    });
    updatePlaybackUi(d);
  }

  function updatePlaybackUi(d) {
    var pts = d.gps_points || [];
    var p = pts[_playIdx];
    var timeEl = qs('atpGpsPlayTime');
    var speedEl = qs('atpGpsPlaySpeed');
    if (timeEl) timeEl.textContent = p ? fmtTime(p.timestamp) : '—';
    if (speedEl) speedEl.textContent = (p && p.speed_kmh != null) ? (p.speed_kmh + ' km/s') : '0 km/s';
    if (_marker && p) _marker.setLatLng(latLngFromPoint(p));
    var slider = qs('atpGpsPlaySlider');
    if (slider) slider.value = _playIdx;
  }

  function startPlayback(d) {
    stopPlayback();
    var btn = qs('atpGpsBtnPlay');
    if (btn) btn.textContent = '⏸ Durdur';
    var pts = d.gps_points || [];
    if (!pts.length) return;
    _playTimer = setInterval(function () {
      _playIdx += 1;
      if (_playIdx >= pts.length) { _playIdx = 0; }
      updatePlaybackUi(d);
    }, Math.max(200, 800 / _playSpeed));
  }

  function stopPlayback() {
    if (_playTimer) { clearInterval(_playTimer); _playTimer = null; }
    var btn = qs('atpGpsBtnPlay');
    if (btn) btn.textContent = '▶ Oynat';
  }

  function showEmpty(msg) {
    var body = qs('atpGpsHistoryBody');
    if (body) {
      body.innerHTML = '<div class="atp-gps-empty">' + esc(msg || 'Veri yok') + '</div>';
    }
  }

  function open(planId, opts) {
    opts = opts || {};
    _openPlanId = planId;
    _returnTab = opts.returnTab || 'gecmis';
    var root = qs('atpV2Root');
    if (root) root.classList.add('atp-gps-history-active');

    var loading = qs('atpGpsHistoryLoading');
    var body = qs('atpGpsHistoryBody');
    if (loading) loading.style.display = '';
    if (body) body.style.display = 'none';

    fetch(API_BASE + '/plan-gps-trail?plan_id=' + encodeURIComponent(planId), { credentials: 'same-origin' })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (res) {
        if (loading) loading.style.display = 'none';
        if (body) body.style.display = '';
        if (!res.ok || !res.d.ok) {
          showEmpty((res.d && (res.d.error || res.d.message)) || 'Yüklenemedi');
          return;
        }
        _data = res.d;
        renderMeta(_data);
        renderKpi(_data.kpi);
        renderVehicleSummary(_data);
        renderTimeline(_data.timeline_events);
        ensureMap();
        drawLayers(_data);
        setupPlayback(_data);
        if (!_data.has_gps_history && qs('atpGpsMapCol')) {
          /* still show planned route if any */
        }
        setTimeout(function () { if (_map) _map.invalidateSize(); }, 120);
      })
      .catch(function () {
        if (loading) loading.style.display = 'none';
        showEmpty('Bağlantı hatası');
      });
  }

  function close() {
    stopPlayback();
    destroyMap();
    _data = null;
    _openPlanId = null;
    var root = qs('atpV2Root');
    if (root) root.classList.remove('atp-gps-history-active');
    if (typeof global.setTab === 'function') {
      global.setTab(_returnTab);
    }
  }

  function bindUi() {
    var back = qs('atpGpsBtnBack');
    if (back) back.addEventListener('click', close);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bindUi);
  } else {
    bindUi();
  }

  global.AtpGpsHistory = {
    open: open,
    close: close,
    destroyMap: destroyMap,
    getOpenPlanId: function () { return _openPlanId; },
  };
})(window);
