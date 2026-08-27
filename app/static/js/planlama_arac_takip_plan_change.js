/**
 * ATP Plan Change — compact modal for cancel / defer / transfer / bind location.
 */
(function () {
  'use strict';

  var INACTIVE = { IPTAL: 1, ERTELENDI: 1, GIDILEMEDI: 1 };
  var CANCEL_BLOCKED_MSG = 'Başlamış veya ziyaret sürecine girmiş iş plan dışına alınamaz.';
  var _state = {
    planItemId: null,
    detail: null,
    vehicles: [],
    submitting: false,
    clientSubmitId: null,
    isLocked: false,
  };

  function qs(id) { return document.getElementById(id); }
  function esc(s) {
    if (s == null) return '';
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }
  function fmtVal(v) { return v == null || v === '' ? '—' : String(v); }

  function planDate() {
    var dash = window.atpDashboard || {};
    if (dash.date) return dash.date;
    var p = new URLSearchParams(window.location.search);
    return p.get('date') || new Date().toISOString().slice(0, 10);
  }

  function uuid() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    return 'cs-' + Date.now() + '-' + Math.random().toString(16).slice(2);
  }

  function showWarn(msg) {
    var el = qs('atpPlanChangeWarn');
    if (!el) return;
    if (msg) {
      el.textContent = msg;
      el.classList.add('show');
    } else {
      el.textContent = '';
      el.classList.remove('show');
    }
  }

  function openBackdrop() {
    var bg = qs('atpPlanChangeBackdrop');
    var modal = qs('atpPlanChangeModal');
    if (bg) { bg.classList.add('open'); bg.setAttribute('aria-hidden', 'false'); }
    if (modal) modal.setAttribute('aria-hidden', 'false');
    document.body.classList.add('atp-modal-open');
  }

  function closeModal() {
    var bg = qs('atpPlanChangeBackdrop');
    var modal = qs('atpPlanChangeModal');
    if (bg) { bg.classList.remove('open'); bg.setAttribute('aria-hidden', 'true'); }
    if (modal) modal.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('atp-modal-open');
    _state.planItemId = null;
    _state.detail = null;
    _state.submitting = false;
    _state.isLocked = false;
    showWarn('');
  }

  function actionNeedsReason(action) {
    return action === 'cancel' || action === 'defer_next_day';
  }

  function _isActionSelected(action) {
    return !!(action && action !== '' && action !== '_none');
  }

  function togglePanels(action) {
    var active = _isActionSelected(action);
    var panels = {
      transfer_vehicle: qs('atpPcPanelTransfer'),
      defer_next_day: qs('atpPcPanelDefer'),
      bind_location: qs('atpPcPanelLocation'),
      reorder_info: qs('atpPcPanelReorder'),
    };
    Object.keys(panels).forEach(function (k) {
      var el = panels[k];
      if (el) el.style.display = (active && k === action) ? 'block' : 'none';
    });
    var reasonWrap = qs('atpPcReasonWrap');
    if (reasonWrap) {
      reasonWrap.style.display = (active && actionNeedsReason(action)) ? 'block' : 'none';
    }
    var info = qs('atpPcReorderInfo');
    if (info && action === 'reorder_info') {
      info.textContent = 'Saatler rota hesaplamasıyla atanır. Sıra değişikliği rota panelinden uygulanır.';
    }
    updateSaveButtonState(action);
  }

  function updateSaveButtonState(action) {
    var saveBtn = qs('atpPcSaveBtn');
    if (!saveBtn || _state.isLocked) return;
    /* Kaydet always visible; reorder_info and empty show messages on click, no POST */
    saveBtn.disabled = false;
  }

  function populateSummary(d) {
    qs('atpPcSummaryJob').textContent = fmtVal(d.job_title) + (d.company_name ? ' / ' + d.company_name : '');
    qs('atpPcSummaryDate').textContent = fmtVal(d.plan_tarihi);
    qs('atpPcSummaryVehicle').textContent = fmtVal(d.arac_plaka_snapshot) + ' · ' + fmtVal(d.sofor_adi_snapshot);
    qs('atpPcSummaryStatus').textContent = fmtVal(d.status_label || d.status);
    var loc = d.has_coordinates ? 'Konumlu' : 'Konum eksik';
    if (d.location_status) loc += ' (' + d.location_status + ')';
    qs('atpPcSummaryLocation').textContent = loc;
  }

  function populateActionSelect(allowed) {
    var sel = qs('atpPcAction');
    if (!sel) return;
    var opts = [
      { v: '_none', l: '— Aksiyon seç —', placeholder: true },
      { v: 'bind_location', l: 'Konum Bağla/Düzelt', key: 'bind_location' },
      { v: 'transfer_vehicle', l: 'Başka Araca Aktar', key: 'transfer_vehicle' },
      { v: 'defer_next_day', l: 'Sonraki Güne Aktar', key: 'defer_next_day' },
      { v: 'cancel', l: 'İptal Et (Plan Dışına Al)', key: 'cancel' },
      { v: 'reorder_info', l: 'Saat/Sıra Değiştir (bilgi)', key: 'reorder_info' },
    ];
    var cancelDisabledReason = allowed && allowed.cancel_disabled_reason;
    sel.innerHTML = opts.map(function (o) {
      if (o.placeholder) {
        return '<option value="_none" selected disabled>— Aksiyon seç —</option>';
      }
      var ok = allowed && allowed[o.key];
      if (o.key === 'cancel' && !ok && cancelDisabledReason) {
        return '<option value="' + o.v + '" disabled title="' + esc(cancelDisabledReason) + '">' +
          esc(o.l) + ' — ' + esc(cancelDisabledReason) + '</option>';
      }
      if (!ok) return '';
      return '<option value="' + o.v + '">' + esc(o.l) + '</option>';
    }).join('');
    sel.value = '_none';
    sel.selectedIndex = 0;
    togglePanels('_none');
  }

  function populateVehicles(vehicles, currentVid) {
    var sel = qs('atpPcTargetVehicle');
    var deferSel = qs('atpPcDeferVehicle');
    if (!sel && !deferSel) return;
    var seen = {};
    var html = '<option value="">— Araç seç —</option>';
    (vehicles || []).forEach(function (v) {
      var vid = String(v.arac_external_id || '');
      if (!vid || seen[vid]) return;
      seen[vid] = true;
      var pl = v.arac_plaka_snapshot || vid;
      var drv = v.sofor_adi_snapshot || '';
      html += '<option value="' + esc(vid) + '" data-driver="' + esc(drv) + '">' +
        esc(pl) + '</option>';
    });
    if (sel) sel.innerHTML = html;
    if (deferSel) deferSel.innerHTML = html;
    if (currentVid) {
      if (sel) sel.value = String(currentVid);
      if (deferSel) deferSel.value = String(currentVid);
    }
    syncDriverFromVehicle();
    syncDeferDriverFromVehicle();
  }

  function syncDeferDriverFromVehicle() {
    var sel = qs('atpPcDeferVehicle');
    var drv = qs('atpPcDeferDriver');
    if (!sel || !drv) return;
    var opt = sel.options[sel.selectedIndex];
    if (opt && opt.getAttribute('data-driver')) drv.value = opt.getAttribute('data-driver');
  }

  function syncDriverFromVehicle() {
    var sel = qs('atpPcTargetVehicle');
    var drv = qs('atpPcTargetDriver');
    if (!sel || !drv) return;
    var opt = sel.options[sel.selectedIndex];
    if (opt && opt.getAttribute('data-driver')) drv.value = opt.getAttribute('data-driver');
  }

  function bindLocationSearch() {
    var input = qs('atpPcLocSearch');
    var dd = qs('atpPcLocDropdown');
    if (!input || !dd || input._atpPcBound) return;
    input._atpPcBound = true;
    var timer = null;
    input.addEventListener('input', function () {
      clearTimeout(timer);
      var q = input.value.trim();
      if (q.length < 2) { dd.classList.remove('open'); dd.innerHTML = ''; return; }
      timer = setTimeout(function () {
        fetch('/planlama/arac-takip/api/locations/search?q=' + encodeURIComponent(q))
          .then(function (r) { return r.json(); })
          .then(function (j) {
            var rows = (j && j.results) || [];
            if (!rows.length) {
              dd.innerHTML = '<div class="firma-dd-label">Sonuç yok</div>';
            } else {
              dd.innerHTML = rows.map(function (r) {
                return '<button type="button" class="firma-dd-item" data-id="' + esc(r.id) + '" ' +
                  'data-lat="' + esc(r.latitude) + '" data-lng="' + esc(r.longitude) + '" ' +
                  'data-adres="' + esc(r.adres || '') + '">' +
                  esc(r.firma_adi || r.label || '') + '</button>';
              }).join('');
            }
            dd.classList.add('open');
          }).catch(function () { dd.classList.remove('open'); });
      }, 250);
    });
    dd.addEventListener('click', function (e) {
      var btn = e.target.closest('.firma-dd-item');
      if (!btn) return;
      qs('atpPcLocationId').value = btn.getAttribute('data-id') || '';
      qs('atpPcLocLat').value = btn.getAttribute('data-lat') || '';
      qs('atpPcLocLng').value = btn.getAttribute('data-lng') || '';
      input.value = btn.textContent.trim();
      dd.classList.remove('open');
    });
  }

  function loadDetail(planItemId) {
    showWarn('');
    qs('atpPlanChangeBody').innerHTML = '<p style="color:var(--gray);font-size:12px">Yükleniyor…</p>';
    openBackdrop();
    return fetch('/planlama/arac-takip/api/plan-job/' + encodeURIComponent(planItemId) + '/detail')
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (res) {
        if (!res.ok || !res.j || !res.j.ok) {
          throw new Error((res.j && res.j.error) || 'Detay alınamadı');
        }
        _state.detail = res.j.detail;
        _state.vehicles = res.j.vehicles || [];
        renderForm(res.j);
      })
      .catch(function (err) {
        showWarn(err.message || 'Detay alınamadı');
      });
  }

  function _statusLockBanner(msg) {
    return '<div class="atp-pc-lock-banner">' + esc(msg) + '</div>';
  }

  function _noActionsBanner() {
    return '<div class="atp-pc-info-banner">Bu iş için şu an kullanılabilir aksiyon yok.</div>';
  }

  function _locationHint(d) {
    if (d.has_coordinates) return '';
    var allowed = d.allowed_actions || {};
    if (!allowed.bind_location) return '';
    return '<div class="atp-pc-location-hint">⚠ Konum eksik — <strong>Konum Bağla/Düzelt</strong> seçerek konum ekleyin.</div>';
  }

  function renderForm(payload) {
    var d = payload.detail;
    var body = qs('atpPlanChangeBody');
    if (!body) return;
    body.innerHTML = document.getElementById('atpPlanChangeFormTpl').innerHTML;
    populateSummary(d);

    var allowed = d.allowed_actions || {};
    var isLocked = !!allowed.locked;
    var lockMsg = allowed.lock_reason || null;

    /* Locked state (e.g. TAMAMLANDI): show banner, disable dropdown, hide save */
    if (isLocked) {
      var lockBanner = document.createElement('div');
      lockBanner.className = 'atp-pc-lock-banner';
      lockBanner.textContent = lockMsg || 'Bu iş değiştirilemez.';
      body.insertBefore(lockBanner, body.firstChild);
    }

    /* Location hint for no-coords PLANLANDI items */
    if (!d.has_coordinates && !isLocked && allowed.bind_location) {
      var locHint = document.createElement('div');
      locHint.className = 'atp-pc-location-hint';
      locHint.innerHTML = '⚠ Konum eksik — aşağıdan <strong>Konum Bağla/Düzelt</strong> seçin.';
      body.insertBefore(locHint, body.firstChild);
    }

    populateActionSelect(allowed);

    /* If locked: disable select, hide save button */
    var actionSel = qs('atpPcAction');
    var saveBtn = qs('atpPcSaveBtn');
    if (isLocked) {
      if (actionSel) { actionSel.disabled = true; actionSel.value = '_none'; actionSel.selectedIndex = 0; }
      if (saveBtn) saveBtn.style.display = 'none';
    } else {
      /* If no options available (all False): inform user */
      var hasOptions = actionSel && actionSel.options.length > 1;
      if (!hasOptions && actionSel) {
        var noOpt = document.createElement('option');
        noOpt.value = '';
        noOpt.textContent = '— Kullanılabilir aksiyon yok —';
        actionSel.innerHTML = '';
        actionSel.appendChild(noOpt);
        actionSel.disabled = true;
        if (saveBtn) saveBtn.style.display = 'none';
      }
    }

    /* Hint: BASLADI / visit — show which actions are blocked */
    var st = (d.status || '').toUpperCase();
    var visit = (d.visit_state || 'OUTSIDE').toUpperCase();
    var hasVisit = visit === 'ARRIVED' || visit === 'DEPARTED_PENDING';
    if (!isLocked && (st === 'BASLADI' || hasVisit)) {
      var note = qs('atpPcStatusNote');
      if (!note) {
        note = document.createElement('div');
        note.id = 'atpPcStatusNote';
        note.className = 'atp-pc-info-banner';
        body.insertBefore(note, body.firstChild);
      }
      var msgs = [];
      if (!allowed.cancel) msgs.push('iptal');
      if (!allowed.transfer_vehicle) msgs.push('araca aktar');
      if (!allowed.bind_location) msgs.push('konum değiştir');
      if (msgs.length) {
        note.textContent = 'Kısıtlı: ' + msgs.join(', ') + ' işlemi bu durumda yapılamaz.';
      }
    }

    populateVehicles(payload.vehicles, d.arac_external_id);
    var deferDate = qs('atpPcTargetDate');
    if (deferDate) deferDate.value = payload.default_target_date || '';
    bindLocationSearch();

    var acil = qs('atpPcAcilWarn');
    if (acil) acil.style.display = (allowed.acil_warning) ? 'block' : 'none';
    if (actionSel && !actionSel.disabled) {
      actionSel.addEventListener('change', function () { togglePanels(actionSel.value); });
    }
    var vsel = qs('atpPcTargetVehicle');
    if (vsel) vsel.addEventListener('change', syncDriverFromVehicle);
    var dsel = qs('atpPcDeferVehicle');
    if (dsel) dsel.addEventListener('change', syncDeferDriverFromVehicle);

    _state.isLocked = isLocked;
  }

  function buildPayload(action) {
    var d = _state.detail || {};
    var payload = {
      action: action,
      reason: (qs('atpPcReason') && qs('atpPcReason').value || '').trim(),
      plan_tarihi: d.plan_tarihi || planDate(),
      arac_external_id: d.arac_external_id,
      client_submit_id: _state.clientSubmitId,
    };
    if (action === 'transfer_vehicle') {
      payload.target_vehicle_external_id = qs('atpPcTargetVehicle') && qs('atpPcTargetVehicle').value;
      payload.sofor_adi = qs('atpPcTargetDriver') && qs('atpPcTargetDriver').value;
    }
    if (action === 'defer_next_day') {
      payload.target_date = qs('atpPcTargetDate') && qs('atpPcTargetDate').value;
      payload.target_vehicle_external_id = qs('atpPcDeferVehicle') && qs('atpPcDeferVehicle').value
        || d.arac_external_id;
      payload.sofor_adi = qs('atpPcDeferDriver') && qs('atpPcDeferDriver').value
        || d.sofor_adi_snapshot;
    }
    if (action === 'bind_location') {
      payload.location_id = qs('atpPcLocationId') && qs('atpPcLocationId').value;
      payload.latitude = qs('atpPcLocLat') && qs('atpPcLocLat').value;
      payload.longitude = qs('atpPcLocLng') && qs('atpPcLocLng').value;
      payload.adres = qs('atpPcLocSearch') && qs('atpPcLocSearch').value;
    }
    return payload;
  }

  function validate(action) {
    if (action === 'reorder_info') return true;
    if (actionNeedsReason(action)) {
      var reason = qs('atpPcReason') && qs('atpPcReason').value.trim();
      if (!reason || reason.length < 2) {
        showWarn('Neden alanı zorunlu (min 2 karakter).');
        return false;
      }
    }
    if (action === 'transfer_vehicle') {
      var vid = qs('atpPcTargetVehicle') && qs('atpPcTargetVehicle').value;
      if (!vid) { showWarn('Hedef araç seçin.'); return false; }
    }
    if (action === 'defer_next_day') {
      var dt = qs('atpPcTargetDate') && qs('atpPcTargetDate').value;
      if (!dt) { showWarn('Hedef tarih seçin.'); return false; }
    }
    if (action === 'bind_location') {
      var locId = qs('atpPcLocationId') && qs('atpPcLocationId').value;
      var lat = qs('atpPcLocLat') && qs('atpPcLocLat').value;
      var lng = qs('atpPcLocLng') && qs('atpPcLocLng').value;
      if (!locId && !(lat && lng)) { showWarn('Konum seçin veya koordinat girin.'); return false; }
    }
    var d = _state.detail || {};
    if (d.allowed_actions && d.allowed_actions.acil_warning &&
        (action === 'transfer_vehicle' || action === 'defer_next_day')) {
      if (!window.confirm('ACİL iş — taşıma/erteleme onaylıyor musunuz?')) return false;
    }
    return true;
  }

  function _friendlyChangeError(msg) {
    if (!msg) return 'Kaydetme hatası';
    if (/FOREIGN KEY|IntegrityError|constraint failed/i.test(msg)) {
      return 'Bu iş silinemez; iptal olarak kapatabilirsiniz.';
    }
    return msg;
  }

  function applyOpsRefresh(j) {
    if (j.dashboard && window.applyAtpDashboard) window.applyAtpDashboard(j.dashboard);
    if (j.today_operations && window.loadAtpTodayOps) {
      window.loadAtpTodayOps();
    } else if (window.loadAtpTodayOps) {
      window.loadAtpTodayOps();
    }
  }

  function submitChange(action) {
    if (_state.submitting) return;
    /* Hard guard: locked items must never POST */
    if (_state.isLocked) {
      showWarn('Bu iş değiştirilemez.');
      return;
    }
    if (!action || action === '_none') {
      showWarn('Lütfen bir aksiyon seçin.');
      return;
    }
    if (action === 'reorder_info') {
      showWarn('Saatler rota hesaplamasıyla atanır. Sıra değişikliği rota panelinden uygulanır.');
      return;
    }
    if (!validate(action)) return;
    if (action === 'cancel') {
      var allowed = (_state.detail && _state.detail.allowed_actions) || {};
      if (!allowed.cancel) {
        showWarn(allowed.cancel_disabled_reason || CANCEL_BLOCKED_MSG);
        return;
      }
    }
    _state.submitting = true;
    _state.clientSubmitId = uuid();
    var payload = buildPayload(action);
    var btn = qs('atpPcSaveBtn');
    if (btn) btn.disabled = true;
    fetch('/planlama/arac-takip/api/plan-job/' + encodeURIComponent(_state.planItemId) + '/change', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }).then(function (r) {
      return r.json().then(function (j) { return { ok: r.ok, status: r.status, j: j }; });
    }).then(function (res) {
      if (!res.ok || !res.j || !res.j.ok) {
        var errMsg = (res.j && res.j.error) || ('İşlem başarısız (' + res.status + ')');
        if (res.status === 409) {
          showWarn(errMsg);
          return;
        }
        throw new Error(errMsg);
      }
      applyOpsRefresh(res.j);
      if (res.j.message && window.toast) window.toast(res.j.message);
      closeModal();
    }).catch(function (err) {
      showWarn(_friendlyChangeError(err.message || 'Kaydetme hatası'));
    }).finally(function () {
      _state.submitting = false;
      if (btn) btn.disabled = false;
    });
  }

  function quickComplete(planItemId) {
    if (!window.confirm('İş sonuçlandırılacak. Onaylıyor musunuz?')) return;
    _state.planItemId = planItemId;
    _state.clientSubmitId = uuid();
    fetch('/planlama/arac-takip/api/plan-job/' + encodeURIComponent(planItemId) + '/change', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        action: 'complete',
        plan_tarihi: planDate(),
        client_submit_id: _state.clientSubmitId,
      }),
    }).then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (res) {
        if (!res.ok || !res.j || !res.j.ok) throw new Error((res.j && res.j.error) || 'Sonuçlandırma başarısız');
        applyOpsRefresh(res.j);
      }).catch(function (err) {
        window.alert(err.message || 'Sonuçlandırma hatası');
      });
  }

  function openView(planItemId, vid) {
    if (vid && window.selectAtpVehicle) window.selectAtpVehicle(String(vid));
    else {
      var det = qs('atpPlanningSection');
      if (det) det.open = true;
    }
  }

  function openChange(planItemId) {
    _state.planItemId = planItemId;
    _state.clientSubmitId = null;
    loadDetail(planItemId);
  }

  function init() {
    var closeBtn = qs('atpPlanChangeClose');
    var cancelBtn = qs('atpPlanChangeCancel');
    var saveBtn = qs('atpPcSaveBtn');
    if (closeBtn) closeBtn.addEventListener('click', closeModal);
    if (cancelBtn) cancelBtn.addEventListener('click', closeModal);
    if (saveBtn) saveBtn.addEventListener('click', function () {
      var action = qs('atpPcAction') && qs('atpPcAction').value;
      if (!_isActionSelected(action)) {
        showWarn('Lütfen bir aksiyon seçin.');
        return;
      }
      submitChange(action);
    });
    document.addEventListener('click', function (e) {
      if (e.target.closest('.atp-job-menu-btn') || e.target.closest('#atpJobMenuFloat')) return;
      if (window.closeAtpJobMenu) window.closeAtpJobMenu();
    });
  }

  window.AtpPlanChange = {
    init: init,
    openChange: openChange,
    openView: openView,
    quickComplete: quickComplete,
    isInactiveStatus: function (st) { return !!INACTIVE[(st || '').toUpperCase()]; },
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
