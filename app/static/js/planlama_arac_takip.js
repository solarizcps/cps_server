/* Araç Takip V2 — main controller
   v=26 — mockup-parity production integration
   Root: #atpV2Root
*/
(function () {
  'use strict';

  /* ─── Root check ─── */
  var root = document.getElementById('atpV2Root');
  if (!root) return;

  /* ─── Dashboard SSR data ─── */
  var dashEl = document.getElementById('atpDashboardJson');
  var dashboard = {};
  try { dashboard = JSON.parse(dashEl ? dashEl.textContent : '{}'); } catch (e) { dashboard = {}; }

  var planDate = root.getAttribute('data-date') || dashboard.date || new Date().toISOString().slice(0, 10);
  var urlParams = new URLSearchParams(window.location.search);
  var initTab = urlParams.get('tab') || 'gunluk';
  var currentTab = initTab;

  /* ─── State ─── */
  var lastVehicles = [];          // filom vehicles from /api/araclar
  var liveMergedVehicles = [];    // merged live data
  var liveOpsCache = null;
  var liveLastPollAt = null;
  var liveSelectedVehicleId = null;
  var liveFetchState = 'idle';
  var liveRoutesVisible = false;
  var liveRouteGeometries = [];
  var liveRouteLayerGroup = null;
  var lastLiveFilomKpi = null;
  var lastLiveFilomCount = null;
  var _opsReqSeq = 0;
  var _opsAbort = null;
  var OPS_TIMEOUT_MS = 25000;
  var LIVE_POLL_MS = 30000;
  var LIVE_TIMEOUT_MS = 20000;
  var pollTimer = null;
  var opsTimer = null;
  var weekOffset = 0;       // for weekly navigation
  var lastOpsData = { vehicles: [], items: [] };
  var _activeVehicleExtId = null;

  /* ─── Helpers ─── */
  function fmtVal(v) { return (v == null || v === '') ? '—' : String(v); }
  function qs(id) { return document.getElementById(id); }

  function toast(msg) {
    var el = qs('atpToast');
    if (!el) return;
    el.textContent = msg;
    el.classList.add('show');
    setTimeout(function () { el.classList.remove('show'); }, 3200);
  }

  function fmtTimeStamp(d) {
    if (!d || isNaN(d.getTime())) return '—';
    return d.toTimeString().slice(0, 8);
  }

  function fmtGpsAge(ts) {
    if (!ts) return 'GPS: —';
    var d = new Date(String(ts).replace(' ', 'T'));
    if (isNaN(d.getTime())) return String(ts);
    var mins = Math.round((Date.now() - d.getTime()) / 60000);
    if (mins < 1) return 'az önce';
    if (mins < 120) return mins + ' dk önce';
    return String(ts);
  }

  function fmtKm(v) {
    if (v == null || v === '' || v === '—') return '—';
    return v + ' km';
  }

  function safeLabel(v, fallback) {
    if (!v || String(v).trim() === '' || String(v) === '—') return fallback || '—';
    return String(v);
  }

  /* Never show raw external IDs to user */
  function safePlate(v) {
    var p = (v && (v.plate_display || v.plate)) || '';
    if (!p || p.trim() === '') return 'Plaka bilgisi yok';
    return p;
  }

  function _fetchWithTimeout(url, signal, ms) {
    var timeoutId;
    var timeoutPromise = new Promise(function (_, reject) {
      timeoutId = setTimeout(function () { reject(new Error('timeout')); }, ms || OPS_TIMEOUT_MS);
    });
    return Promise.race([
      fetch(url, { credentials: 'same-origin', signal: signal }),
      timeoutPromise
    ]).then(function (r) {
      clearTimeout(timeoutId);
      if (!r.ok) { var e = new Error('http'); e.status = r.status; throw e; }
      return r.json();
    }).catch(function (e) { clearTimeout(timeoutId); throw e; });
  }

  /* ─── Tab switching ─── */
  function setTab(tab) {
    currentTab = tab;
    document.querySelectorAll('.atp-tab').forEach(function (btn) {
      btn.classList.toggle('active', btn.getAttribute('data-tab') === tab);
    });
    var panels = {
      canli: 'atpPanelGunluk',
      gunluk: 'atpPanelGunluk',
      haftalik: 'atpPanelHaftalik',
      gecmis: 'atpPanelGecmis',
    };
    ['atpPanelGunluk', 'atpPanelHaftalik', 'atpPanelGecmis'].forEach(function (id) {
      var el = qs(id);
      if (el) el.classList.remove('active');
    });
    var panelId = panels[tab];
    if (panelId) { var p = qs(panelId); if (p) p.classList.add('active'); }

    var canliView = qs('atpCanliView');
    var gunlukView = qs('atpGunlukView');
    var dateBar = qs('atpDateBar');
    var kpiBand = qs('atpKpiBand');
    var kpiCanli = qs('atpKpiBandCanli');

    if (tab === 'canli') {
      if (canliView) canliView.style.display = '';
      if (gunlukView) gunlukView.style.display = 'none';
      if (dateBar) dateBar.style.display = 'none';
      if (kpiBand) kpiBand.style.display = 'none';
      if (kpiCanli) kpiCanli.style.display = '';
      if (window.AtpLiveMap) {
        var vlist = qs('atpVehicleList');
        if (vlist && vlist.querySelector('.atp-loading')) loadLiveVehicles(false);
        else if (liveFetchState === 'error') loadLiveVehicles(false);
        if (liveMergedVehicles.length) renderLiveVehicles(liveMergedVehicles);
        else if (lastVehicles.length) renderLiveVehicles(lastVehicles);
        window.AtpLiveMap.onLiveTabShown();
        syncLiveKpi(lastLiveFilomKpi, lastLiveFilomCount, liveOpsCache);
        if (liveLastPollAt) {
          var rt = qs('atpLiveRefreshText');
          if (rt) rt.textContent = 'Son güncelleme: ' + fmtTimeStamp(liveLastPollAt);
        }
      }
    } else {
      if (canliView) canliView.style.display = 'none';
      if (kpiCanli) kpiCanli.style.display = 'none';
      if (tab === 'gunluk') {
        if (gunlukView) gunlukView.style.display = '';
        if (dateBar) dateBar.style.display = '';
        if (kpiBand) kpiBand.style.display = '';
        if (window.AtpPlanMap) window.AtpPlanMap.onPlanTabShown();
        loadOps();
      } else if (tab === 'haftalik') {
        if (dateBar) dateBar.style.display = 'none';
        if (kpiBand) kpiBand.style.display = 'none';
        loadWeekly(weekOffset);
      } else if (tab === 'gecmis') {
        if (dateBar) dateBar.style.display = 'none';
        if (kpiBand) kpiBand.style.display = 'none';
        loadHistory();
      }
    }

    /* update URL */
    var u = new URL(window.location.href);
    u.searchParams.set('tab', tab);
    if (tab === 'gunluk') u.searchParams.set('date', planDate);
    history.replaceState({}, '', u.pathname + u.search);
  }

  document.querySelectorAll('.atp-tab').forEach(function (btn) {
    btn.addEventListener('click', function () { setTab(btn.getAttribute('data-tab')); });
  });

  /* ─── Date picker ─── */
  var datePicker = qs('atpV2DatePicker');
  if (datePicker) {
    datePicker.addEventListener('change', function () {
      planDate = datePicker.value;
      var u = new URL(window.location.href);
      u.searchParams.set('tab', 'gunluk');
      u.searchParams.set('date', planDate);
      window.location.href = u.pathname + u.search;
    });
  }

  /* ─── KPI render ─── */
  function renderKpi(kpi) {
    function set(id, v, clsId) {
      var el = qs(id);
      if (el) el.textContent = (v != null && v !== '') ? String(v) : '—';
      if (clsId) {
        var card = qs(clsId);
        if (card) {
          card.classList.remove('ok', 'warn', 'err');
          if (id === 'atpKpiTamam' && v > 0) card.classList.add('ok');
          if (id === 'atpKpiSorun' && v > 0) card.classList.add('err');
        }
      }
    }
    if (!kpi) return;
    set('atpKpiAktif', kpi.aktif_arac);
    set('atpKpiHareket', kpi.hareket_halinde);
    set('atpKpiIs', kpi.toplam_is, 'atpKpiCardIs');
    set('atpKpiTamam', kpi.tamamlandi, 'atpKpiCardTamam');
    set('atpKpiDevam', kpi.devam_ediyor, 'atpKpiCardDevam');
    set('atpKpiSorun', kpi.sorunlu, 'atpKpiCardSorun');
  }

  /* ─── Vehicle cards (gunluk) ─── */
  function routeStateBadge(v) {
    if (v.gps_is_stale || v.gps_stale || v.is_stale_data) return '<span class="badge badge-stale">GPS Eski</span>';
    if (v.route_state === 'DEVIATING') return '<span class="badge badge-orange">⚠ Sapma</span>';
    if (v.route_state === 'ON_ROUTE') return '<span class="badge badge-green">● Rotada</span>';
    /* Prefer sqlite GPS activity_status (more real-time) over Filom physical_status */
    var gpsAct = (v.latest_gps || {}).activity_status || '';
    var act = gpsAct || v.physical_status || v.activity_status || '';
    if (act === 'HAREKETLI') return '<span class="badge badge-green">● Yolda</span>';
    if (act === 'ROLANTI') return '<span class="badge badge-orange">○ Rölanti</span>';
    if (act === 'DURAN') return '<span class="badge badge-gray">⏸ Duran</span>';
    /* Map text physical_status values */
    if (act === 'Hareket halinde') return '<span class="badge badge-green">● Yolda</span>';
    if (act === 'Duruyor') return '<span class="badge badge-gray">⏸ Duran</span>';
    var lbl = v.activity_status_label || v.route_status_label || act;
    if (lbl && lbl !== 'NO_ACTIVE_PLAN') return '<span class="badge badge-gray">' + fmtVal(lbl) + '</span>';
    return '<span class="badge badge-gray">—</span>';
  }

  function progressPct(done, total) {
    if (!total) return 0;
    return Math.round(100 * done / total);
  }

  function renderVehicleCards(vehicles) {
    var wrap = qs('atpVehicleCards');
    if (!wrap) return;
    if (!vehicles || !vehicles.length) {
      wrap.innerHTML = '<div class="atp-v2-empty">Henüz planlı araç yok.</div>';
      return;
    }
    wrap.innerHTML = vehicles.map(function (v) {
      var plate = safePlate(v);
      /* API field names: progress_completed / progress_total (fallback completed_count / total_count) */
      var done = v.progress_completed != null ? v.progress_completed : (v.completed_count || 0);
      var total = v.progress_total != null ? v.progress_total : (v.total_count || 0);
      var pct = progressPct(done, total);
      var deviating = v.route_state === 'DEVIATING';
      var stale = v.gps_is_stale || v.gps_stale || v.is_stale_data;
      var cardCls = 'vcard' + (deviating ? ' warn' : (stale ? ' stale' : ' ok'));
      if (_activeVehicleExtId && String(vid) === String(_activeVehicleExtId)) cardCls += ' selected';
      var fillCls = deviating ? 'orange' : (stale ? 'gray' : 'green');
      var badge = routeStateBadge(v);
      var planId = v.plan_id || '';
      var vid = v.arac_external_id || v.id || '';
      /* Next stop: API uses next_stop / next_time (fallback next_stop_name / next_stop_time) */
      var nextName = v.next_stop || v.next_stop_name || '';
      var nextTime = v.next_time || v.next_stop_time || '';
      /* GPS: API uses gps_last_seen_at (vehicles), last_seen_at (araclar) */
      var gpsTs = v.gps_last_seen_at || v.gps_timestamp || v.last_seen_at || '';
      var gpsAge = gpsTs ? fmtGpsAge(gpsTs) : '—';
      /* Route/deviation label */
      var routeLabel = v.route_status_label || '';
      /* Driver: API uses driver (today-ops vehicles) */
      var driver = v.driver_name || v.driver || '—';
      /* Visit info */
      var visitLbl = (v.visit_summary && v.visit_summary.label) || v.visit_label || '';

      /* Detail rows */
      var detailRows = '';
      if (nextName) {
        detailRows += '<div class="vcard-detail-row"><span class="icon">📅</span><span>Sıradaki: <strong>' +
          fmtVal(nextName) + '</strong>' + (nextTime ? ' — ' + nextTime : '') + '</span></div>';
      }
      if (deviating && v.deviation_m != null) {
        var km = (Number(v.deviation_m) / 1000).toLocaleString('tr-TR', { maximumFractionDigits: 1 });
        detailRows += '<div class="vcard-detail-row warn"><span class="icon">⚠️</span><span>Rotadan ' + km + ' km saptı</span></div>';
        if (visitLbl) {
          detailRows += '<div class="vcard-detail-row warn"><span class="icon">📍</span><span>' + fmtVal(visitLbl) + '</span></div>';
        }
      } else if (stale) {
        detailRows += '<div class="vcard-detail-row"><span class="icon" style="color:var(--gray)">⏸</span><span style="color:var(--gray)">GPS verisi eski</span></div>';
      } else if (v.route_state === 'ON_ROUTE') {
        detailRows += '<div class="vcard-detail-row" style="color:var(--green);font-weight:600"><span class="icon">✅</span><span>Rotada</span></div>';
        if (visitLbl) {
          detailRows += '<div class="vcard-detail-row"><span class="icon">📍</span><span>' + fmtVal(visitLbl) + '</span></div>';
        }
      } else {
        /* NO_ACTIVE_PLAN or unknown */
        var act2 = v.physical_status || v.activity_status || '';
        if (act2 === 'HAREKETLI') {
          detailRows += '<div class="vcard-detail-row" style="color:var(--green);font-weight:600"><span class="icon">✅</span><span>Hareketli</span></div>';
        }
        if (visitLbl) {
          detailRows += '<div class="vcard-detail-row"><span class="icon">📍</span><span>' + fmtVal(visitLbl) + '</span></div>';
        }
      }
      if (gpsTs) {
        detailRows += '<div class="vcard-detail-row"><span class="icon" style="opacity:.7">📡</span>' +
          '<span style="color:var(--gray)">Son GPS: ' + gpsAge + '</span></div>';
      }
      var actionBtn = deviating
        ? '<button class="btn btn-orange btn-sm atp-v2-open-plan" data-vid="' + vid + '" data-plan-id="' + planId + '">İncele</button>'
        : '<button class="btn btn-outline btn-sm atp-v2-open-plan" data-vid="' + vid + '" data-plan-id="' + planId + '">Planı Aç</button>';
      return '<div class="' + cardCls + '" data-vid="' + vid + '" data-plan-id="' + planId + '">' +
        '<div class="vcard-inner">' +
        '<div class="vcard-main">' +
        '<div class="vcard-plate-row"><div class="vcard-plate">' + plate + '</div>' + badge + '</div>' +
        '<div class="vcard-driver">' + fmtVal(driver) + '</div>' +
        '<div class="vcard-progress-row"><div class="progress-wrap"><div class="progress-fill ' + fillCls + '" style="width:' + pct + '%"></div></div>' +
        '<span class="progress-label">' + done + ' / ' + total + ' tamamlandı</span></div>' +
        '</div>' +
        '<div class="vcard-detail">' + (detailRows || '<div class="vcard-detail-row"><span style="color:var(--gray)">—</span></div>') + '</div>' +
        '<div class="vcard-action">' + actionBtn + '</div>' +
        '</div></div>';
    }).join('');

    /* bind open-plan buttons */
    wrap.querySelectorAll('.atp-v2-open-plan').forEach(function (btn) {
      btn.addEventListener('click', function (e) {
        e.stopPropagation();
        openPlanRouteForVehicle(btn.getAttribute('data-vid'));
      });
    });
    wrap.querySelectorAll('.atp-v2-timeline-btn').forEach(function (btn) {
      btn.addEventListener('click', function (e) {
        e.stopPropagation();
        openTimelineModal(btn.getAttribute('data-plan-id'), btn.getAttribute('data-vid'));
      });
    });
  }

  /* ─── Vehicle-scoped plan route helpers ─── */
  function findVehicleByExtId(extId) {
    if (!extId) return null;
    var list = lastOpsData.vehicles || [];
    for (var i = 0; i < list.length; i++) {
      if (String(list[i].arac_external_id) === String(extId)) return list[i];
    }
    return null;
  }

  function filterItemsForVehicle(extId, items) {
    if (!extId || !items) return [];
    return items.filter(function (it) {
      return String(it.arac_external_id) === String(extId);
    });
  }

  function sortStopItems(tasks) {
    return (tasks || []).slice().sort(function (a, b) {
      var ao = a.order_no != null && a.order_no !== '' ? Number(a.order_no) : null;
      var bo = b.order_no != null && b.order_no !== '' ? Number(b.order_no) : null;
      if (ao != null && bo != null && ao !== bo) return ao - bo;
      if (ao != null && bo == null) return -1;
      if (ao == null && bo != null) return 1;
      var ap = a.plan_item_id != null ? Number(a.plan_item_id) : 0;
      var bp = b.plan_item_id != null ? Number(b.plan_item_id) : 0;
      if (ap !== bp) return ap - bp;
      return (a.planned_time || '').localeCompare(b.planned_time || '');
    });
  }

  function idsEqualLists(a, b) {
    if (!a || !b || a.length !== b.length) return false;
    for (var i = 0; i < a.length; i++) {
      if (String(a[i]) !== String(b[i])) return false;
    }
    return true;
  }

  function getDomStopItemIds() {
    var nodes = document.querySelectorAll('#atpStopListWrap .stop-item[data-item-id]');
    return Array.prototype.map.call(nodes, function (n) { return n.getAttribute('data-item-id'); });
  }

  function verifyApplyReadback(vid, expectedTaskIds) {
    var expected = (expectedTaskIds || []).map(String);
    var items = sortStopItems(filterItemsForVehicle(vid, lastOpsData.items || []));
    var readbackIds = items.map(function (it) { return String(it.id); });
    var route = window.AtpRoute && window.AtpRoute.getLastRoute && window.AtpRoute.getLastRoute();
    var routeIds = route && route.current && route.current.task_ids
      ? route.current.task_ids.map(String) : [];
    var domIds = getDomStopItemIds().map(String);
    return idsEqualLists(readbackIds, expected)
      && idsEqualLists(routeIds, expected)
      && idsEqualLists(domIds, expected);
  }

  function setActiveVehicleCard(extId) {
    var wrap = qs('atpVehicleCards');
    if (!wrap) return;
    wrap.querySelectorAll('.vcard').forEach(function (card) {
      var vid = card.getAttribute('data-vid');
      card.classList.toggle('selected', extId && String(vid) === String(extId));
    });
  }

  function updatePrsForVehicle(vehicle, items) {
    var prsArac = qs('atpPrsArac');
    var prsSofor = qs('atpPrsSofor');
    var prsSaat = qs('atpPrsSaat');
    var prsBtn = qs('atpBtnPlanaIsEklePrs');
    var sel = qs('atpSelVehicle');

    if (prsArac) prsArac.textContent = vehicle ? safePlate(vehicle) : '—';
    if (prsSofor) prsSofor.textContent = vehicle ? fmtVal(vehicle.driver_name || vehicle.driver) : '—';
    if (prsBtn) prsBtn.style.display = vehicle ? '' : 'none';
    if (sel && vehicle && vehicle.arac_external_id) sel.value = String(vehicle.arac_external_id);

    if (prsSaat && items && items.length) {
      var times = items.map(function (it) { return it.planned_time || ''; }).filter(Boolean).sort();
      if (times.length) {
        prsSaat.textContent = times[0] + ' – ' + times[times.length - 1];
      } else {
        prsSaat.textContent = '—';
      }
    } else if (prsSaat) {
      prsSaat.textContent = '—';
    }
  }

  function updatePrsSummary(vehicles, items) {
    var extId = _activeVehicleExtId;
    var chosen = extId ? findVehicleByExtId(extId) : null;
    if (!chosen && vehicles && vehicles.length) {
      chosen = vehicles[0];
      if (!_activeVehicleExtId && chosen && chosen.arac_external_id) {
        _activeVehicleExtId = String(chosen.arac_external_id);
      }
    }
    var scopedItems = chosen
      ? filterItemsForVehicle(chosen.arac_external_id, items)
      : [];
    updatePrsForVehicle(chosen, scopedItems);
    setActiveVehicleCard(_activeVehicleExtId);
  }

  function openPlanRouteForVehicle(aracExternalId) {
    if (!aracExternalId) return;
    var extId = String(aracExternalId);
    _activeVehicleExtId = extId;

    var vehicle = findVehicleByExtId(extId);
    var items = filterItemsForVehicle(extId, lastOpsData.items || []);

    setActiveVehicleCard(extId);
    updatePrsForVehicle(vehicle, items);
    renderStopList(items, vehicle ? safePlate(vehicle) : '');

    if (window.AtpRoute) {
      if (window.AtpRoute.clearRouteDisplay) window.AtpRoute.clearRouteDisplay();
      if (window.AtpRoute.showRouteLoading) window.AtpRoute.showRouteLoading();
    }

    refreshPlanRoute(extId);

    var det = qs('atpPlanningSection');
    if (det) {
      det.open = true;
      requestAnimationFrame(function () {
        if (window.AtpPlanMap && window.AtpPlanMap.onPlanTabShown) {
          window.AtpPlanMap.onPlanTabShown();
        }
        det.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      });
    }
  }

  /* ─── Jobs table ─── */
  function jobDotClass(status, visitState) {
    if (status === 'TAMAMLANDI') return 'dot-green';
    if (visitState === 'ARRIVED') return 'dot-blue';
    if (status === 'BASLADI' || visitState === 'DEPARTED_PENDING') return 'dot-orange';
    return 'dot-gray';
  }

  function visitRowClass(visitState) {
    if (!visitState || visitState === 'NOT_VISITED') return 'visit-text gray';
    if (visitState === 'ARRIVED') return 'visit-text';
    if (visitState === 'DEPARTED' || visitState === 'DEPARTED_PENDING') return 'visit-text';
    return 'visit-text gray';
  }

  function planBadgeCls(status, visitState) {
    if (status === 'TAMAMLANDI') return 'badge-green';
    if (visitState === 'DEPARTED_PENDING') return 'badge-orange';
    if (status === 'BASLADI') return 'badge-blue';
    return 'badge-gray';
  }

  function fmtTime(dt) {
    if (!dt) return null;
    var m = String(dt).match(/(\d{2}:\d{2})/);
    return m ? m[1] : null;
  }

  function buildVisitLabel(it) {
    var raw = it.visit_label || '';
    var state = it.visit_state || '';
    if (raw && raw !== 'DEPARTED' && raw !== 'ARRIVED' && raw !== 'OUTSIDE') return raw;
    var arr = fmtTime(it.arrived_at);
    var dep = fmtTime(it.departed_at);
    if (state === 'DEPARTED' && arr && dep) return arr + ' Vardı · ' + dep + ' Ayrıldı';
    if (state === 'DEPARTED' && arr) return arr + ' Vardı · Ayrıldı';
    if (state === 'ARRIVED' && arr) return arr + ' Varış · Konumda';
    if (state === 'OUTSIDE') return 'Henüz varmadı';
    return raw || 'Henüz varmadı';
  }

  function makeJobRow(it) {
    var dotCls = jobDotClass(it.status, it.visit_state);
    var visCls = visitRowClass(it.visit_state);
    var badgeCls = planBadgeCls(it.status, it.visit_state);
    var statusLabel = fmtVal(it.status_label);
    var visitLabel = fmtVal(buildVisitLabel(it));
    var actionLabel = (it.visit_state === 'DEPARTED_PENDING' && it.status !== 'TAMAMLANDI')
      ? 'Sonuçlandır' : 'Görüntüle';
    var timeCls = 'job-time' + (it.is_late ? ' late' : '');
    return '<tr data-plan-item="' + (it.plan_item_id || '') + '">' +
      '<td class="' + timeCls + '">' + fmtVal(it.planned_time) + '</td>' +
      '<td><div class="job-firm"><span class="dot ' + dotCls + '"></span>' + fmtVal(it.job_title) +
      (it.company_name ? ' / ' + it.company_name : '') + '</div>' +
      (it.address_text ? '<div class="job-firm-sub">' + it.address_text + '</div>' : '') + '</td>' +
      '<td style="font-size:11.5px;color:#374151">' + fmtVal(it.driver) + '</td>' +
      '<td><span class="badge ' + badgeCls + '">' + statusLabel + '</span></td>' +
      '<td><span class="' + visCls + '">' + visitLabel + '</span></td>' +
      '<td><button class="btn btn-outline btn-sm atp-v2-inspect" ' +
        'data-vid="' + (it.arac_external_id || '') + '" ' +
        'data-plan-item="' + (it.plan_item_id || '') + '">' + actionLabel + '</button></td></tr>';
  }

  function renderJobs(items) {
    var tbody = qs('atpDailyJobsBody');
    if (!tbody) return;
    if (!items || !items.length) {
      tbody.innerHTML = '<tr><td colspan="6" class="atp-v2-empty">Henüz kayıt yok.</td></tr>';
      /* Clear any toggle row */
      var tbl = tbody.closest('table');
      if (tbl) { var tf = tbl.parentNode.querySelector('.atp-jobs-toggle'); if (tf) tf.remove(); }
      return;
    }
    var INIT_SHOW = 4;
    var visible = items.slice(0, INIT_SHOW);
    var hidden  = items.slice(INIT_SHOW);
    tbody.innerHTML = visible.map(makeJobRow).join('');

    /* Remove any existing toggle row */
    var tbl = tbody.closest('table');
    var card = tbl ? tbl.closest('.card') : null;
    if (card) {
      var old = card.querySelector('.atp-jobs-toggle');
      if (old) old.remove();
    }

    if (hidden.length > 0) {
      var total = items.length;
      var toggleRow = document.createElement('div');
      toggleRow.className = 'atp-jobs-toggle';
      toggleRow.style.cssText = 'padding:6px 10px;text-align:left;border-top:1px solid var(--gray-200)';
      var btn = document.createElement('button');
      btn.className = 'btn btn-outline btn-xs';
      btn.style.cssText = 'font-size:11px;color:var(--gray)';
      btn.textContent = 'Tümünü Gör (' + total + ')';
      var expanded = false;
      btn.addEventListener('click', function () {
        expanded = !expanded;
        if (expanded) {
          tbody.innerHTML = items.map(makeJobRow).join('');
          btn.textContent = 'Daha Az Göster';
          attachInspectListeners(tbody);
        } else {
          tbody.innerHTML = visible.map(makeJobRow).join('');
          btn.textContent = 'Tümünü Gör (' + total + ')';
          attachInspectListeners(tbody);
        }
      });
      toggleRow.appendChild(btn);
      if (card) card.appendChild(toggleRow);
    }

    attachInspectListeners(tbody);
  }

  function attachInspectListeners(tbody) {
    tbody.querySelectorAll('.atp-v2-inspect').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var det = qs('atpPlanningSection');
        if (det) det.open = true;
      });
    });
  }

  /* ─── Alerts ─── */
  function makeAlertRow(a) {
    var sev = a.severity || 'info';
    var icon = sev === 'warning' ? '⚠️' : (sev === 'danger' ? '🔴' : '📍');
    var btnCls = sev === 'danger' ? 'btn-red-outline' : (sev === 'warning' ? 'btn-orange' : 'btn-outline');
    var btnLabel = sev === 'danger' ? 'İncele' : (sev === 'warning' ? 'Planı Değiştir' : 'Görüntüle');
    return '<div class="alert-row">' +
      '<div class="alert-icon">' + icon + '</div>' +
      '<div class="alert-body">' +
      '<div class="alert-firm">' + fmtVal(a.title || a.firm || a.message) + '</div>' +
      '<div class="alert-desc">' + fmtVal((a.title || a.firm) ? a.message : '') + '</div>' +
      '</div>' +
      '<button class="btn ' + btnCls + ' btn-xs">' + btnLabel + '</button>' +
      '</div>';
  }

  function renderAlerts(alerts, emptyMsg) {
    var body = qs('atpAlertsBody');
    if (!body) return;
    if (!alerts || !alerts.length) {
      body.innerHTML = '<p style="padding:12px 14px;font-size:12px;color:var(--gray)">' +
        (emptyMsg || 'Dikkat gerektiren durum yok.') + '</p>';
      return;
    }
    var INIT_SHOW = 3;
    var visible = alerts.slice(0, INIT_SHOW);
    var hidden  = alerts.slice(INIT_SHOW);
    var total   = alerts.length;

    var listHtml = '<div class="alert-list" id="atpAlertListInner">' +
      visible.map(makeAlertRow).join('') + '</div>';

    if (hidden.length > 0) {
      listHtml += '<div class="atp-alerts-toggle" style="padding:6px 14px;border-top:1px solid var(--gray-200)">' +
        '<button class="btn btn-outline btn-xs atp-alerts-toggle-btn" style="font-size:11px;color:var(--gray)">' +
        'Tümünü Gör (' + total + ')</button></div>';
    }

    body.innerHTML = listHtml;

    var toggleBtn = body.querySelector('.atp-alerts-toggle-btn');
    if (toggleBtn) {
      var expanded = false;
      toggleBtn.addEventListener('click', function () {
        expanded = !expanded;
        var inner = body.querySelector('#atpAlertListInner');
        if (expanded) {
          if (inner) inner.innerHTML = alerts.map(makeAlertRow).join('');
          toggleBtn.textContent = 'Daha Az Göster';
        } else {
          if (inner) inner.innerHTML = visible.map(makeAlertRow).join('');
          toggleBtn.textContent = 'Tümünü Gör (' + total + ')';
        }
      });
    }
  }

  /* ─── Mini map (plan) ─── */
  var miniMap = null;
  var miniLayer = null;

  function renderMiniMap(mapData) {
    var box = qs('atpMiniMap');
    if (!box || !window.L) return;
    if (!miniMap) {
      miniMap = L.map(box, { zoomControl: false, attributionControl: false }).setView([41.0, 29.0], 10);
      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 18 }).addTo(miniMap);
      miniLayer = L.layerGroup().addTo(miniMap);
    }
    miniLayer.clearLayers();
    var pts = [];
    ((mapData && mapData.vehicles) || []).forEach(function (v) {
      if (v.lat == null) return;
      var m = L.circleMarker([v.lat, v.lng], { radius: 6, color: v.stale ? '#b54708' : '#1a9e3f', fillOpacity: 0.9 });
      m.bindTooltip(v.plate || '—');
      miniLayer.addLayer(m);
      pts.push([v.lat, v.lng]);
    });
    if (pts.length) {
      miniMap.fitBounds(pts, { padding: [20, 20], maxZoom: 12 });
    } else {
      /* No vehicles — show Istanbul/factory default view */
      miniMap.setView([41.02, 29.05], 10);
    }
    /* Multiple invalidateSize passes to handle layout settling */
    miniMap.invalidateSize({ animate: false });
    setTimeout(function () { if (miniMap) miniMap.invalidateSize({ animate: false }); }, 100);
    setTimeout(function () { if (miniMap) miniMap.invalidateSize({ animate: false }); }, 500);
  }

  /* ─── Stop list (plan rota) ─── */
  function renderStopList(tasks, plate) {
    var wrap = qs('atpStopListWrap');
    var title = qs('atpStopListTitle');
    if (!wrap) return;
    if (!tasks || !tasks.length) {
      wrap.innerHTML = '<div class="atp-v2-empty">Henüz planlanmış durak yok.</div>';
      if (title) title.textContent = 'Sıralı Duraklar';
      return;
    }
    var base = (dashboard.base_location && dashboard.base_location.base_name) || 'Fabrika — Tuzla OSB';
    var sorted = sortStopItems(tasks);
    var html = '<div class="factory-row"><span class="fl">🏭</span><span class="factory-label">Başlangıç: ' + base + '</span></div>';
    html += '<div class="stop-list">' + sorted.map(function (t, idx) {
      var done = t.status === 'TAMAMLANDI';
      var late = t.is_late;
      var cls = 'stop-item' + (done ? ' done' : (late ? ' late' : ''));
      var numCls = 'stop-num' + (done ? ' done' : (late ? ' late' : ''));
      var badgeCls = done ? 'badge-green' : (late ? 'badge-orange' : 'badge-gray');
      var badgeLbl = done ? '✓' : (late ? 'Gecikmeli' : fmtVal(t.status_label || t.status || 'Planlandı'));
      var seq = t.order_no != null && t.order_no !== '' ? t.order_no : (idx + 1);
      var itemId = t.id ? String(t.id) : '';
      var talepId = t.is_talebi_id != null ? String(t.is_talebi_id) : '';
      return '<div class="' + cls + '" data-item-id="' + itemId + '" data-is-talebi-id="' + talepId + '">' +
        '<span class="' + numCls + '">' + seq + '</span>' +
        '<span class="stop-name">' + fmtVal(t.company_name || t.job_title) + '</span>' +
        '<span class="badge ' + badgeCls + '" style="margin-right:4px">' + badgeLbl + '</span>' +
        '<span class="stop-time" style="' + (late ? 'color:var(--orange)' : '') + '">' + fmtVal(t.planned_time) + '</span>' +
        '</div>';
    }).join('') + '</div>';
    html += '<div class="factory-row" style="margin-top:4px"><span class="fl">🏭</span><span class="factory-label">Bitiş: Fabrika Dönüş — ' + base + '</span></div>';
    wrap.innerHTML = html;
    if (title) title.textContent = 'Sıralı Duraklar' + (plate ? ' — ' + plate : '');
  }

  /* ─── Empty day: show/hide correct view ─── */
  function switchGunlukView(isEmpty) {
    var bosEl = qs('atpGunlukBos');
    var doluEl = qs('atpGunlukDolu');
    if (bosEl) bosEl.style.display = isEmpty ? '' : 'none';
    if (doluEl) doluEl.style.display = isEmpty ? 'none' : '';
  }

  /* ─── Empty state for accordion (empty day) ─── */
  function syncEmptyDayPlanRota(hasItems) {
    var det = qs('atpPlanningSection');
    if (!hasItems && det) det.open = false;

    var previewBtn = qs('atpBtnPreviewSuggestedRoute');
    var applyBtn = qs('atpBtnApplySuggestedOrder');
    if (!hasItems) {
      if (previewBtn) previewBtn.disabled = true;
      if (applyBtn) applyBtn.disabled = true;
      renderStopList([]);
    }
  }

  /* ─── Empty day unplanned vehicles list ─── */
  function renderUnplannedVehicles(filomVehicles) {
    var wrap = qs('atpUnplannedList');
    if (!wrap) return;
    if (!filomVehicles || !filomVehicles.length) {
      wrap.innerHTML = '<div style="font-size:10px;text-transform:uppercase;letter-spacing:.05em;color:var(--gray);font-weight:700;text-align:left;margin-bottom:6px">Atanmamış Araçlar</div>' +
        '<p style="font-size:11.5px;color:var(--gray)">Araç verisi bulunamadı.</p>';
      return;
    }
    wrap.innerHTML = '<div style="font-size:10px;text-transform:uppercase;letter-spacing:.05em;color:var(--gray);font-weight:700;text-align:left;margin-bottom:6px">Atanmamış Araçlar</div>' +
      filomVehicles.slice(0, 5).map(function (v) {
        return '<div class="unp-item">' +
          '<div><div class="unp-plate">' + safePlate(v) + '</div><div class="unp-driver">' + fmtVal(v.driver_name || v.driver) + '</div></div>' +
          '<span class="badge badge-gray" style="margin-left:8px">Atanmadı</span>' +
          '<button type="button" class="btn btn-outline btn-xs unp-btn">Plan Oluştur</button>' +
          '</div>';
      }).join('');

    /* Quick plan araç select */
    var quickSel = qs('atpQuickArac');
    if (quickSel) {
      quickSel.innerHTML = '<option value="">Araç seç…</option>' +
        filomVehicles.map(function (v) {
          return '<option value="' + (v.id || '') + '" data-driver="' + fmtVal(v.driver_name) + '">' + safePlate(v) + '</option>';
        }).join('');
    }
  }

  /* ─── Operations load ─── */
  function _opsSetLoading(on) { /* loading state managed via content */ }

  function _mergeKpi(opsKpi, filomData) {
    var kpi = Object.assign({
      aktif_arac: null, hareket_halinde: null,
      toplam_is: 0, tamamlandi: 0, devam_ediyor: 0, sorunlu: 0,
    }, opsKpi || {});
    if (filomData && filomData.vehicles) {
      var fKpi = filomData.filom_kpi || {};
      if (kpi.aktif_arac == null) kpi.aktif_arac = fKpi.aktif_arac != null ? fKpi.aktif_arac : filomData.vehicles.length;
      if (kpi.hareket_halinde == null) kpi.hareket_halinde = fKpi.hareket_halinde != null ? fKpi.hareket_halinde : 0;
    }
    ['aktif_arac','hareket_halinde','toplam_is','tamamlandi','devam_ediyor','sorunlu'].forEach(function (k) {
      if (kpi[k] == null) kpi[k] = 0;
    });
    return kpi;
  }

  function _opsApplySuccess(data, filomBody) {
    var kpi = _mergeKpi(data.kpi, filomBody);
    renderKpi(kpi);

    var hasItems = (data.items && data.items.length > 0);
    var hasVehicles = (data.vehicles && data.vehicles.length > 0);
    var isEmpty = !hasItems && !hasVehicles;

    /* Switch between empty-day and dolu-gun views */
    switchGunlukView(isEmpty);

    if (isEmpty) {
      /* Show unplanned vehicles in empty-day panel */
      renderUnplannedVehicles(filomBody && filomBody.vehicles ? filomBody.vehicles : lastVehicles);
      /* Quick plan araç select also updated inside renderUnplannedVehicles */
      /* Accordion: close */
      syncEmptyDayPlanRota(false);
    } else {
      lastOpsData = {
        vehicles: data.vehicles || [],
        items: data.items || [],
      };
      renderVehicleCards(data.vehicles || []);
      renderJobs(data.items || []);
      renderAlerts(data.alerts || [], 'Dikkat gerektiren durum yok.');
      renderMiniMap(data.map || { vehicles: [] });

      /* Summary band — scoped to active or first vehicle */
      if (!_activeVehicleExtId && data.vehicles && data.vehicles.length && data.vehicles[0].arac_external_id) {
        _activeVehicleExtId = String(data.vehicles[0].arac_external_id);
      }
      updatePrsSummary(data.vehicles || [], data.items || []);

      /* Stop list: only selected vehicle items */
      var activeVeh = findVehicleByExtId(_activeVehicleExtId);
      var scopedItems = _activeVehicleExtId
        ? sortStopItems(filterItemsForVehicle(_activeVehicleExtId, data.items || []))
        : [];
      renderStopList(scopedItems, activeVeh ? safePlate(activeVeh) : '');

      /* Date label in jobs header */
      var jobsDateLbl = qs('atpJobsDateLabel');
      if (jobsDateLbl && dashboard.date_label) jobsDateLbl.textContent = dashboard.date_label;

      /* Empty day accordion guard */
      syncEmptyDayPlanRota(hasItems);

      /* Route — active vehicle only */
      if (window.AtpRoute && hasItems && _activeVehicleExtId) {
        refreshPlanRoute(_activeVehicleExtId);
      } else if (window.AtpRoute) {
        if (window.AtpRoute.clearRouteDisplay) window.AtpRoute.clearRouteDisplay();
      }
    }

    /* Populate vehicle select (hidden) for route & modal */
    hydrateVehicleSelect(lastVehicles, hasVehicles ? data.vehicles : []);
  }

  function _opsShowError(status) {
    ['atpKpiIs','atpKpiTamam','atpKpiDevam','atpKpiSorun'].forEach(function (id) {
      var el = qs(id); if (el) el.textContent = '—';
    });
    var wrap = qs('atpVehicleCards');
    if (wrap) wrap.innerHTML = '<div class="atp-v2-error-state">Plan verisi alınamadı. ' +
      '<button class="atp-v2-retry-btn" id="atpOpsRetryBtn">Tekrar Dene</button></div>';
    var jobWrap = qs('atpDailyJobsBody');
    if (jobWrap) jobWrap.innerHTML = '<tr><td colspan="6" class="atp-v2-empty">Plan verisi alınamadı.</td></tr>';
    var alertWrap = qs('atpAlertsBody');
    if (alertWrap) alertWrap.innerHTML = '<p style="padding:12px 14px;font-size:12px;color:var(--red)">Plan verisi alınamadı.</p>';
    var retryBtn = qs('atpOpsRetryBtn');
    if (retryBtn) retryBtn.addEventListener('click', function () { loadOps(); });
    console.warn('[AracTakipV2] today-operations failed', status || 'network');
  }

  function loadOps() {
    if (currentTab !== 'gunluk') return Promise.resolve(false);
    var seq = ++_opsReqSeq;
    if (_opsAbort) { try { _opsAbort.abort(); } catch (e) { /* ignore */ } }
    _opsAbort = typeof AbortController !== 'undefined' ? new AbortController() : null;
    var signal = _opsAbort ? _opsAbort.signal : undefined;

    var opsUrl = '/planlama/arac-takip/api/today-operations?date=' + encodeURIComponent(planDate);
    var filomUrl = '/planlama/arac-takip/api/araclar';

    var opsPromise = _fetchWithTimeout(opsUrl, signal, OPS_TIMEOUT_MS);
    var filomPromise = _fetchWithTimeout(filomUrl, signal, OPS_TIMEOUT_MS).catch(function () { return null; });

    return Promise.all([opsPromise, filomPromise]).then(function (results) {
      if (seq !== _opsReqSeq) return false;
      var data = results[0];
      var filomBody = results[1];
      if (!data || !data.ok) { _opsShowError('nok'); return false; }
      if (filomBody && filomBody.vehicles) {
        lastVehicles = filomBody.vehicles;
      }
      _opsApplySuccess(data, filomBody);
      return true;
    }).catch(function (err) {
      if (seq !== _opsReqSeq) return false;
      if (err && err.name === 'AbortError') return false;
      _opsShowError((err && err.status) || 'network');
      return false;
    });
  }

  window.loadAtpTodayOps = loadOps;

  /* ─── Vehicle select (hidden, feeds route + modal) ─── */
  function hydrateVehicleSelect(filomVehicles, opsVehicles) {
    var sel = qs('atpSelVehicle');
    var reqSel = qs('atpReqArac');
    if (!sel && !reqSel) return;

    var seen = {};
    var opts = [{ value: '', label: '— Araç seç —' }];

    /* Prefer ops vehicles (have plan context) */
    (opsVehicles || []).forEach(function (v) {
      var vid = String(v.arac_external_id || v.id || '');
      if (!vid || seen[vid]) return;
      seen[vid] = true;
      var pl = safePlate(v);
      opts.push({ value: vid, label: pl, driver: v.driver_name || v.driver });
    });
    /* Add filom vehicles not in ops */
    (filomVehicles || []).forEach(function (v) {
      var vid = String(v.id || '');
      if (!vid || seen[vid]) return;
      seen[vid] = true;
      var pl = safePlate(v);
      opts.push({ value: vid, label: pl, driver: v.driver_name });
    });

    var optHtml = opts.map(function (o) {
      return '<option value="' + o.value + '"' + (o.driver ? ' data-driver="' + o.driver + '"' : '') + '>' + o.label + '</option>';
    }).join('');

    if (sel) sel.innerHTML = optHtml;
    if (reqSel) reqSel.innerHTML = optHtml;
  }

  function vehicleId() {
    var sel = qs('atpSelVehicle');
    return _activeVehicleExtId || (sel && sel.value) || urlParams.get('vehicle_id') || dashboard.selected_vehicle_id || null;
  }

  /* ─── Route refresh ─── */
  function refreshPlanRoute(overrideVehicleId) {
    if (currentTab !== 'gunluk' || !window.AtpRoute) return Promise.resolve(null);
    var vid = overrideVehicleId != null ? String(overrideVehicleId) : vehicleId();
    if (!vid) return Promise.resolve(null);
    return new Promise(function (resolve) {
      window.AtpRoute.fetchPlanRoute(planDate, vid, function (dto, responseVid) {
        if (String(_activeVehicleExtId) !== String(responseVid || vid)) {
          resolve(null);
          return;
        }
        if (dto) {
          dashboard = Object.assign({}, dashboard, dto);
          var dashJson = qs('atpDashboardJson');
          if (dashJson) dashJson.textContent = JSON.stringify(dashboard);
        }
      }, {
        expectedVehicleId: vid,
        onStale: function (expectedVid) {
          return String(_activeVehicleExtId) !== String(expectedVid);
        },
        onComplete: function () {
          resolve(window.AtpRoute.getLastRoute ? window.AtpRoute.getLastRoute() : null);
        }
      });
    });
  }

  if (window.AtpRoute) {
    window.addEventListener('load', function () {
      if (_activeVehicleExtId) setTimeout(function () { refreshPlanRoute(_activeVehicleExtId); }, 350);
    });
  }

  window.applyAtpDashboard = function (partial) {
    if (partial.base_location) dashboard.base_location = partial.base_location;
    if (partial.plan_map) dashboard.plan_map = partial.plan_map;
    if (partial.daily_tasks && partial.daily_tasks.length) renderStopList(partial.daily_tasks);
  };

  /* ─── Plan map update ─── */
  function updatePlanMap() {
    if (!window.AtpPlanMap) return;
    var planMapData = dashboard.plan_map || { base: {}, stops: [], completeness: {} };
    window.AtpPlanMap.renderPlanMap(planMapData);
  }

  /* ─── Live vehicles (canli tab) ─── */
  function statusDotClass(st) {
    if (st === 'HAREKETLI') return 'green';
    if (st === 'ROLANTI') return 'orange';
    if (st === 'DURAN') return 'red';
    return 'gray';
  }

  function liveBadge(v) {
    if (v.gps_is_stale || v.is_stale_data)
      return '<span class="badge badge-stale">GPS Eski</span>';
    if (v.route_state === 'DEVIATING')
      return '<span class="badge badge-orange">⚠ Sapma</span>';
    if (v.route_state === 'ON_ROUTE' || v.activity_status === 'HAREKETLI')
      return '<span class="badge badge-green">● Yolda</span>';
    if (v.activity_status === 'DURAN')
      return '<span class="badge badge-gray">⏸ Duran</span>';
    return '<span class="badge badge-gray">' + fmtVal(v.activity_status_label || v.activity_status) + '</span>';
  }

  function renderLiveVehicles(vehicles) {
    var list = qs('atpVehicleList');
    if (!list) return;
    if (!vehicles || !vehicles.length) {
      list.innerHTML = '<div class="live-vehicles-empty">Filom API\'de araç bulunamadı.</div>';
      return;
    }
    list.innerHTML = vehicles.map(function (v) {
      var plate = safePlate(v);
      var badge = liveBadge(v);
      var driver = fmtVal(v.driver_name || v.driver);
      var speed = v.speed_kmh != null ? v.speed_kmh + ' km/s' : '—';
      var note = '';
      if (v.route_state === 'DEVIATING') {
        var km = (Number(v.deviation_m || v.current_deviation_m || 0) / 1000).toLocaleString('tr-TR', { maximumFractionDigits: 1 });
        note = '<div class="lvcard-note">' + km + ' km</div>';
      } else if (v.gps_is_stale || v.is_stale_data) {
        note = '<div class="lvcard-note muted">' + fmtGpsAge(v.gps_last_seen_at || v.last_seen_at) + '</div>';
      }
      var deviating = v.route_state === 'DEVIATING';
      var stale = v.gps_is_stale || v.is_stale_data;
      var cardCls = 'lvcard' + (deviating ? ' warn' : '') + (stale ? ' stale' : '');
      var selected = liveSelectedVehicleId != null && String(v.id) === String(liveSelectedVehicleId);
      if (selected) cardCls += ' selected';
      return '<div class="' + cardCls + '" data-vehicle-id="' + v.id + '">' +
        '<div class="lvcard-plate">' + plate + '</div>' +
        '<div class="lvcard-driver">' + driver + '</div>' +
        '<div class="lvcard-row">' + badge + '<span class="lvcard-speed">' + speed + '</span></div>' +
        note + '</div>';
    }).join('');

    list.querySelectorAll('[data-vehicle-id]').forEach(function (node) {
      node.onclick = function () {
        liveSelectedVehicleId = node.getAttribute('data-vehicle-id');
        list.querySelectorAll('[data-vehicle-id]').forEach(function (n) {
          n.classList.toggle('selected', n.getAttribute('data-vehicle-id') === liveSelectedVehicleId);
        });
        if (window.AtpLiveMap) window.AtpLiveMap.focusVehicle(liveSelectedVehicleId);
      };
    });
  }

  function syncLiveKpi(kpi, count, opsBundle) {
    function s(id, v) { var el = qs(id); if (el && v != null) el.textContent = String(v); }
    /* Merge filom KPI with ops KPI — ops is authoritative for job counts */
    var opsKpi = (opsBundle && opsBundle.kpi) || {};
    /* aktif_arac: prefer filom count (real-time), fallback ops */
    var aktif = (kpi && kpi.aktif_arac != null) ? kpi.aktif_arac
      : (opsKpi.aktif_arac != null ? opsKpi.aktif_arac : (count || 0));
    s('atpKpiAktifCanli', aktif);
    /* hareket_halinde from ops is more reliable (GPS polling) */
    var harak = (kpi && kpi.hareket_halinde != null) ? kpi.hareket_halinde
      : (opsKpi.hareket_halinde != null ? opsKpi.hareket_halinde : 0);
    s('atpKpiHareketCanli', harak);
    var sapmaCard = qs('atpKpiSapmaCard');
    var sapmaEl = qs('atpKpiSapma');
    var sap = liveMergedVehicles.filter(function (v) { return v.route_state === 'DEVIATING'; }).length;
    if (sapmaEl) sapmaEl.textContent = String(sap);
    if (sapmaCard) { sapmaCard.classList.remove('warn'); if (sap > 0) sapmaCard.classList.add('warn'); }
    s('atpKpiSonGuncelleme', liveLastPollAt ? fmtTimeStamp(liveLastPollAt) : '—');
    /* GPS health: fresh = not stale, total = all filom vehicles */
    var all = liveMergedVehicles.length || (count || 0);
    var fresh = liveMergedVehicles.filter(function (v) { return !v.gps_is_stale && !v.is_stale_data; }).length;
    var health = all ? fresh + '/' + all : '—';
    s('atpKpiGpsSaglik', health);
    var gpsCard = qs('atpKpiGpsCard');
    if (gpsCard) {
      gpsCard.classList.remove('ok', 'warn');
      if (health !== '—') {
        var parts = health.split('/');
        if (parts.length === 2 && parseInt(parts[0]) >= parseInt(parts[1])) gpsCard.classList.add('ok');
        else gpsCard.classList.add('warn');
      }
    }
  }

  function mergeLiveData(filomVehicles, opsBundle) {
    if (!opsBundle || !opsBundle.vehicles) return filomVehicles;
    var byId = {};
    (opsBundle.vehicles || []).forEach(function (o) {
      byId[String(o.arac_external_id)] = o;
    });
    return filomVehicles.map(function (v) {
      var ops = byId[String(v.id)];
      if (!ops) return v;
      return Object.assign({}, v, ops, { plate_display: v.plate_display || v.plate, id: v.id });
    });
  }

  function showLiveError(isPoll) {
    liveFetchState = 'error';
    var list = qs('atpVehicleList');
    if (!isPoll && list) list.innerHTML = '<div class="live-vehicles-empty">Canlı araç verisi şu anda alınamıyor.</div>';
    if (window.AtpLiveMap) window.AtpLiveMap.refreshLiveVehicles([], { failed: true });
  }

  function loadLiveVehicles(isPoll) {
    liveFetchState = 'loading';
    var ac = typeof AbortController !== 'undefined' ? new AbortController() : null;
    var signal = ac ? ac.signal : undefined;
    var timeoutId = setTimeout(function () { if (ac) ac.abort(); }, LIVE_TIMEOUT_MS);

    var filomPromise = fetch('/planlama/arac-takip/api/araclar', { credentials: 'same-origin', signal: signal })
      .then(function (r) { return r.json(); });
    var opsPromise = fetch('/planlama/arac-takip/api/today-operations?date=' + encodeURIComponent(planDate), {
      credentials: 'same-origin', signal: signal
    }).then(function (r) { return r.json(); }).catch(function () { return null; });

    Promise.all([filomPromise, opsPromise]).then(function (results) {
      clearTimeout(timeoutId);
      var filomData = results[0];
      var opsData = results[1];
      if (!filomData || !filomData.vehicles) { showLiveError(isPoll); return; }

      lastVehicles = filomData.vehicles;
      liveOpsCache = opsData;
      lastLiveFilomKpi = filomData.filom_kpi || null;
      lastLiveFilomCount = filomData.vehicles.length;
      liveLastPollAt = new Date();

      liveMergedVehicles = mergeLiveData(filomData.vehicles, opsData);
      liveFetchState = 'ok';

      /* Build full vehicle objects for map — includes has_valid_location from filom API */
      var mapVehicles = liveMergedVehicles.map(function (v) {
        return {
          id: v.id,
          latitude: v.latitude, longitude: v.longitude,
          lat: v.latitude, lng: v.longitude,
          has_valid_location: v.has_valid_location != null ? v.has_valid_location
            : (v.latitude != null && v.longitude != null),
          plate: safePlate(v), plate_display: safePlate(v),
          driver_name: v.driver_name || v.driver || '—',
          activity_status: v.activity_status,
          activity_status_label: v.activity_status_label || v.activity_status,
          route_state: v.route_state,
          speed_kmh: v.speed_kmh,
          is_stale_data: v.is_stale_data || v.gps_is_stale,
          last_seen_at: v.last_seen_at || v.gps_last_seen_at,
          total_distance_km: v.total_distance_km,
          address: v.address,
        };
      });

      if (currentTab === 'canli') {
        renderLiveVehicles(liveMergedVehicles);
        syncLiveKpi(lastLiveFilomKpi, lastLiveFilomCount, opsData);
        if (window.AtpLiveMap) {
          window.AtpLiveMap.refreshLiveVehicles(mapVehicles, { success: true });
        }
        var rt = qs('atpLiveRefreshText');
        if (rt) rt.textContent = 'Son güncelleme: ' + fmtTimeStamp(liveLastPollAt);
      }
      /* Also update gunluk KPI band with aktif/hareket */
      if (currentTab === 'gunluk') {
        var aktif = qs('atpKpiAktif');
        var hark = qs('atpKpiHareket');
        if (aktif && aktif.textContent === '—') aktif.textContent = String(lastLiveFilomCount || 0);
        if (hark && hark.textContent === '—') {
          var fk = lastLiveFilomKpi || {};
          var opsKpi = (opsData && opsData.kpi) || {};
          hark.textContent = String(
            fk.hareket_halinde != null ? fk.hareket_halinde
            : opsKpi.hareket_halinde != null ? opsKpi.hareket_halinde : 0
          );
        }
      }
      hydrateVehicleSelect(filomData.vehicles, []);
    }).catch(function (err) {
      clearTimeout(timeoutId);
      if (err && err.name === 'AbortError') return;
      showLiveError(isPoll);
    });
  }

  /* Start live polling */
  loadLiveVehicles(false);
  pollTimer = setInterval(function () { loadLiveVehicles(true); }, LIVE_POLL_MS);

  var liveRefreshBtn = qs('atpLiveRefreshBtn');
  if (liveRefreshBtn) liveRefreshBtn.addEventListener('click', function () { loadLiveVehicles(false); });

  var fitAllBtn = qs('atpBtnFitAll');
  if (fitAllBtn) fitAllBtn.addEventListener('click', function () {
    if (window.AtpLiveMap) window.AtpLiveMap.fitAll();
  });

  /* ─── Timeline modal ─── */
  function openTimelineModal(planId, vid) {
    var backdrop = qs('atpTimelineBackdrop');
    var modal = qs('atpTimelineModal');
    var body = qs('atpTimelineBody');
    if (!backdrop || !modal || !body) return;
    body.innerHTML = '<p style="color:var(--gray);font-size:12px">Yükleniyor…</p>';
    backdrop.classList.add('open');
    backdrop.setAttribute('aria-hidden', 'false');
    modal.setAttribute('aria-hidden', 'false');
    var qs2 = [];
    if (planId) qs2.push('plan_id=' + encodeURIComponent(planId));
    if (vid) qs2.push('vehicle_id=' + encodeURIComponent(vid));
    if (planDate) qs2.push('date=' + encodeURIComponent(planDate));
    fetch('/planlama/arac-takip/api/plan-timeline?' + qs2.join('&'), { credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data || !data.ok || !data.events || !data.events.length) {
          body.innerHTML = '<p style="color:var(--gray);font-size:12px">Bu plan için henüz kayıtlı olay yok.</p>';
          return;
        }
        function dotCls(t) {
          if (t === 'KONUMA_VARILDI' || t === 'ROTA_GERI_DONDU') return 'green';
          if (t === 'KONUMDAN_AYRILDI' || t === 'ROTA_SAPMA_BASLADI') return 'orange';
          return 'gray';
        }
        body.innerHTML = '<div class="timeline">' + data.events.map(function (ev) {
          return '<div class="tl-row">' +
            '<div class="tl-time">' + fmtVal(ev.time_display || ev.time) + '</div>' +
            '<div class="tl-dot ' + dotCls(ev.type) + '"></div>' +
            '<div class="tl-text"><strong>' + fmtVal(ev.title) + '</strong> — ' + fmtVal(ev.message) + '</div></div>';
        }).join('') + '</div>';
      })
      .catch(function () {
        body.innerHTML = '<p style="color:var(--gray);font-size:12px">Olay verisi alınamadı.</p>';
      });
  }

  function closeTimelineModal() {
    var backdrop = qs('atpTimelineBackdrop');
    var modal = qs('atpTimelineModal');
    if (backdrop) { backdrop.classList.remove('open'); backdrop.setAttribute('aria-hidden', 'true'); }
    if (modal) modal.setAttribute('aria-hidden', 'true');
  }

  ['atpTimelineClose','atpTimelineDismiss'].forEach(function (id) {
    var btn = qs(id);
    if (btn) btn.addEventListener('click', closeTimelineModal);
  });
  var tlBackdrop = qs('atpTimelineBackdrop');
  if (tlBackdrop) tlBackdrop.addEventListener('click', function (e) {
    if (e.target === tlBackdrop) closeTimelineModal();
  });

  /* ─── Plana İş Ekle Modal ─── */
  function openPlanaModal() {
    var backdrop = qs('atpModalBackdrop');
    var modal = qs('atpRequestModal');
    var tarih = qs('atpReqTarih');
    if (tarih) tarih.value = planDate;
    /* populate vehicle select */
    var reqSel = qs('atpReqArac');
    if (reqSel && reqSel.options.length <= 1) hydrateVehicleSelect(lastVehicles, []);
    validateAddForm();
    if (backdrop) { backdrop.classList.add('open'); backdrop.setAttribute('aria-hidden', 'false'); }
    if (modal) modal.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden';
    /* focus first input */
    setTimeout(function () {
      var first = modal && modal.querySelector('input:not([readonly]):not([type=hidden]),select');
      if (first) first.focus();
    }, 60);
  }

  function closePlanaModal() {
    var backdrop = qs('atpModalBackdrop');
    var modal = qs('atpRequestModal');
    if (backdrop) { backdrop.classList.remove('open'); backdrop.setAttribute('aria-hidden', 'true'); }
    if (modal) modal.setAttribute('aria-hidden', 'true');
    document.body.style.overflow = '';
  }

  /* Escape key closes modal */
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
      var backdrop = qs('atpModalBackdrop');
      if (backdrop && backdrop.classList.contains('open')) closePlanaModal();
    }
  });

  var btnPlana = qs('atpBtnPlanaIsEkle');
  var btnPlanaPrs = qs('atpBtnPlanaIsEklePrs');
  var btnPlanaEmpty = qs('atpBtnPlanaIsEkleEmpty');
  if (btnPlana) btnPlana.addEventListener('click', openPlanaModal);
  if (btnPlanaPrs) btnPlanaPrs.addEventListener('click', openPlanaModal);
  if (btnPlanaEmpty) btnPlanaEmpty.addEventListener('click', openPlanaModal);

  /* Quick plan vehicle select — sync driver */
  var quickArac = qs('atpQuickArac');
  var quickSofor = qs('atpQuickSofor');
  if (quickArac) quickArac.addEventListener('change', function () {
    var opt = quickArac.options[quickArac.selectedIndex];
    if (opt && quickSofor) quickSofor.value = opt.getAttribute('data-driver') || '';
  });

  var modalCancel = qs('atpModalCancel');
  var modalClose = qs('atpModalClose');
  if (modalCancel) modalCancel.addEventListener('click', closePlanaModal);
  if (modalClose) modalClose.addEventListener('click', closePlanaModal);

  var modalBackdrop = qs('atpModalBackdrop');
  if (modalBackdrop) modalBackdrop.addEventListener('click', function (e) {
    if (e.target === modalBackdrop) closePlanaModal();
  });

  /* Validate add form */
  function validateAddForm() {
    var firma = qs('atpReqFirma');
    var is = qs('atpReqIs');
    var arac = qs('atpReqArac');
    var tarih = qs('atpReqTarih');
    var saat = qs('atpReqSaat');
    var submit = qs('atpModalSubmit');
    var ok = firma && firma.value.trim() &&
      is && is.value.trim() &&
      arac && arac.value &&
      tarih && tarih.value &&
      saat && saat.value;
    if (submit) submit.disabled = !ok;
    return !!ok;
  }

  ['atpReqFirma','atpReqIs','atpReqArac','atpReqTarih','atpReqSaat'].forEach(function (id) {
    var el = qs(id);
    if (el) { el.addEventListener('input', validateAddForm); el.addEventListener('change', validateAddForm); }
  });

  /* Sync driver from vehicle select */
  var reqArac = qs('atpReqArac');
  var reqSofor = qs('atpReqPlanaSofor');
  if (reqArac) reqArac.addEventListener('change', function () {
    var opt = reqArac.options[reqArac.selectedIndex];
    if (opt && reqSofor) reqSofor.value = opt.getAttribute('data-driver') || '';
    validateAddForm();
  });

  /* Submit add form */
  var modalSubmit = qs('atpModalSubmit');
  if (modalSubmit) modalSubmit.addEventListener('click', function () {
    if (!validateAddForm()) {
      var warn = qs('atpModalWarn'); if (warn) warn.classList.add('show');
      return;
    }
    var payload = {
      plan_tarihi: planDate,
      tarih: planDate,
      arac_external_id: (qs('atpReqArac') || {}).value || '',
      yapilacak_is: ((qs('atpReqIs') || {}).value || '').trim(),
      is: ((qs('atpReqIs') || {}).value || '').trim(),
      firma: ((qs('atpReqFirma') || {}).value || '').trim(),
      planlanan_saat: ((qs('atpReqSaat') || {}).value || ''),
      oncelik: ((qs('atpReqOncelik') || {}).value || 'NORMAL'),
      is_turu: ((qs('atpReqIsTuru') || {}).value || 'TESLIM'),
      urun_malzeme: ((qs('atpReqUrun') || {}).value || '').trim(),
      miktar: ((qs('atpReqMiktar') || {}).value || '').trim(),
      miktar_birim: ((qs('atpReqBirim') || {}).value || 'ADET'),
      ek_not: ((qs('atpReqNot') || {}).value || '').trim(),
      location_master_id: ((qs('atpReqLocationMasterId') || {}).value || '') || null,
    };
    modalSubmit.disabled = true;
    fetch('/planlama/arac-takip/api/plana-is-ekle', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }).then(function (r) { return r.json(); }).then(function (j) {
      if (!j.ok) { toast('İş eklenemedi: ' + (j.message || '')); modalSubmit.disabled = false; return; }
      closePlanaModal();
      toast('İş plana eklendi.');
      loadOps();
    }).catch(function () {
      toast('Sunucu hatası. Tekrar deneyin.');
      modalSubmit.disabled = false;
    });
  });

  /* Firma autocomplete */
  var firmaInput = qs('atpReqFirma');
  var firmaDropdown = qs('atpFirmaDropdown');
  var firmaTimer = null;

  if (firmaInput && firmaDropdown) {
    firmaInput.addEventListener('input', function () {
      clearTimeout(firmaTimer);
      var q = firmaInput.value.trim();
      if (q.length < 2) { firmaDropdown.classList.remove('open'); return; }
      firmaTimer = setTimeout(function () {
        fetch('/planlama/arac-takip/api/locations/search?q=' + encodeURIComponent(q), { credentials: 'same-origin' })
          .then(function (r) { return r.json(); })
          .then(function (data) {
            var items = data.results || [];
            if (!items.length) { firmaDropdown.classList.remove('open'); return; }
            firmaDropdown.innerHTML = items.slice(0, 8).map(function (it) {
              return '<div class="firma-dd-item" data-id="' + (it.id || '') + '" data-adres="' + (it.address || '') + '">' +
                '<strong>' + fmtVal(it.name) + '</strong>' +
                '<span>' + fmtVal(it.address) + '</span></div>';
            }).join('');
            firmaDropdown.classList.add('open');
            firmaDropdown.querySelectorAll('.firma-dd-item').forEach(function (item) {
              item.addEventListener('mousedown', function (e) {
                e.preventDefault();
                firmaInput.value = item.querySelector('strong').textContent;
                var lid = item.getAttribute('data-id');
                var midEl = qs('atpReqLocationMasterId');
                if (midEl) midEl.value = lid;
                firmaDropdown.classList.remove('open');
                validateAddForm();
              });
            });
          }).catch(function () { firmaDropdown.classList.remove('open'); });
      }, 300);
    });
    firmaInput.addEventListener('blur', function () { setTimeout(function () { firmaDropdown.classList.remove('open'); }, 180); });
  }

  /* ─── Route UI wiring ─── */
  if (window.AtpRoute) {
    window.AtpRoute.bindRouteUi(planDate, vehicleId, {
      toast: toast,
      getVehicleId: vehicleId,
      getVehiclePlate: function () {
        var v = findVehicleByExtId(_activeVehicleExtId);
        return v ? safePlate(v) : '—';
      },
      isStaleVehicle: function (vid) {
        return String(_activeVehicleExtId) !== String(vid);
      },
      reloadAfterApply: function (vid, expectedTaskIds) {
        if (vid) _activeVehicleExtId = String(vid);
        return loadOps().then(function (ok) {
          if (!ok) return false;
          return refreshPlanRoute(vid).then(function () {
            return verifyApplyReadback(vid, expectedTaskIds);
          });
        });
      }
    });
  }

  /* ─── Calendar (mini) ─── */
  function buildCalendar(containerId) {
    var cal = qs(containerId);
    if (!cal) return;
    var d = new Date(planDate + 'T00:00:00');
    var y = d.getFullYear();
    var m = d.getMonth();
    var daysInMonth = new Date(y, m + 1, 0).getDate();
    var firstDay = new Date(y, m, 1).getDay();
    var startOffset = (firstDay + 6) % 7; /* Mon=0 */
    var days = ['Pt','Sa','Ça','Pe','Cu','Ct','Pz'];
    var todayStr = new Date().toISOString().slice(0, 10);
    var html = '<div class="atp-cal">' +
      days.map(function (d) { return '<span class="atp-cal-hdr">' + d + '</span>'; }).join('');
    for (var i = 0; i < startOffset; i++) html += '<span></span>';
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
  buildCalendar('atpCalendarLive');

  /* ─── Weekly Plan ─── */
  function weekStart(offsetWeeks) {
    var today = new Date();
    var dayOfWeek = today.getDay();
    var diff = (dayOfWeek + 6) % 7; /* Monday */
    var mon = new Date(today);
    mon.setDate(today.getDate() - diff + offsetWeeks * 7);
    return mon;
  }

  function loadWeekly(offset) {
    var mon = weekStart(offset);
    var titleEl = qs('atpWeeklyTitle');
    var grid = qs('atpWeeklyGrid');
    var summCard = qs('atpWeeklySummaryCard');
    var summTitle = qs('atpWeeklySummaryTitle');
    var summBody = qs('atpWeeklySummaryBody');

    var sun = new Date(mon);
    sun.setDate(mon.getDate() + 6);
    var TR_MONTHS = ['Oca','Şub','Mar','Nis','May','Haz','Tem','Ağu','Eyl','Eki','Kas','Ara'];
    var TR_DAYS = ['Pt','Sa','Ça','Pe','Cu','Ct','Pz'];
    var TR_FULL_DAYS = ['Pazartesi','Salı','Çarşamba','Perşembe','Cuma','Cumartesi','Pazar'];
    if (titleEl) titleEl.textContent = mon.getDate() + ' ' + TR_MONTHS[mon.getMonth()] + ' – ' +
      sun.getDate() + ' ' + TR_MONTHS[sun.getMonth()] + ' ' + sun.getFullYear();

    if (grid) grid.innerHTML = '<div class="atp-loading" style="grid-column:1/-1">Yükleniyor…</div>';

    var todayStr = new Date().toISOString().slice(0, 10);
    var promises = [];
    var dates = [];
    for (var i = 0; i < 7; i++) {
      var d = new Date(mon);
      d.setDate(mon.getDate() + i);
      dates.push(d.toISOString().slice(0, 10));
      promises.push(
        fetch('/planlama/arac-takip/api/day-plan-summary?date=' + d.toISOString().slice(0, 10), { credentials: 'same-origin' })
          .then(function (r) { return r.json(); })
          .catch(function () { return { ok: false }; })
      );
    }

    Promise.all(promises).then(function (results) {
      if (!grid) return;
      var totalJobs = 0, totalDone = 0, totalVeh = 0;
      grid.innerHTML = results.map(function (res, i) {
        var ds = dates[i];
        var d = new Date(ds + 'T00:00:00');
        var isToday = ds === todayStr;
        var summ = (res && res.day_plan_summary) || {};
        var jobs = summ.toplam_is || 0;
        var done = summ.tamamlandi || 0;
        var veh = summ.arac_sayisi || 0;
        var km = summ.toplam_km || 0;
        totalJobs += jobs;
        totalDone += done;
        totalVeh = Math.max(totalVeh, veh);
        var dayLink = '?tab=gunluk&date=' + ds;
        return '<div class="day-card' + (isToday ? ' today' : '') + '" style="cursor:pointer" onclick="window.location.href=\'' + dayLink + '\'">' +
          '<div class="day-name">' + TR_DAYS[i] + '</div>' +
          '<div class="day-num">' + d.getDate() + '</div>' +
          (jobs ? '<div class="day-stat">' +
            '<div class="day-stat-row"><span>Araç</span><span>' + veh + '</span></div>' +
            '<div class="day-stat-row"><span>İş</span><span>' + jobs + '</span></div>' +
            '<div class="day-stat-row" style="color:' + (done >= jobs ? 'var(--green)' : 'var(--orange)') + '"><span>Tamamlandı</span><span>' + done + '</span></div>' +
            (km ? '<div class="day-stat-row"><span>KM</span><span>' + km + '</span></div>' : '') +
          '</div>' : '<div class="day-empty">Plan yok</div>') +
          '</div>';
      }).join('');

      /* Weekly summary */
      if (summCard) summCard.style.display = '';
      if (summTitle) summTitle.textContent = 'Haftalık Özet — ' + mon.getDate() + ' ' + TR_MONTHS[mon.getMonth()] + ' – ' +
        sun.getDate() + ' ' + TR_MONTHS[sun.getMonth()] + ' ' + sun.getFullYear();
      if (summBody) summBody.innerHTML = [
        [totalJobs, 'Toplam İş', '#111827'],
        [totalDone, 'Tamamlandı', 'var(--green)'],
        [totalJobs - totalDone, 'Bekleyen', 'var(--orange)'],
        [totalVeh, 'Maks. Araç', '#111827'],
        ['—', 'km', '#111827'],
      ].map(function (item) {
        return '<div style="text-align:center"><div style="font-size:22px;font-weight:800;color:' + item[2] + '">' +
          item[0] + '</div><div style="font-size:11px;color:var(--gray)">' + item[1] + '</div></div>';
      }).join('');
    });
  }

  var btnPrev = qs('atpBtnPrevWeek');
  var btnNext = qs('atpBtnNextWeek');
  if (btnPrev) btnPrev.addEventListener('click', function () { weekOffset--; loadWeekly(weekOffset); });
  if (btnNext) btnNext.addEventListener('click', function () { weekOffset++; loadWeekly(weekOffset); });

  /* ─── History ─── */
  function loadHistory() {
    var body = qs('atpHistBody');
    if (!body) return;
    var baslangic = (qs('atpHistBaslangic') || {}).value || '';
    var bitis = (qs('atpHistBitis') || {}).value || '';
    var arac = (qs('atpHistArac') || {}).value || '';
    var sofor = (qs('atpHistSofor') || {}).value || '';
    body.innerHTML = '<tr><td colspan="8" class="hist-empty">Yükleniyor…</td></tr>';

    /* Use dashboard history_rows (SSR) or fetch */
    var rows = dashboard.history_rows || [];
    if (rows.length) {
      renderHistoryRows(rows);
    } else {
      /* No dedicated history endpoint; show empty state */
      body.innerHTML = '<tr><td colspan="8" class="hist-empty">Geçmiş plan verisi bulunamadı.</td></tr>';
    }
  }

  function renderHistoryRows(rows) {
    var body = qs('atpHistBody');
    if (!body) return;
    if (!rows.length) {
      body.innerHTML = '<tr><td colspan="8" class="hist-empty">Kayıt yok.</td></tr>';
      return;
    }
    var MONTHS = ['Oca','Şub','Mar','Nis','May','Haz','Tem','Ağu','Eyl','Eki','Kas','Ara'];
    body.innerHTML = rows.map(function (r) {
      var d = new Date((r.date || '') + 'T00:00:00');
      var dateLbl = isNaN(d) ? r.date : d.getDate() + ' ' + MONTHS[d.getMonth()];
      var stCls = r.status === 'TAMAMLANDI' ? 'badge-green' : (r.status === 'KISMI' ? 'badge-orange' : 'badge-red');
      return '<tr>' +
        '<td style="font-weight:600">' + dateLbl + '</td>' +
        '<td>' + fmtVal(r.vehicle) + '</td>' +
        '<td>' + fmtVal(r.driver) + '</td>' +
        '<td>' + fmtVal(r.total_jobs) + '</td>' +
        '<td style="color:' + (r.completed >= r.total_jobs ? 'var(--green)' : 'var(--orange)') + ';font-weight:600">' + fmtVal(r.completed) + '</td>' +
        '<td>' + fmtVal(r.total_km) + ' km</td>' +
        '<td><span class="badge ' + stCls + '">' + fmtVal(r.status_label) + '</span></td>' +
        '<td><button class="btn btn-outline btn-xs">Görüntüle</button></td></tr>';
    }).join('');
  }

  var btnHistFiltrele = qs('atpBtnHistFiltrele');
  if (btnHistFiltrele) btnHistFiltrele.addEventListener('click', loadHistory);

  /* ─── Initial tab setup ─── */
  /* Init view states before setTab is called */
  (function initViews() {
    var canliView = qs('atpCanliView');
    var gunlukView = qs('atpGunlukView');
    var dateBar = qs('atpDateBar');
    var kpiBand = qs('atpKpiBand');
    var kpiCanli = qs('atpKpiBandCanli');
    /* Start with everything hidden, setTab will show correct view */
    if (canliView) canliView.style.display = 'none';
    if (kpiCanli) kpiCanli.style.display = 'none';
    if (gunlukView) gunlukView.style.display = (initTab === 'gunluk') ? '' : 'none';
    if (dateBar) dateBar.style.display = (initTab === 'gunluk') ? '' : 'none';
    if (kpiBand) kpiBand.style.display = (initTab === 'gunluk') ? '' : 'none';
  }());

  try { setTab(initTab); } catch (e) {
    console.error('[AracTakipV2] tab init error:', e);
    currentTab = initTab;
  }

  /* ─── Plan map init ─── */
  if (initTab === 'gunluk' && window.AtpPlanMap) updatePlanMap();

  /* ─── Ops load on gunluk ─── */
  if (initTab === 'gunluk') {
    loadOps();
    opsTimer = setInterval(loadOps, 60000);
  }

  /* ─── Haftalik / Gecmis init ─── */
  if (initTab === 'haftalik') loadWeekly(0);
  if (initTab === 'gecmis') loadHistory();

  /* ─── WhatsApp ─── */
  var btnWa = qs('atpBtnWhatsapp');
  if (btnWa) btnWa.addEventListener('click', function () {
    fetch('/planlama/arac-takip/api/whatsapp?date=' + encodeURIComponent(planDate), { credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (j.url) window.open(j.url, '_blank');
        else toast(j.message || 'WhatsApp bağlantısı oluşturulamadı.');
      }).catch(function () { toast('WhatsApp bağlantısı oluşturulamadı.'); });
  });

  /* ─── Base location button ─── */
  var btnBase = qs('atpBtnBaseLocation');
  if (btnBase) btnBase.addEventListener('click', function () {
    if (window.AtpPlanMap) window.AtpPlanMap.focusBase();
  });

  /* ─── ESC close modals ─── */
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') { closeTimelineModal(); closePlanaModal(); }
  });

  /* ─── Accordion toggle: init plan map when opened ─── */
  var planAcc = qs('atpPlanningSection');
  if (planAcc) {
    planAcc.addEventListener('toggle', function () {
      if (planAcc.open && window.AtpPlanMap) {
        /* Give the browser one frame to render the now-visible container */
        requestAnimationFrame(function () {
          window.AtpPlanMap.onPlanTabShown();
        });
        /* Extra safety pass */
        setTimeout(function () {
          if (window.AtpPlanMap) window.AtpPlanMap.onPlanTabShown();
        }, 250);
      }
    });
  }

  /* ─── Expose for external scripts ─── */
  window.atpOpenTimeline = openTimelineModal;
  window.atpSetTab = setTab;

}());
