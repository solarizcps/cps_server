/* Araç Takip V2 — main controller
   v=26 — mockup-parity production integration
   Root: #atpV2Root
*/
(function () {
  'use strict';

  /* ─── Root check ─── */
  var root = document.getElementById('atpV2Root');
  if (!root) return;

  /* ─── Injected styles (firma dropdown + validation errors) ─── */
  (function () {
    var s = document.createElement('style');
    s.textContent =
      '.firma-dd-item.firma-dd-focused{background:#fffbec;outline:2px solid #f59e0b;}' +
      '.firma-dd-item.firma-dd-new strong{color:#1d4ed8;font-style:italic;}' +
      /* validation error states */
      '.atp-field-err input,.atp-field-err select,.atp-field-err textarea{border-color:#ef4444!important;box-shadow:0 0 0 2px rgba(239,68,68,.18)!important;}' +
      '.atp-field-err-msg{display:block;color:#dc2626;font-size:12px;margin-top:3px;font-weight:500;}' +
      '#atpValidationSummary .atp-val-box{background:#fef2f2;border:1px solid #fca5a5;border-radius:6px;padding:8px 12px;font-size:13px;color:#991b1b;line-height:1.5;}' +
      '#atpValidationSummary .atp-val-box ul{margin:4px 0 0 16px;padding:0;}' +
      '#atpValidationSummary .atp-val-box ul li{margin:2px 0;}';
    document.head.appendChild(s);
  }());

  /* ─── Dashboard SSR data ─── */
  var dashEl = document.getElementById('atpDashboardJson');
  var dashboard = {};
  try { dashboard = JSON.parse(dashEl ? dashEl.textContent : '{}'); } catch (e) { dashboard = {}; }

  var planDate = root.getAttribute('data-date') || dashboard.date || new Date().toISOString().slice(0, 10);
  window.ATP_PLAN_DATE = planDate;
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
  var lastPassiveJobs = [];
  var _passiveJobsExpanded = false;
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
  window.toast = toast;

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

  var PLAN_PROVIDER_FILOM = 'TURKCELL_FILOM';

  function normalizePhysicalPlate(label) {
    var raw = String(label || '').trim();
    if (!raw || raw === 'Plaka bilgisi yok') return '';
    var compact = raw.toUpperCase().replace(/[\s.\-_]+/g, '');
    var m = compact.match(/^(\d{2})([A-Z]{1,3})(\d{2,4})$/);
    if (m) return m[1] + ' ' + m[2] + ' ' + m[3];
    return raw.toUpperCase().replace(/\s+/g, ' ').trim();
  }

  function _vehicleGpsTs(v) {
    var ts = v && (v.gps_last_seen_at || v.last_seen_at || v.posTimestamp);
    if (!ts) return 0;
    var d = new Date(String(ts).replace(' ', 'T'));
    return isNaN(d.getTime()) ? 0 : d.getTime();
  }

  function _vehicleCanonicalScore(externalId) {
    var ext = String(externalId || '');
    if (/^45\d{5,}$/.test(ext)) return 30;
    if (/^99\d{3,}$/.test(ext)) return 5;
    return 15;
  }

  function _uniqueVehiclePriority(c) {
    if (c.has_current_plan) {
      return 1000000 + _vehicleCanonicalScore(c.external_id) * 1000;
    }
    if (!c.is_stale && c.source === 'filom') {
      return 500000 + _vehicleCanonicalScore(c.external_id) * 1000;
    }
    if (c.source === 'today-operations') {
      return 200000 + _vehicleCanonicalScore(c.external_id) * 1000;
    }
    return 100000 + _vehicleCanonicalScore(c.external_id);
  }

  function _candidateBeats(next, prev) {
    var pn = _uniqueVehiclePriority(next);
    var pp = _uniqueVehiclePriority(prev);
    if (pn !== pp) return pn > pp;
    if (next.gps_ts !== prev.gps_ts) return next.gps_ts > prev.gps_ts;
    return _vehicleCanonicalScore(next.external_id) > _vehicleCanonicalScore(prev.external_id);
  }

  function buildUniquePhysicalVehicleOptions(filomVehicles, opsVehicles) {
    var candidates = [];

    function pushCandidate(v, source) {
      var ext = String(v.arac_external_id || v.id || '').trim();
      if (!ext) return;
      var provider = String(v.arac_provider || v.provider || PLAN_PROVIDER_FILOM).trim();
      var livePlate = normalizePhysicalPlate(v.plate_display || v.plate);
      var opsPlate = normalizePhysicalPlate(v.arac_plaka_snapshot);
      var plateKey = livePlate || opsPlate || '';
      candidates.push({
        external_id: ext,
        provider: provider,
        plateKey: plateKey,
        driver: v.driver_name || v.driver || v.sofor_adi_snapshot || '',
        plan_id: v.plan_id != null ? v.plan_id : null,
        has_current_plan: v.plan_id != null && v.plan_id !== '',
        is_stale: !!(v.is_stale_data || v.gps_is_stale),
        gps_ts: _vehicleGpsTs(v),
        source: source,
      });
    }

    (opsVehicles || []).forEach(function (v) { pushCandidate(v, 'today-operations'); });
    (filomVehicles || []).forEach(function (v) { pushCandidate(v, 'filom'); });

    var winnerByPlate = {};
    var winnerByBlankKey = {};

    candidates.forEach(function (c) {
      if (c.plateKey) {
        var prev = winnerByPlate[c.plateKey];
        if (!prev || _candidateBeats(c, prev)) {
          winnerByPlate[c.plateKey] = c;
        }
      } else {
        var blankKey = c.provider + ':' + c.external_id;
        var prevBlank = winnerByBlankKey[blankKey];
        if (!prevBlank || _candidateBeats(c, prevBlank)) {
          winnerByBlankKey[blankKey] = c;
        }
      }
    });

    var winners = [];
    Object.keys(winnerByPlate).forEach(function (plateKey) {
      winners.push({
        value: winnerByPlate[plateKey].external_id,
        label: plateKey,
        driver: winnerByPlate[plateKey].driver,
        provider: winnerByPlate[plateKey].provider,
        plan_id: winnerByPlate[plateKey].plan_id,
      });
    });

    Object.keys(winnerByBlankKey).forEach(function (blankKey) {
      var c = winnerByBlankKey[blankKey];
      var ext = c.external_id;
      var resolvedPlate = '';
      candidates.forEach(function (x) {
        if (x.external_id === ext && x.plateKey) resolvedPlate = x.plateKey;
      });
      if (resolvedPlate) return;
      if (!c.plateKey) return;
      winners.push({
        value: c.external_id,
        label: c.plateKey,
        driver: c.driver,
        provider: c.provider,
        plan_id: c.plan_id,
      });
    });

    winners.sort(function (a, b) {
      return String(a.label).localeCompare(String(b.label), 'tr');
    });

    return [{ value: '', label: '— Araç seç —', driver: '', provider: '', plan_id: null }].concat(winners);
  }

  function vehicleUniqueOptionsToHtml(options) {
    return (options || []).map(function (o) {
      var attrs = ' value="' + o.value + '"';
      if (o.driver) attrs += ' data-driver="' + o.driver + '"';
      if (o.label && o.value) attrs += ' data-plate="' + o.label + '"';
      if (o.value) attrs += ' data-provider="' + (o.provider || PLAN_PROVIDER_FILOM) + '"';
      if (o.plan_id != null) attrs += ' data-plan-id="' + o.plan_id + '"';
      return '<option' + attrs + '>' + o.label + '</option>';
    }).join('');
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

  function _mergeFilomGpsIntoVehicles(vehicles, filomBody) {
    if (!vehicles || !vehicles.length) return vehicles || [];
    var filom = {};
    var src = (filomBody && filomBody.vehicles) || lastVehicles || [];
    src.forEach(function (v) {
      if (v.id != null) filom[String(v.id)] = v;
    });
    return vehicles.map(function (v) {
      var out = Object.assign({}, v);
      var f = filom[String(v.arac_external_id || '')];
      if (!f) return out;
      if (!out.gps_last_seen_at && !out.gps_timestamp) {
        out.gps_last_seen_at = f.last_seen_at;
        out.gps_timestamp = f.last_seen_at;
      }
      if (out.gps_is_stale == null && out.gps_stale == null) {
        out.gps_is_stale = f.is_stale_data;
        out.gps_stale = f.is_stale_data;
      }
      if (!out.physical_status || out.physical_status === '—') {
        out.physical_status = f.activity_status || f.activity_label || f.status_label;
      }
      if (!out.latest_gps && f.latitude != null) {
        out.latest_gps = {
          latitude: f.latitude,
          longitude: f.longitude,
          gps_timestamp: f.last_seen_at,
          activity_status: f.activity_status,
        };
      }
      return out;
    });
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
      var planEmpty = total === 0;
      var deviating = v.route_state === 'DEVIATING';
      var stale = v.gps_is_stale || v.gps_stale || v.is_stale_data;
      var cardCls = 'vcard' + (deviating ? ' warn' : (stale ? ' stale' : ' ok'));
      if (_activeVehicleExtId && String(vid) === String(_activeVehicleExtId)) cardCls += ' selected';
      var fillCls = deviating ? 'orange' : (stale ? 'gray' : 'green');
      var badge = routeStateBadge(v);
      var planId = v.plan_id || '';
      var vid = v.arac_external_id || v.id || '';
      /* Next stop: canonical label from API or local fallback */
      var nextName = v.next_stop || v.next_stop_name || '';
      var nextLabel = v.next_stop_label || '';
      var nextTime = v.next_time || v.next_stop_time || '';
      var nextOrder = v.next_order_no != null && v.next_order_no !== '' ? v.next_order_no : null;
      var nextDisplayOrder = v.next_display_order_no != null && v.next_display_order_no !== '' ? v.next_display_order_no : nextOrder;
      if (!nextLabel) {
        if (nextName && nextTime && nextTime !== '—') {
          nextLabel = nextDisplayOrder != null ? nextTime + ' · ' + nextDisplayOrder + '. Durak · ' + nextName : nextTime + ' · ' + nextName;
        } else if (nextName && nextDisplayOrder != null) {
          nextLabel = nextDisplayOrder + '. Durak · ' + nextName;
        } else {
          nextLabel = nextName;
        }
      }
      /* GPS: API uses gps_last_seen_at (vehicles), last_seen_at (araclar) */
      var gpsTs = v.gps_last_seen_at || v.gps_timestamp || v.last_seen_at || '';
      var gpsAge = gpsTs ? fmtGpsAge(gpsTs) : '—';
      /* Route/deviation label */
      var routeLabel = v.route_status_label || '';
      /* Driver: API uses driver (today-ops vehicles) */
      var driver = v.driver_name || v.driver || '—';
      /* Visit info */
      var visitLbl = (v.visit_summary && v.visit_summary.label) || v.visit_label || '';

      /* Detail rows — plan state and GPS are independent */
      var detailRows = '';
      if (planEmpty) {
        detailRows += '<div class="vcard-detail-row"><span class="icon">📋</span>' +
          '<span style="color:var(--gray)">Sıradaki iş yok — plan boş</span></div>';
      } else if (nextLabel) {
        detailRows += '<div class="vcard-detail-row"><span class="icon">📅</span><span>Sıradaki: <strong>' +
          fmtVal(nextLabel) + '</strong></span></div>';
      }
      if (deviating && v.deviation_m != null) {
        var km = (Number(v.deviation_m) / 1000).toLocaleString('tr-TR', { maximumFractionDigits: 1 });
        detailRows += '<div class="vcard-detail-row warn"><span class="icon">⚠️</span><span>Rotadan ' + km + ' km saptı</span></div>';
        if (visitLbl) {
          detailRows += '<div class="vcard-detail-row warn"><span class="icon">📍</span><span>' + fmtVal(visitLbl) + '</span></div>';
        }
      } else if (!planEmpty && v.route_state === 'ON_ROUTE') {
        detailRows += '<div class="vcard-detail-row" style="color:var(--green);font-weight:600"><span class="icon">✅</span><span>Rotada</span></div>';
        if (visitLbl) {
          detailRows += '<div class="vcard-detail-row"><span class="icon">📍</span><span>' + fmtVal(visitLbl) + '</span></div>';
        }
      } else if (!planEmpty) {
        var act2 = v.physical_status || v.activity_status || '';
        if (act2 === 'HAREKETLI') {
          detailRows += '<div class="vcard-detail-row" style="color:var(--green);font-weight:600"><span class="icon">✅</span><span>Hareketli</span></div>';
        } else if (act2 === 'ROLANTI') {
          detailRows += '<div class="vcard-detail-row" style="color:var(--orange);font-weight:600"><span class="icon">○</span><span>Rölanti</span></div>';
        }
        if (visitLbl) {
          detailRows += '<div class="vcard-detail-row"><span class="icon">📍</span><span>' + fmtVal(visitLbl) + '</span></div>';
        }
      } else {
        var act3 = v.physical_status || v.activity_status || '';
        if (act3 === 'HAREKETLI') {
          detailRows += '<div class="vcard-detail-row" style="color:var(--green);font-weight:600"><span class="icon">✅</span><span>Hareketli</span></div>';
        } else if (act3 === 'ROLANTI') {
          detailRows += '<div class="vcard-detail-row" style="color:var(--orange);font-weight:600"><span class="icon">○</span><span>Rölanti</span></div>';
        }
      }
      var gpsStatusLbl = stale ? 'GPS Eski' : (gpsTs ? 'GPS Güncel' : 'GPS bekleniyor');
      detailRows += '<div class="vcard-detail-row"><span class="icon" style="opacity:.7">📡</span>' +
        '<span style="color:var(--gray)">' + gpsStatusLbl +
        (gpsTs ? ' · Son GPS: ' + gpsAge : '') + '</span></div>';
      var progressLabel = planEmpty ? 'Plan boş' : (done + ' / ' + total + ' tamamlandı');
      var actionBtn = deviating
        ? '<button class="btn btn-orange btn-sm atp-v2-open-plan" data-vid="' + vid + '" data-plan-id="' + planId + '">İncele</button>'
        : '<button class="btn btn-outline btn-sm atp-v2-open-plan" data-vid="' + vid + '" data-plan-id="' + planId + '">Planı Aç</button>';
      return '<div class="' + cardCls + '" data-vid="' + vid + '" data-plan-id="' + planId + '">' +
        '<div class="vcard-inner">' +
        '<div class="vcard-main">' +
        '<div class="vcard-plate-row"><div class="vcard-plate">' + plate + '</div>' + badge + '</div>' +
        '<div class="vcard-driver">' + fmtVal(driver) + '</div>' +
        '<div class="vcard-progress-row"><div class="progress-wrap"><div class="progress-fill ' + fillCls + '" style="width:' + pct + '%"></div></div>' +
        '<span class="progress-label">' + progressLabel + '</span></div>' +
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

  var INACTIVE_PLAN_STATUSES = { IPTAL: 1, ERTELENDI: 1, GIDILEMEDI: 1 };

  function isActivePlanItem(it) {
    var st = (it && it.status || 'PLANLANDI').toUpperCase();
    return !INACTIVE_PLAN_STATUSES[st];
  }

  function filterItemsForVehicle(extId, items) {
    if (!extId || !items) return [];
    return items.filter(function (it) {
      return String(it.arac_external_id) === String(extId) && isActivePlanItem(it);
    });
  }

  function compareOrderNo(a, b) {
    var ao = a.order_no != null && a.order_no !== '' ? Number(a.order_no) : null;
    var bo = b.order_no != null && b.order_no !== '' ? Number(b.order_no) : null;
    if (ao != null && bo != null && ao !== bo) return ao - bo;
    if (ao != null && bo == null) return -1;
    if (ao == null && bo != null) return 1;
    if (ao == null && bo == null) {
      var ptA = (a.planned_time || '').replace('—', '');
      var ptB = (b.planned_time || '').replace('—', '');
      var ptCmp = ptA.localeCompare(ptB);
      if (ptCmp !== 0) return ptCmp;
    }
    var ap = a.plan_item_id != null ? Number(a.plan_item_id) : 0;
    var bp = b.plan_item_id != null ? Number(b.plan_item_id) : 0;
    return ap - bp;
  }

  function sortStopItems(tasks) {
    return (tasks || []).slice().sort(compareOrderNo);
  }

  function sortActiveJobItems(items) {
    return activeJobItems(items).slice().sort(function (a, b) {
      var va = String(a.arac_plaka_snapshot || a.plate || a.arac_external_id || '');
      var vb = String(b.arac_plaka_snapshot || b.plate || b.arac_external_id || '');
      if (va !== vb) return va.localeCompare(vb);
      return compareOrderNo(a, b);
    });
  }

  function idsEqualLists(a, b) {
    if (!a || !b || a.length !== b.length) return false;
    for (var i = 0; i < a.length; i++) {
      if (String(a[i]) !== String(b[i])) return false;
    }
    return true;
  }

  function domOrderPrefixMatches(domIds, expected) {
    if (!domIds || !domIds.length || !expected || !expected.length) return false;
    for (var i = 0; i < domIds.length; i++) {
      if (i >= expected.length) break;
      if (String(domIds[i]) !== String(expected[i])) return false;
    }
    return true;
  }

  function getDomStopItemIds() {
    var nodes = document.querySelectorAll('#atpStopListWrap .stop-item[data-item-id]');
    return Array.prototype.map.call(nodes, function (n) { return n.getAttribute('data-item-id'); });
  }

  function getDomJobItemIdsForVehicle(vid) {
    if (!vid) return [];
    var rows = document.querySelectorAll('#atpDailyJobsBody tr[data-item-id]');
    var ids = [];
    rows.forEach(function (row) {
      if (String(row.getAttribute('data-vid') || '') !== String(vid)) return;
      var id = row.getAttribute('data-item-id');
      if (id) ids.push(String(id));
    });
    return ids;
  }

  var APPLY_VERIFY_FAIL_MSG = 'Rota sırası doğrulanamadı. Planı değişmiş kabul etmeyin.';

  function verifyApplyReadback(vid, expectedTaskIds) {
    var expected = (expectedTaskIds || []).map(String);
    var items = sortStopItems(filterItemsForVehicle(vid, lastOpsData.items || []));
    var readbackIds = items.map(function (it) { return String(it.id); });
    var route = window.AtpRoute && window.AtpRoute.getLastRoute && window.AtpRoute.getLastRoute();
    var routeIds = route && route.current && (route.current.full_task_ids || route.current.task_ids)
      ? (route.current.full_task_ids || route.current.task_ids).map(String) : [];
    var domStopIds = getDomStopItemIds().map(String);
    var domJobIds = getDomJobItemIdsForVehicle(vid).map(String);
    var domJobOk = domJobIds.length === 0
      ? false
      : (domJobIds.length === expected.length
        ? idsEqualLists(domJobIds, expected)
        : domOrderPrefixMatches(domJobIds, expected));
    return idsEqualLists(readbackIds, expected)
      && idsEqualLists(routeIds, expected)
      && idsEqualLists(domStopIds, expected)
      && domJobOk;
  }

  function verifyGoogleApplyReadback(vid, expectedTaskIds) {
    var expected = (expectedTaskIds || []).map(String);
    var items = sortStopItems(filterItemsForVehicle(vid, lastOpsData.items || []));
    var readbackIds = items.map(function (it) { return String(it.id); });
    var domStopIds = getDomStopItemIds().map(String);
    var domJobIds = getDomJobItemIdsForVehicle(vid).map(String);
    var domJobOk = domJobIds.length === 0
      ? false
      : (domJobIds.length === expected.length
        ? idsEqualLists(domJobIds, expected)
        : domOrderPrefixMatches(domJobIds, expected));
    return idsEqualLists(readbackIds, expected)
      && idsEqualLists(domStopIds, expected)
      && domJobOk;
  }

  function verifyGoogleProfileApplyReadback(vid, expectedTaskIds, expectedProfile, expectedReturn) {
    if (!verifyGoogleApplyReadback(vid, expectedTaskIds)) return false;
    var route = window.AtpRoute && window.AtpRoute.getLastRoute && window.AtpRoute.getLastRoute();
    if (!route || !route.current) return false;
    var prov = String(route.current.provider || route.current.routing_provider || '');
    var want = expectedProfile === 'toll_free' ? 'traffic-free' : 'traffic-fast';
    if (prov.indexOf(want) === -1) return false;
    if (expectedReturn) {
      var ret = route.current.estimated_return_time || route.current.return_display || '';
      if (ret && String(ret) !== String(expectedReturn)) return false;
    }
    return true;
  }

  function reloadAfterGoogleProfileApply(vid, expectedTaskIds, expectedProfile, expectedReturn) {
    if (vid) _activeVehicleExtId = String(vid);
    return loadOps().then(function (ok) {
      if (!ok) return false;
      return refreshPlanRoute(vid).then(function () {
        updatePlanMap();
        return verifyGoogleProfileApplyReadback(vid, expectedTaskIds, expectedProfile, expectedReturn);
      });
    });
  }

  function reloadAfterGoogleApply(vid, expectedTaskIds) {
    if (vid) _activeVehicleExtId = String(vid);
    return loadOps().then(function (ok) {
      if (!ok) return false;
      return refreshPlanRoute(vid).then(function () {
        updatePlanMap();
        return verifyGoogleApplyReadback(vid, expectedTaskIds);
      });
    });
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
    var cikisSaatiInput = qs('atpCikisSaatiInput');
    var cikisSaatiMsg = qs('atpCikisSaatiMsg');

    if (prsArac) prsArac.textContent = vehicle ? safePlate(vehicle) : '—';
    if (prsSofor) prsSofor.textContent = vehicle ? fmtVal(vehicle.driver_name || vehicle.driver) : '—';
    if (prsBtn) prsBtn.style.display = vehicle ? '' : 'none';
    if (sel && vehicle && vehicle.arac_external_id) sel.value = String(vehicle.arac_external_id);

    if (prsSaat && items && items.length) {
      var sorted = sortStopItems(items);
      var times = sorted.map(function (it) {
        var pt = (it.planned_time || '').trim();
        return pt && pt !== '—' ? pt : '';
      }).filter(Boolean);
      if (times.length) {
        prsSaat.textContent = times[0] + (times.length > 1 ? ' – ' + times[times.length - 1] : '');
      } else {
        prsSaat.textContent = '—';
      }
    } else if (prsSaat) {
      prsSaat.textContent = '—';
    }

    /* Çıkış Saati: populate from vehicle's plan data, clear message */
    if (cikisSaatiInput) {
      var cs = (vehicle && (vehicle.cikis_saati || vehicle.departure_time)) || '';
      cikisSaatiInput.value = cs ? cs.substring(0, 5) : '';
    }
    if (cikisSaatiMsg) {
      if (!vehicle) {
        cikisSaatiMsg.textContent = '';
      } else if (!(vehicle.cikis_saati || vehicle.departure_time)) {
        cikisSaatiMsg.textContent = 'Durak saatlerini hesaplamak için Çıkış Saati girin.';
        cikisSaatiMsg.style.color = 'var(--gray)';
      } else {
        cikisSaatiMsg.textContent = '';
      }
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

  var _timelineSyncToken = 0;

  function _planDateForApi() {
    return window.ATP_PLAN_DATE || lastOpsData.plan_date || (root && root.getAttribute('data-date')) || '';
  }

  function _mergeDepartureTasksIntoOps(vid, dailyTasks) {
    if (!dailyTasks || !dailyTasks.length) return;
    var updMap = {};
    dailyTasks.forEach(function (t) { if (t.id) updMap[t.id] = t; });
    if (lastOpsData.items) {
      lastOpsData.items = lastOpsData.items.map(function (t) {
        return updMap[t.id] ? Object.assign({}, t, updMap[t.id]) : t;
      });
    } else {
      lastOpsData.items = dailyTasks.slice();
    }
    var veh = findVehicleByExtId(vid);
    var scopedItems = filterItemsForVehicle(vid, lastOpsData.items || dailyTasks);
    renderJobs(lastOpsData.items || []);
    renderStopList(scopedItems, veh ? safePlate(veh) : '');
    updatePrsForVehicle(veh, scopedItems);
    updatePlanMap();
  }

  function fetchPlanTimeline(vid) {
    var planDate = _planDateForApi();
    if (!vid || !planDate) return Promise.resolve(null);
    var q = '/planlama/arac-takip/api/plan/timeline?date=' + encodeURIComponent(planDate) +
      '&vehicle_id=' + encodeURIComponent(vid);
    return fetch(q, { credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d && d.stops && d.stops.length) {
          renderTimeline(d);
          return d;
        }
        if (d && d.timeline) {
          renderTimeline(d.timeline);
          return d.timeline;
        }
        return null;
      })
      .catch(function () { return null; });
  }

  function persistDepartureEtasIfNeeded(vid, cikis) {
    if (!vid || !cikis) return Promise.resolve(null);
    var scoped = filterItemsForVehicle(vid, lastOpsData.items || []);
    var needsEta = scoped.some(function (t) {
      return !(t.eta_time || t.tahmini_varis_saati);
    });
    if (!needsEta) return Promise.resolve(null);
    var planDate = _planDateForApi();
    if (!planDate) return Promise.resolve(null);
    return fetch('/planlama/arac-takip/api/plan/departure-time', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({
        date: planDate,
        vehicle_id: vid,
        departure_time: cikis.substring(0, 5),
      }),
    })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
      .then(function (res) {
        if (!res.ok || !res.data || !res.data.ok) return null;
        var d = res.data;
        var veh = findVehicleByExtId(vid);
        if (veh) veh.cikis_saati = d.departure_time || cikis;
        if (d.daily_tasks && d.daily_tasks.length) {
          _mergeDepartureTasksIntoOps(vid, d.daily_tasks);
        }
        if (d.timeline) renderTimeline(d.timeline);
        return d;
      })
      .catch(function () { return null; });
  }

  function syncDepartureAndTimeline(vid) {
    if (!vid) return Promise.resolve();
    var token = ++_timelineSyncToken;
    var veh = findVehicleByExtId(vid);
    var cikis = veh && (veh.cikis_saati || veh.departure_time);
    if (cikis && qs('atpCikisSaatiInput') && !qs('atpCikisSaatiInput').value) {
      qs('atpCikisSaatiInput').value = cikis.substring(0, 5);
    }
    return fetchPlanTimeline(vid).then(function () {
      if (token !== _timelineSyncToken) return;
      if (!cikis) return;
      return persistDepartureEtasIfNeeded(vid, cikis);
    });
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

    updatePlanMap();

    if (window.AtpRoute) {
      if (window.AtpRoute.clearRouteDisplay) window.AtpRoute.clearRouteDisplay();
      if (window.AtpRoute.showRouteLoading) window.AtpRoute.showRouteLoading();
    }

    refreshPlanRoute(extId);

    syncDepartureAndTimeline(extId);

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
    var st = (status || '').toUpperCase();
    if (st === 'TAMAMLANDI') return 'badge-green';
    if (st === 'IPTAL')      return 'badge-gray';
    if (st === 'ERTELENDI')  return 'badge-orange';
    if (st === 'GECIKIYOR')  return 'badge-orange';
    if (visitState === 'DEPARTED_PENDING') return 'badge-orange';
    if (st === 'BASLADI' || st === 'YOLDA') return 'badge-blue';
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
    var status = (it.status || '').toUpperCase();
    if (raw && raw !== 'DEPARTED' && raw !== 'ARRIVED' && raw !== 'OUTSIDE') return raw;
    var arr = fmtTime(it.arrived_at);
    var dep = fmtTime(it.departed_at);
    /* Tamamlandı: vardı / ayrıldı / süre */
    if (state === 'DEPARTED' && arr && dep) return arr + ' Vardı · ' + dep + ' Ayrıldı';
    if (state === 'DEPARTED' && arr) return arr + ' Vardı · Ayrıldı';
    /* Durakta */
    if (state === 'ARRIVED' && arr) return arr + ' Vardı · Konumda';
    /* Yolda: show current ETA if available */
    if (status === 'BASLADI' || status === 'YOLDA') {
      var eta = fmtTime(it.eta_time || it.tahmini_varis_saati);
      if (eta) return 'Güncel tahmin ' + eta;
      return 'Yolda';
    }
    if (state === 'OUTSIDE') return 'Henüz varmadı';
    return raw || 'Henüz varmadı';
  }

  function _jobMenuItemsFor(st, visit) {
    st = (st || 'PLANLANDI').toUpperCase();
    visit = (visit || 'OUTSIDE').toUpperCase();
    var canComplete = (visit === 'DEPARTED_PENDING' && st !== 'TAMAMLANDI') || st === 'BASLADI';
    var items = '<button type="button" class="atp-job-menu-item" data-act="view">Görüntüle</button>';
    if (st === 'TAMAMLANDI') return items;
    if (st === 'PLANLANDI') {
      items += '<button type="button" class="atp-job-menu-item" data-act="change">Planı Değiştir</button>';
    } else if (st === 'BASLADI' || visit === 'ARRIVED' || visit === 'DEPARTED_PENDING') {
      items += '<button type="button" class="atp-job-menu-item" data-act="change">Planı Değiştir</button>';
    }
    if (canComplete) {
      items += '<button type="button" class="atp-job-menu-item" data-act="complete">Sonuçlandır</button>';
    }
    return items;
  }

  function _jobMenuItems(it) {
    return _jobMenuItemsFor(it.status, it.visit_state);
  }

  var _activeJobMenuBtn = null;

  function closeJobMenu() {
    var floatMenu = document.getElementById('atpJobMenuFloat');
    if (floatMenu) floatMenu.classList.remove('open');
    _activeJobMenuBtn = null;
  }

  function positionJobMenu(btn, floatMenu) {
    if (!btn || !floatMenu) return;
    var r = btn.getBoundingClientRect();
    var mw = Math.max(148, floatMenu.offsetWidth || 148);
    var left = Math.min(r.right - mw, window.innerWidth - mw - 8);
    left = Math.max(8, left);
    var top = r.bottom + 4;
    floatMenu.style.transform = '';
    if (top + 120 > window.innerHeight && r.top > 130) {
      top = r.top - 4;
      floatMenu.style.transform = 'translateY(-100%)';
    }
    floatMenu.style.top = top + 'px';
    floatMenu.style.left = left + 'px';
  }

  function openJobMenu(btn) {
    var floatMenu = document.getElementById('atpJobMenuFloat');
    if (!floatMenu || !btn) return;
    if (_activeJobMenuBtn === btn && floatMenu.classList.contains('open')) {
      closeJobMenu();
      return;
    }
    closeJobMenu();
    floatMenu.innerHTML = _jobMenuItemsFor(
      btn.getAttribute('data-status'),
      btn.getAttribute('data-visit')
    );
    floatMenu.setAttribute('data-plan-item', btn.getAttribute('data-plan-item') || '');
    floatMenu.setAttribute('data-vid', btn.getAttribute('data-vid') || '');
    floatMenu.classList.add('open');
    positionJobMenu(btn, floatMenu);
    _activeJobMenuBtn = btn;
  }

  function handleJobMenuItemClick(item) {
    var floatMenu = document.getElementById('atpJobMenuFloat');
    var planId = floatMenu && floatMenu.getAttribute('data-plan-item');
    var vid = floatMenu && floatMenu.getAttribute('data-vid');
    var act = item.getAttribute('data-act');
    closeJobMenu();
    if (!planId) return;
    if (act === 'view') {
      if (window.AtpPlanChange && window.AtpPlanChange.openView) {
        window.AtpPlanChange.openView(planId, vid);
      } else {
        var det = qs('atpPlanningSection');
        if (det) det.open = true;
      }
    } else if (act === 'change') {
      if (window.AtpPlanChange && window.AtpPlanChange.openChange) {
        window.AtpPlanChange.openChange(planId);
      }
    } else if (act === 'complete') {
      if (window.AtpPlanChange && window.AtpPlanChange.quickComplete) {
        window.AtpPlanChange.quickComplete(planId);
      }
    }
  }

  function initJobActionMenu() {
    if (initJobActionMenu._bound) return;
    initJobActionMenu._bound = true;

    document.addEventListener('click', function (e) {
      var btn = e.target.closest('.atp-job-menu-btn');
      if (btn) {
        e.preventDefault();
        e.stopPropagation();
        openJobMenu(btn);
        return;
      }
      var item = e.target.closest('#atpJobMenuFloat .atp-job-menu-item');
      if (item) {
        e.preventDefault();
        e.stopPropagation();
        handleJobMenuItemClick(item);
        return;
      }
      if (!e.target.closest('#atpJobMenuFloat')) {
        closeJobMenu();
      }
    });

    window.addEventListener('scroll', closeJobMenu, true);
    window.addEventListener('resize', closeJobMenu);
  }

  window.closeAtpJobMenu = closeJobMenu;

  /* Return true if s looks like a URL (http/https or maps.app.goo). */
  function _isUrl(s) {
    return /^https?:\/\//i.test(s) || /^maps\.app\.goo/i.test(s);
  }

  /* Build address sub-row: suppress raw URLs; show pin link instead if we have coords. */
  function _addressSubHtml(it) {
    var raw = it.address_text || '';
    if (!raw) return '';
    if (_isUrl(raw)) {
      /* Replace bare URL with a small location link if coordinates exist */
      if (it.latitude != null && it.longitude != null) {
        var mapsUrl = 'https://www.google.com/maps?q=' + it.latitude + ',' + it.longitude;
        return '<div class="job-firm-sub"><a href="' + mapsUrl + '" target="_blank" rel="noopener noreferrer" class="atp-loc-link" title="Konumu haritada gör">📍 Konum</a></div>';
      }
      return ''; /* hide bare URL entirely */
    }
    return '<div class="job-firm-sub">' + fmtVal(raw) + '</div>';
  }

  function makeJobRow(it) {
    var dotCls = jobDotClass(it.status, it.visit_state);
    var visCls = visitRowClass(it.visit_state);
    var badgeCls = planBadgeCls(it.status, it.visit_state);
    var statusLabel = fmtVal(it.status_label);
    var visitLabel = fmtVal(buildVisitLabel(it));
    var isLate = !!it.is_late;
    var itemId = it.id ? String(it.id) : '';
    var vidAttr = it.arac_external_id != null ? String(it.arac_external_id) : '';

    /* ── Tahmini Varış Saati — yalnız ETA/tahmini_varis_saati ── */
    var eta = it.eta_time || it.tahmini_varis_saati || null;
    var etaHtml = eta
      ? '<span class="job-eta' + (isLate ? ' late' : '') + '">' + fmtVal(eta) + '</span>'
      : '<span class="job-eta-empty" title="ETA hesaplanmadı">—</span>';

    return '<tr data-plan-item="' + (it.plan_item_id || '') + '" data-item-id="' + itemId + '" data-vid="' + vidAttr + '">' +
      '<td class="job-eta-cell">' + etaHtml + '</td>' +
      '<td><div class="job-firm"><span class="dot ' + dotCls + '"></span>' +
        fmtVal(it.job_title) + (it.company_name ? ' / ' + it.company_name : '') +
        '</div>' + _addressSubHtml(it) + '</td>' +
      '<td class="job-driver-cell">' + fmtVal(it.driver || '—') + '</td>' +
      '<td><span class="badge ' + badgeCls + '">' + statusLabel + '</span></td>' +
      '<td><span class="' + visCls + '">' + visitLabel + '</span></td>' +
      '<td><div class="atp-job-menu-wrap">' +
        '<button type="button" class="btn btn-outline btn-sm atp-job-menu-btn" ' +
          'data-vid="' + (it.arac_external_id || '') + '" ' +
          'data-plan-item="' + (it.plan_item_id || '') + '" ' +
          'data-status="' + (it.status || '') + '" ' +
          'data-visit="' + (it.visit_state || '') + '">İşlem ▾</button></div></td></tr>';
  }

  function activeJobItems(items) {
    return (items || []).filter(isActivePlanItem);
  }

  function renderJobs(items) {
    var tbody = qs('atpDailyJobsBody');
    if (!tbody) return;
    var activeItems = sortActiveJobItems(items);
    if (!activeItems.length) {
      tbody.innerHTML = '<tr><td colspan="6" class="atp-v2-empty">Henüz kayıt yok.</td></tr>';
      /* Clear any toggle row */
      var tbl = tbody.closest('table');
      if (tbl) { var tf = tbl.parentNode.querySelector('.atp-jobs-toggle'); if (tf) tf.remove(); }
      return;
    }
    var INIT_SHOW = 4;
    var visible = activeItems.slice(0, INIT_SHOW);
    var hidden  = activeItems.slice(INIT_SHOW);
    tbody.innerHTML = visible.map(makeJobRow).join('');

    /* Remove any existing toggle row */
    var tbl = tbody.closest('table');
    var card = tbl ? tbl.closest('.card') : null;
    if (card) {
      var old = card.querySelector('.atp-jobs-toggle');
      if (old) old.remove();
    }

    if (hidden.length > 0) {
      var total = activeItems.length;
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
          tbody.innerHTML = activeItems.map(makeJobRow).join('');
          btn.textContent = 'Daha Az Göster';
        } else {
          tbody.innerHTML = visible.map(makeJobRow).join('');
          btn.textContent = 'Tümünü Gör (' + total + ')';
        }
      });
      toggleRow.appendChild(btn);
      if (card) card.appendChild(toggleRow);
    }
  }

  function fmtDateTime(ts) {
    if (!ts) return '—';
    var s = String(ts).replace(' ', 'T');
    var d = new Date(s);
    if (isNaN(d.getTime())) return fmtVal(ts);
    var dd = String(d.getDate()).padStart(2, '0');
    var mm = String(d.getMonth() + 1).padStart(2, '0');
    var hh = String(d.getHours()).padStart(2, '0');
    var mi = String(d.getMinutes()).padStart(2, '0');
    return dd + '.' + mm + '.' + d.getFullYear() + ' ' + hh + ':' + mi;
  }

  function passiveStatusBadgeCls(st) {
    st = (st || '').toUpperCase();
    if (st === 'IPTAL') return 'badge-gray';
    if (st === 'ERTELENDI') return 'badge-orange';
    if (st === 'GIDILEMEDI') return 'badge-red';
    return 'badge-gray';
  }

  function makePassiveJobRow(it, idx) {
    var jobLabel = fmtVal(it.yapilacak_is) + (it.firma ? ' / ' + it.firma : '');
    return '<tr class="atp-passive-job-row" data-plan-item="' + (it.plan_is_id || '') + '">' +
      '<td class="job-time">' + fmtVal(it.planned_time) + '</td>' +
      '<td><div class="job-firm" style="color:var(--gray)">' + jobLabel + '</div></td>' +
      '<td style="font-size:11.5px;color:var(--gray)">' + fmtVal(it.sofor) + '</td>' +
      '<td><span class="badge ' + passiveStatusBadgeCls(it.new_durum) + '">' + fmtVal(it.new_durum_label || it.new_durum) + '</span></td>' +
      '<td style="font-size:11.5px;color:var(--gray);max-width:120px">' + fmtVal(it.reason) + '</td>' +
      '<td style="font-size:11px;color:var(--gray)">' + fmtDateTime(it.created_at) + '</td>' +
      '<td style="font-size:11.5px;color:var(--gray)">' + fmtVal(it.created_by_name) + '</td>' +
      '<td><button type="button" class="btn btn-outline btn-xs atp-passive-detail-btn" data-idx="' + idx + '">Detay</button></td></tr>';
  }

  function renderPassiveJobsSection(items) {
    var toggleEl = qs('atpPassiveJobsToggle');
    var panelEl = qs('atpPassiveJobsPanel');
    if (!toggleEl || !panelEl) return;
    var list = items || [];
    var count = list.length;
    if (!count) {
      toggleEl.style.display = 'none';
      panelEl.style.display = 'none';
      toggleEl.innerHTML = '';
      panelEl.innerHTML = '';
      return;
    }
    toggleEl.style.display = '';
    var label = count === 1
      ? 'Bugün plan dışına alınan 1 iş var — Göster'
      : ('Bugün plan dışına alınan ' + count + ' iş var — Göster');
    if (_passiveJobsExpanded) {
      label = label.replace('Göster', 'Gizle');
    }
    toggleEl.innerHTML = '<button type="button" class="btn btn-outline btn-xs atp-passive-toggle-btn">' + label + '</button>';
    var tbtn = toggleEl.querySelector('.atp-passive-toggle-btn');
    if (tbtn) {
      tbtn.addEventListener('click', function () {
        _passiveJobsExpanded = !_passiveJobsExpanded;
        renderPassiveJobsSection(lastPassiveJobs);
      });
    }
    if (!_passiveJobsExpanded) {
      panelEl.style.display = 'none';
      panelEl.innerHTML = '';
      return;
    }
    panelEl.style.display = '';
    panelEl.innerHTML =
      '<table class="jobs-tbl atp-passive-jobs-tbl">' +
      '<thead><tr>' +
      '<th>Saat</th><th>İş / Firma</th><th>Şoför</th><th>Durum</th><th>Neden</th>' +
      '<th>İşlem zamanı</th><th>İşlemi yapan</th><th></th>' +
      '</tr></thead><tbody>' +
      list.map(makePassiveJobRow).join('') +
      '</tbody></table>';
    panelEl.querySelectorAll('.atp-passive-detail-btn').forEach(function (btn) {
      btn.addEventListener('click', function (e) {
        e.preventDefault();
        var idx = parseInt(btn.getAttribute('data-idx'), 10);
        if (!isNaN(idx) && list[idx]) openPassiveJobDetail(list[idx]);
      });
    });
  }

  function openPassiveJobDetail(it) {
    var backdrop = qs('atpPassiveJobBackdrop');
    var body = qs('atpPassiveJobBody');
    var title = qs('atpPassiveJobTitle');
    if (!backdrop || !body) return;
    if (title) title.textContent = it.message || 'İş plan dışına alındı';
    var jobLabel = fmtVal(it.yapilacak_is) + (it.firma ? ' / ' + it.firma : '');
    body.innerHTML =
      '<div class="atp-passive-detail-grid">' +
      '<div class="atp-passive-detail-row"><span class="lbl">Firma / İş</span><span class="val">' + jobLabel + '</span></div>' +
      '<div class="atp-passive-detail-row"><span class="lbl">Araç</span><span class="val">' + fmtVal(it.plaka) + '</span></div>' +
      '<div class="atp-passive-detail-row"><span class="lbl">Şoför</span><span class="val">' + fmtVal(it.sofor) + '</span></div>' +
      '<div class="atp-passive-detail-row"><span class="lbl">Eski durum</span><span class="val">' + fmtVal(it.old_durum_label || it.old_durum) + '</span></div>' +
      '<div class="atp-passive-detail-row"><span class="lbl">Yeni durum</span><span class="val">' + fmtVal(it.new_durum_label || it.new_durum) + '</span></div>' +
      '<div class="atp-passive-detail-row"><span class="lbl">Neden</span><span class="val">' + fmtVal(it.reason) + '</span></div>' +
      '<div class="atp-passive-detail-row"><span class="lbl">İşlemi yapan</span><span class="val">' + fmtVal(it.created_by_name) + '</span></div>' +
      '<div class="atp-passive-detail-row"><span class="lbl">İşlem zamanı</span><span class="val">' + fmtDateTime(it.created_at) + '</span></div>' +
      '</div>';
    backdrop.classList.add('open');
    backdrop.setAttribute('aria-hidden', 'false');
    var modal = qs('atpPassiveJobModal');
    if (modal) modal.setAttribute('aria-hidden', 'false');
  }

  function closePassiveJobDetail() {
    var backdrop = qs('atpPassiveJobBackdrop');
    if (!backdrop) return;
    backdrop.classList.remove('open');
    backdrop.setAttribute('aria-hidden', 'true');
    var modal = qs('atpPassiveJobModal');
    if (modal) modal.setAttribute('aria-hidden', 'true');
  }

  function loadPlanChanges() {
    if (currentTab !== 'gunluk') return Promise.resolve(false);
    var url = '/planlama/arac-takip/api/plan-changes?date=' + encodeURIComponent(planDate);
    return fetch(url, { credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (!j || !j.ok) {
          lastPassiveJobs = [];
          renderPassiveJobsSection([]);
          return false;
        }
        lastPassiveJobs = j.items || [];
        renderPassiveJobsSection(lastPassiveJobs);
        return true;
      })
      .catch(function () {
        lastPassiveJobs = [];
        renderPassiveJobsSection([]);
        return false;
      });
  }

  window.loadAtpPlanChanges = loadPlanChanges;

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
  var lastMiniMapData = null;

  var ISTANBUL_FALLBACK = { lat: 41.0, lng: 29.0, zoom: 10 };

  function resolveMiniMapBase(mapData) {
    var candidates = [
      dashboard.base_location,
      dashboard.plan_map && dashboard.plan_map.base,
      mapData && mapData.base,
    ];
    for (var i = 0; i < candidates.length; i++) {
      var b = candidates[i];
      if (!b || b.latitude == null || b.longitude == null) continue;
      if (b.has_coordinates === false) continue;
      return b;
    }
    return null;
  }

  function miniBaseMarkerIcon() {
    return L.divIcon({
      className: 'atp-mini-base-pin',
      html: '<div class="atp-mini-base-pin-inner" title="Fabrika Başlangıç Noktası">🏭</div>',
      iconSize: [26, 26],
      iconAnchor: [13, 13],
      tooltipAnchor: [0, -10],
    });
  }

  function focusMiniMapBase() {
    var base = resolveMiniMapBase(lastMiniMapData);
    if (!base || base.latitude == null || base.longitude == null) return;
    if (!miniMap) {
      renderMiniMap(lastMiniMapData || { vehicles: [] });
    }
    if (!miniMap) return;
    miniMap.setView([Number(base.latitude), Number(base.longitude)], 14, { animate: false });
    miniMap.invalidateSize({ animate: false });
  }

  window.focusAtpMiniMapBase = focusMiniMapBase;

  function getMiniMapState() {
    if (!miniMap) return null;
    var c = miniMap.getCenter();
    var markers = [];
    if (miniLayer) {
      miniLayer.eachLayer(function (layer) {
        if (!layer.getLatLng) return;
        var ll = layer.getLatLng();
        var cls = (layer.options && layer.options.icon && layer.options.icon.options &&
          layer.options.icon.options.className) || '';
        markers.push({
          lat: ll.lat,
          lng: ll.lng,
          isBase: cls.indexOf('atp-mini-base-pin') >= 0,
        });
      });
    }
    return {
      center: { lat: c.lat, lng: c.lng },
      zoom: miniMap.getZoom(),
      markers: markers,
    };
  }

  window.getAtpMiniMapState = getMiniMapState;

  function renderMiniMap(mapData) {
    lastMiniMapData = mapData || { vehicles: [] };
    var box = qs('atpMiniMap');
    if (!box || !window.L) return;
    var base = resolveMiniMapBase(lastMiniMapData);
    var initLat = base ? Number(base.latitude) : ISTANBUL_FALLBACK.lat;
    var initLng = base ? Number(base.longitude) : ISTANBUL_FALLBACK.lng;
    var initZoom = base ? 13 : ISTANBUL_FALLBACK.zoom;
    if (!miniMap) {
      miniMap = L.map(box, { zoomControl: false, attributionControl: false }).setView([initLat, initLng], initZoom);
      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 18 }).addTo(miniMap);
      miniLayer = L.layerGroup().addTo(miniMap);
    }
    miniLayer.clearLayers();
    var pts = [];

    if (base && base.latitude != null && base.longitude != null) {
      var baseLat = Number(base.latitude);
      var baseLng = Number(base.longitude);
      var baseMk = L.marker([baseLat, baseLng], { icon: miniBaseMarkerIcon(), zIndexOffset: 1000 });
      var baseLabel = base.base_name || 'Fabrika Başlangıç Noktası';
      baseMk.bindTooltip('Fabrika Başlangıç Noktası' + (baseLabel ? ' — ' + baseLabel : ''));
      miniLayer.addLayer(baseMk);
      pts.push([baseLat, baseLng]);
    }

    ((lastMiniMapData.vehicles) || []).forEach(function (v) {
      if (v.lat == null) return;
      var m = L.circleMarker([v.lat, v.lng], { radius: 6, color: v.stale ? '#b54708' : '#1a9e3f', fillOpacity: 0.9 });
      m.bindTooltip(v.plate || '—');
      miniLayer.addLayer(m);
      pts.push([v.lat, v.lng]);
    });

    if (pts.length === 1) {
      miniMap.setView(pts[0], 13, { animate: false });
    } else if (pts.length > 1) {
      miniMap.fitBounds(pts, { padding: [20, 20], maxZoom: 12 });
    } else {
      miniMap.setView([ISTANBUL_FALLBACK.lat, ISTANBUL_FALLBACK.lng], ISTANBUL_FALLBACK.zoom, { animate: false });
    }

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
      wrap.innerHTML = '<div class="atp-v2-empty">Plan boş — aktif durak yok.</div>';
      if (title) title.textContent = 'Sıralı Duraklar';
      return;
    }
    var base = (dashboard.base_location && dashboard.base_location.base_name) || 'Fabrika — Tuzla OSB';
    var sorted = sortStopItems(tasks);
    /* Assign frontend display_order_no if backend didn't send it (fallback for PLANLANDI items) */
    var activeIdx = 0;
    sorted.forEach(function (t) {
      if (t.display_order_no == null && isActivePlanItem(t)) {
        activeIdx++;
        t.display_order_no = activeIdx;
      }
    });
    var html = '<div class="factory-row"><span class="fl">🏭</span><span class="factory-label">Başlangıç: ' + base + '</span></div>';
    html += '<div class="stop-list">' + sorted.map(function (t, idx) {
      /* Active/inactive decision: status-based (canonical), not display_order_no presence */
      var inact = !isActivePlanItem(t);
      var done = t.status === 'TAMAMLANDI';
      var late = t.is_late;
      var cls = 'stop-item' + (inact ? ' passive' : (done ? ' done' : (late ? ' late' : '')));
      var numCls = 'stop-num' + (inact ? ' passive' : (done ? ' done' : (late ? ' late' : '')));
      var badgeCls = done ? 'badge-green' : (late ? 'badge-orange' : 'badge-gray');
      var badgeLbl = done ? '✓' : (late ? 'Gecikmeli' : fmtVal(t.status_label || t.status || 'Planlandı'));
      var seq = inact
        ? '—'
        : (t.display_order_no != null && t.display_order_no !== ''
            ? t.display_order_no
            : (t.order_no != null && t.order_no !== '' ? t.order_no : (idx + 1)));
      var prevSiraHtml = inact && t.order_no != null
        ? '<span class="stop-prev-sira">Önceki sıra: ' + t.order_no + '</span>'
        : '';
      var itemId = t.id ? String(t.id) : '';
      var talepId = t.is_talebi_id != null ? String(t.is_talebi_id) : '';
      var priHtml = (t.priority && t.priority !== 'NORMAL')
        ? '<span class="badge badge-orange" style="margin-right:4px;font-size:10px">' + fmtVal(t.priority_label || t.priority) + '</span>'
        : '';
      return '<div class="' + cls + '" data-item-id="' + itemId + '" data-is-talebi-id="' + talepId + '">' +
        '<span class="' + numCls + '">' + seq + '</span>' +
        '<span class="stop-name">' + fmtVal(t.company_name || t.job_title) + '</span>' +
        priHtml +
        '<span class="badge ' + badgeCls + '" style="margin-right:4px">' + badgeLbl + '</span>' +
        prevSiraHtml +
        '<span class="stop-time" style="' + (late ? 'color:var(--orange)' : '') + '">' +
        (inact ? '' : fmtVal(t.eta_time || t.tahmini_varis_saati || '—')) + '</span>' +
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
        var vid = String(v.arac_external_id || v.id || '');
        return '<div class="unp-item">' +
          '<div><div class="unp-plate">' + safePlate(v) + '</div><div class="unp-driver">' + fmtVal(v.driver_name || v.driver) + '</div></div>' +
          '<span class="badge badge-gray" style="margin-left:8px">Atanmadı</span>' +
          '<button type="button" class="btn btn-outline btn-xs unp-btn" data-vid="' + vid + '">Plan Oluştur</button>' +
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

    var activeItems = activeJobItems(data.items || []);
    var hasActiveItems = activeItems.length > 0;
    var hasPlanVehicles = (data.vehicles && data.vehicles.length > 0);
    var planCount = (data.day_plan_summary && data.day_plan_summary.plan_count) || 0;
    var hasAnyItems = (data.items && data.items.length > 0);
    var hasPlanDay = hasPlanVehicles || planCount > 0 || hasAnyItems;
    var isPlanlessDay = !hasPlanDay;

    /* Planless day vs plan-with-no-active-jobs are different states */
    switchGunlukView(isPlanlessDay);

    if (isPlanlessDay) {
      /* Show unplanned vehicles in empty-day panel */
      renderUnplannedVehicles(filomBody && filomBody.vehicles ? filomBody.vehicles : lastVehicles);
      /* Quick plan araç select also updated inside renderUnplannedVehicles */
      /* Accordion: close */
      syncEmptyDayPlanRota(false);
    } else {
      var vehiclesForCards = _mergeFilomGpsIntoVehicles(data.vehicles || [], filomBody);
      lastOpsData = {
        vehicles: vehiclesForCards,
        items: data.items || [],
      };
      renderVehicleCards(vehiclesForCards);
      renderJobs(data.items || []);
      renderAlerts(data.alerts || [], 'Dikkat gerektiren durum yok.');
      renderMiniMap(data.map || { vehicles: [] });

      var urlVid = urlParams.get('vehicle_id');
      var urlVehicleMatch = urlVid && vehiclesForCards.some(function (v) {
        return String(v.arac_external_id) === String(urlVid);
      });

      if (urlVehicleMatch) {
        openPlanRouteForVehicle(String(urlVid));
      } else {
        /* Summary band — scoped to active or first vehicle */
        if (!_activeVehicleExtId && vehiclesForCards.length && vehiclesForCards[0].arac_external_id) {
          _activeVehicleExtId = String(vehiclesForCards[0].arac_external_id);
        }
        updatePrsSummary(vehiclesForCards, data.items || []);

        /* Stop list: only selected vehicle active items */
        var activeVeh = findVehicleByExtId(_activeVehicleExtId);
        var scopedItems = _activeVehicleExtId
          ? sortStopItems(filterItemsForVehicle(_activeVehicleExtId, data.items || []))
          : [];
        renderStopList(scopedItems, activeVeh ? safePlate(activeVeh) : '');

        /* Route — only when active jobs exist */
        if (window.AtpRoute && hasActiveItems && _activeVehicleExtId) {
          refreshPlanRoute(_activeVehicleExtId);
        } else if (window.AtpRoute && window.AtpRoute.showRouteEmptyPlan) {
          window.AtpRoute.showRouteEmptyPlan('Aktif iş yok — plan boş.');
        } else if (window.AtpRoute) {
          window.AtpRoute.clearRouteDisplay();
        }

        if (_activeVehicleExtId) {
          syncDepartureAndTimeline(_activeVehicleExtId);
        }
      }

      /* Date label in jobs header */
      var jobsDateLbl = qs('atpJobsDateLabel');
      if (jobsDateLbl && dashboard.date_label) jobsDateLbl.textContent = dashboard.date_label;

      /* Empty plan guard — active jobs, not raw item count */
      syncEmptyDayPlanRota(hasActiveItems);
    }

    /* Populate vehicle select (hidden) for route & modal */
    hydrateVehicleSelect(lastVehicles, hasPlanVehicles ? data.vehicles : []);
    loadPlanChanges();
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
    renderPassiveJobsSection([]);
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
  window.selectAtpVehicle = openPlanRouteForVehicle;

  /* ─── Vehicle select (hidden, feeds route + modal) ─── */
  function hydrateVehicleSelect(filomVehicles, opsVehicles) {
    var sel = qs('atpSelVehicle');
    var reqSel = qs('atpReqArac');
    if (!sel && !reqSel) return;

    var liveCatalog = (filomVehicles && filomVehicles.length) ? filomVehicles : (lastVehicles || []);
    var optHtml = vehicleUniqueOptionsToHtml(
      buildUniquePhysicalVehicleOptions(liveCatalog, opsVehicles)
    );

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
          updatePlanMap();
          requestAnimationFrame(function () {
            if (window.AtpPlanMap && window.AtpPlanMap.onPlanTabShown) {
              window.AtpPlanMap.onPlanTabShown();
            }
          });
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
  function buildPlanMapPayload() {
    var base = (dashboard.plan_map && dashboard.plan_map.base) || dashboard.base_location || {};
    var tasks = [];
    if (_activeVehicleExtId && lastOpsData && lastOpsData.items) {
      tasks = sortStopItems(filterItemsForVehicle(_activeVehicleExtId, lastOpsData.items));
    } else if (dashboard.daily_tasks && dashboard.daily_tasks.length) {
      tasks = sortStopItems((dashboard.daily_tasks || []).filter(function (t) {
        return isActivePlanItem(t);
      }));
    } else if (dashboard.plan_map && dashboard.plan_map.stops) {
      tasks = sortStopItems((dashboard.plan_map.stops || []).filter(function (s) {
        return isActivePlanItem({ status: s.status || 'PLANLANDI' });
      }));
    }
    var stops = tasks.map(function (t, idx) {
      return {
        id: t.id,
        plan_item_id: t.plan_item_id,
        is_talebi_id: t.is_talebi_id,
        order_no: t.order_no != null && t.order_no !== '' ? t.order_no : (idx + 1),
        display_order_no: t.display_order_no != null && t.display_order_no !== ''
          ? t.display_order_no
          : (idx + 1),
        company_name: t.company_name,
        job_title: t.job_title,
        planned_time: t.planned_time,
        address_text: t.address_text,
        latitude: t.latitude,
        longitude: t.longitude,
        has_coordinates: !!t.has_coordinates,
        location_source_label: t.location_source_label,
        status: t.status
      };
    });
    var ready = stops.filter(function (s) { return s.has_coordinates; }).length;
    return {
      base: base,
      stops: stops,
      completeness: {
        total_stops: stops.length,
        ready: ready,
        missing: stops.length - ready,
        base_configured: !!(base && base.has_coordinates)
      }
    };
  }

  function updatePlanMap() {
    if (!window.AtpPlanMap) return;
    window.AtpPlanMap.renderPlanMap(buildPlanMapPayload());
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

  /* ─── Plana İş Ekle Modal (legacy restore + Kayıtlı Konum V1) ─── */
  var _locState = {
    anchorId: null,
    cariId: null,
    locations: [],
    selectedId: null,
    mode: 'saved',
    validated: null,
    submitToken: null,
  };
  var _konumMiniMap = null;
  var _konumMiniLayer = null;
  var _konumMiniMarker = null;
  var _konumMapInit = false;
  var _submitInFlight = false;

  function _genSubmitToken() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    return 'atp-' + Date.now() + '-' + Math.random().toString(16).slice(2);
  }

  function _setHidden(id, val) {
    var el = qs(id);
    if (el) el.value = val == null ? '' : String(val);
  }

  function _clearKonumStatus() {
    var st = qs('atpKonumStatus');
    if (st) { st.textContent = ''; st.className = 'konum-status'; }
  }

  function _showKonumStatus(html, cls) {
    var st = qs('atpKonumStatus');
    if (!st) return;
    st.innerHTML = html;
    st.className = 'konum-status' + (cls ? ' ' + cls : '');
  }

  function initKonumMiniMap() {
    var box = qs('atpKonumMapMini');
    if (!box || !window.L) return;
    if (_konumMapInit && _konumMiniMap) {
      setTimeout(function () { _konumMiniMap.invalidateSize({ animate: false }); }, 80);
      return;
    }
    box.innerHTML = '';
    _konumMiniMap = L.map(box, { zoomControl: false, attributionControl: false, keyboard: false }).setView([41.02, 29.05], 11);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 18 }).addTo(_konumMiniMap);
    _konumMiniLayer = L.layerGroup().addTo(_konumMiniMap);
    // Suppress clicks during the init settle period (Leaflet fires spurious events on setView).
    var _mapReady = false;
    setTimeout(function () { _mapReady = true; }, 300);
    _konumMiniMap.on('click', function (e) {
      if (!_mapReady) return;  // ignore clicks during init
      if (_locState.mode !== 'new') return;
      setKonumCoords(e.latlng.lat, e.latlng.lng, null, true, 'manual_pin');
      _showKonumStatus(
        'Haritadan pin seçildi (' + e.latlng.lat.toFixed(6) + ', ' + e.latlng.lng.toFixed(6) + '). ' +
        '"Konumu Kontrol Et" ile doğrulayın.',
        'ok'
      );
      validateAddForm();
    });
    box.addEventListener('mousedown', function (ev) { ev.stopPropagation(); });
    box.addEventListener('pointerdown', function (ev) { ev.stopPropagation(); });
    _konumMapInit = true;
  }

  function setKonumMarker(lat, lng) {
    if (!_konumMiniMap || lat == null || lng == null) return;
    if (_konumMiniLayer) _konumMiniLayer.clearLayers();
    _konumMiniMarker = L.circleMarker([lat, lng], {
      radius: 8, color: '#F97316', fillColor: '#F97316', fillOpacity: 0.95, weight: 2,
    });
    _konumMiniLayer.addLayer(_konumMiniMarker);
    _konumMiniMap.setView([lat, lng], 14);
    setTimeout(function () { if (_konumMiniMap) _konumMiniMap.invalidateSize({ animate: false }); }, 60);
  }

  // source: 'api_resolved' | 'manual_pin' | 'saved'
  function setKonumCoords(lat, lng, mapsUrl, fromMapClick, source) {
    _locState.validated = {
      latitude: lat,
      longitude: lng,
      maps_url: mapsUrl || (lat + ',' + lng),
      adres: mapsUrl || (lat + ',' + lng),
      source: source || (fromMapClick ? 'manual_pin' : 'api_resolved'),
    };
    _setHidden('atpReqLat', lat);
    _setHidden('atpReqLng', lng);
    _setHidden('atpReqAdres', _locState.validated.adres);
    var mapsInp = qs('atpReqMapsUrl');
    if (mapsInp && !fromMapClick && mapsUrl) mapsInp.value = mapsUrl;
    var hiddenMaps = qs('atpReqMapsUrlHidden');
    if (hiddenMaps) hiddenMaps.value = _locState.validated.maps_url;
    setKonumMarker(lat, lng);
    validateAddForm(false);
  }

  // Clear all coordinate state when the Maps input changes (user is editing).
  function _clearMapsInputState() {
    if (_locState.validated) {
      _locState.validated = null;
      _setHidden('atpReqLat', '');
      _setHidden('atpReqLng', '');
      _setHidden('atpReqAdres', '');
      var hiddenMaps = qs('atpReqMapsUrlHidden');
      if (hiddenMaps) hiddenMaps.value = '';
      if (_konumMiniLayer) _konumMiniLayer.clearLayers();
      _clearKonumStatus();
      validateAddForm();
    }
  }

  function showKonumSection(show, initMap) {
    var sec = qs('atpKonumSection');
    if (sec) sec.style.display = show ? '' : 'none';
    if (show && initMap) {
      initKonumMiniMap();
      setTimeout(function () { if (_konumMiniMap) _konumMiniMap.invalidateSize({ animate: false }); }, 120);
    }
  }

  function populateKonumSelect(locations, selectId) {
    var sel = qs('atpReqKonumSelect');
    if (!sel) return;
    sel.innerHTML = '<option value="">— Konum seç —</option>' +
      (locations || []).map(function (loc) {
        var label = loc.display_label || loc.konum_adi || loc.short_adres || loc.adres || loc.address || 'Konum';
        return '<option value="' + loc.id + '">' + fmtVal(label) + '</option>';
      }).join('');
    sel.disabled = !(locations && locations.length);
    if (selectId) sel.value = String(selectId);
  }

  function applySavedLocation(loc) {
    if (!loc) return;
    _locState.selectedId = loc.id;
    _locState.mode = 'saved';
    _locState.validated = {
      latitude: loc.latitude,
      longitude: loc.longitude,
      maps_url: loc.maps_url || '',
      adres: loc.adres || loc.address || '',
      source: 'saved',
    };
    _setHidden('atpReqLocationMasterId', loc.id);
    _setHidden('atpReqIsNewLocation', '0');
    _setHidden('atpReqLat', loc.latitude);
    _setHidden('atpReqLng', loc.longitude);
    _setHidden('atpReqAdres', _locState.validated.adres);
    if (loc.cari_id != null) _setHidden('atpReqCariId', loc.cari_id);
    var mapsInp = qs('atpReqMapsUrl');
    if (mapsInp) {
      mapsInp.value = loc.maps_url || _locState.validated.adres || '';
      mapsInp.readOnly = true;
    }
    var yeniFields = qs('atpYeniKonumFields');
    if (yeniFields) yeniFields.hidden = true;
    var konumAdi = qs('atpReqKonumAdi');
    if (konumAdi) konumAdi.value = loc.konum_adi || '';
    var firma = (qs('atpReqFirma') || {}).value || loc.firma || loc.name || '';
    _showKonumStatus(
      '<span class="konum-check">✓ Bu konum <strong>' + fmtVal(firma) + '</strong> için kayıtlıdır.<br>Sonraki işlerde otomatik gelir.</span>',
      'ok'
    );
    if (loc.latitude != null && loc.longitude != null) setKonumMarker(loc.latitude, loc.longitude);
    validateAddForm();
  }

  function enterNewKonumMode(focusMaps) {
    _locState.mode = 'new';
    _locState.selectedId = null;
    _locState.validated = null;
    _setHidden('atpReqLocationMasterId', '');
    _setHidden('atpReqIsNewLocation', '1');
    _setHidden('atpReqLat', '');
    _setHidden('atpReqLng', '');
    var sel = qs('atpReqKonumSelect');
    if (sel) sel.value = '';
    var yeniFields = qs('atpYeniKonumFields');
    if (yeniFields) yeniFields.hidden = false;
    var mapsInp = qs('atpReqMapsUrl');
    if (mapsInp) {
      mapsInp.value = '';
      mapsInp.readOnly = false;
      if (focusMaps) mapsInp.focus();
    }
    var konumAdi = qs('atpReqKonumAdi');
    if (konumAdi) konumAdi.value = '';
    _clearKonumStatus();
    if (_konumMiniLayer) _konumMiniLayer.clearLayers();
    validateAddForm();
  }

  function loadCompanyLocations(anchorId, cariId) {
    var qsParts = [];
    if (anchorId) qsParts.push('anchor_id=' + encodeURIComponent(anchorId));
    if (cariId) qsParts.push('cari_id=' + encodeURIComponent(cariId));
    if (!qsParts.length) {
      enterNewKonumMode(false);
      showKonumSection(true, true);
      return Promise.resolve();
    }
    return fetch('/planlama/arac-takip/api/locations/for-company?' + qsParts.join('&'), { credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        _locState.locations = data.locations || [];
        if (data.company) {
          _locState.anchorId = data.company.anchor_location_id || anchorId;
          _locState.cariId = data.company.cari_id || cariId || null;
          if (_locState.cariId != null) _setHidden('atpReqCariId', _locState.cariId);
        }
        showKonumSection(true, true);
        populateKonumSelect(_locState.locations, null);
        if (_locState.locations.length) {
          applySavedLocation(_locState.locations[0]);
          populateKonumSelect(_locState.locations, _locState.locations[0].id);
        } else {
          enterNewKonumMode(false);
        }
      })
      .catch(function () {
        showKonumSection(true, true);
        enterNewKonumMode(false);
      });
  }

  function onFirmaTyped() {
    var firma = ((qs('atpReqFirma') || {}).value || '').trim();
    if (firma.length < 2) {
      showKonumSection(false);
      _locState.anchorId = null;
      _locState.locations = [];
      _setHidden('atpReqLocationMasterId', '');
      return;
    }
    // Do NOT call enterNewKonumMode() or initKonumMiniMap() while the user is still typing.
    // The location section becomes active only after an explicit dropdown selection.
  }

  function _resetPlanaForm() {
    var form = qs('atpRequestForm');
    if (form) form.reset();
    var tarih = qs('atpReqTarih');
    if (tarih) tarih.value = planDate;
    /* saat is optional — do NOT auto-fill with 10:00; leave empty so backend assigns via route optimization */
    _locState = {
      anchorId: null, cariId: null, locations: [], selectedId: null,
      mode: 'new', validated: null, submitToken: _genSubmitToken(),
    };
    _setHidden('atpReqLocationMasterId', '');
    _setHidden('atpReqLat', '');
    _setHidden('atpReqLng', '');
    _setHidden('atpReqAdres', '');
    _setHidden('atpReqCariId', '');
    _setHidden('atpReqIsNewLocation', '0');
    var hiddenMaps = qs('atpReqMapsUrlHidden');
    if (hiddenMaps) hiddenMaps.value = '';
    var warn = qs('atpModalWarn'); if (warn) warn.classList.remove('show');
    _clearValidationSummary();
    /* Clear all per-field error states */
    ['atpReqFirma','atpReqIs','atpReqArac','atpReqTarih','atpReqMapsUrl','atpReqKonumSec'].forEach(function (id) {
      var el = qs(id); if (el) _clearFieldErr(el);
    });
    var dd = qs('atpFirmaDropdown'); if (dd) dd.classList.remove('open');
    showKonumSection(false);
    populateKonumSelect([], null);
    var yeniFields = qs('atpYeniKonumFields'); if (yeniFields) yeniFields.hidden = true;
    var mapsInp = qs('atpReqMapsUrl'); if (mapsInp) { mapsInp.value = ''; mapsInp.readOnly = false; }
    _clearKonumStatus();
    if (_konumMiniLayer) _konumMiniLayer.clearLayers();
    _submitInFlight = false;
  }

  function openPlanaModal(mode, prefillVehicleExtId) {
    var backdrop = qs('atpModalBackdrop');
    var modal = qs('atpRequestModal');
    var titleEl = qs('atpModalTitle');
    if (titleEl) titleEl.textContent = '+ Plana İş Ekle';
    _resetPlanaForm();
    var reqSel = qs('atpReqArac');
    if (reqSel && reqSel.options.length <= 1) hydrateVehicleSelect(lastVehicles, []);
    if (mode === 'existing' && prefillVehicleExtId && reqSel) {
      reqSel.value = String(prefillVehicleExtId);
      var opt = reqSel.options[reqSel.selectedIndex];
      var soforEl = qs('atpReqPlanaSofor');
      if (opt && soforEl) soforEl.value = opt.getAttribute('data-driver') || '';
    }
    validateAddForm();
    if (backdrop) { backdrop.classList.add('open'); backdrop.setAttribute('aria-hidden', 'false'); }
    if (modal) modal.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden';
    setTimeout(function () {
      var firmaEl = qs('atpReqFirma');
      if (firmaEl) firmaEl.focus();
    }, 60);
  }

  function closePlanaModal() {
    var backdrop = qs('atpModalBackdrop');
    var modal = qs('atpRequestModal');
    if (backdrop) { backdrop.classList.remove('open'); backdrop.setAttribute('aria-hidden', 'true'); }
    if (modal) modal.setAttribute('aria-hidden', 'true');
    document.body.style.overflow = '';
    _submitInFlight = false;
    var submit = qs('atpModalSubmit');
    if (submit) submit.disabled = false;
  }

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
      var backdrop = qs('atpModalBackdrop');
      if (backdrop && backdrop.classList.contains('open')) closePlanaModal();
    }
  });

  /* Daily multi-modal entry points bound after atpMultiOpen init (see _initDailyMultiEntryPoints). */

  /* ─── Çıkış Saati: Kaydet ve Hesapla → Google Route Options ─── */
  (function initCikisSaati() {
    var btn = qs('atpBtnCikisSaatiKaydet');
    var inp = qs('atpCikisSaatiInput');
    var msg = qs('atpCikisSaatiMsg');
    if (!btn || !inp) return;

    var _googleCalcInFlight = false;

    function _setMsg(text, isError) {
      if (!msg) return;
      msg.textContent = text || '';
      msg.style.color = isError ? 'var(--red, #ef4444)' : 'var(--gray)';
    }

    function _hhmm(hh, mm) {
      return (hh < 10 ? '0' : '') + hh + ':' + (mm < 10 ? '0' : '') + mm;
    }

    function _departureIsFuture(planDateStr, hhmm) {
      if (!planDateStr || !hhmm) return false;
      var parts = hhmm.split(':');
      if (parts.length < 2) return false;
      var hh = String(parseInt(parts[0], 10));
      var mm = String(parseInt(parts[1], 10));
      if (hh === 'NaN' || mm === 'NaN') return false;
      hh = (hh.length < 2 ? '0' : '') + hh;
      mm = (mm.length < 2 ? '0' : '') + mm;
      var dep = new Date(planDateStr + 'T' + hh + ':' + mm + ':00');
      if (isNaN(dep.getTime())) return false;
      return dep.getTime() > Date.now();
    }

    var _GOOGLE_PAST_DEPARTURE_MSG =
      'Google trafik tahmini için çıkış tarihi ve saati gelecekte olmalıdır.';

    function _resetCalcBtn() {
      _googleCalcInFlight = false;
      btn.disabled = false;
      btn.textContent = 'Saati Kaydet ve Hesapla';
    }

    function _planIdForVehicle(vid) {
      var veh = findVehicleByExtId(vid);
      if (veh && veh.plan_id != null && veh.plan_id !== '') return veh.plan_id;
      var items = filterItemsForVehicle(vid, lastOpsData.items || []);
      for (var i = 0; i < items.length; i++) {
        if (items[i].plan_id != null && items[i].plan_id !== '') return items[i].plan_id;
      }
      return null;
    }

    function _planMapPayloadForVehicle(vid) {
      var base = (dashboard.plan_map && dashboard.plan_map.base) || dashboard.base_location || {};
      var items = sortStopItems(filterItemsForVehicle(vid, lastOpsData.items || []));
      return {
        base: base,
        stops: items.map(function (t) {
          return {
            id: t.id,
            plan_item_id: t.plan_item_id,
            order_no: t.order_no,
            company_name: t.company_name,
            job_title: t.job_title || t.yapilacak_is || '',
            has_coordinates: !!t.has_coordinates,
            latitude: t.latitude,
            longitude: t.longitude,
            priority: t.priority,
            is_locked: !!t.is_locked,
          };
        }),
      };
    }

    function _openGoogleModalOrError(dto) {
      if (!dto || (window.AtpRouteExplainer && AtpRouteExplainer.bothProfilesFailed && AtpRouteExplainer.bothProfilesFailed(dto))) {
        _setMsg('Google rota hesabı tamamlanamadı.', true);
        return;
      }
      var payload = _planMapPayloadForVehicle(_activeVehicleExtId);
      var opened = window.AtpRouteExplainer && AtpRouteExplainer.openGoogleModal
        ? AtpRouteExplainer.openGoogleModal(dto, payload)
        : false;
      if (!opened) {
        _setMsg('Google rota hesabı tamamlanamadı.', true);
        return;
      }
      _setMsg('Google rota seçenekleri hesaplandı.', false);
    }

    btn.addEventListener('click', function () {
      if (_googleCalcInFlight) return;
      var val = (inp.value || '').trim();
      if (!val) {
        _setMsg('Önce çıkış saati girin.', false);
        return;
      }
      /* HH:mm client-side check */
      if (!/^\d{1,2}:\d{2}$/.test(val)) {
        _setMsg('Geçersiz saat formatı — HH:mm girin (örnek: 09:00)', true);
        return;
      }
      var parts = val.split(':');
      var hh = parseInt(parts[0], 10), mm = parseInt(parts[1], 10);
      if (hh > 23 || mm > 59) {
        _setMsg('Geçersiz saat değeri.', true);
        return;
      }
      var vid = _activeVehicleExtId;
      if (!vid) {
        _setMsg('Araç seçili değil.', true);
        return;
      }
      var planDate = (window.ATP_PLAN_DATE || lastOpsData.plan_date || root.getAttribute('data-date') || '');
      if (!planDate) {
        _setMsg('Plan tarihi bulunamadı.', true);
        return;
      }
      var hhmm = _hhmm(hh, mm);
      _googleCalcInFlight = true;
      btn.disabled = true;
      btn.textContent = 'Kaydediliyor…';
      _setMsg('', false);

      fetch('/planlama/arac-takip/api/plan/departure-time', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          date: planDate,
          vehicle_id: vid,
          departure_time: hhmm,
        }),
        credentials: 'same-origin',
      })
      .then(function (r) { return r.json().then(function (d) { return {ok: r.ok, data: d}; }); })
      .then(function (res) {
        if (!res.ok || !res.data.ok) {
          var errMsg = (res.data && res.data.error) || 'Kayıt başarısız.';
          _setMsg('Hata: ' + errMsg, true);
          _resetCalcBtn();
          return null;
        }
        var d = res.data;
        /* Update local vehicle record with new cikis_saati */
        var veh = findVehicleByExtId(vid);
        if (veh) veh.cikis_saati = d.departure_time;
        /* Re-render with updated tasks */
        if (d.daily_tasks && d.daily_tasks.length) {
          var updMap = {};
          d.daily_tasks.forEach(function (t) { if (t.id) updMap[t.id] = t; });
          if (lastOpsData.items) {
            lastOpsData.items = lastOpsData.items.map(function (t) {
              return updMap[t.id] ? Object.assign({}, t, updMap[t.id]) : t;
            });
          }
          var scopedItems = filterItemsForVehicle(vid, lastOpsData.items || d.daily_tasks);
          renderJobs(scopedItems);
          renderStopList(scopedItems, veh ? safePlate(veh) : '');
          updatePrsForVehicle(veh, scopedItems);
        }
        if (d.dashboard) {
          dashboard = Object.assign({}, dashboard, d.dashboard);
        }
        if (d.timeline) renderTimeline(d.timeline);
        if (!_departureIsFuture(planDate, hhmm)) {
          _setMsg(_GOOGLE_PAST_DEPARTURE_MSG, true);
          _resetCalcBtn();
          return null;
        }
        btn.textContent = 'Google rotaları hesaplanıyor…';
        var gBody = {
          date: planDate,
          vehicle_id: vid,
          departure_time: hhmm,
        };
        var planId = _planIdForVehicle(vid);
        if (d.plan_id != null && d.plan_id !== '') planId = d.plan_id;
        if (planId != null && planId !== '') gBody.plan_id = planId;
        return fetch('/planlama/arac-takip/api/plan/google-route-options', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(gBody),
          credentials: 'same-origin',
        }).then(function (r) {
          return r.json().then(function (gd) { return { ok: r.ok, status: r.status, data: gd }; })
            .catch(function () { return { ok: false, status: r.status, data: {} }; });
        });
      })
      .then(function (gres) {
        if (!gres) return;
        var gd = gres.data || {};
        var code = gd.code || gd.error_code || '';
        if (!gres.ok || gd.ok === false) {
          var gMsg = (window.AtpRouteExplainer && AtpRouteExplainer.googleHttpErrorMessage)
            ? AtpRouteExplainer.googleHttpErrorMessage(gres.status, code)
            : (gd.error || 'Google rota hesabı tamamlanamadı.');
          _setMsg(gMsg, true);
          return;
        }
        _openGoogleModalOrError(gd);
      })
      .catch(function (err) {
        _setMsg('Bağlantı hatası: ' + (err.message || err), true);
      })
      .then(function () {
        _resetCalcBtn();
      });
    });
  }());

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
  var _backdropPointerDown = false;
  if (modalBackdrop) {
    modalBackdrop.addEventListener('pointerdown', function (e) {
      _backdropPointerDown = (e.target === modalBackdrop);
    });
    modalBackdrop.addEventListener('click', function (e) {
      if (_backdropPointerDown && e.target === modalBackdrop) closePlanaModal();
      _backdropPointerDown = false;
    });
  }

  /* ── Validation helpers ── */
  function _fieldWrap(el) {
    if (!el) return null;
    var p = el.parentElement;
    return (p && (p.classList.contains('form-ctrl') || p.classList.contains('firma-wrap') || p.classList.contains('input-wrap'))) ? p : el.parentElement;
  }

  function _setFieldErr(el, msg) {
    if (!el) return;
    var wrap = _fieldWrap(el);
    if (wrap) wrap.classList.add('atp-field-err');
    var existing = el.parentElement && el.parentElement.querySelector('.atp-field-err-msg[data-for="' + el.id + '"]');
    if (!existing) {
      var span = document.createElement('span');
      span.className = 'atp-field-err-msg';
      span.setAttribute('data-for', el.id);
      span.textContent = msg;
      el.parentElement.appendChild(span);
    } else {
      existing.textContent = msg;
    }
  }

  function _clearFieldErr(el) {
    if (!el) return;
    var wrap = _fieldWrap(el);
    if (wrap) wrap.classList.remove('atp-field-err');
    var existing = el.parentElement && el.parentElement.querySelector('.atp-field-err-msg[data-for="' + el.id + '"]');
    if (existing) existing.remove();
  }

  function _showValidationSummary(errors) {
    var box = document.getElementById('atpValidationSummary');
    if (!box) return;
    if (!errors || errors.length === 0) { box.style.display = 'none'; box.innerHTML = ''; return; }
    var html = '<div class="atp-val-box"><strong>Planı eklemek için aşağıdaki alanları düzeltin:</strong><ul>';
    errors.forEach(function (e) { html += '<li>' + e + '</li>'; });
    html += '</ul></div>';
    box.innerHTML = html;
    box.style.display = 'block';
  }

  function _clearValidationSummary() {
    var box = document.getElementById('atpValidationSummary');
    if (box) { box.style.display = 'none'; box.innerHTML = ''; }
    var warn = qs('atpModalWarn'); if (warn) warn.classList.remove('show');
  }

  /* Core validation — always clears all errors first, then marks bad fields.
     showErrors=true: updates UI feedback (called on submit click).
     showErrors=false: silent check only (called on input/change for live clear). */
  function validateAddForm(showErrors) {
    var firma = qs('atpReqFirma');
    var isEl = qs('atpReqIs');
    var arac = qs('atpReqArac');
    var tarih = qs('atpReqTarih');
    /* saat is optional — no longer validated as required */

    var errors = [];
    var firstErrEl = null;

    /* ── Araç ── */
    var aracOk = arac && arac.value;
    if (!aracOk) {
      errors.push('Araç seçmelisiniz.');
      if (showErrors) _setFieldErr(arac, 'Araç seçmelisiniz.');
      if (!firstErrEl && arac) firstErrEl = arac;
    } else {
      _clearFieldErr(arac);
    }

    /* ── Firma ── */
    var firmaOk = firma && firma.value.trim().length >= 2;
    if (!firmaOk) {
      errors.push('Firma adı en az 2 karakter olmalıdır.');
      if (showErrors) _setFieldErr(firma, 'Firma adı giriniz.');
      if (!firstErrEl && firma) firstErrEl = firma;
    } else {
      _clearFieldErr(firma);
    }

    /* ── Konum / koordinat ── */
    var locOk = (_locState.mode === 'saved' || _locState.mode === 'new') &&
      _locState.validated && _locState.validated.latitude != null;
    if (!locOk) {
      var locMsg = firma && firma.value.trim().length >= 2
        ? 'Kayıtlı konumu seçin veya Maps bağlantısını doğrulayın.'
        : 'Firma seçildikten sonra konum giriniz.';
      errors.push(locMsg);
      if (showErrors) {
        var konumSec = qs('atpKonumSection');
        var mapsInp = qs('atpReqMapsUrl');
        var konumSelect = qs('atpReqKonumSec');
        if (mapsInp && !mapsInp.hidden && konumSec && konumSec.style.display !== 'none') {
          _setFieldErr(mapsInp, locMsg);
          if (!firstErrEl) firstErrEl = mapsInp;
        } else if (konumSelect && konumSec && konumSec.style.display !== 'none') {
          _setFieldErr(konumSelect, locMsg);
          if (!firstErrEl) firstErrEl = konumSelect;
        } else if (firma && firma.value.trim().length >= 2) {
          if (!firstErrEl) firstErrEl = firma;
        }
      }
    } else {
      var mapsInp2 = qs('atpReqMapsUrl'); if (mapsInp2) _clearFieldErr(mapsInp2);
      var konumSelect2 = qs('atpReqKonumSec'); if (konumSelect2) _clearFieldErr(konumSelect2);
    }

    /* ── Yapılacak iş ── */
    var isOk = isEl && isEl.value.trim();
    if (!isOk) {
      errors.push('Yapılacak işi yazınız.');
      if (showErrors) _setFieldErr(isEl, 'Yapılacak işi yazınız.');
      if (!firstErrEl && isEl) firstErrEl = isEl;
    } else {
      _clearFieldErr(isEl);
    }

    /* ── Tarih ── */
    var tarihOk = tarih && tarih.value;
    if (!tarihOk) {
      errors.push('Tarih seçiniz.');
      if (showErrors) _setFieldErr(tarih, 'Tarih seçiniz.');
      if (!firstErrEl && tarih) firstErrEl = tarih;
    } else {
      _clearFieldErr(tarih);
      /* Past date: warn but do not block (backend enforces business rules) */
      if (showErrors && tarih.value < new Date().toISOString().slice(0, 10)) {
        _setFieldErr(tarih, 'Geçmiş tarih: plan eklenebilir fakat dikkat ediniz.');
      }
    }

    /* Saat optional: no required validation; just clear any stale error */
    var saatEl = qs('atpReqSaat'); if (saatEl) _clearFieldErr(saatEl);

    var ok = errors.length === 0;

    if (showErrors) {
      _showValidationSummary(errors);
      if (firstErrEl) {
        firstErrEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
        setTimeout(function () { try { firstErrEl.focus(); } catch (e) {} }, 300);
      }
    } else {
      /* Live mode: only hide summary if now fully valid */
      if (ok) _clearValidationSummary();
    }

    return ok;
  }

  /* Live field-clear: whenever user fixes a field, re-run silent validation */
  ['atpReqFirma','atpReqIs','atpReqArac','atpReqTarih','atpReqKonumAdi'].forEach(function (id) {
    var el = qs(id);
    if (el) {
      el.addEventListener('input', function () { validateAddForm(false); });
      el.addEventListener('change', function () { validateAddForm(false); });
    }
  });

  var reqArac = qs('atpReqArac');
  var reqSofor = qs('atpReqPlanaSofor');
  var soforDropdown = qs('atpSoforDropdown');
  var soforTimer = null;

  if (reqArac) reqArac.addEventListener('change', function () {
    var opt = reqArac.options[reqArac.selectedIndex];
    // Prefill with default driver but do NOT lock it — user can always override.
    if (opt && reqSofor) {
      var defaultDriver = opt.getAttribute('data-driver') || '';
      reqSofor.value = defaultDriver;
      if (defaultDriver) {
        reqSofor.title = 'Varsayılan şoför: ' + defaultDriver + ' — Değiştirebilirsiniz';
      } else {
        reqSofor.title = '';
      }
    }
    validateAddForm();
  });

  // ── Şoför autocomplete ──
  function _positionSoforDropdown() {
    if (!reqSofor || !soforDropdown) return;
    var r = reqSofor.getBoundingClientRect();
    soforDropdown.style.left  = r.left + 'px';
    soforDropdown.style.width = r.width + 'px';
    soforDropdown.style.top   = (r.bottom + 2) + 'px';
  }

  function _closeSoforDropdown() {
    if (soforDropdown) soforDropdown.style.display = 'none';
  }

  function _renderSoforDropdown(users) {
    if (!soforDropdown || !users.length) { _closeSoforDropdown(); return; }
    _positionSoforDropdown();
    soforDropdown.innerHTML = users.map(function (u) {
      var nm = u.display_name || u.kullanici_adi || '';
      return '<div class="firma-dd-item" style="padding:7px 12px;cursor:pointer;" tabindex="-1">' + fmtVal(nm) + '</div>';
    }).join('');
    soforDropdown.style.display = 'block';
    soforDropdown.querySelectorAll('.firma-dd-item').forEach(function (item, idx) {
      item.addEventListener('mousedown', function (e) {
        e.preventDefault();
        reqSofor.value = users[idx].display_name || users[idx].kullanici_adi || '';
        _closeSoforDropdown();
        validateAddForm();
      });
    });
  }

  if (reqSofor && soforDropdown) {
    reqSofor.addEventListener('input', function () {
      clearTimeout(soforTimer);
      var q = reqSofor.value.trim();
      if (q.length < 1) { _closeSoforDropdown(); return; }
      soforTimer = setTimeout(function () {
        fetch('/planlama/arac-takip/api/users/search?q=' + encodeURIComponent(q) + '&limit=8', { credentials: 'same-origin' })
          .then(function (r) { return r.json(); })
          .then(function (data) { _renderSoforDropdown(data.results || []); })
          .catch(function () { _closeSoforDropdown(); });
      }, 250);
    });
    reqSofor.addEventListener('blur', function () {
      setTimeout(_closeSoforDropdown, 200);
    });
    window.addEventListener('scroll', _positionSoforDropdown, true);
  }

  var modalSubmit = qs('atpModalSubmit');
  if (modalSubmit) modalSubmit.addEventListener('click', function () {
    if (_submitInFlight) return;

    /* Run full validation with error UI */
    if (!validateAddForm(true)) return;

    _submitInFlight = true;
    modalSubmit.disabled = true;
    var v = _locState.validated || {};
    var tarihEl = qs('atpReqTarih');
    var useTarih = (tarihEl && tarihEl.value) ? tarihEl.value : planDate;
    var payload = {
      plan_tarihi: useTarih,
      tarih: useTarih,
      arac_external_id: (qs('atpReqArac') || {}).value || '',
      yapilacak_is: ((qs('atpReqIs') || {}).value || '').trim(),
      is: ((qs('atpReqIs') || {}).value || '').trim(),
      firma: ((qs('atpReqFirma') || {}).value || '').trim(),
      planlanan_saat: ((qs('atpReqSaat') || {}).value || '') || null,
      oncelik: ((qs('atpReqOncelik') || {}).value || 'NORMAL'),
      is_turu: ((qs('atpReqIsTuru') || {}).value || 'TESLIM'),
      urun_malzeme: ((qs('atpReqUrun') || {}).value || '').trim(),
      miktar: ((qs('atpReqMiktar') || {}).value || '').trim(),
      miktar_birim: ((qs('atpReqBirim') || {}).value || 'ADET'),
      sofor_adi: ((qs('atpReqPlanaSofor') || {}).value || '').trim(),
      ek_not: ((qs('atpReqNot') || {}).value || '').trim(),
      location_master_id: ((qs('atpReqLocationMasterId') || {}).value || '') || null,
      latitude: v.latitude,
      longitude: v.longitude,
      lat: v.latitude,
      lng: v.longitude,
      adres: v.adres || ((qs('atpReqMapsUrl') || {}).value || '').trim(),
      maps_url: v.maps_url || ((qs('atpReqMapsUrl') || {}).value || '').trim(),
      is_new_location: _locState.mode === 'new',
      konum_adi: ((qs('atpReqKonumAdi') || {}).value || '').trim() || null,
      cari_id: ((qs('atpReqCariId') || {}).value || '') || null,
      client_submit_id: _locState.submitToken,
      save_to_master: _locState.mode === 'new',
    };
    fetch('/planlama/arac-takip/api/plana-is-ekle', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }).then(function (r) { return r.json(); }).then(function (j) {
      if (!j.ok) {
        toast('İş eklenemedi: ' + (j.error || j.message || ''));
        _submitInFlight = false;
        modalSubmit.disabled = false;
        return;
      }
      closePlanaModal();
      toast('İş plana eklendi.');
      loadOps();
    }).catch(function () {
      toast('Sunucu hatası. Tekrar deneyin.');
      _submitInFlight = false;
      modalSubmit.disabled = false;
    });
  });

  var firmaInput = qs('atpReqFirma');
  var firmaDropdown = qs('atpFirmaDropdown');
  var firmaTimer = null;

  // Position the dropdown using fixed coords so modal overflow:hidden/auto cannot clip it.
  function _positionFirmaDropdown() {
    if (!firmaInput || !firmaDropdown) return;
    var r = firmaInput.getBoundingClientRect();
    firmaDropdown.style.position = 'fixed';
    firmaDropdown.style.left = r.left + 'px';
    firmaDropdown.style.width = r.width + 'px';
    firmaDropdown.style.top = (r.bottom + 2) + 'px';
    firmaDropdown.style.right = '';
  }

  // Select a firma item from the dropdown: set state, close dropdown, load locations.
  function _selectFirmaItem(lid, cari, firmaName) {
    _locState.anchorId = lid || null;
    _setHidden('atpReqLocationMasterId', lid || '');
    if (cari) _setHidden('atpReqCariId', cari);
    firmaInput.value = firmaName;
    firmaDropdown.classList.remove('open');
    if (lid) {
      loadCompanyLocations(lid, cari || null);
    } else {
      // "Yeni firma" path: no anchor, open new location mode
      showKonumSection(true, true);
      enterNewKonumMode(false);
    }
  }

  // Render search results (or "yeni firma" fallback) into dropdown and open it.
  function _renderFirmaDropdown(items, rawQuery) {
    _positionFirmaDropdown();
    var html = items.slice(0, 8).map(function (it) {
      var nm = it.firma || it.name || '';
      var ad = it.adres || it.address || it.short_adres || '';
      return '<div class="firma-dd-item" data-id="' + (it.id || '') + '" data-cari="' + (it.cari_id || '') + '" tabindex="-1">' +
        '<strong>' + fmtVal(nm) + '</strong>' +
        (ad ? '<span>' + fmtVal(ad) + '</span>' : '') +
        '</div>';
    }).join('');
    // Always append "new company" option
    if (rawQuery && rawQuery.length >= 2) {
      html += '<div class="firma-dd-item firma-dd-new" data-id="" data-cari="" tabindex="-1">' +
        '<strong>Yeni firma olarak kullan: ' + fmtVal(rawQuery) + '</strong>' +
        '</div>';
    }
    firmaDropdown.innerHTML = html;
    firmaDropdown.classList.add('open');

    firmaDropdown.querySelectorAll('.firma-dd-item').forEach(function (item) {
      item.addEventListener('mousedown', function (e) {
        e.preventDefault();
        var lid = item.getAttribute('data-id');
        var cari = item.getAttribute('data-cari');
        var nm = (item.querySelector('strong') || {}).textContent || rawQuery;
        if (!lid) {
          // "Yeni firma" selected — use raw query as firm name
          _selectFirmaItem('', '', rawQuery);
        } else {
          _selectFirmaItem(lid, cari, nm);
        }
      });
    });
  }

  // Keyboard navigation index within the open dropdown.
  var _firmaDdFocusIdx = -1;

  function _firmaDdItems() {
    return firmaDropdown ? Array.from(firmaDropdown.querySelectorAll('.firma-dd-item')) : [];
  }

  function _firmaDdMoveFocus(delta) {
    var items = _firmaDdItems();
    if (!items.length) return;
    _firmaDdFocusIdx = Math.max(0, Math.min(items.length - 1, _firmaDdFocusIdx + delta));
    items.forEach(function (el, i) { el.classList.toggle('firma-dd-focused', i === _firmaDdFocusIdx); });
    items[_firmaDdFocusIdx].scrollIntoView({ block: 'nearest' });
  }

  if (firmaInput && firmaDropdown) {
    firmaInput.addEventListener('input', function () {
      clearTimeout(firmaTimer);
      onFirmaTyped();
      _firmaDdFocusIdx = -1;
      var q = firmaInput.value.trim();
      if (q.length < 2) { firmaDropdown.classList.remove('open'); return; }
      firmaTimer = setTimeout(function () {
        fetch('/planlama/arac-takip/api/locations/search?q=' + encodeURIComponent(q), { credentials: 'same-origin' })
          .then(function (r) { return r.json(); })
          .then(function (data) {
            _renderFirmaDropdown(data.results || [], q);
          })
          .catch(function () {
            // On error, still show "new company" option
            _renderFirmaDropdown([], q);
          });
      }, 300);
    });

    firmaInput.addEventListener('keydown', function (e) {
      if (!firmaDropdown.classList.contains('open')) return;
      if (e.key === 'ArrowDown') { e.preventDefault(); _firmaDdMoveFocus(1); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); _firmaDdMoveFocus(-1); }
      else if (e.key === 'Enter') {
        e.preventDefault();
        var items = _firmaDdItems();
        if (_firmaDdFocusIdx >= 0 && items[_firmaDdFocusIdx]) {
          items[_firmaDdFocusIdx].dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
        }
      } else if (e.key === 'Escape') {
        firmaDropdown.classList.remove('open');
      }
    });

    /* Track whether the mouse button is held down inside firmaInput.
       While dragging (text selection), a blur event must NOT close the dropdown
       so the user can freely select/copy text without losing the open state. */
    var _firmaMouseHeld = false;
    firmaInput.addEventListener('mousedown', function () { _firmaMouseHeld = true; });
    document.addEventListener('mouseup', function () { _firmaMouseHeld = false; });

    firmaInput.addEventListener('blur', function () {
      setTimeout(function () {
        if (_firmaMouseHeld) return; // drag still in progress — keep dropdown open
        firmaDropdown.classList.remove('open');
      }, 200);
    });

    // Reposition on scroll/resize so fixed coords stay accurate
    window.addEventListener('scroll', _positionFirmaDropdown, true);
    window.addEventListener('resize', _positionFirmaDropdown);
  }

  var konumSelect = qs('atpReqKonumSelect');
  if (konumSelect) konumSelect.addEventListener('change', function () {
    var id = konumSelect.value;
    if (!id) return;
    var loc = (_locState.locations || []).find(function (l) { return String(l.id) === String(id); });
    if (loc) applySavedLocation(loc);
  });

  var btnYeniKonum = qs('atpBtnYeniKonum');
  if (btnYeniKonum) btnYeniKonum.addEventListener('click', function (e) {
    e.preventDefault();
    enterNewKonumMode(true);
  });

  // Clear stale coords whenever the Maps input is edited.
  var mapsUrlInput = qs('atpReqMapsUrl');
  if (mapsUrlInput) {
    mapsUrlInput.addEventListener('input', function () {
      _clearMapsInputState();
    });
  }

  var btnKonumKontrol = qs('atpBtnKonumKontrol');
  if (btnKonumKontrol) btnKonumKontrol.addEventListener('click', function () {
    var mapsVal = ((qs('atpReqMapsUrl') || {}).value || '').trim();
    if (!mapsVal) {
      _showKonumStatus('Google Maps bağlantısı veya adres girin.', 'err');
      return;
    }
    btnKonumKontrol.disabled = true;
    fetch('/planlama/arac-takip/api/maps/resolve', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ maps_url: mapsVal, adres: mapsVal }),
    }).then(function (r) { return r.json(); }).then(function (j) {
      btnKonumKontrol.disabled = false;
      if (!j.ok) {
        _showKonumStatus(j.error || 'Konum bulunamadı.', 'err');
        validateAddForm();
        return;
      }
      setKonumCoords(j.latitude, j.longitude, j.maps_url || mapsVal, false, 'api_resolved');
      _setHidden('atpReqAdres', j.adres || mapsVal);
      _showKonumStatus(
        'Konum doğrulandı: ' + Number(j.latitude).toFixed(6) + ', ' + Number(j.longitude).toFixed(6) +
        (j.resolved_url && j.resolved_url !== mapsVal ? ' (bağlantı çözüldü)' : ''),
        'ok'
      );
      validateAddForm();
    }).catch(function () {
      btnKonumKontrol.disabled = false;
      _showKonumStatus('Konum doğrulanamadı.', 'err');
    });
  });

  var btnHaritadaGor = qs('atpBtnHaritadaGor');
  if (btnHaritadaGor) btnHaritadaGor.addEventListener('click', function () {
    var v = _locState.validated;
    // Only use coordinates that were explicitly resolved via API or loaded from saved location.
    // A manual_pin or no-source state must be re-verified with "Konumu Kontrol Et" first.
    if (v && v.latitude != null && v.longitude != null &&
        (v.source === 'api_resolved' || v.source === 'saved')) {
      var url = 'https://www.google.com/maps?q=' + v.latitude + ',' + v.longitude;
      window.open(url, '_blank', 'noopener');
    } else {
      _showKonumStatus(
        'Önce "Konumu Kontrol Et" ile koordinatı doğrulayın.',
        'err'
      );
    }
  });

  var modalBody = document.querySelector('#atpRequestModal .modal-body');
  if (modalBody) {
    modalBody.addEventListener('mousedown', function (e) { e.stopPropagation(); });
  }

  /* ─── Route explainer button wiring ─── */
  if (window.AtpRouteExplainer) {
    window.AtpRouteExplainer.bindExplainerButton(
      function () { return window.AtpRoute && window.AtpRoute.getLastRoute ? window.AtpRoute.getLastRoute() : null; },
      function () { return typeof buildPlanMapPayload === 'function' ? buildPlanMapPayload() : null; }
    );
    window.AtpRouteExplainer.bindApplyHooks({
      getVehicleId: vehicleId,
      getPlanDate: _planDateForApi,
      toast: toast,
      reloadAfterApply: reloadAfterGoogleApply,
      reloadAfterProfileApply: reloadAfterGoogleProfileApply,
    });
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
  initJobActionMenu();
  (function bindPassiveJobDetailModal() {
    var closeBtn = qs('atpPassiveJobClose');
    var okBtn = qs('atpPassiveJobOk');
    var backdrop = qs('atpPassiveJobBackdrop');
    if (closeBtn) closeBtn.addEventListener('click', closePassiveJobDetail);
    if (okBtn) okBtn.addEventListener('click', closePassiveJobDetail);
    if (backdrop) {
      backdrop.addEventListener('click', function (e) {
        if (e.target === backdrop) closePassiveJobDetail();
      });
    }
  }());
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

  /* ─── Base location button — focus mini map preview ─── */
  var btnBase = qs('atpBtnBaseLocation');
  if (btnBase) btnBase.addEventListener('click', function () {
    if (typeof focusMiniMapBase === 'function') focusMiniMapBase();
  });

  /* ─── ESC close timeline modal (plan modal handled by its own listener) ─── */
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') { closeTimelineModal(); }
  });

  /* ─── Accordion toggle + summary click isolation ─── */
  var planAcc = qs('atpPlanningSection');
  var planSummary = planAcc && planAcc.querySelector('summary.plan-rota-summary');
  var chevronEl   = qs('atpPrsChevron');

  function _syncChevronState() {
    if (!chevronEl || !planAcc) return;
    var open = !!planAcc.open;
    chevronEl.textContent = open ? '▲' : '▼';
    chevronEl.setAttribute('aria-expanded', open ? 'true' : 'false');
  }

  function _togglePlanAcc(forceOpen) {
    if (!planAcc) return;
    if (typeof forceOpen === 'boolean') {
      planAcc.open = forceOpen;
    } else {
      planAcc.open = !planAcc.open;
    }
    _syncChevronState();
    /* fire map init if just opened */
    if (planAcc.open && window.AtpPlanMap) {
      requestAnimationFrame(function () { window.AtpPlanMap.onPlanTabShown(); });
      setTimeout(function () { if (window.AtpPlanMap) window.AtpPlanMap.onPlanTabShown(); }, 250);
    }
  }

  if (planAcc) {
    planAcc.addEventListener('toggle', function () {
      _syncChevronState();
      if (planAcc.open && window.AtpPlanMap) {
        requestAnimationFrame(function () { window.AtpPlanMap.onPlanTabShown(); });
        setTimeout(function () { if (window.AtpPlanMap) window.AtpPlanMap.onPlanTabShown(); }, 250);
      }
    });
  }

  if (planSummary) {
    _syncChevronState();

    if (chevronEl) {
      chevronEl.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        _togglePlanAcc();
      });
    }

    /* Single summary-level click interceptor */
    planSummary.addEventListener('click', function (e) {
      /* Always prevent native <details> toggle — we control it manually */
      e.preventDefault();

      var target = e.target;

      /* Chevron handled by its own listener */
      if (target === chevronEl || (chevronEl && chevronEl.contains(target))) {
        return;
      }

      /* Plana İş Ekle (prs) — handled by dedicated listener; do not open legacy modal here */

      /* All other summary children (Araç, Şoför, Tarih, Saat divs) → no-op */
    });

    planSummary.style.cursor = 'default';
  }

  /* ─── Expose for external scripts ─── */
  window.atpOpenTimeline = openTimelineModal;
  window.atpSetTab = setTab;

  /* ═══════════════════════════════════════════════════════════════════════
     ÇOKLU İŞ EKLE MODAL  — atpMulti controller  (FIX1: mouse + row-state)
     Self-contained: does not modify any existing single-modal variables.
  ═══════════════════════════════════════════════════════════════════════ */
  (function () {
    'use strict';

    /* ── Leaflet mini-map ── */
    var _mMap = null;
    var _mMapLayer = null;

    function _initMMap() {
      var el = document.getElementById('atpMultiMapMini');
      if (!el || _mMap) return;
      try {
        _mMap = window.L.map(el, { zoomControl: false, attributionControl: false, keyboard: false });
        window.L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(_mMap);
        _mMapLayer = window.L.layerGroup().addTo(_mMap);
        _mMap.setView([41.0, 29.0], 10);
      } catch (e) { /* leaflet not ready */ }
    }

    function _showMMapPin(lat, lng, adres) {
      if (!_mMap) _initMMap();
      if (!_mMap) return;
      if (_mMapLayer) _mMapLayer.clearLayers();
      window.L.marker([lat, lng]).addTo(_mMapLayer);
      _mMap.setView([lat, lng], 14);
      var addrEl = document.getElementById('atpMultiMapAddr');
      if (addrEl) addrEl.textContent = adres || (lat.toFixed(4) + ', ' + lng.toFixed(4));
      setTimeout(function () { _mMap.invalidateSize({ animate: false }); }, 80);
    }

    /* ── FINAL LOCK: close only via X / İptal / submit_ok ── */
    var _multiMouseHeld = false;
    var _multiMouseDownInsideModal = false;
    var _multiModalEl = null;
    var _CLOSE_OK = { x: 1, cancel: 1, submit_ok: 1 };

    function _getModal() {
      if (!_multiModalEl) _multiModalEl = document.getElementById('atpMultiModal');
      return _multiModalEl;
    }

    function _eventPathIncludesModal(e) {
      var modal = _getModal();
      if (!modal) return false;
      if (modal.contains(e.target)) return true;
      if (typeof e.composedPath === 'function') {
        var path = e.composedPath();
        for (var i = 0; i < path.length; i++) {
          if (path[i] === modal) return true;
        }
      }
      var dd = _getFirmaDD();
      if (dd && dd.contains(e.target)) return true;
      return false;
    }

    function _insideModal(target) {
      var modal = _getModal();
      var dd = _getFirmaDD();
      return (modal && modal.contains(target)) || (dd && dd.contains(target));
    }

    function _resetMultiMouseGuards() {
      _multiMouseHeld = false;
      _multiMouseDownInsideModal = false;
    }

    document.addEventListener('mousedown', function (e) {
      if (_insideModal(e.target)) {
        _multiMouseHeld = true;
        _multiMouseDownInsideModal = true;
      }
    }, true);

    document.addEventListener('mouseup', function () {
      setTimeout(_resetMultiMouseGuards, 180);
    }, true);

    function _wireModalCloseGuards() {
      var modal = _getModal();
      if (!modal || modal._atpMultiCloseGuard) return;
      modal._atpMultiCloseGuard = true;
      ['mousedown', 'mouseup', 'click'].forEach(function (evtName) {
        modal.addEventListener(evtName, function (e) {
          e.stopPropagation();
          if (evtName === 'mousedown') {
            _multiMouseHeld = true;
            _multiMouseDownInsideModal = true;
          }
        });
      });
    }
    _wireModalCloseGuards();

    /* ── Row state ── */
    var _rows = [];
    var _rowUidSeq = 0;
    var _submitInFlight = false;

    function _mkRowState() {
      return {
        uid: 'r' + (++_rowUidSeq),   // immutable unique identifier (BUG2 FIX)
        firma: '',
        firmaAnchorId: null,
        cariId: null,
        konumId: null,
        konumAdi: '',
        mapsUrl: '',
        lat: null,
        lng: null,
        adres: '',
        status: 'empty',   // empty | pending | ok | err
        yapilacakIs: '',
        oncelik: 'NORMAL',
      };
    }

    /* ── Helpers ── */
    function _qs(id) { return document.getElementById(id); }

    function _aracOpts() {
      var dst = _qs('atpMultiArac');
      if (!dst) return;
      var prev = dst.value;
      var opsVehicles = (lastOpsData && lastOpsData.vehicles) ? lastOpsData.vehicles : [];
      dst.innerHTML = vehicleUniqueOptionsToHtml(
        buildUniquePhysicalVehicleOptions(lastVehicles, opsVehicles)
      );
      if (prev) dst.value = prev;
    }

    /* Find row by its uid attribute on the TR (BUG2 FIX: uid not index) */
    function _rowByEl(el) {
      var tr = el.closest ? el.closest('tr[data-row-uid]') : null;
      if (!tr) {
        /* fallback: walk up manually */
        var p = el;
        while (p && p !== document.body) {
          if (p.hasAttribute && p.hasAttribute('data-row-uid')) { tr = p; break; }
          p = p.parentElement;
        }
      }
      var uid = tr ? tr.getAttribute('data-row-uid') : null;
      return uid ? _rows.find(function (r) { return r.uid === uid; }) : null;
    }

    /* ── Patch single row's dynamic cells without full DOM rebuild ──────────
       This avoids the "user loses typed text" problem and the async-wrong-row
       problem: only the badge/konum cells are updated, input values are untouched.
    ──────────────────────────────────────────────────────────────────────── */
    function _patchRowDom(row) {
      var tr = document.querySelector('tr[data-row-uid="' + row.uid + '"]');
      if (!tr) return; // row was deleted before async resolved

      /* Badge */
      var durumCell = tr.querySelector('.col-durum');
      if (durumCell) {
        var badge = '';
        if (row.status === 'ok') {
          badge = '<span class="atp-multi-badge ok">✓ Doğrulandı</span>';
        } else if (row.status === 'pending') {
          badge = '<span class="atp-multi-badge warn">⚠ Kontrol et</span>';
        } else if (row.status === 'err') {
          badge = '<span class="atp-multi-badge err">Hata</span>';
        } else {
          badge = '<span class="atp-multi-badge err">Eksik</span>';
        }
        durumCell.innerHTML = badge;
      }

      /* Konum column */
      var konumCell = tr.querySelector('.col-konum');
      if (konumCell) {
        var konumLabel = row.konumAdi
          ? '<strong>' + fmtVal(row.konumAdi) + '</strong>'
          : '<span style="color:#9ca3af">—</span>';
        var linkText = '+ ' + (row.konumAdi ? 'Değiştir' : 'Yeni Konum');
        konumCell.innerHTML = konumLabel +
          '<a class="atp-multi-konum-link" data-action="konum-edit">' + linkText + '</a>';
        konumCell.querySelector('[data-action="konum-edit"]').addEventListener('click', function () {
          _openKonumEditor(row);
        });
      }

      /* Harita button enable/disable */
      var haritaBtn = tr.querySelector('.row-btn-harita');
      if (haritaBtn) haritaBtn.disabled = (row.status !== 'ok');

      _updateSummary();
    }

    /* ── Row HTML (full render — called on full rebuild only) ── */
    function _rowHtml(row) {
      var oncelikSel = ['NORMAL','YUKSEK','ACIL','DUSUK'].map(function (v) {
        var lbl = {NORMAL:'Normal',YUKSEK:'Yüksek',ACIL:'Acil',DUSUK:'Düşük'}[v];
        return '<option value="' + v + '"' + (row.oncelik === v ? ' selected' : '') + '>' + lbl + '</option>';
      }).join('');

      var badge = '';
      if (row.status === 'ok') badge = '<span class="atp-multi-badge ok">✓ Doğrulandı</span>';
      else if (row.status === 'pending') badge = '<span class="atp-multi-badge warn">⚠ Kontrol et</span>';
      else if (row.status === 'err') badge = '<span class="atp-multi-badge err">Hata</span>';
      else badge = '<span class="atp-multi-badge err">Eksik</span>';

      var konumLabel = row.konumAdi
        ? '<strong>' + fmtVal(row.konumAdi) + '</strong>'
        : '<span style="color:#9ca3af">—</span>';
      var konumLink = '<a class="atp-multi-konum-link" data-action="konum-edit">+ ' +
        (row.konumAdi ? 'Değiştir' : 'Yeni Konum') + '</a>';

      return '<tr data-row-uid="' + row.uid + '">' +
        '<td class="col-no" style="color:#9ca3af;font-size:11px;text-align:center">' + (row._idx || '') + '</td>' +
        '<td class="col-firma"><div style="position:relative">' +
          '<input class="row-input row-firma" placeholder="Firma adı…" value="' + fmtVal(row.firma || '') + '" autocomplete="off">' +
        '</div></td>' +
        '<td class="col-konum">' + konumLabel + konumLink + '</td>' +
        '<td class="col-is"><input class="row-input row-is" placeholder="Yapılacak iş…" value="' + fmtVal(row.yapilacakIs || '') + '"></td>' +
        '<td class="col-oncelik"><select class="row-input row-oncelik">' + oncelikSel + '</select></td>' +
        '<td class="col-durum">' + badge + '</td>' +
        '<td class="col-saat"><span class="atp-multi-badge auto">Otomatik</span></td>' +
        '<td class="col-islem">' +
          '<button class="btn btn-xs btn-outline row-btn-harita" title="Haritada Gör"' +
            (row.status === 'ok' ? '' : ' disabled') + '>🗺</button> ' +
          '<button class="btn btn-xs row-btn-sil" style="color:#ef4444;border:1px solid #fca5a5;background:#fef2f2">Sil</button>' +
        '</td>' +
      '</tr>';
    }

    /* ── Full render (called on add/delete/open) ── */
    function _renderRows() {
      var tbody = _qs('atpMultiTbody');
      if (!tbody) return;
      tbody.innerHTML = _rows.map(function (r, i) {
        r._idx = i + 1;
        return _rowHtml(r);
      }).join('');
      _attachRowListeners();
      _updateSummary();
    }

    /* ── Attach per-row listeners (runs after full render) ── */
    function _attachRowListeners() {
      var tbody = _qs('atpMultiTbody');
      if (!tbody) return;

      /* Firma inputs */
      tbody.querySelectorAll('.row-firma').forEach(function (inp) {
        /* BUG1 FIX: track mousedown on input so blur won't close DD during drag */
        var _inpMouseHeld = false;
        inp.addEventListener('mousedown', function () { _inpMouseHeld = true; });
        document.addEventListener('mouseup', function () { _inpMouseHeld = false; }, { once: false });

        inp.addEventListener('input', function () {
          var row = _rowByEl(inp);
          if (!row) return;
          row.firma = inp.value;
          row.firmaAnchorId = null;
          row.cariId = null;
          if (row.status === 'ok') { row.status = 'pending'; _patchRowDom(row); }
          _openFirmaDD(row, inp);
        });

        inp.addEventListener('blur', function () {
          setTimeout(function () {
            if (_inpMouseHeld || _multiMouseHeld) return; // drag in progress
            _closeFirmaDD();
          }, 200);
        });

        inp.addEventListener('keydown', function (e) {
          if (e.key === 'Escape') _closeFirmaDD();
        });
      });

      /* İş inputs */
      tbody.querySelectorAll('.row-is').forEach(function (inp) {
        inp.addEventListener('input', function () {
          var row = _rowByEl(inp);
          if (row) { row.yapilacakIs = inp.value; _updateSummary(); }
        });
      });

      /* Öncelik selects */
      tbody.querySelectorAll('.row-oncelik').forEach(function (sel) {
        sel.addEventListener('change', function () {
          var row = _rowByEl(sel);
          if (row) row.oncelik = sel.value;
        });
      });

      /* Konum edit links */
      tbody.querySelectorAll('[data-action="konum-edit"]').forEach(function (a) {
        a.addEventListener('click', function () {
          var row = _rowByEl(a);
          if (row) _openKonumEditor(row);
        });
      });

      /* Harita buttons */
      tbody.querySelectorAll('.row-btn-harita').forEach(function (btn) {
        btn.addEventListener('click', function () {
          var row = _rowByEl(btn);
          if (row && row.lat != null && row.lng != null) {
            _showMMapPin(row.lat, row.lng, row.adres);
          }
        });
      });

      /* Sil buttons */
      tbody.querySelectorAll('.row-btn-sil').forEach(function (btn) {
        btn.addEventListener('click', function () {
          var row = _rowByEl(btn);
          if (!row) return;
          /* BUG2 FIX: mark uid as deleted so any in-flight async ignores it */
          row._deleted = true;
          _rows = _rows.filter(function (r) { return r.uid !== row.uid; });
          if (!_rows.length) _addRow();
          else _renderRows();
        });
      });
    }

    /* ── Firma dropdown (shared, position:fixed) ── */
    var _firmaDDEl = null;
    var _firmaDDRow = null;
    var _firmaDDInp = null;
    var _firmaDDTimer = null;

    function _getFirmaDD() {
      if (!_firmaDDEl) _firmaDDEl = _qs('atpMultiFirmaDD');
      return _firmaDDEl;
    }

    function _closeFirmaDD() {
      var dd = _getFirmaDD();
      if (dd) dd.style.display = 'none';
      _firmaDDRow = null;
      _firmaDDInp = null;
    }

    function _openFirmaDD(row, inp) {
      var q = (inp.value || '').trim();
      _firmaDDRow = row;
      _firmaDDInp = inp;
      clearTimeout(_firmaDDTimer);
      if (q.length < 2) { _closeFirmaDD(); return; }
      _firmaDDTimer = setTimeout(function () {
        fetch('/planlama/arac-takip/api/locations/search?q=' + encodeURIComponent(q), { credentials: 'same-origin' })
          .then(function (r) { return r.json(); })
          .then(function (data) { _renderFirmaDD(data.results || [], q, row, inp); })
          .catch(function () { _renderFirmaDD([], q, row, inp); });
      }, 280);
    }

    function _renderFirmaDD(items, rawQuery, row, inp) {
      var dd = _getFirmaDD();
      /* BUG2 FIX: discard if row deleted or different row opened since */
      if (!dd || _firmaDDRow !== row || row._deleted) return;
      var r = inp.getBoundingClientRect();
      dd.style.left = r.left + 'px';
      dd.style.width = r.width + 'px';
      dd.style.top = (r.bottom + 2) + 'px';

      var html = items.slice(0, 8).map(function (it) {
        var nm = it.firma || it.name || '';
        var ad = it.adres || it.address || it.short_adres || '';
        return '<div class="mdd-item" data-id="' + (it.id || '') + '" data-cari="' + (it.cari_id || '') + '">' +
          '<strong>' + fmtVal(nm) + '</strong>' +
          (ad ? '<span>' + fmtVal(ad) + '</span>' : '') +
          '</div>';
      }).join('');
      if (rawQuery && rawQuery.length >= 2) {
        html += '<div class="mdd-item mdd-new" data-id="" data-cari="">' +
          '<strong>Yeni firma: ' + fmtVal(rawQuery) + '</strong></div>';
      }
      dd.innerHTML = html;
      dd.style.display = 'block';

      dd.querySelectorAll('.mdd-item').forEach(function (item) {
        item.addEventListener('mousedown', function (e) {
          e.preventDefault();
          var lid = item.getAttribute('data-id');
          var cariId = item.getAttribute('data-cari');
          var nm = (item.querySelector('strong') || {}).textContent || rawQuery;
          row.firmaAnchorId = lid || null;
          row.cariId = cariId || null;
          if (lid) {
            row.firma = nm.replace(/^Yeni firma: /, '');
            /* Update the input value without re-rendering all rows */
            if (inp && inp.isConnected) inp.value = row.firma;
            _closeFirmaDD();
            _loadRowLocations(row, lid, cariId);
          } else {
            row.firma = rawQuery;
            row.status = 'pending';
            if (inp && inp.isConnected) inp.value = row.firma;
            _closeFirmaDD();
            _patchRowDom(row);
          }
        });
      });
    }

    /* Load saved locations for a row — BUG2 FIX: uses row.uid to verify row still alive */
    function _loadRowLocations(row, anchorId, cariId) {
      var rowUid = row.uid;
      var url = '/planlama/arac-takip/api/locations/for-company?anchor_id=' + encodeURIComponent(anchorId || '') +
        (cariId ? '&cari_id=' + encodeURIComponent(cariId) : '');
      fetch(url, { credentials: 'same-origin' })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          /* Discard if row was deleted or replaced */
          if (row._deleted || !_rows.find(function (r2) { return r2.uid === rowUid; })) return;
          var locs = d.locations || [];
          if (locs.length > 0) {
            var best = locs.find(function (l) { return l.latitude != null; }) || locs[0];
            row.konumId = best.id;
            row.konumAdi = best.konum_adi || best.name || '';
            row.mapsUrl = best.maps_url || '';
            row.lat = best.latitude;
            row.lng = best.longitude;
            row.adres = best.adres || best.address || '';
            row.status = (row.lat != null && row.lng != null) ? 'ok' : 'pending';
          } else {
            row.konumId = null;
            row.konumAdi = '';
            row.status = 'pending';
          }
          _patchRowDom(row); /* BUG2 FIX: patch only this row, don't full-rebuild */
        })
        .catch(function () {
          if (row._deleted) return;
          row.status = 'pending';
          _patchRowDom(row);
        });
    }

    /* ── Konum editor via prompt → resolve ── */
    function _openKonumEditor(row) {
      var rowUid = row.uid;
      var mapsVal = window.prompt('Google Maps bağlantısı veya koordinat (lat,lng):', row.mapsUrl || '');
      if (mapsVal === null) return;
      mapsVal = mapsVal.trim();
      if (!mapsVal) { row.status = 'pending'; _patchRowDom(row); return; }
      row.mapsUrl = mapsVal;
      row.status = 'pending';
      _patchRowDom(row);
      fetch('/planlama/arac-takip/api/maps/resolve', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ maps_url: mapsVal, adres: mapsVal }),
      }).then(function (r) { return r.json(); }).then(function (j) {
        /* BUG2 FIX: check row still alive */
        if (row._deleted || !_rows.find(function (r2) { return r2.uid === rowUid; })) return;
        if (j.ok && j.latitude != null) {
          row.lat = j.latitude;
          row.lng = j.longitude;
          row.adres = j.adres || j.maps_url || mapsVal;
          row.mapsUrl = j.maps_url || mapsVal;
          row.status = 'ok';
          _showMMapPin(row.lat, row.lng, row.adres);
        } else {
          row.status = 'err';
          toast('Konum bulunamadı: ' + (j.error || mapsVal));
        }
        _patchRowDom(row);
      }).catch(function () {
        if (row._deleted) return;
        row.status = 'err';
        _patchRowDom(row);
      });
    }

    /* ── Bulk location check — BUG2 FIX: capture rowUid per iteration ── */
    function _bulkKonumKontrol() {
      var pending = _rows.filter(function (r) { return r.status === 'pending' && r.mapsUrl; });
      if (!pending.length) {
        toast('Kontrol edilecek bekleyen satır yok.');
        return;
      }
      pending.forEach(function (row) {
        var rowUid = row.uid;
        fetch('/planlama/arac-takip/api/maps/resolve', {
          method: 'POST',
          credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ maps_url: row.mapsUrl, adres: row.mapsUrl }),
        }).then(function (r) { return r.json(); }).then(function (j) {
          /* BUG2 FIX: verify row still in _rows by uid */
          if (row._deleted || !_rows.find(function (r2) { return r2.uid === rowUid; })) return;
          if (j.ok && j.latitude != null) {
            row.lat = j.latitude; row.lng = j.longitude;
            row.adres = j.adres || j.maps_url || row.mapsUrl;
            row.status = 'ok';
          } else {
            row.status = 'err';
          }
          _patchRowDom(row); /* only this row */
        }).catch(function () {
          if (row._deleted) return;
          row.status = 'err';
          _patchRowDom(row);
        });
      });
    }

    /* ── Summary line ── */
    function _updateSummary() {
      var el = _qs('atpMultiSummary');
      if (!el) return;
      var total = _rows.length;
      var okCount = _rows.filter(function (r) { return r.status === 'ok'; }).length;
      var pendCount = _rows.filter(function (r) { return r.status !== 'ok'; }).length;
      el.innerHTML =
        '<span class="s-count">' + total + ' satır</span>' +
        ' • <span class="s-ok">✓ ' + okCount + ' konum doğrulandı</span>' +
        (pendCount ? ' • <span class="s-warn">⚠ ' + pendCount + ' konum bekliyor</span>' : '');
    }

    /* ── Add row ── */
    function _addRow() {
      _rows.push(_mkRowState()); /* new row always starts empty — no state copy */
      _renderRows();
    }

    /* ── Sentinel guard: reject placeholders that are not real values ── */
    var _SENTINEL = /^[\s\-—–]+$/;  // only dashes / whitespace = empty
    function _isBlank(s) {
      return !s || !s.trim() || _SENTINEL.test(s.trim());
    }

    /* ── Per-row validation error mark ── */
    function _markRowError(uid, fieldCls, msg) {
      var tr = document.querySelector('tr[data-row-uid="' + uid + '"]');
      if (!tr) return;
      var inp = tr.querySelector('.' + fieldCls);
      if (!inp) return;
      inp.style.borderColor = '#ef4444';
      inp.title = msg;
      /* Small red helper below input */
      var helper = inp.parentElement.querySelector('.row-err-hint');
      if (!helper) {
        helper = document.createElement('div');
        helper.className = 'row-err-hint';
        helper.style.cssText = 'color:#ef4444;font-size:10.5px;margin-top:2px';
        inp.parentElement.appendChild(helper);
      }
      helper.textContent = msg;
    }

    function _clearRowErrors() {
      document.querySelectorAll('#atpMultiTbody .row-input').forEach(function (inp) {
        inp.style.borderColor = '';
        inp.title = '';
      });
      document.querySelectorAll('#atpMultiTbody .row-err-hint').forEach(function (el) {
        el.textContent = '';
      });
    }

    /* ── Strict submit validation — returns true only if ALL rows are valid ── */
    function _validateAllRows(showErrors) {
      /* Step 1: sync DOM → state */
      _rows.forEach(function (r) {
        var tr = document.querySelector('tr[data-row-uid="' + r.uid + '"]');
        if (!tr) return;
        var firmaInp = tr.querySelector('.row-firma');
        var isInp = tr.querySelector('.row-is');
        if (firmaInp) r.firma = firmaInp.value;
        if (isInp) r.yapilacakIs = isInp.value;
      });

      if (showErrors) _clearRowErrors();

      var valid = true;

      _rows.forEach(function (r, i) {
        var rowValid = true;

        /* firma: min 2 real chars, no placeholder sentinels */
        var firmaClean = (r.firma || '').trim();
        if (_isBlank(firmaClean) || firmaClean.length < 2) {
          rowValid = false;
          if (showErrors) _markRowError(r.uid, 'row-firma', 'Firma adı en az 2 karakter');
        }

        /* yapilacak_is: min 2 real chars */
        var isClean = (r.yapilacakIs || '').trim();
        if (_isBlank(isClean) || isClean.length < 2) {
          rowValid = false;
          if (showErrors) _markRowError(r.uid, 'row-is', 'Yapılacak iş en az 2 karakter');
        }

        /* konum: must be status=ok AND have lat/lng */
        if (r.status !== 'ok' || r.lat == null || r.lng == null) {
          rowValid = false;
          if (showErrors) {
            var tr = document.querySelector('tr[data-row-uid="' + r.uid + '"]');
            var durumCell = tr && tr.querySelector('.col-durum');
            if (durumCell) {
              var existing = durumCell.querySelector('.row-err-hint');
              if (!existing) {
                var hint = document.createElement('div');
                hint.className = 'row-err-hint';
                hint.style.cssText = 'color:#ef4444;font-size:10.5px;margin-top:2px';
                hint.textContent = 'Konum doğrulanmalı';
                durumCell.appendChild(hint);
              }
            }
          }
        }

        if (!rowValid) valid = false;
      });

      return valid;
    }

    /* ── Submit ── */
    function _submit() {
      if (_submitInFlight) return;
      var arac = (_qs('atpMultiArac') || {}).value || '';
      var sofor = ((_qs('atpMultiSofor') || {}).value || '').trim();
      var tarih = (_qs('atpMultiTarih') || {}).value || '';

      /* Header validation */
      var headerErrors = [];
      if (!arac) headerErrors.push('Araç seçmelisiniz.');
      if (!tarih) headerErrors.push('Tarih seçiniz.');
      if (headerErrors.length) { toast(headerErrors.join(' ')); return; }

      /* Row validation — strict, with visual feedback */
      if (!_validateAllRows(true)) {
        /* Count problems for user */
        var badFirma = _rows.filter(function (r) { return _isBlank((r.firma || '').trim()) || (r.firma || '').trim().length < 2; }).length;
        var badIs = _rows.filter(function (r) { return _isBlank((r.yapilacakIs || '').trim()) || (r.yapilacakIs || '').trim().length < 2; }).length;
        var badKonum = _rows.filter(function (r) { return r.status !== 'ok' || r.lat == null; }).length;
        var msgs = [];
        if (badFirma) msgs.push(badFirma + ' satırda firma eksik');
        if (badIs) msgs.push(badIs + ' satırda yapılacak iş eksik');
        if (badKonum) msgs.push(badKonum + ' satırda konum doğrulanmamış');
        /* Show persistent error in summary area */
        var summaryEl = _qs('atpMultiSummary');
        if (summaryEl) {
          var prev = summaryEl.querySelector('.multi-submit-err');
          if (!prev) {
            prev = document.createElement('div');
            prev.className = 'multi-submit-err';
            prev.style.cssText = 'color:#ef4444;font-weight:600;margin-top:4px';
            summaryEl.appendChild(prev);
          }
          prev.textContent = 'Eksik satırlar var, kaydedilmedi: ' + msgs.join(', ');
        }
        toast('Eksik veya hatalı satırlar var — kaydedilmedi. ' + msgs.join(', '));
        return;
      }

      /* Clear any previous error markers */
      _clearRowErrors();
      var summaryEl2 = _qs('atpMultiSummary');
      if (summaryEl2) {
        var errMsg = summaryEl2.querySelector('.multi-submit-err');
        if (errMsg) errMsg.remove();
      }

      /* Build payload — only include validated rows; double-check each field */
      var payloadRows = _rows.map(function (r) {
        var firmaFinal = (r.firma || '').trim();
        var isFinal = (r.yapilacakIs || '').trim();
        return {
          plan_tarihi: tarih, tarih: tarih,
          arac_external_id: arac,
          sofor_adi: sofor || null,
          planlanan_saat: null,
          firma: firmaFinal,
          yapilacak_is: isFinal,
          is: isFinal,
          oncelik: r.oncelik || 'NORMAL',
          location_master_id: r.konumId || null,
          latitude: r.lat,
          longitude: r.lng,
          lat: r.lat,
          lng: r.lng,
          adres: (r.adres || '').trim() || null,
          maps_url: r.mapsUrl || '',
          is_new_location: !r.konumId,
          konum_adi: r.konumAdi || null,
          client_submit_id: 'multi_' + r.uid + '_' + Date.now(),
          save_to_master: !r.konumId,
        };
      });

      _submitInFlight = true;
      var submitBtns = [_qs('atpMultiBtnSubmit'), _qs('atpMultiBtnSubmitTop')];
      submitBtns.forEach(function (b) { if (b) b.disabled = true; });

      fetch('/planlama/arac-takip/api/plana-is-ekle-batch', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rows: payloadRows, plan_tarihi: tarih, arac_external_id: arac }),
      }).then(function (r) { return r.json(); }).then(function (j) {
        _submitInFlight = false;
        submitBtns.forEach(function (b) { if (b) b.disabled = false; });
        if (j.ok) {
          toast('✓ ' + j.ok_count + '/' + j.total + ' iş plana eklendi.');
          _closeModal('submit_ok');
          loadOps();
        } else {
          var errs = (j.results || []).filter(function (r) { return !r.ok; });
          var msg = errs.map(function (r) { return 'Satır ' + (r.row + 1) + ': ' + (r.error || ''); }).join(' | ');
          toast('Bazı satırlar eklenemedi: ' + (msg || j.error || ''));
          (j.results || []).forEach(function (res) {
            if (!res.ok) {
              var target = _rows[res.row];
              if (target) { target.status = 'err'; _patchRowDom(target); }
            }
          });
        }
      }).catch(function () {
        _submitInFlight = false;
        submitBtns.forEach(function (b) { if (b) b.disabled = false; });
        toast('Sunucu hatası. Tekrar deneyin.');
      });
    }

    /* ── Open / close modal ── */
    function _openModal(opts) {
      opts = opts || {};
      var lockVehicle = !!opts.lockVehicle;
      var prefillVid = opts.vehicleExtId ? String(opts.vehicleExtId) : '';
      var backdrop = _qs('atpMultiBackdrop');
      var modal = _qs('atpMultiModal');
      if (!backdrop || !modal) return;
      _multiModalEl = modal;
      _wireModalCloseGuards();

      var tarihEl = _qs('atpMultiTarih');
      if (tarihEl) tarihEl.value = planDate || new Date().toISOString().slice(0, 10);

      _aracOpts();
      var aracEl = _qs('atpMultiArac');
      if (aracEl) {
        aracEl.disabled = lockVehicle;
        var targetVid = prefillVid || (lockVehicle ? String(_activeVehicleExtId || '') : '');
        if (targetVid) {
          aracEl.value = targetVid;
          if (!aracEl.value) {
            var _vList = (lastOpsData && lastOpsData.vehicles) ? lastOpsData.vehicles : lastVehicles;
            for (var _vi = 0; _vi < _vList.length; _vi++) {
              var _veh = _vList[_vi];
              if (String(_veh.id || '') === targetVid ||
                  String(_veh.arac_id || '') === targetVid ||
                  String(_veh.arac_external_id || '') === targetVid) {
                aracEl.value = String(_veh.arac_external_id || _veh.id || '');
                break;
              }
            }
          }
        } else if (!lockVehicle) {
          aracEl.value = '';
        }
      }
      if (aracEl && _qs('atpMultiSofor')) {
        var opt = aracEl.options[aracEl.selectedIndex];
        _qs('atpMultiSofor').value = (opt && opt.getAttribute('data-driver')) || '';
      }

      _rows = [];
      _addRow();

      backdrop.classList.add('open');
      modal.setAttribute('aria-hidden', 'false');
      document.body.style.overflow = 'hidden';
      setTimeout(function () { _initMMap(); }, 100);
    }

    function _closeModal(reason) {
      if (!_CLOSE_OK[reason]) return;
      var backdrop = _qs('atpMultiBackdrop');
      var modal = _qs('atpMultiModal');
      if (backdrop) backdrop.classList.remove('open');
      if (modal) modal.setAttribute('aria-hidden', 'true');
      document.body.style.overflow = '';
      _closeFirmaDD();
      _submitInFlight = false;
    }

    /* ── Araç change → prefill driver ── */
    var aracEl2 = _qs('atpMultiArac');
    if (aracEl2) aracEl2.addEventListener('change', function () {
      var opt = aracEl2.options[aracEl2.selectedIndex];
      var soforEl = _qs('atpMultiSofor');
      if (soforEl && opt) soforEl.value = opt.getAttribute('data-driver') || '';
    });

    /* ── Event wiring ── */
    var btnClose = _qs('atpMultiClose');
    if (btnClose) btnClose.addEventListener('click', function () { _closeModal('x'); });

    var btnCancel = _qs('atpMultiBtnCancel');
    if (btnCancel) btnCancel.addEventListener('click', function () { _closeModal('cancel'); });

    var btnSatirEkle = _qs('atpMultiBtnSatirEkle');
    if (btnSatirEkle) btnSatirEkle.addEventListener('click', _addRow);

    var btnKonumKontrol = _qs('atpMultiBtnKonumKontrol');
    if (btnKonumKontrol) btnKonumKontrol.addEventListener('click', _bulkKonumKontrol);

    var btnSubmitTop = _qs('atpMultiBtnSubmitTop');
    if (btnSubmitTop) btnSubmitTop.addEventListener('click', _submit);

    var btnSubmit = _qs('atpMultiBtnSubmit');
    if (btnSubmit) btnSubmit.addEventListener('click', _submit);

    /* No backdrop/outside-click close — X and İptal only (submit_ok on success) */

    /* Dropdown close — separate from modal close */
    document.addEventListener('mousedown', function (e) {
      var dd = _getFirmaDD();
      if (!dd || dd.style.display === 'none') return;
      /* Keep open if click is inside dropdown or inside modal */
      if (dd.contains(e.target)) return;
      if (_firmaDDInp && _firmaDDInp.contains(e.target)) return;
      if (_insideModal(e.target)) return; /* BUG1 FIX: clicks inside modal don't close DD */
      _closeFirmaDD();
    });

    /* Expose opener — accepts optional {lockVehicle, vehicleExtId} */
    window.atpMultiOpen = function (opts) { _openModal(opts); };

  }());

  var _dailyMultiEntryBound = false;

  function _openDailyMultiModal(opts) {
    if (typeof window.atpMultiOpen !== 'function') {
      console.error('[ATP] atpMultiOpen unavailable — multi modal controller failed to initialize');
      toast('Çoklu plan ekranı yüklenemedi. Sayfayı yenileyin.');
      return false;
    }
    window.atpMultiOpen(opts || { lockVehicle: false });
    return true;
  }

  function _initDailyMultiEntryPoints() {
    if (_dailyMultiEntryBound) return;
    _dailyMultiEntryBound = true;

    var btnPlana = qs('atpBtnPlanaIsEkle');
    var btnPlanaPrs = qs('atpBtnPlanaIsEklePrs');
    var btnPlanaEmpty = qs('atpBtnPlanaIsEkleEmpty');
    var btnPlanOlusturEmpty = qs('atpBtnPlanOlusturEmpty');
    var btnQuickPlan = qs('atpBtnQuickPlan');
    var unplannedList = qs('atpUnplannedList');

    if (btnPlana) {
      btnPlana.addEventListener('click', function (e) {
        e.stopPropagation();
        _openDailyMultiModal({ lockVehicle: false });
      });
    }
    if (btnPlanaEmpty) {
      btnPlanaEmpty.addEventListener('click', function (e) {
        e.stopPropagation();
        _openDailyMultiModal({ lockVehicle: false });
      });
    }
    if (btnPlanOlusturEmpty) {
      btnPlanOlusturEmpty.addEventListener('click', function (e) {
        e.stopPropagation();
        _openDailyMultiModal({ lockVehicle: false });
      });
    }
    if (btnPlanaPrs) {
      btnPlanaPrs.addEventListener('click', function (e) {
        e.stopPropagation();
        _openDailyMultiModal({ lockVehicle: true, vehicleExtId: _activeVehicleExtId });
      });
    }
    if (btnQuickPlan) {
      btnQuickPlan.addEventListener('click', function (e) {
        e.stopPropagation();
        var quickSel = qs('atpQuickArac');
        var vid = quickSel && quickSel.value ? String(quickSel.value) : '';
        if (!vid) {
          toast('Hızlı planlama için önce araç seçin.');
          return;
        }
        _openDailyMultiModal({ lockVehicle: true, vehicleExtId: vid });
      });
    }
    if (unplannedList) {
      unplannedList.addEventListener('click', function (e) {
        var btn = e.target && e.target.closest ? e.target.closest('.unp-btn') : null;
        if (!btn) return;
        e.preventDefault();
        e.stopPropagation();
        var vid = btn.getAttribute('data-vid') || '';
        if (!vid) {
          toast('Araç kimliği bulunamadı.');
          return;
        }
        _openDailyMultiModal({ lockVehicle: true, vehicleExtId: vid });
      });
    }
  }

  _initDailyMultiEntryPoints();

  /* ─── Timeline Panel: Çıkış Saati sonrası durak zinciri ─── */
  function buildDurationLabelLines(tl) {
    if (!tl) return [];
    if (tl.duration_labels && tl.duration_labels.lines && tl.duration_labels.lines.length) {
      return tl.duration_labels.lines.slice();
    }
    function ceilMin(sec) {
      if (sec == null || sec === '') return null;
      return Math.ceil(Math.max(0, Number(sec)) / 60);
    }
    var outbound = ceilMin(tl.outbound_travel_seconds);
    var ret = ceilMin(tl.return_travel_seconds != null ? tl.return_travel_seconds : tl.return_seconds);
    var totalDrive = ceilMin(tl.total_travel_seconds);
    var service = tl.total_service_minutes != null
      ? tl.total_service_minutes
      : ceilMin(tl.total_service_seconds);
    var totalPlan = (tl.total_travel_seconds != null && tl.total_service_seconds != null)
      ? ceilMin(Number(tl.total_travel_seconds) + Number(tl.total_service_seconds))
      : tl.estimated_total_minutes;
    var lines = [];
    if (outbound != null) lines.push('Duraklara kadar sürüş: yaklaşık ' + outbound + ' dk');
    if (ret != null) lines.push('Fabrikaya dönüş: yaklaşık ' + ret + ' dk');
    if (totalDrive != null) lines.push('Toplam sürüş: ' + totalDrive + ' dk');
    if (service != null) lines.push('İşlem: ' + service + ' dk');
    if (totalPlan != null) lines.push('Toplam plan: ' + totalPlan + ' dk');
    return lines;
  }

  function renderTimeline(tl) {
    var summaryEl  = document.getElementById('atpTimelineSummary');
    var returnEl   = document.getElementById('atpTimelineReturn');
    var totalsEl   = document.getElementById('atpTimelineTotals');
    var listEl     = document.getElementById('atpTimelineList');
    if (!summaryEl) return;

    /* Always hide the stop-by-stop duplicate list — ETAs already in jobs table */
    if (listEl) listEl.style.display = 'none';

    if (!tl || tl.status === 'CIKIS_SAATI_EKSIK' || !tl.stops || !tl.stops.length) {
      summaryEl.style.display = 'none';
      return;
    }

    /* Build compact one-line return summary */
    var retTime = tl.estimated_return_time || null;
    if (returnEl) {
      returnEl.innerHTML = retTime
        ? '<span class="atp-tl-ret-label">Tahmini dönüş:</span> <strong class="atp-tl-ret-val">' + fmtVal(retTime) + '</strong>'
        : '<span class="atp-tl-ret-label">Dönüş hesaplanamadı</span>';
    }

    /* Build compact totals: show tooltip trigger with full detail lines */
    if (totalsEl) {
      var labelLines = buildDurationLabelLines(tl);
      if (labelLines.length) {
        /* Compact: "191 dk sürüş · 30 dk işlem · 221 dk toplam" */
        var totalDrive = tl.total_travel_minutes != null ? tl.total_travel_minutes : null;
        var totalSvc   = tl.total_service_minutes != null ? tl.total_service_minutes : null;
        var totalPlan  = tl.total_plan_minutes != null ? tl.total_plan_minutes : null;
        var parts = [];
        if (totalDrive != null) parts.push(totalDrive + ' dk sürüş');
        if (totalSvc   != null) parts.push(totalSvc   + ' dk işlem');
        if (totalPlan  != null) parts.push(totalPlan  + ' dk toplam');
        var compact = parts.join(' · ');
        var tip = labelLines.join('\n');
        totalsEl.innerHTML = compact
          ? '<span class="atp-tl-totals-compact" title="' + fmtVal(tip) + '">' + compact + ' <span class="atp-tl-info">ⓘ</span></span>'
          : '';
      } else {
        totalsEl.textContent = '';
      }
    }
    summaryEl.style.display = '';
  }

  /* ─── İstenen Varış Saati: popup handler (bu fazda gizli, altyapı korunur) ─── */
  (function initDesiredTime() {
    var backdrop = document.getElementById('atpDesiredTimeBackdrop');
    var modal    = document.getElementById('atpDesiredTimeModal');
    var infoEl   = document.getElementById('atpDesiredTimeInfo');
    var inp      = document.getElementById('atpDesiredTimeInput');
    var freeChk  = document.getElementById('atpDesiredTimeFree');
    var msgEl    = document.getElementById('atpDesiredTimeMsg');
    var saveBtn  = document.getElementById('atpDesiredTimeSave');
    var cancelBtn= document.getElementById('atpDesiredTimeClose');
    var cancelBtn2=document.getElementById('atpDesiredTimeCancel');
    if (!backdrop || !modal || !inp || !saveBtn) return;

    var _state = { planItemId: null, vid: null, company: '', date: '' };

    function _open(btn) {
      _state.planItemId = btn.dataset.planItemId || '';
      _state.vid        = btn.dataset.vid || '';
      _state.company    = btn.dataset.company || '—';
      var prev          = btn.dataset.istened || '';
      var isFree        = btn.dataset.free === '1';
      var kaynak        = btn.dataset.kaynak || 'YOK';
      _state.date       = window.ATP_PLAN_DATE || '';

      if (infoEl) {
        var src = kaynak === 'SISTEM' ? ' (Kaynak sistem)' : (kaynak === 'MANUEL' ? ' (Manuel)' : '');
        infoEl.textContent = _state.company + (prev ? ' — Mevcut: ' + prev + src : ' — Saat girilmemiş');
      }
      inp.value    = prev || '';
      freeChk.checked = isFree;
      inp.disabled = isFree;
      msgEl.textContent = '';

      backdrop.setAttribute('aria-hidden', 'false');
      modal.setAttribute('aria-hidden', 'false');
      backdrop.style.display = '';
      if (!isFree) { try { inp.focus(); } catch(e) {} }
    }

    function _close() {
      backdrop.setAttribute('aria-hidden', 'true');
      modal.setAttribute('aria-hidden', 'true');
      backdrop.style.display = 'none';
      _state = { planItemId: null, vid: null, company: '', date: '' };
    }

    freeChk.addEventListener('change', function() {
      inp.disabled = this.checked;
      if (this.checked) { inp.value = ''; msgEl.textContent = ''; }
    });

    function _save() {
      var timeFree = freeChk.checked;
      var raw = (inp.value || '').trim();
      if (!timeFree && !raw) {
        msgEl.textContent = 'Saat girin veya "Saat serbest" seçin.';
        return;
      }
      if (!_state.planItemId || !_state.vid || !_state.date) {
        msgEl.textContent = 'İç hata: plan bilgisi eksik.';
        return;
      }
      saveBtn.disabled = true;
      msgEl.textContent = 'Kaydediliyor…';
      var payload = {
        date: _state.date,
        vehicle_id: _state.vid,
        plan_item_id: parseInt(_state.planItemId, 10),
        desired_time: timeFree ? null : raw,
        time_free: timeFree
      };
      fetch('/planlama/arac-takip/api/plan-job/desired-time', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        credentials: 'same-origin'
      })
      .then(function(r) { return r.json().then(function(d){ return { ok: r.ok, data: d }; }); })
      .then(function(res) {
        saveBtn.disabled = false;
        if (!res.ok || !res.data.ok) {
          msgEl.textContent = (res.data && res.data.error) || 'Kayıt hatası.';
          return;
        }
        _close();
        /* Refresh: update dashboard + jobs if callback available */
        if (typeof refreshDashboardPartial === 'function') {
          var tasks = res.data.tasks || [];
          refreshDashboardPartial({ daily_tasks: tasks, dashboard: res.data.dashboard });
        } else if (typeof loadGunlukData === 'function') {
          loadGunlukData();
        }
      })
      .catch(function(err) {
        saveBtn.disabled = false;
        msgEl.textContent = 'Bağlantı hatası: ' + err.message;
      });
    }

    saveBtn.addEventListener('click', _save);
    if (cancelBtn)  cancelBtn.addEventListener('click',  _close);
    if (cancelBtn2) cancelBtn2.addEventListener('click', _close);
    backdrop.addEventListener('click', function(e) { if (e.target === backdrop) _close(); });

    /* Delegate: open popup on .atp-desired-time-btn click */
    document.addEventListener('click', function(e) {
      var btn = e.target.closest && e.target.closest('.atp-desired-time-btn');
      if (btn) { e.preventDefault(); _open(btn); }
    });
  }());

}());
