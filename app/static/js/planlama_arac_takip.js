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
  var liveFetchState = 'idle';

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
    if (poolWrap) poolWrap.style.display = isGunluk ? '' : 'none';

    if (isCanli && window.AtpLiveMap) {
      var list = document.getElementById('atpVehicleList');
      if (list && list.querySelector('.atp-live-loading')) loadLiveVehicles(false);
      else if (liveFetchState === 'error') loadLiveVehicles(false);
      if (lastVehicles.length) renderLiveVehicles(lastVehicles);
      window.AtpLiveMap.onLiveTabShown();
      var vid = new URLSearchParams(window.location.search).get('vehicle_id');
      if (vid) window.AtpLiveMap.focusVehicle(vid);
    }
    if (isGunluk) {
      if (window.AtpPlanMap) window.AtpPlanMap.onPlanTabShown();
      updatePlanMap();
      updatePlanSidebar();
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

  function bindVehiclePanelClicks() {
    document.querySelectorAll('#atpVehicleList li[data-vehicle-id]').forEach(function (li) {
      li.onclick = function () {
        var id = li.getAttribute('data-vehicle-id');
        if (currentTab !== 'canli') setTab('canli');
        if (window.AtpLiveMap) window.AtpLiveMap.focusVehicle(id);
      };
    });
  }

  function renderLiveVehicles(vehicles) {
    var list = document.getElementById('atpVehicleList');
    if (!list) return;
    if (!vehicles || !vehicles.length) {
      list.innerHTML = '<li class="atp-live-empty">Filom API\'de araç bulunamadı.</li>';
      return;
    }
    list.innerHTML = vehicles.map(function (v) {
      var driver = v.driver_name || '—';
      var plate = v.plate_display || v.plate || '—';
      var stale = v.is_stale_data ? ' <span class="atp-stale-badge">Eski veri</span>' : '';
      return '<li data-vehicle-id="' + v.id + '" class="atp-veh-row">' +
        '<span class="atp-dot atp-dot-' + statusDotClass(v.activity_status) + '"></span><div>' +
        '<strong>' + plate + '</strong>' + stale + ' · ' + driver + '<br>' +
        '<small>' + (v.speed_kmh != null ? v.speed_kmh : 0) + ' km/s · ' + (v.activity_status_label || '—') + '</small></div></li>';
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
    if (!sel) return;
    var planV = planVehicleOption();
    var filom = vehicles || [];
    var urlId = new URLSearchParams(window.location.search).get('vehicle_id') || '';
    var cur = sel.value || dashboard.selected_vehicle_id || urlId || '';
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
    sel.innerHTML = opts.map(function (o) {
      return '<option value="' + o.value + '">' + o.label + '</option>';
    }).join('');
    if (cur && sel.querySelector('option[value="' + cur + '"]')) sel.value = cur;
    else if (planV && planV.id) sel.value = planV.id;
    else if (filom.length === 1) sel.value = filom[0].id;
    updatePlanSidebar();
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

  function updateLiveKpi(kpi, count) {
    var elA = document.getElementById('atpKpiAktif');
    var elAS = document.getElementById('atpKpiAktifSub');
    var elH = document.getElementById('atpKpiHareket');
    var elHS = document.getElementById('atpKpiHareketSub');
    if (kpi) {
      if (elA) elA.textContent = kpi.aktif_arac != null ? kpi.aktif_arac : '—';
      if (elAS) elAS.textContent = 'Toplam ' + (kpi.aktif_arac_toplam != null ? kpi.aktif_arac_toplam : count) + ' araç';
      if (elH) elH.textContent = kpi.hareket_halinde != null ? kpi.hareket_halinde : '—';
      if (elHS) elHS.textContent = kpi.hareket_pct != null ? ('%' + kpi.hareket_pct) : '';
    }
  }

  function showLiveError(isPoll) {
    liveFetchState = 'error';
    var list = document.getElementById('atpVehicleList');
    if (!isPoll && list) list.innerHTML = '<li class="atp-live-error">Canlı araç verisi şu anda alınamıyor.</li>';
    if (currentTab !== 'canli') {
      if (window.AtpLiveMap) window.AtpLiveMap.refreshLiveVehicles(lastVehicles, { failed: true });
      return;
    }
    if (!isPoll) {
      var elA = document.getElementById('atpKpiAktif');
      var elH = document.getElementById('atpKpiHareket');
      var elAS = document.getElementById('atpKpiAktifSub');
      var elHS = document.getElementById('atpKpiHareketSub');
      if (elA) elA.textContent = '—';
      if (elH) elH.textContent = '—';
      if (elAS) elAS.textContent = 'Filom bağlantı hatası';
      if (elHS) elHS.textContent = '';
    }
    if (window.AtpLiveMap) window.AtpLiveMap.refreshLiveVehicles(lastVehicles, { failed: true });
  }

  function applyLiveData(j, isPoll) {
    if (j.ok && j.vehicles) {
      liveFetchState = 'ok';
      lastVehicles = j.vehicles;
      renderLiveVehicles(j.vehicles);
      updateLiveKpi(j.kpi, j.count);
      fillVehicleSelect(j.vehicles);
      if (window.AtpLiveMap) {
        window.AtpLiveMap.refreshLiveVehicles(j.vehicles, { success: true, silent: isPoll });
        if (currentTab === 'canli') window.AtpLiveMap.onLiveTabShown();
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
      if (list) list.innerHTML = '<li class="atp-live-loading">Canlı araç verisi yükleniyor…</li>';
    }
    var ctrl = typeof AbortController !== 'undefined' ? new AbortController() : null;
    var tid = setTimeout(function () {
      if (ctrl) ctrl.abort();
    }, LIVE_FETCH_TIMEOUT_MS);
    var opts = { credentials: 'same-origin' };
    if (ctrl) opts.signal = ctrl.signal;
    fetch('/planlama/arac-takip/api/araclar', opts)
      .then(function (r) { return r.json().then(function (j) { return { status: r.status, body: j }; }); })
      .then(function (res) {
        clearTimeout(tid);
        applyLiveData(res.body, !!isPoll);
      })
      .catch(function () {
        clearTimeout(tid);
        showLiveError(!!isPoll);
      });
  }

  loadLiveVehicles(false);
  pollTimer = setInterval(function () { loadLiveVehicles(true); }, LIVE_POLL_MS);
  window.addEventListener('beforeunload', function () {
    if (pollTimer) clearInterval(pollTimer);
  });
})();
