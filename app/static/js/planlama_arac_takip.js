(function () {
  'use strict';

  var root = document.getElementById('atpRoot');
  if (!root) return;

  var dashEl = document.getElementById('atpDashboardJson');
  var dashboard = dashEl ? JSON.parse(dashEl.textContent) : {};
  var planDate = root.getAttribute('data-date') || dashboard.date;
  var LIVE_POLL_MS = 30000;
  var pollTimer = null;
  var currentTab = 'gunluk';
  var lastVehicles = [];

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
    var pins = (dashboard.map_pins || []).filter(function (p) {
      return p.lat != null && p.lng != null;
    });
    var emptyEl = document.getElementById('atpPlanMapEmpty');
    var svg = document.getElementById('atpMapSvg');
    if (!pins.length) {
      if (emptyEl) emptyEl.style.display = '';
      if (svg) { svg.style.display = 'none'; svg.innerHTML = ''; }
      return;
    }
    if (emptyEl) emptyEl.style.display = 'none';
    if (svg) svg.style.display = 'block';
    window.AtpMap.renderPins(pins);
  }

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
      if (lastVehicles.length) renderLiveVehicles(lastVehicles);
      window.AtpLiveMap.onLiveTabShown();
      var vid = new URLSearchParams(window.location.search).get('vehicle_id');
      if (vid) window.AtpLiveMap.focusVehicle(vid);
    }
    if (isGunluk) {
      updatePlanMap();
      updatePlanSidebar();
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
  setTab(initTab);

  function renderTable(tasks) {
    var tbody = document.getElementById('atpTaskBody');
    if (!tbody) return;
    tbody.innerHTML = tasks.map(function (t) {
      var priCls = t.priority === 'YUKSEK' ? 'yuksek' : (t.priority === 'DUSUK' ? 'dusuk' : 'normal');
      var stCls = t.status === 'BEKLIYOR' ? 'bekliyor' : (t.status === 'BASLANGIC' ? 'baslangic' : 'planlandi');
      return '<tr data-task-id="' + t.id + '">' +
        '<td>' + t.order_no + '</td><td>' + t.planned_time + '</td>' +
        '<td><strong>' + (t.job_title || '') + '</strong><br><small>' + (t.company_name || '') + '</small></td>' +
        '<td>' + (t.address_text || '') + '</td>' +
        '<td><span class="atp-badge atp-pri-' + priCls + '">' + (t.priority_label || '') + '</span></td>' +
        '<td>' + fmtDist(t.distance_km) + '</td>' +
        '<td class="atp-st-' + stCls + '">' + (t.status_label || '') + '</td>' +
        '<td><div class="atp-sort-btns"><button type="button" data-dir="up">▲</button><button type="button" data-dir="down">▼</button></div></td></tr>';
    }).join('');
    bindSortButtons();
    dashboard.daily_tasks = tasks;
    updatePlanSidebar();
    updatePlanMap();
  }

  function fmtDist(km) {
    if (window.AtpFmtDist) return window.AtpFmtDist(km);
    if (km == null || km === '' || km === '—') return '—';
    return km + ' km';
  }

  function reorderApi(taskId, direction) {
    var vid = document.getElementById('atpSelVehicle');
    fetch('/planlama/arac-takip/api/reorder', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        date: planDate, task_id: taskId, direction: direction,
        vehicle_id: vid && vid.value ? vid.value : null,
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

  var sortBtn = document.getElementById('atpBtnSortSuggest');
  if (sortBtn) sortBtn.addEventListener('click', function () {
    toast('Rota optimizasyonu V2.4\'te aktif olacak.');
  });

  var applyRouteBtn = document.getElementById('atpBtnApplyRoute');
  if (applyRouteBtn) applyRouteBtn.addEventListener('click', function () {
    toast('Önerilen rota V2.4\'te uygulanacak.');
  });

  document.getElementById('atpBtnWhatsapp').addEventListener('click', function () {
    var vid = document.getElementById('atpSelVehicle');
    var q = '?date=' + encodeURIComponent(planDate);
    if (vid && vid.value) q += '&vehicle_id=' + encodeURIComponent(vid.value);
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

  window.AtpMap = {
    renderPins: function (pins) {
      var svg = document.getElementById('atpMapSvg');
      if (!svg || !pins || !pins.length) return;
      var coords = pins.filter(function (p) { return p.lat != null && p.lng != null; });
      if (!coords.length) return;
      var minLat = Math.min.apply(null, coords.map(function (p) { return p.lat; }));
      var maxLat = Math.max.apply(null, coords.map(function (p) { return p.lat; }));
      var minLng = Math.min.apply(null, coords.map(function (p) { return p.lng; }));
      var maxLng = Math.max.apply(null, coords.map(function (p) { return p.lng; }));
      function px(lat, lng) {
        var x = 40 + ((lng - minLng) / (maxLng - minLng || 1)) * 320;
        var y = 280 - ((lat - minLat) / (maxLat - minLat || 1)) * 240;
        return { x: x, y: y };
      }
      var pathD = coords.map(function (p, i) {
        var pt = px(p.lat, p.lng);
        return (i === 0 ? 'M' : 'L') + pt.x + ' ' + pt.y;
      }).join(' ');
      var inner = '<path d="' + pathD + '" fill="none" stroke="#2563eb" stroke-width="3" stroke-dasharray="6 4"/>';
      coords.forEach(function (p) {
        var pt = px(p.lat, p.lng);
        inner += '<circle cx="' + pt.x + '" cy="' + pt.y + '" r="14" fill="#c8922a" stroke="#fff" stroke-width="2"/>';
        inner += '<text x="' + pt.x + '" y="' + (pt.y + 4) + '" text-anchor="middle" fill="#fff" font-size="11" font-weight="700">' + p.order + '</text>';
      });
      svg.innerHTML = inner;
    },
    init: function () { updatePlanMap(); }
  };
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
    if (currentTab !== 'canli') return;
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

  function fillVehicleSelect(vehicles) {
    var sel = document.getElementById('atpSelVehicle');
    if (!sel || !vehicles || !vehicles.length) return;
    var cur = sel.value || dashboard.selected_vehicle_id || new URLSearchParams(window.location.search).get('vehicle_id') || '';
    sel.innerHTML = '<option value="">— Araç seç —</option>' + vehicles.map(function (v) {
      return '<option value="' + v.id + '">' + (v.plate_display || v.plate || v.id) + '</option>';
    }).join('');
    if (cur && sel.querySelector('option[value="' + cur + '"]')) sel.value = cur;
    else if (vehicles.length === 1) sel.value = vehicles[0].id;
    updatePlanSidebar();
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
    if (currentTab !== 'canli') return;
    var list = document.getElementById('atpVehicleList');
    if (!isPoll && list) list.innerHTML = '<li class="atp-live-error">Canlı araç verisi şu anda alınamıyor.</li>';
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
    fetch('/planlama/arac-takip/api/araclar', { credentials: 'same-origin' })
      .then(function (r) { return r.json().then(function (j) { return { status: r.status, body: j }; }); })
      .then(function (res) { applyLiveData(res.body, !!isPoll); })
      .catch(function () { showLiveError(!!isPoll); });
  }

  loadLiveVehicles(false);
  pollTimer = setInterval(function () { loadLiveVehicles(true); }, LIVE_POLL_MS);
  window.addEventListener('beforeunload', function () {
    if (pollTimer) clearInterval(pollTimer);
  });
})();
