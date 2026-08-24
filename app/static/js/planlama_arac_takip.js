(function () {
  'use strict';

  var root = document.getElementById('atpRoot');
  if (!root) return;

  var dashEl = document.getElementById('atpDashboardJson');
  var dashboard = dashEl ? JSON.parse(dashEl.textContent) : {};
  var planDate = root.getAttribute('data-date') || dashboard.date;
  var urlVehicleId = new URLSearchParams(window.location.search).get('vehicle_id');
  if (urlVehicleId && !dashboard.selected_vehicle_id) {
    dashboard.selected_vehicle_id = urlVehicleId;
  }
  var LIVE_POLL_MS = 30000;
  var LIVE_FETCH_TIMEOUT_MS = 20000;
  var pollTimer = null;
  var currentTab = 'gunluk';
  var lastVehicles = [];
  var liveMergedVehicles = [];
  var liveFetchState = 'idle';
  var liveOpsCache = null;
  var liveRouteGeometries = [];
  var liveRouteLayerGroup = null;
  var liveRoutesVisible = false;
  var liveLastPollAt = null;
  var liveSelectedVehicleId = null;
  var lastLiveFilomKpi = null;
  var lastLiveFilomCount = null;

  function normalizeExternalId(id) {
    if (id === null || id === undefined) return '';
    return String(id).trim();
  }

  function buildOpsByExternalId(opsBundle) {
    var map = {};
    if (!opsBundle || !opsBundle.vehicles) return map;
    opsBundle.vehicles.forEach(function (o) {
      var key = normalizeExternalId(o.arac_external_id);
      if (key) map[key] = o;
    });
    return map;
  }

  function filomExternalId(filomV) {
    return normalizeExternalId(filomV.id || filomV.mobile_id || filomV.external_id);
  }

  function fmtVal(v) {
    return v === null || v === undefined || v === '' ? '—' : String(v);
  }

  function fmtTimeStamp(date) {
    if (!date || isNaN(date.getTime())) return '—';
    var h = String(date.getHours()).padStart(2, '0');
    var m = String(date.getMinutes()).padStart(2, '0');
    var s = String(date.getSeconds()).padStart(2, '0');
    return h + ':' + m + ':' + s;
  }

  function fmtGpsAgeShort(ts) {
    if (!ts) return 'GPS: —';
    var d = new Date(String(ts).replace(' ', 'T'));
    if (isNaN(d.getTime())) return fmtVal(ts);
    var mins = Math.round((Date.now() - d.getTime()) / 60000);
    if (mins < 1) return 'az önce';
    if (mins < 120) return mins + ' dk önce';
    return String(ts);
  }

  function fmtLiveDeviationNote(v) {
    if (v.deviation_label) return v.deviation_label;
    if (v.route_state !== 'DEVIATING') return '';
    var m = v.deviation_m != null ? v.deviation_m : v.current_deviation_m;
    if (m == null) return 'Rotadan sapıyor';
    var km = (Number(m) / 1000).toLocaleString('tr-TR', { maximumFractionDigits: 1 });
    var dur = '';
    if (v.deviation_started_at) {
      var dd = new Date(String(v.deviation_started_at).replace(' ', 'T'));
      if (!isNaN(dd.getTime())) {
        var dm = Math.max(0, Math.round((Date.now() - dd.getTime()) / 60000));
        if (dm) dur = ' · ' + dm + ' dk';
      }
    }
    return km + ' km' + dur;
  }

  function findOpsVehicle(filomV, opsBundle, opsIndex) {
    var bundle = opsBundle || liveOpsCache;
    if (!bundle || !bundle.vehicles) return null;
    var fid = filomExternalId(filomV);
    if (!fid) return null;
    if (opsIndex && opsIndex[fid]) return opsIndex[fid];
    for (var i = 0; i < bundle.vehicles.length; i++) {
      var o = bundle.vehicles[i];
      if (normalizeExternalId(o.arac_external_id) === fid) return o;
    }
    return null;
  }

  function mergeLiveVehicle(v, opsBundle, opsIndex) {
    var ops = findOpsVehicle(v, opsBundle, opsIndex);
    var merged = Object.assign({}, v);
    if (ops) {
      merged.route_state = ops.route_state;
      merged.route_status_label = ops.route_status_label;
      merged.deviation_m = ops.deviation_m != null ? ops.deviation_m : ops.current_deviation_m;
      merged.deviation_started_at = ops.deviation_started_at;
      merged.deviation_label = ops.deviation_label;
      merged.gps_last_seen_at = ops.gps_last_seen_at || ops.gps_timestamp || v.last_seen_at;
      merged.gps_is_stale = !!(v.is_stale_data || ops.gps_is_stale || ops.gps_stale);
      if (ops.driver) merged.driver_name = ops.driver;
    } else {
      merged.gps_is_stale = !!v.is_stale_data;
      merged.gps_last_seen_at = v.last_seen_at;
    }
    return merged;
  }

  function mergeAllLiveVehicles(filomVehicles, opsBundle) {
    var bundle = opsBundle && opsBundle.ok ? opsBundle : liveOpsCache;
    var opsIndex = buildOpsByExternalId(bundle);
    return (filomVehicles || []).map(function (v) {
      return mergeLiveVehicle(v, bundle, opsIndex);
    });
  }

  function syncLivePollTimestamp(date) {
    if (!date) return;
    liveLastPollAt = date instanceof Date ? date : new Date(date);
    setLiveRefreshBar(liveLastPollAt);
    if (currentTab !== 'canli') return;
    var elSon = document.getElementById('atpKpiSonGuncelleme');
    if (elSon) elSon.textContent = fmtTimeStamp(liveLastPollAt);
  }

  function countSapma(vehicles) {
    if (!vehicles || !vehicles.length) return null;
    return vehicles.filter(function (v) { return v.route_state === 'DEVIATING'; }).length;
  }

  function computeGpsHealth(vehicles, fallbackCount) {
    var list = vehicles || [];
    var total = list.length || (fallbackCount != null ? fallbackCount : 0);
    if (!total) return null;
    var fresh = list.filter(function (v) { return !(v.gps_is_stale || v.is_stale_data); }).length;
    return { fresh: fresh, total: total };
  }

  function mapMarkerStatus(v) {
    if (v.gps_is_stale || v.is_stale_data) return 'PASIF';
    if (v.route_state === 'DEVIATING') return 'ROLANTI';
    if (v.activity_status === 'HAREKETLI') return 'HAREKETLI';
    if (v.activity_status === 'DURAN' || v.activity_status === 'ROLANTI') return 'PASIF';
    return v.activity_status || 'BILINMIYOR';
  }

  function vehiclesForMap(vehicles) {
    return (vehicles || []).map(function (v) {
      var copy = Object.assign({}, v);
      copy.activity_status = mapMarkerStatus(v);
      return copy;
    });
  }

  function extractRouteGeometries(ops) {
    if (!ops || !ops.map) return [];
    var out = [];
    ['tracks', 'routes'].forEach(function (key) {
      (ops.map[key] || []).forEach(function (item) {
        if (item.geometry && item.geometry.length >= 2) out.push(item.geometry);
        else if (item.points && item.points.length >= 2) out.push(item.points);
      });
    });
    return out;
  }

  function resolveLiveLeafletMap() {
    var el = document.getElementById('atpLeafletMap');
    if (!el || typeof L === 'undefined' || el._leaflet_id == null) return null;
    if (typeof L.Map.get === 'function') return L.Map.get(el);
    var key;
    for (key in el) {
      if (Object.prototype.hasOwnProperty.call(el, key) && el[key] instanceof L.Map) return el[key];
    }
    return null;
  }

  function updateRouteButtonState() {
    var btn = document.getElementById('atpBtnShowRoutes');
    if (!btn) return;
    var hasRoutes = liveRouteGeometries.length > 0;
    btn.disabled = !hasRoutes;
    btn.title = hasRoutes ? 'GPS iz / plan rotasını göster' : 'Rota geometrisi yok';
    btn.classList.toggle('atp-btn-active', liveRoutesVisible && hasRoutes);
  }

  function clearLiveRouteLayer() {
    var map = resolveLiveLeafletMap();
    if (liveRouteLayerGroup && map) {
      map.removeLayer(liveRouteLayerGroup);
    }
    liveRouteLayerGroup = null;
    liveRoutesVisible = false;
    updateRouteButtonState();
  }

  function drawLiveRouteLayer() {
    var map = resolveLiveLeafletMap();
    if (!map || !liveRouteGeometries.length) return false;
    clearLiveRouteLayer();
    liveRouteLayerGroup = L.layerGroup();
    liveRouteGeometries.forEach(function (pts) {
      if (!pts || pts.length < 2) return;
      L.polyline(pts, {
        color: '#1976d2',
        weight: 3,
        opacity: 0.85,
        dashArray: '8, 6'
      }).addTo(liveRouteLayerGroup);
    });
    liveRouteLayerGroup.addTo(map);
    liveRoutesVisible = true;
    updateRouteButtonState();
    return true;
  }

  function toggleLiveRoutes() {
    if (!liveRouteGeometries.length) return;
    if (liveRoutesVisible) {
      clearLiveRouteLayer();
      return;
    }
    if (window.AtpLiveMap) window.AtpLiveMap.onLiveTabShown();
    if (!drawLiveRouteLayer()) toast('Rota katmanı haritaya eklenemedi');
  }

  function setLiveRefreshBar(date) {
    var el = document.getElementById('atpLiveRefreshText');
    if (!el) return;
    if (!date) {
      el.textContent = 'Son güncelleme: —';
      return;
    }
    el.textContent = 'Son güncelleme: ' + fmtTimeStamp(date);
  }

  function syncLiveSelectionHighlight() {
    document.querySelectorAll('#atpVehicleList [data-vehicle-id]').forEach(function (node) {
      node.classList.toggle('atp-lvcard-selected', liveSelectedVehicleId != null &&
        node.getAttribute('data-vehicle-id') === String(liveSelectedVehicleId));
    });
  }

  function toast(msg) {
    var el = document.getElementById('atpToast');
    if (!el) return;
    el.textContent = msg;
    el.classList.add('show');
    setTimeout(function () { el.classList.remove('show'); }, 3200);
  }

  function updatePlanSidebar() {
    var jobEl = document.getElementById('atpPlanSideJobCount');
    var dateEl = document.getElementById('atpPlanSideDate');
    var driverEl = document.getElementById('atpPlanSideDriver');
    var tasks = dashboard.daily_tasks || [];
    if (jobEl) jobEl.textContent = String(tasks.length);
    if (dateEl) dateEl.textContent = dashboard.date_label || planDate;
    var selV = document.getElementById('atpSelVehicle');
    if (driverEl && selV && selV.selectedIndex >= 0) {
      var v = lastVehicles.find(function (x) { return String(x.id) === String(selV.value); });
      driverEl.textContent = (v && v.driver_name) ? v.driver_name : (dashboard.selected_driver_name || '—');
    }
  }

  function updatePlanMap() {
    var planMapData = dashboard.plan_map || { base: {}, stops: [], completeness: {} };
    if (window.AtpPlanMap) {
      window.AtpPlanMap.renderPlanMap(planMapData);
    }
  }

  function applyDashboardUpdate(dto) {
    if (!dto) return;
    dashboard = dto;
    var dashEl = document.getElementById('atpDashboardJson');
    if (dashEl) dashEl.textContent = JSON.stringify(dashboard);
    hydrateVehicleSelect(lastVehicles);
    if (dto.daily_tasks) renderTable(dto.daily_tasks);
    else updatePlanMap();
    updatePlanSidebar();
    refreshPlanRoute();
  }

  function vehicleId() {
    var vid = document.getElementById('atpSelVehicle');
    if (vid && vid.value) return vid.value;
    var fromUrl = new URLSearchParams(window.location.search).get('vehicle_id');
    if (fromUrl) return fromUrl;
    return dashboard.selected_vehicle_id || null;
  }

  function refreshPlanRoute() {
    if (currentTab !== 'gunluk' || !window.AtpRoute) return;
    window.AtpRoute.fetchPlanRoute(planDate, vehicleId(), function (dto) {
      if (dto) {
        dashboard = dto;
        var dashJson = document.getElementById('atpDashboardJson');
        if (dashJson) dashJson.textContent = JSON.stringify(dashboard);
        updatePlanMap();
      }
    });
  }

  window.applyDashboardUpdate = applyDashboardUpdate;
  window.applyAtpDashboard = function (partial) {
    if (partial.base_location) {
      dashboard.base_location = partial.base_location;
      if (dashboard.plan_map) dashboard.plan_map.base = partial.base_location;
    }
    if (partial.plan_map) dashboard.plan_map = partial.plan_map;
    applyDashboardUpdate(dashboard);
  };

  function updateTabLayout(tab) {
    currentTab = tab;
    var isCanli = tab === 'canli';
    var isGunluk = tab === 'gunluk';
    var panel = document.getElementById('atpPanelGunluk');
    var grid = document.getElementById('atpGridMain');
    var liveBox = document.getElementById('atp-live-map-container');
    var planBox = document.getElementById('atp-plan-map-container');
    var hdrLive = document.getElementById('atpMapHdrLive');
    var hdrPlan = document.getElementById('atpMapHdrPlan');
    var mapTitle = document.getElementById('atpMapTitle');
    var routeBlock = document.querySelector('.atp-route');
    var sideLive = document.getElementById('atpSideLive');
    var sidePlan = document.getElementById('atpSidePlan');
    var poolWrap = document.getElementById('atpPoolWrap');
    var planningSection = document.getElementById('atpPlanningSection');
    var v2View = document.getElementById('atpV2GunlukView');

    if (v2View) v2View.style.display = isGunluk ? '' : 'none';
    if (planningSection) {
      if (isCanli) {
        planningSection.open = true;
        planningSection.classList.add('atp-v2-planning-canli');
      } else if (isGunluk) {
        planningSection.classList.remove('atp-v2-planning-canli');
      }
    }

    if (panel) {
      panel.classList.toggle('atp-mode-canli', isCanli);
      panel.classList.toggle('atp-mode-gunluk', isGunluk);
    }
    if (grid) grid.classList.toggle('atp-grid-canli', isCanli);
    if (liveBox) liveBox.style.display = isCanli ? '' : 'none';
    if (planBox) planBox.style.display = isGunluk ? '' : 'none';
    if (hdrLive) hdrLive.style.display = isCanli ? 'flex' : 'none';
    if (hdrPlan) hdrPlan.style.display = isGunluk ? 'flex' : 'none';
    if (mapTitle) mapTitle.textContent = isGunluk ? 'PLAN HARİTASI' : 'CANLI HARİTA';
    if (routeBlock) routeBlock.style.display = isCanli ? 'none' : '';
    if (sideLive) sideLive.classList.toggle('atp-side-hidden', !isCanli);
    if (sidePlan) sidePlan.classList.toggle('atp-side-hidden', !isGunluk);
    if (poolWrap) {
      poolWrap.classList.add('atp-v2-pool-hidden');
      poolWrap.style.display = 'none';
    }

    if (isCanli && window.AtpLiveMap) {
      var list = document.getElementById('atpVehicleList');
      if (list && list.querySelector('.atp-live-loading')) loadLiveVehicles(false);
      else if (liveFetchState === 'error') loadLiveVehicles(false);
      if (liveMergedVehicles.length) renderLiveVehicles(liveMergedVehicles);
      else if (lastVehicles.length) renderLiveVehicles(mergeAllLiveVehicles(lastVehicles, liveOpsCache));
      updateLiveKpi(lastLiveFilomKpi, lastLiveFilomCount, liveOpsCache);
      syncLivePollTimestamp(liveLastPollAt);
      window.AtpLiveMap.onLiveTabShown();
      var vid = new URLSearchParams(window.location.search).get('vehicle_id');
      if (vid) {
        liveSelectedVehicleId = vid;
        syncLiveSelectionHighlight();
        window.AtpLiveMap.focusVehicle(vid);
      }
    }
    if (isGunluk) {
      if (window.AtpPlanMap) window.AtpPlanMap.onPlanTabShown();
      updatePlanMap();
      updatePlanSidebar();
      if (window.loadAtpTodayOps) window.loadAtpTodayOps();
      if (window.AtpRoute && window.AtpPlanMap) {
        var lr = window.AtpRoute.getLastRoute();
        if (lr && lr.current && lr.current.geometry && lr.current.geometry.length) {
          window.AtpPlanMap.setCurrentRouteGeometry(lr.current.geometry);
        }
      }
    }
  }

  function setTab(tab) {
    var gunlukPanel = document.getElementById('atpPanelGunluk');
    var haftalik = document.getElementById('atpPanelHaftalik');
    var gecmis = document.getElementById('atpPanelGecmis');
    var dailyBlock = document.getElementById('atpDailyBlock');
    if (gunlukPanel) gunlukPanel.classList.toggle('atp-panel-hidden', tab !== 'canli' && tab !== 'gunluk');
    if (haftalik) haftalik.classList.toggle('atp-panel-hidden', tab !== 'haftalik');
    if (gecmis) gecmis.classList.toggle('atp-panel-hidden', tab !== 'gecmis');
    if (dailyBlock) dailyBlock.style.display = tab === 'canli' ? 'none' : '';
    document.querySelectorAll('.atp-tab').forEach(function (btn) {
      btn.classList.toggle('active', btn.getAttribute('data-tab') === tab);
    });
    var url = new URL(window.location.href);
    url.searchParams.set('tab', tab);
    history.replaceState({}, '', url.pathname + url.search);
    root.classList.toggle('atp-tab-canli', tab === 'canli');
    root.classList.toggle('atp-tab-gunluk', tab === 'gunluk');
    root.classList.toggle('atp-tab-haftalik', tab === 'haftalik');
    root.classList.toggle('atp-tab-gecmis', tab === 'gecmis');
    if (tab !== 'canli') clearLiveRouteLayer();
    updateTabLayout(tab);
  }

  document.querySelectorAll('.atp-tab').forEach(function (btn) {
    btn.addEventListener('click', function () {
      setTab(btn.getAttribute('data-tab'));
    });
  });

  var initTab = new URLSearchParams(window.location.search).get('tab') || 'gunluk';
  try {
    setTab(initTab);
  } catch (initErr) {
    console.error('ATP tab init:', initErr);
    currentTab = initTab;
  }

  function renderTable(tasks) {
    var tbody = document.getElementById('atpTaskBody');
    if (!tbody) return;
    tbody.innerHTML = tasks.map(function (t) {
      var priCls = t.priority === 'YUKSEK' || t.priority === 'ACIL' ? 'yuksek' : (t.priority === 'DUSUK' ? 'dusuk' : 'normal');
      var stCls = t.status === 'BEKLIYOR' ? 'bekliyor' : (t.status === 'BASLANGIC' ? 'baslangic' : 'planlandi');
      var locBadge = '';
      if (!t.has_coordinates) {
        locBadge = ' <span class="atp-badge atp-loc-missing">Konum Eksik</span>';
      }
      var konumBtn = !t.has_coordinates
        ? ' <button type="button" class="atp-btn atp-btn-xs atp-btn-konum-ekle" data-talep-id="' + t.is_talebi_id + '">Konum Ekle</button>'
        : '';
      return '<tr data-task-id="' + t.id + '" data-talep-id="' + t.is_talebi_id + '">' +
        '<td>' + t.order_no + '</td><td>' + t.planned_time + '</td>' +
        '<td><strong>' + (t.job_title || '') + '</strong><br><small>' + (t.company_name || '') + '</small>' + locBadge + konumBtn + '</td>' +
        '<td>' + (t.address_text || '') + '</td>' +
        '<td><span class="atp-badge atp-pri-' + priCls + '">' + (t.priority_label || '') + '</span></td>' +
        '<td>' + fmtDist(t.distance_km) + '</td>' +
        '<td class="atp-st-' + stCls + '">' + (t.status_label || '') + '</td>' +
        '<td><div class="atp-sort-btns"><button type="button" data-dir="up">▲</button><button type="button" data-dir="down">▼</button></div></td></tr>';
    }).join('');
    bindSortButtons();
    bindKonumButtons(tasks);
    dashboard.daily_tasks = tasks;
    if (dashboard.plan_map) {
      dashboard.plan_map.stops = tasks.map(function (t) {
        return {
          id: t.id, plan_item_id: t.plan_item_id, is_talebi_id: t.is_talebi_id,
          order_no: t.order_no, company_name: t.company_name, job_title: t.job_title,
          planned_time: t.planned_time, address_text: t.address_text,
          priority_label: t.priority_label, latitude: t.latitude, longitude: t.longitude,
          location_status: t.location_status, location_source: t.location_source,
          location_source_label: t.location_source_label, has_coordinates: t.has_coordinates,
          kayitli_yer_id: t.kayitli_yer_id
        };
      });
      var ready = tasks.filter(function (t) { return t.has_coordinates; }).length;
      dashboard.plan_map.completeness = {
        total_stops: tasks.length,
        ready: ready,
        missing: tasks.length - ready,
        base_configured: dashboard.plan_map.base && dashboard.plan_map.base.has_coordinates
      };
      dashboard.location_completeness = dashboard.plan_map.completeness;
    }
    updatePlanSidebar();
    updatePlanMap();
  }

  function bindKonumButtons(tasks) {
    var byTalep = {};
    (tasks || []).forEach(function (t) { byTalep[t.is_talebi_id] = t; });
    document.querySelectorAll('.atp-btn-konum-ekle').forEach(function (btn) {
      btn.onclick = function () {
        var tid = btn.getAttribute('data-talep-id');
        var task = byTalep[tid];
        if (task && window.AtpLocationModals) {
          window.AtpLocationModals.openKonumModal(task, function (j) {
            if (j.dashboard) applyDashboardUpdate(j.dashboard);
            else if (j.daily_tasks) renderTable(j.daily_tasks);
          });
        }
      };
    });
  }

  function fmtDist(km) {
    if (window.AtpFmtDist) return window.AtpFmtDist(km);
    if (km == null || km === '' || km === '—') return '—';
    return km + ' km';
  }

  function reorderApi(taskId, direction) {
    fetch('/planlama/arac-takip/api/reorder', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        date: planDate, task_id: taskId, direction: direction,
        vehicle_id: vehicleId(),
      })
    }).then(function (r) { return r.json(); }).then(function (j) {
      if (j.ok && j.daily_tasks) renderTable(j.daily_tasks);
    }).catch(function () { toast('Sıra güncellenemedi'); });
  }

  function bindSortButtons() {
    document.querySelectorAll('#atpTaskBody .atp-sort-btns button').forEach(function (btn) {
      btn.onclick = function () {
        var tr = btn.closest('tr');
        if (!tr) return;
        reorderApi(tr.getAttribute('data-task-id'), btn.getAttribute('data-dir'));
      };
    });
  }
  bindSortButtons();
  bindKonumButtons(dashboard.daily_tasks || []);

  if (window.AtpRoute) {
    window.AtpRoute.bindRouteUi(planDate, vehicleId, applyDashboardUpdate, renderTable);
  }

  document.getElementById('atpBtnWhatsapp').addEventListener('click', function () {
    var q = '?date=' + encodeURIComponent(planDate);
    var vid = vehicleId();
    if (vid) q += '&vehicle_id=' + encodeURIComponent(vid);
    fetch('/planlama/arac-takip/api/whatsapp' + q, { credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (j.ok && j.whatsapp_url) window.open(j.whatsapp_url, '_blank');
        else toast('WhatsApp mesajı oluşturulamadı');
      })
      .catch(function () { toast('WhatsApp hatası'); });
  });

  document.querySelectorAll('.atp-week-day').forEach(function (el) {
    el.addEventListener('click', function () {
      var d = el.getAttribute('data-date');
      window.location.href = '/planlama/arac-takip?tab=gunluk&date=' + encodeURIComponent(d);
    });
  });

  function buildCalendar(targetId) {
    var cal = document.getElementById(targetId);
    if (!cal) return;
    var parts = planDate.split('-');
    var y = parseInt(parts[0], 10), m = parseInt(parts[1], 10) - 1;
    var first = new Date(y, m, 1);
    var daysInMonth = new Date(y, m + 1, 0).getDate();
    var startWd = (first.getDay() + 6) % 7;
    var html = '<div class="atp-cal-grid">';
    ['Pt', 'Sa', 'Ça', 'Pe', 'Cu', 'Ct', 'Pz'].forEach(function (d) { html += '<span style="font-weight:600">' + d + '</span>'; });
    for (var i = 0; i < startWd; i++) html += '<span></span>';
    var todayStr = new Date().toISOString().slice(0, 10);
    for (var day = 1; day <= daysInMonth; day++) {
      var ds = y + '-' + String(m + 1).padStart(2, '0') + '-' + String(day).padStart(2, '0');
      var cls = ds === planDate ? 'sel' : (ds === todayStr ? 'today' : '');
      html += '<span class="' + cls + '" data-date="' + ds + '">' + day + '</span>';
    }
    html += '</div>';
    cal.innerHTML = html;
    cal.querySelectorAll('[data-date]').forEach(function (sp) {
      sp.addEventListener('click', function () {
        var u = new URL(window.location.href);
        u.searchParams.set('tab', 'gunluk');
        u.searchParams.set('date', sp.getAttribute('data-date'));
        window.location.href = u.pathname + u.search;
      });
    });
  }
  buildCalendar('atpCalendar');
  buildCalendar('atpCalendarLive');

  if (initTab === 'gunluk') updatePlanMap();

  document.getElementById('atpHistFilter').addEventListener('click', function () {
    toast('Geçmiş filtre mock — V1.2\'de backend bağlanacak.');
  });

  var selV = document.getElementById('atpSelVehicle');
  if (selV) selV.addEventListener('change', function () {
    var u = new URL(window.location.href);
    u.searchParams.set('tab', 'gunluk');
    if (selV.value) u.searchParams.set('vehicle_id', selV.value);
    else u.searchParams.delete('vehicle_id');
    window.location.href = u.pathname + u.search;
  });

  function statusDotClass(st) {
    if (st === 'HAREKETLI') return 'green';
    if (st === 'ROLANTI') return 'orange';
    if (st === 'DURAN') return 'red';
    if (st === 'PASIF') return 'gray';
    return 'gray';
  }

  function liveBadge(v) {
    if (v.gps_is_stale || v.is_stale_data) return { cls: 'atp-lv-badge-stale', text: 'GPS Eski' };
    if (v.route_state === 'DEVIATING') return { cls: 'atp-lv-badge-warn', text: '⚠ Sapma' };
    if (v.route_state === 'ON_ROUTE' || v.activity_status === 'HAREKETLI') return { cls: 'atp-lv-badge-ok', text: '● Yolda' };
    if (v.activity_status === 'DURAN') return { cls: 'atp-lv-badge-neutral', text: '⏸ Duran' };
    return { cls: 'atp-lv-badge-neutral', text: fmtVal(v.activity_status_label) };
  }

  function bindVehiclePanelClicks() {
    document.querySelectorAll('#atpVehicleList [data-vehicle-id]').forEach(function (node) {
      node.onclick = function () {
        var id = node.getAttribute('data-vehicle-id');
        liveSelectedVehicleId = id;
        syncLiveSelectionHighlight();
        if (currentTab !== 'canli') setTab('canli');
        if (window.AtpLiveMap) window.AtpLiveMap.focusVehicle(id);
      };
    });
  }

  function renderLiveVehicles(vehicles) {
    var list = document.getElementById('atpVehicleList');
    if (!list) return;
    if (!vehicles || !vehicles.length) {
      list.innerHTML = '<div class="atp-live-empty">Filom API\'de araç bulunamadı.</div>';
      return;
    }
    list.innerHTML = vehicles.map(function (v) {
      var badge = liveBadge(v);
      var driver = v.driver_name || v.driver || '—';
      var plate = v.plate_display || v.plate || '—';
      var speed = v.speed_kmh != null ? (v.speed_kmh + ' km/s') : '—';
      var devNote = fmtLiveDeviationNote(v);
      var gpsNote = (v.gps_is_stale || v.is_stale_data)
        ? fmtGpsAgeShort(v.gps_last_seen_at || v.last_seen_at)
        : '';
      var cardCls = 'atp-lvcard';
      if (v.route_state === 'DEVIATING') cardCls += ' atp-lvcard-warn';
      if (v.gps_is_stale || v.is_stale_data) cardCls += ' atp-lvcard-stale';
      if (liveSelectedVehicleId != null && String(v.id) === String(liveSelectedVehicleId)) {
        cardCls += ' atp-lvcard-selected';
      }
      return '<div class="' + cardCls + '" data-vehicle-id="' + v.id + '">' +
        '<div class="atp-lvcard-plate">' + plate + '</div>' +
        '<div class="atp-lvcard-driver">' + driver + '</div>' +
        '<div class="atp-lvcard-row">' +
        '<span class="atp-lv-badge ' + badge.cls + '">' + badge.text + '</span>' +
        '<span class="atp-lvcard-speed">' + speed + '</span></div>' +
        (devNote ? '<div class="atp-lvcard-note">' + devNote + '</div>' : '') +
        (gpsNote ? '<div class="atp-lvcard-note atp-lvcard-note-muted">' + gpsNote + '</div>' : '') +
        '</div>';
    }).join('');
    bindVehiclePanelClicks();
  }

  function planVehicleOption() {
    var urlId = new URLSearchParams(window.location.search).get('vehicle_id') || '';
    var id = dashboard.selected_vehicle_id || urlId || '';
    if (!id) return null;
    var label = dashboard.selected_plate && dashboard.selected_plate !== '—'
      ? dashboard.selected_plate
      : (dashboard.plan_vehicle && dashboard.plan_vehicle.plate_snapshot) || id;
    return { id: String(id), label: String(label) };
  }

  function hydrateVehicleSelect(vehicles) {
    var sel = document.getElementById('atpSelVehicle');
    var reqSel = document.getElementById('atpReqArac');
    if (!sel && !reqSel) return;
    var planV = planVehicleOption();
    var filom = vehicles || [];
    var urlId = new URLSearchParams(window.location.search).get('vehicle_id') || '';
    var cur = (sel && sel.value) || dashboard.selected_vehicle_id || urlId || '';
    var opts = [{ value: '', label: '— Araç seç —' }];
    var seen = {};
    if (planV && planV.id) {
      opts.push({ value: planV.id, label: planV.label });
      seen[planV.id] = true;
      cur = cur || planV.id;
    }
    filom.forEach(function (v) {
      if (seen[v.id]) return;
      seen[v.id] = true;
      opts.push({ value: String(v.id), label: v.plate_display || v.plate || v.id });
    });
    if (sel) {
      sel.innerHTML = opts.map(function (o) {
        return '<option value="' + o.value + '">' + o.label + '</option>';
      }).join('');
      if (cur && sel.querySelector('option[value="' + cur + '"]')) sel.value = cur;
      else if (planV && planV.id) sel.value = planV.id;
      else if (filom.length === 1) sel.value = filom[0].id;
    }
    if (reqSel) {
      reqSel.innerHTML = opts.filter(function (o) { return o.value; }).map(function (o) {
        return '<option value="' + o.value + '">' + o.label + '</option>';
      }).join('');
      if (!reqSel.options.length) {
        reqSel.innerHTML = '<option value="">— Araç seç —</option>';
      } else if (cur && reqSel.querySelector('option[value="' + cur + '"]')) {
        reqSel.value = cur;
      } else if (filom.length === 1) {
        reqSel.value = filom[0].id;
      }
      syncReqPlanaSofor();
    }
    updatePlanSidebar();
  }

  function syncReqPlanaSofor() {
    var reqSel = document.getElementById('atpReqArac');
    var lbl = document.getElementById('atpReqPlanaSofor');
    if (!reqSel || !lbl) return;
    var v = lastVehicles.find(function (x) { return String(x.id) === String(reqSel.value); });
    lbl.textContent = (v && v.driver_name) ? v.driver_name : '—';
  }

  function fillVehicleSelect(vehicles) {
    lastVehicles = vehicles || lastVehicles;
    hydrateVehicleSelect(lastVehicles);
    if (currentTab === 'gunluk' && window.AtpRoute && !window.AtpRoute.getLastRoute()) {
      refreshPlanRoute();
    }
  }

  hydrateVehicleSelect([]);

  if (window.AtpRoute) {
    refreshPlanRoute();
    window.addEventListener('load', function () {
      setTimeout(refreshPlanRoute, 300);
    });
  }

  function updateLiveKpi(kpi, count, opsData) {
    var isV2 = root.getAttribute('data-mehmet-v2') === '1';
    var isLiveTab = currentTab === 'canli';
    var isDailyTab = currentTab === 'gunluk';
    if (isV2 && !isLiveTab && !isDailyTab) return;
    var elA = document.getElementById('atpKpiAktif');
    var elH = document.getElementById('atpKpiHareket');
    if (kpi) {
      if (elA && kpi.aktif_arac != null) elA.textContent = String(kpi.aktif_arac);
      if (elH && kpi.hareket_halinde != null) elH.textContent = String(kpi.hareket_halinde);
    }
    if (!isLiveTab) return;
    var elSapma = document.getElementById('atpKpiSapma');
    var elSon = document.getElementById('atpKpiSonGuncelleme');
    var elGps = document.getElementById('atpKpiGpsSaglik');
    var sapmaN = countSapma(liveMergedVehicles);
    if (sapmaN === null && opsData && opsData.vehicles) sapmaN = countSapma(opsData.vehicles);
    if (elSapma) elSapma.textContent = sapmaN !== null ? String(sapmaN) : '—';
    if (elSon) {
      elSon.textContent = liveLastPollAt ? fmtTimeStamp(liveLastPollAt) : '—';
    }
    if (elGps) {
      var health = computeGpsHealth(liveMergedVehicles, count);
      elGps.textContent = health ? (health.fresh + '/' + health.total) : '—';
    }
  }

  function showLiveError(isPoll) {
    liveFetchState = 'error';
    var list = document.getElementById('atpVehicleList');
    if (!isPoll && list) list.innerHTML = '<div class="atp-live-error">Canlı araç verisi şu anda alınamıyor.</div>';
    if (currentTab !== 'canli') {
      if (window.AtpLiveMap) window.AtpLiveMap.refreshLiveVehicles(vehiclesForMap(liveMergedVehicles.length ? liveMergedVehicles : lastVehicles), { failed: true });
      return;
    }
    if (!isPoll) {
      var liveKpiIds = ['atpKpiAktif', 'atpKpiHareket', 'atpKpiSapma', 'atpKpiSonGuncelleme', 'atpKpiGpsSaglik'];
      liveKpiIds.forEach(function (id) {
        var el = document.getElementById(id);
        if (el) el.textContent = '—';
      });
      setLiveRefreshBar(null);
    }
    if (window.AtpLiveMap) {
      window.AtpLiveMap.refreshLiveVehicles(vehiclesForMap(liveMergedVehicles.length ? liveMergedVehicles : lastVehicles), { failed: true });
    }
  }

  function applyLiveData(j, opsData, isPoll) {
    if (opsData && opsData.ok) {
      liveOpsCache = opsData;
      liveRouteGeometries = extractRouteGeometries(opsData);
      updateRouteButtonState();
    }
    if (j.ok && j.vehicles) {
      liveFetchState = 'ok';
      var opsBundle = opsData && opsData.ok ? opsData : liveOpsCache;
      lastLiveFilomKpi = j.kpi || null;
      lastLiveFilomCount = j.count != null ? j.count : j.vehicles.length;
      lastVehicles = j.vehicles;
      liveMergedVehicles = mergeAllLiveVehicles(j.vehicles, opsBundle);
      renderLiveVehicles(liveMergedVehicles);
      syncLivePollTimestamp(new Date());
      updateLiveKpi(lastLiveFilomKpi, lastLiveFilomCount, opsBundle);
      fillVehicleSelect(j.vehicles);
      var forMap = vehiclesForMap(liveMergedVehicles);
      if (window.AtpLiveMap) {
        window.AtpLiveMap.refreshLiveVehicles(forMap, { success: true, silent: isPoll });
        if (currentTab === 'canli') window.AtpLiveMap.onLiveTabShown();
        syncLivePollTimestamp(liveLastPollAt);
      }
      if (liveRoutesVisible && liveRouteGeometries.length) {
        setTimeout(function () { drawLiveRouteLayer(); }, 120);
      }
    } else if (!isPoll) {
      showLiveError(false);
    } else {
      showLiveError(true);
    }
  }

  function loadLiveVehicles(isPoll) {
    liveFetchState = 'loading';
    if (!isPoll) {
      var list = document.getElementById('atpVehicleList');
      if (list) list.innerHTML = '<div class="atp-live-loading">Canlı araç verisi yükleniyor…</div>';
    }
    var ctrl = typeof AbortController !== 'undefined' ? new AbortController() : null;
    var tid = setTimeout(function () {
      if (ctrl) ctrl.abort();
    }, LIVE_FETCH_TIMEOUT_MS);
    var opts = { credentials: 'same-origin' };
    if (ctrl) opts.signal = ctrl.signal;
    var today = planDate || new Date().toISOString().slice(0, 10);
    var opsUrl = '/planlama/arac-takip/api/today-operations?date=' + encodeURIComponent(today);
    Promise.all([
      fetch('/planlama/arac-takip/api/araclar', opts)
        .then(function (r) { return r.json().then(function (j) { return { status: r.status, body: j }; }); }),
      fetch(opsUrl, { credentials: 'same-origin' })
        .then(function (r) { return r.ok ? r.json() : null; })
        .catch(function () { return null; })
    ]).then(function (results) {
      clearTimeout(tid);
      applyLiveData(results[0].body, results[1], !!isPoll);
    }).catch(function () {
      clearTimeout(tid);
      showLiveError(!!isPoll);
    });
  }

  loadLiveVehicles(false);
  pollTimer = setInterval(function () { loadLiveVehicles(true); }, LIVE_POLL_MS);
  window.addEventListener('beforeunload', function () {
    if (pollTimer) clearInterval(pollTimer);
  });

  var btnFitMap = document.getElementById('atpBtnFitAllMap');
  if (btnFitMap) {
    btnFitMap.addEventListener('click', function () {
      if (window.AtpLiveMap) window.AtpLiveMap.fitAll();
    });
  }
  var btnShowRoutes = document.getElementById('atpBtnShowRoutes');
  if (btnShowRoutes) btnShowRoutes.addEventListener('click', toggleLiveRoutes);
  var btnLiveRefresh = document.getElementById('atpLiveRefreshBtn');
  if (btnLiveRefresh) btnLiveRefresh.addEventListener('click', function () { loadLiveVehicles(false); });

  /* ─── Mehmet V2 — today-operations + Plana İş Ekle ─── */
  if (root.getAttribute('data-mehmet-v2') === '1') {
    var miniMap = null;
    var miniLayer = null;
    var opsTimer = null;

    function fmtVal(v) {
      return v === null || v === undefined || v === '' ? '—' : String(v);
    }

    function fmtGpsAge(ts) {
      if (!ts) return 'Henüz GPS verisi yok';
      var d = new Date(String(ts).replace(' ', 'T'));
      if (isNaN(d.getTime())) return fmtVal(ts);
      var mins = Math.round((Date.now() - d.getTime()) / 60000);
      if (mins < 1) return 'Son GPS: az önce';
      if (mins < 120) return 'Son GPS: ' + mins + ' dk önce';
      return 'Son GPS: ' + ts;
    }

    function fmtDeviation(v) {
      if (v.route_state !== 'DEVIATING') return '';
      var m = v.current_deviation_m;
      if (m == null) return 'Rotadan sapıyor';
      var km = (Number(m) / 1000).toLocaleString('tr-TR', { maximumFractionDigits: 1 });
      var dur = '';
      if (v.deviation_started_at) {
        var dd = new Date(String(v.deviation_started_at).replace(' ', 'T'));
        if (!isNaN(dd.getTime())) {
          var dm = Math.max(0, Math.round((Date.now() - dd.getTime()) / 60000));
          dur = dm ? (' · ' + dm + ' dakikadır devam ediyor') : '';
        }
      }
      return 'Rotadan ' + km + ' km saptı' + dur;
    }

    function renderKpiV2(kpi) {
      if (!kpi || currentTab === 'canli') return;
      var map = {
        atpKpiAktif: kpi.aktif_arac,
        atpKpiHareket: kpi.hareket_halinde,
        atpKpiIs: kpi.toplam_is,
        atpKpiTamam: kpi.tamamlandi,
        atpKpiDevam: kpi.devam_ediyor,
        atpKpiSorun: kpi.sorunlu,
      };
      Object.keys(map).forEach(function (id) {
        var el = document.getElementById(id);
        if (!el) return;
        var val = map[id];
        el.textContent = val === null || val === undefined || val === '' ? '—' : String(val);
      });
    }

    function badgeClass(v) {
      if (v.gps_stale) return 'atp-v2-badge-warn';
      if (v.route_state === 'DEVIATING') return 'atp-v2-badge-warn';
      if (v.route_state === 'ON_ROUTE') return 'atp-v2-badge-ok';
      return 'atp-v2-badge-neutral';
    }

    function vehicleCardClass(v) {
      if (v.route_state === 'DEVIATING' || v.gps_stale) return 'warn';
      return 'ok';
    }

    function visitRowClass(state) {
      if (state === 'ARRIVED') return 'atp-v2-visit-arrived';
      if (state === 'DEPARTED_PENDING') return 'atp-v2-visit-departed';
      return 'atp-v2-visit-muted';
    }

    function renderVehicleCards(vehicles) {
      var wrap = document.getElementById('atpVehicleCards');
      if (!wrap) return;
      if (!vehicles || !vehicles.length) {
        wrap.innerHTML = '<div class="atp-v2-empty">Henüz planlı araç yok.</div>';
        return;
      }
      wrap.innerHTML = vehicles.map(function (v) {
        var pct = v.progress_total ? Math.round(100 * v.progress_completed / v.progress_total) : 0;
        var cardCls = vehicleCardClass(v);
        var devLine = v.deviation_label || fmtDeviation(v);
        var gpsLine = v.gps_is_stale || v.gps_stale
          ? '<span class="atp-v2-stale">⚠ GPS verisi eski</span>'
          : (v.route_status_label ? fmtVal(v.route_status_label) : '—');
        var visitLine = v.visit_label ? fmtVal(v.visit_label) : '';
        var openLabel = v.route_state === 'DEVIATING' ? 'İncele' : 'Planı Aç';
        var vid = v.arac_external_id || '';
        var planId = v.plan_id || '';

        var leftBlock =
          '<div class="atp-v2-vcard-main">' +
          '<div class="atp-v2-plate">' + fmtVal(v.plate) + '</div>' +
          '<div class="atp-v2-driver">' + fmtVal(v.driver) + '</div>' +
          '<div style="margin-top:4px"><span class="atp-v2-badge ' + badgeClass(v) + '">' + fmtVal(v.route_status_label) + '</span></div>' +
          '<div class="atp-v2-progress" style="margin-top:6px">' +
          '<div class="atp-v2-progress-track"><div class="atp-v2-progress-fill" style="width:' + pct + '%"></div></div>' +
          '<span class="atp-v2-progress-lbl">' + fmtVal(v.progress_label) + '</span></div>' +
          '</div>';

        var midBlock =
          '<div class="atp-v2-vcard-detail">' +
          '<div class="atp-v2-detail-row"><span class="atp-v2-detail-icon">📍</span>Sıradaki: <strong>' + fmtVal(v.next_stop) + '</strong></div>' +
          '<div class="atp-v2-detail-row"><span class="atp-v2-detail-icon">🕐</span>Saat: ' + fmtVal(v.next_time) + '</div>' +
          (visitLine ? '<div class="atp-v2-detail-row"><span class="atp-v2-detail-icon">🏁</span>' + visitLine + '</div>' : '') +
          (devLine ? '<div class="atp-v2-detail-row warn"><span class="atp-v2-detail-icon">📏</span>' + devLine + '</div>' : '') +
          '<div class="atp-v2-detail-row"><span class="atp-v2-detail-icon">📡</span>' + gpsLine +
          ' <em style="color:#9ca3af;margin-left:4px">' + fmtGpsAge(v.gps_last_seen_at || v.gps_timestamp) + '</em></div>' +
          '<div class="atp-v2-detail-row"><span class="atp-v2-detail-icon">🚦</span>' + fmtVal(v.physical_status) + '</div>' +
          '</div>';

        var rightBlock =
          '<div class="atp-v2-vcard-action">' +
          '<button type="button" class="atp-btn atp-btn-sm atp-v2-open-plan" data-vid="' + vid + '">' + openLabel + '</button>' +
          (planId ? '<button type="button" class="atp-btn atp-btn-sm atp-v2-timeline-btn" data-plan-id="' + planId + '" data-vid="' + vid + '">Zaman Çizelgesi</button>' : '') +
          (v.route_state === 'DEVIATING'
            ? '<button type="button" class="atp-btn atp-btn-sm atp-v2-open-plan" data-vid="' + vid + '">Planı Aç</button>'
            : '') +
          '</div>';

        return '<div class="atp-v2-vehicle-card ' + cardCls + '" data-vid="' + vid + '">' +
          '<div class="atp-v2-vcard-inner">' + leftBlock + midBlock + rightBlock + '</div></div>';
      }).join('');

      wrap.querySelectorAll('.atp-v2-open-plan').forEach(function (btn) {
        btn.addEventListener('click', function () {
          var vid = btn.getAttribute('data-vid');
          var sel = document.getElementById('atpSelVehicle');
          if (sel && vid) { sel.value = vid; sel.dispatchEvent(new Event('change')); }
          var det = document.getElementById('atpPlanningSection');
          if (det) det.open = true;
        });
      });
      wrap.querySelectorAll('.atp-v2-timeline-btn').forEach(function (btn) {
        btn.addEventListener('click', function (e) {
          e.stopPropagation();
          openTimelineModal(btn.getAttribute('data-plan-id'), btn.getAttribute('data-vid'));
        });
      });
    }

    function planBadgeClass(status, visitState) {
      if (status === 'TAMAMLANDI') return 'atp-v2-badge-ok';
      if (visitState === 'DEPARTED_PENDING') return 'atp-v2-badge-warn';
      if (status === 'BASLANGIC') return 'atp-v2-badge-ok';
      return 'atp-v2-badge-neutral';
    }

    var _jobsExpanded = false;
    var _jobsAllItems = [];
    var JOBS_PREVIEW = 5;

    function _buildJobRow(it) {
      var visitCls = visitRowClass(it.visit_state);
      var actionLabel = it.visit_state === 'DEPARTED_PENDING' && it.status !== 'TAMAMLANDI' ? 'Sonuçlandır' : 'Görüntüle';
      return '<tr data-plan-item="' + (it.plan_item_id || '') + '">' +
        '<td class="job-time">' + fmtVal(it.planned_time) + '</td>' +
        '<td><div class="atp-v2-job-title">' + fmtVal(it.job_title) + '</div>' +
        '<div class="atp-v2-job-sub">' + fmtVal(it.company_name) + '</div></td>' +
        '<td>' + fmtVal(it.driver) + '</td>' +
        '<td><span class="atp-v2-badge ' + planBadgeClass(it.status, it.visit_state) + '">' + fmtVal(it.status_label) + '</span></td>' +
        '<td><span class="' + visitCls + '">' + fmtVal(it.visit_label) + '</span></td>' +
        '<td><button type="button" class="atp-btn atp-btn-xs atp-v2-inspect" data-vid="' + (it.arac_external_id || '') + '" data-plan-item="' + (it.plan_item_id || '') + '">' + actionLabel + '</button></td></tr>';
    }

    function _renderJobsWithToggle(items, body) {
      var show = _jobsExpanded ? items : items.slice(0, JOBS_PREVIEW);
      var rows = show.map(_buildJobRow).join('');
      if (items.length > JOBS_PREVIEW) {
        var label = _jobsExpanded
          ? 'Daralt'
          : ('Tümünü Gör (' + items.length + ')');
        rows += '<tr class="atp-v2-jobs-more-row"><td colspan="6"><button class="atp-v2-jobs-more-btn" id="atpJobsMoreBtn">' + label + '</button></td></tr>';
      }
      body.innerHTML = rows;
      body.querySelectorAll('.atp-v2-inspect').forEach(function (btn) {
        btn.addEventListener('click', function () {
          var vid = btn.getAttribute('data-vid');
          var sel = document.getElementById('atpSelVehicle');
          if (sel && vid) { sel.value = vid; sel.dispatchEvent(new Event('change')); }
          var det = document.getElementById('atpPlanningSection');
          if (det) det.open = true;
        });
      });
      var moreBtn = document.getElementById('atpJobsMoreBtn');
      if (moreBtn) {
        moreBtn.addEventListener('click', function () {
          _jobsExpanded = !_jobsExpanded;
          _renderJobsWithToggle(_jobsAllItems, body);
        });
      }
    }

    function renderJobs(items) {
      /* support both old id and new id */
      var body = document.getElementById('atpDailyJobsBody') || document.getElementById('atpV2JobsBody');
      if (!body) return;
      _jobsAllItems = items || [];
      if (!_jobsAllItems.length) {
        body.innerHTML = '<tr><td colspan="6" class="atp-v2-empty">Bugün plan verisi yok.</td></tr>';
        return;
      }
      _renderJobsWithToggle(_jobsAllItems, body);
    }

    var ALERTS_PREVIEW = 3;

    function renderAlerts(alerts, normalMsg) {
      var body = document.getElementById('atpAlertsBody');
      if (!body) return;
      if (!alerts || !alerts.length) {
        body.innerHTML = '<p class="atp-v2-normal">' + (normalMsg || 'Bugünkü plan normal ilerliyor') + '</p>';
        return;
      }
      var show = alerts.slice(0, ALERTS_PREVIEW);
      var html = show.map(function (a) {
        var sev = a.severity || 'info';
        var iconMap = { warning: '⚠️', danger: '🔴', info: 'ℹ️' };
        var icon = iconMap[sev] || 'ℹ️';
        return '<div class="atp-v2-alert atp-v2-alert-' + sev + '">' +
          '<span class="atp-v2-alert-icon">' + icon + '</span>' +
          '<div class="atp-v2-alert-body">' +
          '<div class="atp-v2-alert-firm">' + fmtVal(a.title || a.firm || '') + '</div>' +
          '<div class="atp-v2-alert-desc">' + fmtVal(a.message || '') + '</div>' +
          '</div>' +
          '<span></span>' +
          '</div>';
      }).join('');
      if (alerts.length > ALERTS_PREVIEW) {
        html += '<div class="atp-v2-alerts-more"><button class="atp-v2-alerts-more-btn">Tümünü Gör (' + alerts.length + ')</button></div>';
      }
      body.innerHTML = html;
    }

    function renderMiniMap(mapData) {
      var box = document.getElementById('atpMiniMap');
      if (!box || !window.L) return;
      if (!miniMap) {
        miniMap = L.map(box, { zoomControl: false, attributionControl: false }).setView([41.0, 29.0], 10);
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 18 }).addTo(miniMap);
        miniLayer = L.layerGroup().addTo(miniMap);
      }
      miniLayer.clearLayers();
      var pts = [];
      (mapData && mapData.vehicles || []).forEach(function (v) {
        if (v.lat == null) return;
        var m = L.circleMarker([v.lat, v.lng], { radius: 6, color: v.stale ? '#b54708' : '#027a48', fillOpacity: 0.9 });
        m.bindTooltip(v.plate || v.id);
        miniLayer.addLayer(m);
        pts.push([v.lat, v.lng]);
      });
      if (pts.length) miniMap.fitBounds(pts, { padding: [20, 20], maxZoom: 12 });
      setTimeout(function () { if (miniMap) miniMap.invalidateSize(); }, 200);
    }

    function updatePrsSummaryBand(vehicles) {
      /* Seçili aracı bul (atpSelVehicle veya ilk araç) */
      var selEl = document.getElementById('atpSelVehicle');
      var selVid = selEl ? selEl.value : null;
      var chosen = null;
      if (vehicles && vehicles.length) {
        if (selVid) chosen = vehicles.filter(function (v) { return String(v.arac_external_id) === String(selVid); })[0];
        if (!chosen) chosen = vehicles[0];
      }
      var prsArac  = document.getElementById('atpPrsArac');
      var prsSofor = document.getElementById('atpPrsSofor');
      var prsBtnPrs = document.getElementById('atpBtnPlanaIsEklePrs');
      if (prsArac)  prsArac.textContent  = chosen ? fmtVal(chosen.plate)  : '—';
      if (prsSofor) prsSofor.textContent = chosen ? fmtVal(chosen.driver) : '—';
      if (prsBtnPrs) prsBtnPrs.style.display = chosen ? '' : 'none';
    }

    function timelineDotClass(type) {
      if (type === 'KONUMA_VARILDI' || type === 'ROTA_GERI_DONDU') return 'green';
      if (type === 'KONUMDAN_AYRILDI' || type === 'ROTA_SAPMA_BASLADI') return 'orange';
      if (type === 'AMBIGUOUS_STOP') return 'red';
      return 'gray';
    }

    function closeTimelineModal() {
      var bd = document.getElementById('atpTimelineBackdrop');
      var md = document.getElementById('atpTimelineModal');
      if (bd) { bd.classList.remove('open'); bd.setAttribute('aria-hidden', 'true'); }
      if (md) md.setAttribute('aria-hidden', 'true');
    }

    function openTimelineModal(planId, vehicleId) {
      var bd = document.getElementById('atpTimelineBackdrop');
      var md = document.getElementById('atpTimelineModal');
      var body = document.getElementById('atpTimelineBody');
      if (!bd || !md || !body) return;
      body.innerHTML = '<p class="atp-v2-normal">Yükleniyor…</p>';
      bd.classList.add('open');
      bd.setAttribute('aria-hidden', 'false');
      md.setAttribute('aria-hidden', 'false');
      var qs = [];
      if (planId) qs.push('plan_id=' + encodeURIComponent(planId));
      if (vehicleId) qs.push('vehicle_id=' + encodeURIComponent(vehicleId));
      if (planDate) qs.push('date=' + encodeURIComponent(planDate));
      fetch('/planlama/arac-takip/api/plan-timeline?' + qs.join('&'), { credentials: 'same-origin' })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (!data || !data.ok) {
            body.innerHTML = '<p class="atp-v2-normal">Olay verisi alınamadı.</p>';
            return;
          }
          if (!data.events || !data.events.length) {
            body.innerHTML = '<p class="atp-v2-normal">Bu plan için henüz kayıtlı olay yok.</p>';
            return;
          }
          body.innerHTML = '<div class="atp-timeline-list">' + data.events.map(function (ev) {
            return '<div class="atp-timeline-row">' +
              '<div class="atp-timeline-time">' + fmtVal(ev.time_display || ev.time) + '</div>' +
              '<div class="atp-timeline-dot ' + timelineDotClass(ev.type) + '"></div>' +
              '<div class="atp-timeline-text">' +
              '<div class="atp-timeline-title">' + fmtVal(ev.title) + '</div>' +
              '<div class="atp-timeline-desc">' + fmtVal(ev.message) + '</div>' +
              '</div></div>';
          }).join('') + '</div>';
        })
        .catch(function () {
          body.innerHTML = '<p class="atp-v2-normal">Olay verisi alınamadı.</p>';
        });
    }

    ['atpTimelineClose', 'atpTimelineDismiss'].forEach(function (id) {
      var btn = document.getElementById(id);
      if (btn) btn.addEventListener('click', closeTimelineModal);
    });
    var tlBackdrop = document.getElementById('atpTimelineBackdrop');
    if (tlBackdrop) {
      tlBackdrop.addEventListener('click', function (e) {
        if (e.target === tlBackdrop) closeTimelineModal();
      });
    }

    function _opsShowError(status) {
      var kpiIds = ['atpKpiAktif','atpKpiHareket','atpKpiIs','atpKpiTamam','atpKpiDevam','atpKpiSorun'];
      kpiIds.forEach(function (id) { var el = document.getElementById(id); if (el) el.textContent = '—'; });
      var wrap = document.getElementById('atpVehicleCards');
      var jobWrap = document.getElementById('atpDailyJobsBody');
      var alertWrap = document.getElementById('atpAlertsList');
      var msg = '<div class="atp-v2-error-state">' +
        'Plan verisi şu anda alınamadı. <button type="button" class="atp-v2-retry-btn" onclick="window.loadAtpTodayOps&&window.loadAtpTodayOps()">Yeniden dene</button>' +
        '</div>';
      if (wrap) wrap.innerHTML = msg;
      if (jobWrap) jobWrap.innerHTML = '<tr><td colspan="5" class="atp-v2-empty">Veri yok.</td></tr>';
      if (alertWrap) alertWrap.innerHTML = '';
      console.warn('[AracTakipV2] today-operations hata', status || 'network');
    }

    function loadOps() {
      if (currentTab !== 'gunluk') return;
      fetch('/planlama/arac-takip/api/today-operations?date=' + encodeURIComponent(planDate), { credentials: 'same-origin' })
        .then(function (r) {
          if (!r.ok) {
            console.warn('[AracTakipV2] today-operations HTTP', r.status);
            _opsShowError(r.status);
            return null;
          }
          return r.json();
        })
        .then(function (data) {
          if (!data) return;
          if (!data.ok) { _opsShowError('nok'); return; }
          renderKpiV2(data.kpi);
          renderVehicleCards(data.vehicles);
          renderJobs(data.items);
          renderAlerts(data.alerts, data.alerts_normal_message);
          renderMiniMap(data.map);
          /* Planlama & Rota özet bant güncelle */
          updatePrsSummaryBand(data.vehicles);
          /* İş sayısı güncelle */
          var prsIs = document.getElementById('atpPrsIsSayisi');
          if (prsIs) prsIs.textContent = data.items ? data.items.length : '—';
        })
        .catch(function (err) {
          console.warn('[AracTakipV2] today-operations fetch error', err);
          _opsShowError('network');
        });
    }

    window.loadAtpTodayOps = loadOps;

    var btnPlana = document.getElementById('atpBtnPlanaIsEkle');
    var reqModal = document.getElementById('atpRequestModal');
    var reqBackdrop = document.getElementById('atpModalBackdrop');
    var modalTitle = document.getElementById('atpModalTitle');
    var modalSubmit = document.getElementById('atpModalSubmit');

    function setPlanaModalMode(on) {
      if (modalTitle) modalTitle.textContent = on ? 'Plana İş Ekle' : 'Yeni İş Talebi';
      if (modalSubmit) {
        modalSubmit.textContent = on
          ? (modalSubmit.getAttribute('data-label-plana') || 'Plana Ekle')
          : (modalSubmit.getAttribute('data-label-request') || 'Talebi Oluştur');
      }
      if (reqModal) {
        if (on) reqModal.setAttribute('data-plana-mode', '1');
        else reqModal.removeAttribute('data-plana-mode');
      }
      var reqTarih = document.getElementById('atpReqTarih');
      if (on && reqTarih) reqTarih.value = planDate;
      if (on) syncReqPlanaSofor();
    }

    function openPlanaModal() {
      setPlanaModalMode(true);
      var hiddenReq = document.getElementById('atpBtnNewRequest');
      if (hiddenReq) hiddenReq.click();
    }

    if (btnPlana) btnPlana.addEventListener('click', openPlanaModal);

    var btnPlanaprs = document.getElementById('atpBtnPlanaIsEklePrs');
    if (btnPlanaprs) btnPlanaprs.addEventListener('click', function (e) {
      e.preventDefault();
      e.stopPropagation();
      openPlanaModal();
    });

    var reqArac = document.getElementById('atpReqArac');
    if (reqArac) reqArac.addEventListener('change', syncReqPlanaSofor);

    var v2Date = document.getElementById('atpV2DatePicker');
    if (v2Date) {
      v2Date.addEventListener('change', function () {
        var u = new URL(window.location.href);
        u.searchParams.set('tab', 'gunluk');
        u.searchParams.set('date', v2Date.value);
        window.location.href = u.pathname + u.search;
      });
    }

    var v2BaseBtn = document.getElementById('atpV2BtnBaseLocation');
    var baseBtn = document.getElementById('atpBtnBaseLocation');
    if (v2BaseBtn && baseBtn) {
      v2BaseBtn.addEventListener('click', function () { baseBtn.click(); });
    }

    function readSoforFromForm() {
      var form = document.getElementById('atpRequestForm');
      if (!form) return null;
      var checked = form.querySelector('input[name="sofor_secim"]:checked');
      var code = checked ? checked.value : 'OKTAY';
      if (code === 'OKTAY') return 'Oktay KAŞIKÇI';
      if (code === 'SERHAT') return 'Serhat GÜLMEN';
      var other = document.getElementById('atpSoforOtherName');
      return other && other.value.trim() ? other.value.trim() : null;
    }

    function readLocFromDom() {
      var masterId = document.getElementById('atpLocMasterId');
      var cardFirma = document.getElementById('atpLocCardFirma');
      var cardAdres = document.getElementById('atpLocCardAdres');
      var search = document.getElementById('atpLocSearch');
      var newFirma = document.getElementById('atpNewFirma');
      var newAdres = document.getElementById('atpNewAdres');
      var newMaps = document.getElementById('atpNewMaps');
      var locCard = document.getElementById('atpLocCard');
      if (locCard && !locCard.hidden && cardFirma) {
        return {
          firma: cardFirma.textContent.trim(),
          adres: cardAdres ? cardAdres.textContent.trim() : '',
          location_master_id: masterId ? masterId.value : '',
          maps_url: '',
        };
      }
      if (newFirma && newFirma.value.trim()) {
        return {
          firma: newFirma.value.trim(),
          adres: newAdres ? newAdres.value.trim() : '',
          location_master_id: masterId ? masterId.value : '',
          maps_url: newMaps ? newMaps.value.trim() : '',
        };
      }
      return {
        firma: search ? search.value.trim() : '',
        adres: '',
        location_master_id: masterId ? masterId.value : '',
        maps_url: '',
      };
    }

    function buildPlanaPayload() {
      var reqSel = document.getElementById('atpReqArac');
      var sideSel = document.getElementById('atpSelVehicle');
      var aracId = (reqSel && reqSel.value) || (sideSel && sideSel.value) || '';
      var loc = readLocFromDom();
      var payload = {
        plan_tarihi: planDate,
        tarih: planDate,
        arac_external_id: aracId,
        arac_plaka: reqSel && reqSel.selectedOptions[0] ? reqSel.selectedOptions[0].textContent : '',
        yapilacak_is: document.getElementById('atpReqIs') && document.getElementById('atpReqIs').value.trim(),
        is: document.getElementById('atpReqIs') && document.getElementById('atpReqIs').value.trim(),
        firma: loc.firma,
        adres: loc.adres,
        location_master_id: loc.location_master_id || null,
        kayitli_yer_id: loc.location_master_id || null,
        maps_url: loc.maps_url || undefined,
        planlanan_saat: document.getElementById('atpReqSaat') && document.getElementById('atpReqSaat').value,
        oncelik: document.getElementById('atpReqOncelik') && document.getElementById('atpReqOncelik').value,
        sofor_adi: readSoforFromForm(),
        ek_not: document.getElementById('atpReqNot') && document.getElementById('atpReqNot').value.trim(),
      };
      var urun = document.getElementById('atpReqUrun');
      var miktar = document.getElementById('atpReqMiktar');
      var birim = document.getElementById('atpReqBirim');
      if (urun && urun.value.trim()) payload.urun_malzeme = urun.value.trim();
      if (miktar && miktar.value.trim()) payload.miktar = miktar.value.trim();
      if (birim && birim.value) payload.miktar_birim = birim.value;
      var isTuru = document.querySelector('#atpRequestForm input[name="is_turu"]:checked');
      if (isTuru) payload.is_turu = isTuru.value;
      return payload;
    }

    var reqForm = document.getElementById('atpRequestForm');
    if (reqForm) {
      reqForm.addEventListener('submit', function (ev) {
        if (reqForm.getAttribute('data-plana-handler')) return;
        var modal = document.getElementById('atpRequestModal');
        if (!modal || modal.getAttribute('data-plana-mode') !== '1') return;
        ev.preventDefault();
        ev.stopImmediatePropagation();
        var payload = buildPlanaPayload();
        if (!payload.arac_external_id) { toast('Araç seçin'); return; }
        if (!payload.is) { toast('Yapılacak iş gerekli'); return; }
        if (!payload.firma && !payload.location_master_id) { toast('Firma veya kayıtlı yer seçin'); return; }
        fetch('/planlama/arac-takip/api/plana-is-ekle', {
          method: 'POST',
          credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        }).then(function (r) { return r.json(); }).then(function (res) {
          if (res.ok) {
            toast('İş plana eklendi');
            setPlanaModalMode(false);
            reqBackdrop.classList.remove('open');
            modal.classList.remove('open');
            document.body.style.overflow = '';
            loadOps();
            if (res.dashboard && window.applyDashboardUpdate) window.applyDashboardUpdate(res.dashboard);
            else refreshPlanRoute();
          } else {
            toast(res.error || 'Plana eklenemedi');
          }
        }).catch(function () { toast('Plana eklenemedi'); });
      }, true);
      reqForm.setAttribute('data-plana-handler', '1');
    }

    var modalClose = document.getElementById('atpModalClose');
    var modalCancel = document.getElementById('atpModalCancel');
    [modalClose, modalCancel].forEach(function (btn) {
      if (!btn) return;
      btn.addEventListener('click', function () { setPlanaModalMode(false); });
    });

    loadOps();
    opsTimer = setInterval(loadOps, 60000);
    window.addEventListener('beforeunload', function () {
      if (opsTimer) clearInterval(opsTimer);
    });
  }
})();
