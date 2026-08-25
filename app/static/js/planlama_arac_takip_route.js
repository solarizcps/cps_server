(function (global) {

  'use strict';



  var lastRoute = null;

  var _routeFetchToken = 0;

  var _routeAbort = null;

  var _previewMode = 'current';

  var _applyInFlight = false;

  var _hooks = {};



  function el(id) { return document.getElementById(id); }



  function fmtKm(v) {

    if (v == null || v === '' || v === '—') return '—';

    return v + ' km';

  }



  function fmtGainKm(v) {

    if (v == null || v === '—') return '—';

    return v + ' km';

  }



  function setText(node, text) {

    if (node) node.textContent = text;

  }



  function taskIdsKey(ids) {

    return (ids || []).map(String).join(',');

  }



  function hasOrderDiff(route) {

    if (!route) return false;

    var cur = route.current || {};

    var sug = route.suggested || {};

    var curFull = sug.full_task_ids && sug.full_task_ids.length
      ? (cur.full_task_ids || cur.task_ids)
      : cur.task_ids;

    var sugFull = sug.full_task_ids || sug.apply_task_ids || sug.task_ids;

    if (!sugFull || !sugFull.length) return false;

    if (!curFull || !curFull.length) return false;

    return taskIdsKey(sugFull) !== taskIdsKey(curFull);

  }



  function geometrySame(a, b) {

    if (!a || !b || !a.length || !b.length) return false;

    if (a.length !== b.length) return false;

    for (var i = 0; i < a.length; i++) {

      if (Number(a[i][0]) !== Number(b[i][0]) || Number(a[i][1]) !== Number(b[i][1])) return false;

    }

    return true;

  }



  function isSameRoute(route) {

    if (!route) return true;

    var sug = route.suggested || {};

    if (sug.apply_disabled_reason === 'NO_ELIGIBLE_REORDER' || sug.apply_disabled_reason === 'ALREADY_OPTIMAL') {

      return true;

    }

    if (sug.apply_enabled === false) return true;

    var gain = route.gain || {};

    var cur = route.current || {};

    var gainKm = gain.km;

    var zeroGain = gainKm === 0 || gainKm === '0' || gainKm === 0.0;

    if (!hasOrderDiff(route) && zeroGain) return true;

    if (zeroGain && geometrySame(cur.geometry, sug.geometry)) return true;

    return false;

  }



  function getApplyTaskIds(route) {

    if (!route || !route.suggested) return [];

    return route.suggested.apply_task_ids || route.suggested.full_task_ids || route.suggested.task_ids || [];

  }



  function validTaskIds(ids) {

    if (!ids || !ids.length) return false;

    for (var i = 0; i < ids.length; i++) {

      if (!ids[i] || !String(ids[i]).trim()) return false;

    }

    return true;

  }



  function canApplyRoute(route, vehicleId) {

    if (_applyInFlight || !vehicleId || !route) return false;

    var sug = route.suggested || {};

    if (sug.apply_enabled === false) return false;

    if (sug.apply_disabled_reason) return false;

    if (!hasOrderDiff(route)) return false;

    return validTaskIds(getApplyTaskIds(route));

  }



  function canPreviewRoute(route) {

    if (!route) return false;

    var sug = route.suggested || {};

    return !!(sug.geometry && sug.geometry.length >= 2);

  }



  var ALREADY_OPTIMAL_MSG = 'Mevcut sıra rota motoruna göre zaten uygun.';



  function alreadyOptimalMessage(route) {

    if (!route || route.status !== 'OK' || !isSameRoute(route)) return '';

    return ALREADY_OPTIMAL_MSG;

  }



  function updateFuelDisplay(route, fuelSaving) {

    var fuelEl = el('atpRouteFuelL');

    var fuelTryEl = el('atpRouteFuelTry');

    var fuelCard = el('atpRouteFuelCard');

    var tip = 'Araç tüketim bilgisi tanımlı değil';

    var fs = fuelSaving || (route && route.fuel_saving) || null;

    var liters = fs && fs.liters;

    var tryAmt = fs && (fs.try_amount != null ? fs.try_amount : fs.try);

    var hasFuel = liters != null && liters !== '—' && liters !== '' &&

      tryAmt != null && tryAmt !== '—' && tryAmt !== '';

    if (hasFuel) {

      if (fuelEl) fuelEl.textContent = liters + (String(liters).indexOf('L') >= 0 ? '' : ' L');

      if (fuelTryEl) {

        var tryStr = String(tryAmt);

        fuelTryEl.textContent = tryStr.indexOf('₺') >= 0 ? tryStr : '≈ ₺' + tryAmt;

      }

      if (fuelCard) fuelCard.removeAttribute('title');

    } else {

      if (fuelEl) fuelEl.textContent = '—';

      if (fuelTryEl) fuelTryEl.textContent = '—';

      if (fuelCard) fuelCard.title = tip;

    }

  }



  function _noEligibleReorderReason(route) {

    if (!route) return null;

    var sug = (route.suggested || {});

    if (sug.apply_disabled_reason !== 'NO_ELIGIBLE_REORDER') return null;

    var c = route.constraints || {};

    var lockedCount = (c.locked_task_ids || []).length;

    var eligibleCount = (c.eligible_task_ids || []).length;

    if (eligibleCount === 1) {

      return 'Rota önerisi oluşturulamadı: ' + lockedCount + ' iş tamamlanmış, başlamış veya kilitli. Yalnız ' + eligibleCount + ' iş yeniden sıralanabilir; en az 2 uygun iş gerekir.';

    }

    if (eligibleCount === 0) {

      return 'Rota önerisi oluşturulamadı: tüm ' + lockedCount + ' iş kilitli. Yeniden sıralanabilir iş yok.';

    }

    return 'Kilitli işler nedeniyle yeniden sıralama yapılamaz.';

  }



  function updateRouteButtons(route) {

    var previewBtn = el('atpBtnPreviewSuggestedRoute');

    var applyBtn = el('atpBtnApplySuggestedOrder');

    var vehicleId = typeof _hooks.getVehicleId === 'function' ? _hooks.getVehicleId() : null;

    var same = isSameRoute(route);

    var noEligible = !!_noEligibleReorderReason(route);

    var previewOk = canPreviewRoute(route) && !noEligible;

    if (previewBtn) {

      previewBtn.title = '';

      if (!previewOk) {

        previewBtn.disabled = true;

        previewBtn.textContent = 'Önerilen Rotayı Göster';

      } else if (same) {

        previewBtn.disabled = false;

        previewBtn.textContent = 'Öneri = Mevcut';

        previewBtn.title = 'Mevcut rota zaten optimal; haritada göster';

      } else if (_previewMode === 'suggested') {

        previewBtn.disabled = false;

        previewBtn.textContent = 'Karşılaştırma Görünümü';

      } else if (_previewMode === 'compare') {

        previewBtn.disabled = false;

        previewBtn.textContent = 'Mevcut Rotaya Dön';

      } else {

        previewBtn.disabled = false;

        previewBtn.textContent = 'Önerilen Rotayı Göster';

      }

    }

    if (applyBtn) {

      var canApply = canApplyRoute(route, vehicleId) && !same;

      applyBtn.disabled = !canApply;

      applyBtn.textContent = _applyInFlight ? 'Uygulanıyor…' : '✔ Önerilen Sırayı Uygula';

      if (same) {

        applyBtn.title = 'Mevcut sıra zaten uygun — uygulama gerekmiyor';

      } else if (!canApply) {

        applyBtn.title = 'Öneri uygulanamıyor';

      } else {

        applyBtn.title = '';

      }

    }

    if (global.AtpRouteExplainer && global.AtpRouteExplainer.updateExplainerButton) {

      global.AtpRouteExplainer.updateExplainerButton(route);

    }

    var bannerEl = el('atpRouteConstraintBanner');

    if (bannerEl) {

      var bannerReason = _noEligibleReorderReason(route);

      if (bannerReason) {

        bannerEl.textContent = '\uD83D\uDD12 Rota değiştirilemez: ' + bannerReason.replace('Rota önerisi oluşturulamadı: ', '');

        bannerEl.style.display = '';

      } else {

        bannerEl.textContent = '';

        bannerEl.style.display = 'none';

      }

    }

  }



  function updateRouteCards(route, opts) {

    opts = opts || {};

    var ra = route || {};

    var cur = ra.current || {};

    var sug = ra.suggested || {};

    var gain = ra.gain || {};

    setText(el('atpRouteCurrentKm'), fmtKm(cur.km));

    setText(el('atpRouteCurrentDur'), cur.duration_label || '—');

    setText(el('atpRouteSugKm'), fmtKm(sug.km));

    setText(el('atpRouteSugDur'), sug.duration_label || '—');

    setText(el('atpRouteGainKm'), fmtGainKm(gain.km != null && gain.km !== '—' ? gain.km : '—'));

    var gainDur = gain.duration_label || '—';

    var gainPct = gain.pct != null && gain.pct !== '—' ? '%' + gain.pct + ' daha kısa' : '—';

    if (gain.pct === 0 || gain.pct === '0' || gain.pct === 0.0) gainPct = '%0 daha kısa';

    setText(el('atpRouteGainDetail'), gainDur + (gainPct !== '—' ? ' · ' + gainPct : ''));

    updateFuelDisplay(ra, opts.fuelSaving);

    setText(el('atpRouteCurrentOrder'), cur.order_labels || '—');

    setText(el('atpRouteSuggestedOrder'), sug.order_labels || '—');

    var msgEl = el('atpRouteStatusMsg');

    if (msgEl) {

      msgEl.classList.remove('already-optimal');

      var msg = ra.message || '';

      var noEligReason = _noEligibleReorderReason(ra);

      if (ra.status === 'UNCONFIGURED') {

        msg = ra.message || 'Rota servisi yapılandırılmamış.';

      } else if (ra.status === 'ERROR' || ra.status === 'TIMEOUT' || ra.status === 'AUTH') {

        msg = ra.message || 'Rota hesaplanamadı.';

      } else if (noEligReason) {

        msg = noEligReason;

      } else if (typeof gain.km === 'number' && gain.km < 0) {

        msg = (msg ? msg + ' · ' : '') + 'API önerisi mevcut rotadan daha uzun (' + gain.km + ' km).';

      } else if (isSameRoute(ra) && ra.status === 'OK') {

        msg = ALREADY_OPTIMAL_MSG;

        if (msgEl) msgEl.classList.add('already-optimal');

      }

      var warnList = ra.warnings || [];

      if (warnList.length) {

        var warnText = warnList.map(function (w) { return w.message || w.code; }).join(' · ');

        msg = (msg ? msg + ' · ' : '') + warnText;

      }

      msgEl.textContent = msg;

      msgEl.style.display = msg ? '' : 'none';

    }

    var legsEl = el('atpRouteLegs');

    if (legsEl) {

      var legs = ra.leg_details || [];

      if (!legs.length) {

        legsEl.innerHTML = '';

      } else {

        legsEl.innerHTML = legs.map(function (lg) {

          return '<div class="atp-route-leg">' +

            '<strong>' + (lg.order_no || '?') + ' ' + (lg.company_name || '') + '</strong>' +

            '<span>' + (lg.distance_km || '—') + ' · ' + (lg.duration_label || '—') + '</span></div>';

        }).join('');

      }

    }

    updateRouteButtons(ra);

  }



  function updateDailyTotalsFooter(route, dashboard) {

    var foot = el('atpFootTotal');

    if (!foot) return;

    var cur = route && route.current;

    var totals = dashboard && dashboard.daily_totals;

    var km = (cur && cur.km != null && cur.km !== '—') ? cur.km : (totals && totals.distance_km);

    var dur = (cur && cur.duration_label) ? cur.duration_label : (totals && totals.duration_label);

    if (km == null || km === '' || km === '—') km = '—';

    if (!dur) dur = '—';

    foot.textContent = 'Toplam Mesafe: ' + km + ' km · Tahmini Süre: ' + dur;

  }



  function updateTaskDistances(route) {

    var legs = (route && route.leg_details) || [];

    if (!legs.length) return;

    var byTask = {};

    legs.forEach(function (lg) {

      if (lg.task_id) byTask[String(lg.task_id)] = lg.distance_km;

    });

    document.querySelectorAll('#atpTaskBody tr[data-task-id]').forEach(function (tr) {

      var tid = tr.getAttribute('data-task-id');

      var km = byTask[tid];

      if (km == null) return;

      var cells = tr.querySelectorAll('td');

      if (cells.length >= 6) cells[5].textContent = (km === '—' ? '—' : km + ' km');

    });

  }



  function resetPreviewMode() {

    _previewMode = 'current';

  }



  function renderPreviewMode() {

    if (!global.AtpPlanMap || !lastRoute) return;

    var cur = lastRoute.current || {};

    var sug = lastRoute.suggested || {};

    if (global.AtpPlanMap.clearRouteLayers) global.AtpPlanMap.clearRouteLayers();

    if (_previewMode === 'current') {

      if (cur.geometry && cur.geometry.length) global.AtpPlanMap.setCurrentRouteGeometry(cur.geometry);

    } else if (_previewMode === 'suggested') {

      if (sug.geometry && sug.geometry.length) global.AtpPlanMap.setSuggestedRouteGeometry(sug.geometry);

    } else if (_previewMode === 'compare') {

      if (cur.geometry && cur.geometry.length) global.AtpPlanMap.setCurrentRouteGeometry(cur.geometry);

      if (sug.geometry && sug.geometry.length) global.AtpPlanMap.setSuggestedRouteGeometry(sug.geometry);

    }

  }



  function applyRouteGeometry(route) {

    lastRoute = route;

    resetPreviewMode();

    renderPreviewMode();

    if (global.AtpRouteExplainer && global.AtpRouteExplainer.updateExplainerButton) {

      global.AtpRouteExplainer.updateExplainerButton(route);

    }

  }



  function clearRouteDisplay() {

    resetPreviewMode();

    updateRouteCards({});

    setText(el('atpRouteFuelL'), '—');

    setText(el('atpRouteFuelTry'), '—');

    var fuelCard = el('atpRouteFuelCard');

    if (fuelCard) fuelCard.title = 'Araç tüketim bilgisi tanımlı değil';

    var msgEl = el('atpRouteStatusMsg');

    if (msgEl) {

      msgEl.textContent = '';

      msgEl.style.display = 'none';

    }

    var previewBtn = el('atpBtnPreviewSuggestedRoute');

    var applyBtn = el('atpBtnApplySuggestedOrder');

    if (previewBtn) {

      previewBtn.disabled = true;

      previewBtn.textContent = 'Önerilen Rotayı Göster';

    }

    if (applyBtn) {

      applyBtn.disabled = true;

      applyBtn.textContent = '✔ Önerilen Sırayı Uygula';

    }

    if (global.AtpPlanMap && global.AtpPlanMap.clearRouteLayers) {

      global.AtpPlanMap.clearRouteLayers();

    }

    lastRoute = null;

  }



  function showRouteEmptyPlan(message) {

    resetPreviewMode();

    updateRouteCards({});

    setText(el('atpRouteCurrentKm'), '—');

    setText(el('atpRouteCurrentDur'), '—');

    setText(el('atpRouteSugKm'), '—');

    setText(el('atpRouteSugDur'), '—');

    setText(el('atpRouteGainKm'), '—');

    setText(el('atpRouteGainDetail'), '—');

    setText(el('atpRouteFuelL'), '—');

    setText(el('atpRouteFuelTry'), '—');

    var fuelCard = el('atpRouteFuelCard');

    if (fuelCard) fuelCard.title = 'Araç tüketim bilgisi tanımlı değil';

    var previewBtn = el('atpBtnPreviewSuggestedRoute');

    var applyBtn = el('atpBtnApplySuggestedOrder');

    if (previewBtn) {

      previewBtn.disabled = true;

      previewBtn.textContent = 'Önerilen Rotayı Göster';

    }

    if (applyBtn) {

      applyBtn.disabled = true;

      applyBtn.textContent = '✔ Önerilen Sırayı Uygula';

    }

    if (global.AtpPlanMap && global.AtpPlanMap.clearRouteLayers) {

      global.AtpPlanMap.clearRouteLayers();

    }

    lastRoute = null;

    var msgEl = el('atpRouteStatusMsg');

    if (msgEl) {

      msgEl.textContent = message || 'Aktif iş yok — plan boş.';

      msgEl.style.display = '';

    }

  }



  function showRouteLoading() {

    resetPreviewMode();

    setText(el('atpRouteCurrentKm'), '…');

    setText(el('atpRouteCurrentDur'), '…');

    setText(el('atpRouteSugKm'), '…');

    setText(el('atpRouteSugDur'), '…');

    setText(el('atpRouteGainKm'), '…');

    setText(el('atpRouteGainDetail'), '…');

    setText(el('atpRouteFuelL'), '…');

    setText(el('atpRouteFuelTry'), '…');

    var msgEl = el('atpRouteStatusMsg');

    if (msgEl) {

      msgEl.textContent = '';

      msgEl.style.display = 'none';

    }

    var previewBtn = el('atpBtnPreviewSuggestedRoute');

    var applyBtn = el('atpBtnApplySuggestedOrder');

    if (previewBtn) {

      previewBtn.disabled = true;

      previewBtn.textContent = 'Önerilen Rotayı Göster';

    }

    if (applyBtn) {

      applyBtn.disabled = true;

      applyBtn.textContent = '✔ Önerilen Sırayı Uygula';

    }

    if (global.AtpPlanMap && global.AtpPlanMap.clearRouteLayers) {

      global.AtpPlanMap.clearRouteLayers();

    }

  }



  function fetchPlanRoute(planDate, vehicleId, cb, opts) {

    opts = opts || {};

    var token = ++_routeFetchToken;

    if (_routeAbort) {

      try { _routeAbort.abort(); } catch (e) { /* ignore */ }

    }

    _routeAbort = typeof AbortController !== 'undefined' ? new AbortController() : null;

    var signal = _routeAbort ? _routeAbort.signal : undefined;

    var expectedVid = vehicleId != null ? String(vehicleId) : '';



    var q = '?date=' + encodeURIComponent(planDate);

    if (vehicleId) q += '&vehicle_id=' + encodeURIComponent(vehicleId);

    fetch('/planlama/arac-takip/api/route/plan' + q, { credentials: 'same-origin', signal: signal })

      .then(function (r) { return r.json(); })

      .then(function (j) {

        if (token !== _routeFetchToken) return;

        if (opts.expectedVehicleId != null && String(opts.expectedVehicleId) !== expectedVid) return;

        if (!j.ok) {

          clearRouteDisplay();

          var failMsg = el('atpRouteStatusMsg');

          if (failMsg) {

            failMsg.textContent = 'Rota hesaplanamadı.';

            failMsg.style.display = '';

          }

          if (typeof opts.onComplete === 'function') opts.onComplete(null);

          return;

        }

        var route = j.route || {};

        if (opts.onStale && opts.onStale(expectedVid)) return;

        var fuelSaving = j.dashboard && j.dashboard.route_analysis && j.dashboard.route_analysis.fuel_saving;

        lastRoute = route;

        resetPreviewMode();

        updateRouteCards(route, { fuelSaving: fuelSaving });

        updateDailyTotalsFooter(route, j.dashboard);

        updateTaskDistances(route);

        if (j.dashboard && typeof cb === 'function') cb(j.dashboard, expectedVid);

        if (route.status === 'NO_STOPS' || !(route.current && route.current.geometry && route.current.geometry.length)) {

          if (global.AtpPlanMap && global.AtpPlanMap.clearRouteLayers) {

            global.AtpPlanMap.clearRouteLayers();

          }

        } else {

          applyRouteGeometry(route);

        }

        if (typeof opts.onComplete === 'function') opts.onComplete(route);

      })

      .catch(function (err) {

        if (token !== _routeFetchToken) return;

        if (err && err.name === 'AbortError') return;

        clearRouteDisplay();

        var msgEl = el('atpRouteStatusMsg');

        if (msgEl) {

          msgEl.textContent = 'Rota hesaplanamadı.';

          msgEl.style.display = '';

        }

        if (typeof opts.onComplete === 'function') opts.onComplete(null);

      });

  }



  function notify(msg) {

    if (typeof _hooks.toast === 'function') _hooks.toast(msg);

  }



  function openApplyConfirm(planDate, vehicleId, onConfirm) {

    var modal = el('atpRouteApplyModal');

    if (!modal || !lastRoute) return;

    var cur = lastRoute.current || {};

    var sug = lastRoute.suggested || {};

    var gain = lastRoute.gain || {};

    var plate = typeof _hooks.getVehiclePlate === 'function' ? _hooks.getVehiclePlate() : '—';

    setText(el('atpRouteApplyVehicle'), plate);

    setText(el('atpRouteApplyDate'), planDate || '—');

    setText(el('atpRouteApplyCurrentKm'), fmtKm(cur.km) + (cur.duration_label ? ' · ' + cur.duration_label : ''));

    setText(el('atpRouteApplySuggestedKm'), fmtKm(sug.km) + (sug.duration_label ? ' · ' + sug.duration_label : ''));

    setText(el('atpRouteApplyCurrent'), cur.order_labels || '—');

    setText(el('atpRouteApplyNew'), sug.order_labels || '—');

    var gainParts = [];

    if (gain.km != null && gain.km !== '—') gainParts.push(gain.km + ' km');

    if (gain.duration_label && gain.duration_label !== '—') gainParts.push(gain.duration_label);

    if (gain.pct != null && gain.pct !== '—') gainParts.push('%' + gain.pct + ' daha kısa');

    else if (gain.pct === 0 || gain.pct === '0') gainParts.push('%0 daha kısa');

    setText(el('atpRouteApplyGain'), gainParts.length ? gainParts.join(' · ') : '—');

    var warnEl = el('atpRouteApplyWarnings');

    var routeWarnings = (lastRoute && lastRoute.warnings) || [];

    if (warnEl) {

      if (routeWarnings.length) {

        warnEl.innerHTML = routeWarnings.map(function (w) {

          return '<div class="atp-route-apply-warn">⚠ ' + (w.message || w.code || '') + '</div>';

        }).join('');

        warnEl.style.display = '';

      } else {

        warnEl.innerHTML = '';

        warnEl.style.display = 'none';

      }

    }

    modal.style.display = 'flex';

    var confirmBtn = el('atpRouteApplyConfirm');

    var cancelBtn = el('atpRouteApplyCancel');

    var inner = el('atpRouteApplyInner');

    function close() {

      modal.style.display = 'none';

      document.removeEventListener('keydown', onKey);

      modal.onclick = null;

    }

    function onKey(ev) {

      if (ev.key === 'Escape') close();

    }

    function onOverlayClick(ev) {

      if (ev.target === modal) close();

    }

    document.addEventListener('keydown', onKey);

    modal.onclick = onOverlayClick;

    if (cancelBtn) cancelBtn.onclick = function (ev) { ev.stopPropagation(); close(); };

    if (inner) inner.onclick = function (ev) { ev.stopPropagation(); };

    if (confirmBtn) {

      confirmBtn.disabled = false;

      confirmBtn.textContent = 'Uygula';

      confirmBtn.onclick = function (ev) {

        ev.stopPropagation();

        close();

        if (typeof onConfirm === 'function') onConfirm();

      };

    }

    if (cancelBtn) cancelBtn.focus();

  }



  function postApplyRoute(planDate, vehicleId) {

    if (_applyInFlight || !lastRoute) return;

    var taskIds = getApplyTaskIds(lastRoute);

    if (!validTaskIds(taskIds) || !vehicleId) {

      notify('Önerilen sıra uygulanamadı: geçersiz görev listesi.');

      return;

    }

    var appliedTaskIds = taskIds.map(String);

    _applyInFlight = true;

    updateRouteButtons(lastRoute);

    fetch('/planlama/arac-takip/api/route/apply', {

      method: 'POST',

      credentials: 'same-origin',

      headers: { 'Content-Type': 'application/json' },

      body: JSON.stringify({

        date: planDate,

        vehicle_id: String(vehicleId),

        task_ids: taskIds

      })

    })

      .then(function (r) {

        return r.json().then(function (j) { return { status: r.status, body: j }; });

      })

      .then(function (res) {

        var j = res.body || {};

        if (!j.ok) {

          _applyInFlight = false;

          updateRouteButtons(lastRoute);

          var errMsg = j.message || j.error || ('HTTP ' + res.status);

          if (j.code === 'LOCKED_TASK_MOVE') errMsg = j.message || 'Tamamlanmış veya başlamış işler taşınamaz.';

          notify('Sıra uygulanamadı: ' + errMsg);

          return;

        }

        var reload = _hooks.reloadAfterApply;

        if (typeof reload === 'function') {

          var reloadResult = reload(vehicleId, appliedTaskIds);

          if (reloadResult && typeof reloadResult.then === 'function') {

            reloadResult.then(function (verified) {

              _applyInFlight = false;

              if (lastRoute) updateRouteButtons(lastRoute);

              if (verified) notify('Önerilen sıra uygulandı.');

              else notify('Sıra kaydedildi ancak ekran doğrulanamadı. Lütfen yenileyin.');

            }).catch(function () {

              _applyInFlight = false;

              if (lastRoute) updateRouteButtons(lastRoute);

              notify('Sıra kaydedildi ancak ekran doğrulanamadı. Lütfen yenileyin.');

            });

            return;

          }

        }

        _applyInFlight = false;

        fetchPlanRoute(planDate, vehicleId, _hooks.onDashboard, {

          expectedVehicleId: vehicleId,

          onStale: function (vid) {

            return typeof _hooks.isStaleVehicle === 'function' && _hooks.isStaleVehicle(vid);

          },

          onComplete: function () {

            if (lastRoute) updateRouteButtons(lastRoute);

            notify('Önerilen sıra uygulandı.');

          }

        });

      })

      .catch(function () {

        _applyInFlight = false;

        updateRouteButtons(lastRoute);

        notify('Sıra uygulanamadı: sunucu hatası.');

      });

  }



  function bindRouteUi(planDate, getVehicleId, hooks) {

    _hooks = hooks || {};

    if (typeof getVehicleId === 'function') {

      _hooks.getVehicleId = getVehicleId;

    }



    var previewBtn = el('atpBtnPreviewSuggestedRoute');

    if (previewBtn) {

      previewBtn.addEventListener('click', function () {

        if (!lastRoute || !global.AtpPlanMap) return;

        if (isSameRoute(lastRoute)) {

          notify(ALREADY_OPTIMAL_MSG);

          resetPreviewMode();

          renderPreviewMode();

          if (global.AtpPlanMap && global.AtpPlanMap.focusCurrentRoute) {

            global.AtpPlanMap.focusCurrentRoute();

          }

          return;

        }

        if (!canPreviewRoute(lastRoute)) return;

        if (_previewMode === 'current') _previewMode = 'suggested';

        else if (_previewMode === 'suggested') _previewMode = 'compare';

        else _previewMode = 'current';

        updateRouteButtons(lastRoute);

        renderPreviewMode();

      });

    }



    var applyBtn = el('atpBtnApplySuggestedOrder');

    if (applyBtn) {

      applyBtn.addEventListener('click', function () {

        if (_applyInFlight) return;

        var vid = typeof _hooks.getVehicleId === 'function' ? _hooks.getVehicleId() : null;

        if (!canApplyRoute(lastRoute, vid)) return;

        openApplyConfirm(planDate, vid, function () {

          postApplyRoute(planDate, vid);

        });

      });

    }



    var sortBtn = el('atpBtnSortSuggest');

    if (sortBtn) {

      sortBtn.addEventListener('click', function () {

        var vid = typeof _hooks.getVehicleId === 'function' ? _hooks.getVehicleId() : null;

        fetchPlanRoute(planDate, vid, _hooks.onDashboard);

      });

    }

  }



  global.AtpRoute = {

    fetchPlanRoute: fetchPlanRoute,

    bindRouteUi: bindRouteUi,

    getLastRoute: function () { return lastRoute; },

    updateRouteCards: updateRouteCards,

    clearRouteDisplay: clearRouteDisplay,

    showRouteEmptyPlan: showRouteEmptyPlan,

    showRouteLoading: showRouteLoading,

    hasOrderDiff: hasOrderDiff,

    isSameRoute: isSameRoute,

    alreadyOptimalMessage: alreadyOptimalMessage

  };

})(window);
