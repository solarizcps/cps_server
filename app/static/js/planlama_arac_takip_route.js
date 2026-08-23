(function (global) {
  'use strict';

  var lastRoute = null;

  function el(id) { return document.getElementById(id); }

  function fmtKm(v) {
    if (v == null || v === '' || v === '—') return '—';
    return v + ' km';
  }

  function setText(node, text) {
    if (node) node.textContent = text;
  }

  function updateRouteCards(route) {
    var ra = route || {};
    var cur = ra.current || {};
    var sug = ra.suggested || {};
    var gain = ra.gain || {};
    setText(el('atpRouteCurrentKm'), fmtKm(cur.km));
    setText(el('atpRouteCurrentDur'), cur.duration_label || '—');
    setText(el('atpRouteSugKm'), fmtKm(sug.km));
    setText(el('atpRouteSugDur'), sug.duration_label || '—');
    setText(el('atpRouteGainKm'), gain.km != null && gain.km !== '—' ? gain.km + ' km' : '—');
    var gainDur = gain.duration_label || '—';
    var gainPct = gain.pct != null && gain.pct !== '—' ? '%' + gain.pct + ' daha kısa' : '—';
    setText(el('atpRouteGainDetail'), gainDur + (gainPct !== '—' ? ' · ' + gainPct : ''));
    setText(el('atpRouteCurrentOrder'), cur.order_labels || '—');
    setText(el('atpRouteSuggestedOrder'), sug.order_labels || '—');
    var msgEl = el('atpRouteStatusMsg');
    if (msgEl) {
      var msg = ra.message || '';
      if (ra.status === 'UNCONFIGURED') msg = ra.message || 'Rota servisi yapılandırılmamış.';
      else if (ra.status === 'ERROR' || ra.status === 'TIMEOUT' || ra.status === 'AUTH') {
        msg = ra.message || 'Rota hesaplanamadı.';
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
    var previewBtn = el('atpBtnPreviewSuggestedRoute');
    var applyBtn = el('atpBtnApplySuggestedOrder');
    var hasSug = sug.task_ids && sug.task_ids.length && cur.task_ids &&
      sug.task_ids.join(',') !== cur.task_ids.join(',');
    if (previewBtn) previewBtn.disabled = !hasSug || !(sug.geometry && sug.geometry.length);
    if (applyBtn) applyBtn.disabled = !hasSug;
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

  function applyRouteGeometry(route) {
    if (!global.AtpPlanMap) return;
    var cur = route && route.current;
    var draw = function () {
      if (cur && cur.geometry && cur.geometry.length) {
        global.AtpPlanMap.setCurrentRouteGeometry(cur.geometry);
      }
    };
    if (global.AtpPlanMap.hasInstance && global.AtpPlanMap.hasInstance()) draw();
    else requestAnimationFrame(function () { requestAnimationFrame(draw); });
  }

  function fetchPlanRoute(planDate, vehicleId, cb) {
    var q = '?date=' + encodeURIComponent(planDate);
    if (vehicleId) q += '&vehicle_id=' + encodeURIComponent(vehicleId);
    fetch('/planlama/arac-takip/api/route/plan' + q, { credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (!j.ok) return;
        lastRoute = j.route;
        updateRouteCards(j.route);
        updateDailyTotalsFooter(j.route, j.dashboard);
        updateTaskDistances(j.route);
        if (j.dashboard && typeof cb === 'function') cb(j.dashboard);
        applyRouteGeometry(j.route);
        if (global.AtpPlanMap && global.AtpPlanMap.clearSuggestedRouteGeometry) {
          global.AtpPlanMap.clearSuggestedRouteGeometry();
        }
      })
      .catch(function () {
        var msgEl = el('atpRouteStatusMsg');
        if (msgEl) {
          msgEl.textContent = 'Rota hesaplanamadı.';
          msgEl.style.display = '';
        }
      });
  }

  function openApplyConfirm(onConfirm) {
    var modal = el('atpRouteApplyModal');
    if (!modal || !lastRoute) return;
    var cur = lastRoute.current || {};
    var sug = lastRoute.suggested || {};
    var gain = lastRoute.gain || {};
    setText(el('atpRouteApplyCurrent'), cur.order_labels || '—');
    setText(el('atpRouteApplyNew'), sug.order_labels || '—');
    var gainParts = [];
    if (gain.km != null && gain.km !== '—') gainParts.push(gain.km + ' km');
    if (gain.duration_label && gain.duration_label !== '—') gainParts.push(gain.duration_label);
    if (gain.pct != null && gain.pct !== '—') gainParts.push('%' + gain.pct + ' daha kısa');
    setText(el('atpRouteApplyGain'), gainParts.length ? gainParts.join(' · ') : '—');
    modal.style.display = 'flex';
    var confirmBtn = el('atpRouteApplyConfirm');
    var cancelBtn = el('atpRouteApplyCancel');
    var inner = modal.querySelector('.atp-route-apply-modal');
    function close() {
      modal.style.display = 'none';
      document.removeEventListener('keydown', onKey);
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
      confirmBtn.onclick = function (ev) {
        ev.stopPropagation();
        close();
        if (typeof onConfirm === 'function') onConfirm();
      };
    }
    if (cancelBtn) cancelBtn.focus();
  }

  function bindRouteUi(planDate, getVehicleId, applyDashboard, renderTable) {
    var previewBtn = el('atpBtnPreviewSuggestedRoute');
    if (previewBtn) {
      previewBtn.addEventListener('click', function () {
        if (!lastRoute || !global.AtpPlanMap) return;
        var sug = lastRoute.suggested || {};
        if (sug.geometry && sug.geometry.length) {
          global.AtpPlanMap.setSuggestedRouteGeometry(sug.geometry);
        }
      });
    }
    var applyBtn = el('atpBtnApplySuggestedOrder');
    if (applyBtn) {
      applyBtn.addEventListener('click', function () {
        if (!lastRoute || !lastRoute.suggested || !lastRoute.suggested.task_ids) return;
        openApplyConfirm(function () {
          var vid = getVehicleId();
          fetch('/planlama/arac-takip/api/route/apply', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              date: planDate,
              vehicle_id: vid || null,
              task_ids: lastRoute.suggested.apply_task_ids || lastRoute.suggested.task_ids
            })
          }).then(function (r) { return r.json(); }).then(function (j) {
            if (!j.ok) return;
            if (j.dashboard && applyDashboard) applyDashboard(j.dashboard);
            else if (j.daily_tasks && renderTable) renderTable(j.daily_tasks);
            fetchPlanRoute(planDate, vid, applyDashboard);
          });
        });
      });
    }
    var sortBtn = el('atpBtnSortSuggest');
    if (sortBtn) {
      sortBtn.addEventListener('click', function () {
        fetchPlanRoute(planDate, getVehicleId(), applyDashboard);
      });
    }
  }

  global.AtpRoute = {
    fetchPlanRoute: fetchPlanRoute,
    bindRouteUi: bindRouteUi,
    getLastRoute: function () { return lastRoute; },
    updateRouteCards: updateRouteCards
  };
})(window);
