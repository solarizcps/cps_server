/**
 * ATP — Manual reorder UI controller (U3D2).
 * Depends on ATP_MANUAL_REORDER state motor; no optimizer/maps calls.
 */
(function (root, factory) {
  'use strict';
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.AtpManualReorderUI = factory();
  }
}(typeof globalThis !== 'undefined' ? globalThis : typeof window !== 'undefined' ? window : this, function (root) {
  'use strict';

  var CONTEXT_URL = '/planlama/arac-takip/api/plan/manual-reorder-context';
  var APPLY_URL = '/planlama/arac-takip/api/plan/manual-reorder';
  var SUCCESS_MSG = 'Görev sırası güncellendi. Rota ve tahmini saatler yeniden hesaplanmayı bekliyor.';
  var CONFLICT_MSG = 'Plan siz düzenlerken değişti. Güncel sıralamayı yükleyin.';
  var EDIT_HINT = 'Planlanmış durakları sürükleyin veya oklarla taşıyın.';
  var DIRTY_INFO = 'Kaydedilmemiş sıra değişikliği';
  var NAV_GUARD_MSG = 'Kaydedilmemiş sıra değişiklikleri var. Vazgeçilsin mi?';

  var LOCK_LABELS = {
    STATUS_BASLADI: 'Başlanan görev taşınamaz',
    STATUS_TAMAMLANDI: 'Tamamlanan görev taşınamaz',
    STATUS_INACTIVE: 'Aktif olmayan görev taşınamaz',
    VISIT_ARRIVED: 'Konuma varılan görev taşınamaz',
    VISIT_DEPARTED_PENDING: 'Ziyaret sonucu bekleyen görev taşınamaz',
    VISIT_DEPARTED_LEGACY: 'Ziyareti başlayan görev taşınamaz',
    VISIT_TIMESTAMP: 'Ziyaret kaydı bulunan görev taşınamaz',
  };

  function escHtml(v) {
    return String(v == null ? '' : v)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function lockLabel(reason) {
    if (!reason) return 'Görev güvenlik nedeniyle taşınamaz';
    return LOCK_LABELS[reason] || 'Görev güvenlik nedeniyle taşınamaz';
  }

  function defaultDeps() {
    return {
      document: typeof document !== 'undefined' ? document : null,
      fetch: typeof fetch !== 'undefined' ? fetch.bind(root) : null,
      confirmFn: (root && typeof root.confirm === 'function')
        ? root.confirm.bind(root)
        : function () { return true; },
      getMotor: function () { return root.ATP_MANUAL_REORDER || null; },
      getPlanId: function () { return null; },
      getVehicleId: function () { return null; },
      getPlanDate: function () { return root.ATP_PLAN_DATE || ''; },
      getTasksForVehicle: function () { return []; },
      getBaseLocation: function () { return 'Fabrika — Tuzla OSB'; },
      loadOps: function () { return Promise.resolve(false); },
      toast: function () {},
      fmtVal: function (v) { return (v == null || v === '') ? '—' : String(v); },
      isActivePlanItem: function () { return true; },
      safePlate: function (v) { return v && v.plate ? v.plate : '—'; },
      findVehicleByExtId: function () { return null; },
    };
  }

  function createController(userDeps) {
    var deps = Object.assign(defaultDeps(), userDeps || {});
    var MR = deps.getMotor();
    var editMode = false;
    var state = null;
    var lastTasks = [];
    var lastPlate = '';
    var contextReqSeq = 0;
    var activeContextReq = null;
    var boundPlanId = null;
    var boundVehicleId = null;
    var dragSourceId = null;
    var eventsBound = false;
    var fetchLog = [];

    function qs(id) {
      if (!deps.document) return null;
      return deps.document.getElementById(id);
    }

    function motorReady() {
      return !!(deps.getMotor && deps.getMotor());
    }

    function failClosed(msg) {
      if (msg && deps.toast) deps.toast(msg);
      return false;
    }

    function getMotor() {
      return deps.getMotor();
    }

    function isEditMode() {
      return editMode;
    }

    function isDirty() {
      if (!state || !motorReady()) return false;
      return getMotor().isDirty(state);
    }

    function taskById(taskId) {
      var tid = String(taskId || '');
      for (var i = 0; i < lastTasks.length; i += 1) {
        if (String(lastTasks[i].id) === tid) return lastTasks[i];
      }
      return null;
    }

    function tasksInDraftOrder() {
      if (!state || !motorReady()) return lastTasks.slice();
      var visibleIds = getMotor().getVisibleDraftOrder(state);
      var map = {};
      lastTasks.forEach(function (t) { if (t.id != null) map[String(t.id)] = t; });
      var ordered = [];
      visibleIds.forEach(function (id) {
        if (map[id]) ordered.push(map[id]);
      });
      lastTasks.forEach(function (t) {
        var id = t.id != null ? String(t.id) : '';
        if (id && ordered.indexOf(t) < 0 && deps.isActivePlanItem(t)) ordered.push(t);
      });
      return ordered;
    }

    function toolbarEl() {
      var el = qs('atpManualReorderToolbar');
      if (!el && deps.document) {
        var title = qs('atpStopListTitle');
        if (!title || !title.parentNode) return null;
        el = deps.document.createElement('div');
        el.id = 'atpManualReorderToolbar';
        el.className = 'atp-manual-reorder-toolbar';
        title.parentNode.insertBefore(el, title.nextSibling);
      }
      return el;
    }

    function msgEl() {
      var el = qs('atpManualReorderMsg');
      if (!el && deps.document) {
        var tb = toolbarEl();
        if (!tb || !tb.parentNode) return null;
        el = deps.document.createElement('div');
        el.id = 'atpManualReorderMsg';
        el.className = 'atp-manual-reorder-msg';
        el.setAttribute('aria-live', 'polite');
        tb.parentNode.insertBefore(el, tb.nextSibling);
      }
      return el;
    }

    function setMsg(text, kind) {
      var el = msgEl();
      if (!el) return;
      el.textContent = text || '';
      el.className = 'atp-manual-reorder-msg' + (kind ? (' is-' + kind) : '');
    }

    function headerActionEl() {
      return qs('atpManualReorderHeaderAction');
    }

    function restorePanelTitle() {
      var title = qs('atpStopListTitle');
      if (title) title.textContent = 'Sıralı Duraklar' + (lastPlate ? ' — ' + lastPlate : '');
    }

    function renderToolbar() {
      var tb = toolbarEl();
      var headerAct = headerActionEl();
      if (!motorReady()) {
        if (tb) { tb.style.display = 'none'; tb.innerHTML = ''; }
        if (headerAct) { headerAct.innerHTML = ''; headerAct.style.display = 'none'; }
        return;
      }
      if (!editMode) {
        if (tb) { tb.style.display = 'none'; tb.innerHTML = ''; }
        if (headerAct) {
          headerAct.style.display = '';
          headerAct.innerHTML =
            '<button type="button" class="btn btn-outline btn-sm atp-mr-btn-edit" id="atpBtnManualReorderEdit">Sırayı Düzenle</button>';
        }
        var editBtn = qs('atpBtnManualReorderEdit');
        if (editBtn) editBtn.disabled = !lastTasks.length || !deps.getPlanId();
        setMsg('', '');
        return;
      }
      if (headerAct) { headerAct.innerHTML = ''; headerAct.style.display = 'none'; }
      if (!tb) return;
      tb.style.display = '';
      var dirty = isDirty();
      var saving = state && state.saving;
      var conflicted = state && state.conflicted;
      var html = '<div class="atp-mr-toolbar-row atp-mr-toolbar-edit">';
      html += '<span class="atp-mr-toolbar-hint">' + escHtml(EDIT_HINT) + '</span>';
      html += '<span class="atp-mr-toolbar-actions">';
      html += '<button type="button" class="btn btn-gold btn-sm" id="atpBtnManualReorderApply" ' +
        (dirty && !saving && !conflicted ? '' : 'disabled') + '>Sıralamayı Uygula</button>';
      html += '<button type="button" class="btn btn-outline btn-sm atp-mr-btn-neutral" id="atpBtnManualReorderDiscard" ' +
        (saving ? 'disabled' : '') + '>Vazgeç</button>';
      html += '</span></div>';
      if (dirty && !conflicted) {
        html += '<div class="atp-mr-dirty-info">' + escHtml(DIRTY_INFO) + '</div>';
      }
      if (conflicted) {
        html += '<div class="atp-mr-conflict-banner" role="alert">' +
          '<span class="atp-mr-conflict-text">' + escHtml(CONFLICT_MSG) + '</span>' +
          '<button type="button" class="btn btn-outline btn-sm atp-mr-reload" id="atpBtnManualReorderReload">Güncel Planı Yükle</button>' +
          '</div>';
      }
      tb.innerHTML = html;
      if (conflicted) setMsg('', '');
    }

    function rowMeta(taskId) {
      if (!state || !motorReady()) return { movable: false, lockReason: null };
      var motor = getMotor();
      var meta = motor.getTask(state, taskId);
      if (!meta) return { movable: false, lockReason: null };
      return {
        movable: motor.canMoveTask(state, taskId),
        lockReason: meta.lock_reason,
        segment: meta.segment_index,
      };
    }

    function canMoveUp(taskId) {
      if (!state || !motorReady()) return false;
      var moved = getMotor().moveUp(state, taskId);
      return moved.result && moved.result.ok && moved.result.changed;
    }

    function canMoveDown(taskId) {
      if (!state || !motorReady()) return false;
      var moved = getMotor().moveDown(state, taskId);
      return moved.result && moved.result.ok && moved.result.changed;
    }

    function buildStopRowHtml(t, seq, meta) {
      var inact = !deps.isActivePlanItem(t);
      var done = t.status === 'TAMAMLANDI';
      var late = t.is_late;
      var cls = 'stop-item atp-mr-stop-item';
      if (editMode) cls += ' atp-mr-edit-mode';
      if (inact) cls += ' passive';
      else if (done) cls += ' done';
      else if (late) cls += ' late';
      var numCls = 'stop-num' + (inact ? ' passive' : (done ? ' done' : (late ? ' late' : '')));
      var badgeCls = done ? 'badge-green' : (late ? 'badge-orange' : 'badge-gray');
      var badgeLbl = done ? '✓' : (late ? 'Gecikmeli' : deps.fmtVal(t.status_label || t.status || 'Planlandı'));
      var itemId = t.id ? String(t.id) : '';
      var priHtml = (t.priority && t.priority !== 'NORMAL')
        ? '<span class="badge badge-orange" style="margin-right:4px;font-size:10px">' +
          escHtml(deps.fmtVal(t.priority_label || t.priority)) + '</span>'
        : '';
      var controls = '';
      if (editMode) {
        if (meta.movable) {
          var upDis = canMoveUp(itemId) ? '' : ' disabled';
          var downDis = canMoveDown(itemId) ? '' : ' disabled';
          controls =
            '<span class="atp-mr-controls">' +
            '<span class="atp-mr-drag-handle" draggable="true" aria-label="Görevi sürükleyerek taşı" title="Sürükle" data-task-id="' + escHtml(itemId) + '">⠿</span>' +
            '<button type="button" class="atp-mr-arrow atp-mr-up" data-task-id="' + escHtml(itemId) + '" aria-label="Görevi yukarı taşı"' + upDis + '>▲</button>' +
            '<button type="button" class="atp-mr-arrow atp-mr-down" data-task-id="' + escHtml(itemId) + '" aria-label="Görevi aşağı taşı"' + downDis + '>▼</button>' +
            '</span>';
        } else {
          controls =
            '<span class="atp-mr-controls atp-mr-locked" title="' + escHtml(lockLabel(meta.lockReason)) + '">' +
            '<span class="atp-mr-lock" aria-label="' + escHtml(lockLabel(meta.lockReason)) + '">🔒</span>' +
            '</span>';
        }
      }
      return '<div class="' + cls + '" data-item-id="' + escHtml(itemId) + '" data-task-id="' + escHtml(itemId) + '">' +
        controls +
        '<span class="' + numCls + '">' + escHtml(String(seq)) + '</span>' +
        '<span class="stop-name">' + escHtml(deps.fmtVal(t.company_name || t.job_title)) + '</span>' +
        priHtml +
        '<span class="badge ' + badgeCls + '" style="margin-right:4px">' + escHtml(badgeLbl) + '</span>' +
        '<span class="stop-time" style="' + (late ? 'color:var(--orange)' : '') + '">' +
        (inact ? '' : escHtml(deps.fmtVal(t.eta_time || t.tahmini_varis_saati || '—'))) + '</span>' +
        '</div>';
    }

    function renderEditStopList() {
      var wrap = qs('atpStopListWrap');
      if (!wrap || !state) return;
      var base = deps.getBaseLocation();
      var tasks = tasksInDraftOrder();
      var seq = 0;
      var html = '<div class="factory-row atp-mr-factory-row"><span class="fl">🏭</span><span class="factory-label">Başlangıç: ' + escHtml(base) + '</span></div>';
      html += '<div class="stop-list atp-mr-stop-list">';
      tasks.forEach(function (t) {
        if (!deps.isActivePlanItem(t)) return;
        seq += 1;
        html += buildStopRowHtml(t, seq, rowMeta(String(t.id)));
      });
      html += '</div>';
      html += '<div class="factory-row atp-mr-factory-row" style="margin-top:4px"><span class="fl">🏭</span><span class="factory-label">Bitiş: Fabrika Dönüş — ' + escHtml(base) + '</span></div>';
      wrap.innerHTML = html;
      wrap.classList.toggle('atp-mr-editing', true);
      bindListEvents(wrap);
      renderToolbar();
    }

    function bindListEvents(wrap) {
      if (!wrap) return;
      wrap.querySelectorAll('.atp-mr-up').forEach(function (btn) {
        btn.addEventListener('click', onArrowClick);
      });
      wrap.querySelectorAll('.atp-mr-down').forEach(function (btn) {
        btn.addEventListener('click', onArrowClick);
      });
      wrap.querySelectorAll('.atp-mr-drag-handle').forEach(function (handle) {
        handle.addEventListener('dragstart', onDragStart);
        handle.addEventListener('dragend', onDragEnd);
      });
      wrap.querySelectorAll('.atp-mr-stop-item').forEach(function (row) {
        row.addEventListener('dragover', onDragOver);
        row.addEventListener('dragleave', onDragLeave);
        row.addEventListener('drop', onDrop);
      });
    }

    function onArrowClick(ev) {
      if (!state || state.saving) return;
      var btn = ev.currentTarget;
      var taskId = btn.getAttribute('data-task-id');
      if (!taskId || btn.disabled) return;
      var motor = getMotor();
      var out = btn.classList.contains('atp-mr-up')
        ? motor.moveUp(state, taskId)
        : motor.moveDown(state, taskId);
      if (out.result && out.result.ok && out.result.changed) {
        state = out.state;
        renderEditStopList();
      }
    }

    function onDragStart(ev) {
      if (!state || state.saving) return;
      var handle = ev.currentTarget;
      var taskId = handle.getAttribute('data-task-id');
      if (!taskId || !getMotor().canMoveTask(state, taskId)) {
        ev.preventDefault();
        return;
      }
      dragSourceId = taskId;
      ev.dataTransfer.effectAllowed = 'move';
      try { ev.dataTransfer.setData('text/plain', taskId); } catch (e) { /* ignore */ }
      var row = handle.closest('.atp-mr-stop-item');
      if (row) row.classList.add('atp-mr-dragging');
    }

    function onDragEnd() {
      dragSourceId = null;
      var wrap = qs('atpStopListWrap');
      if (!wrap) return;
      wrap.querySelectorAll('.atp-mr-dragging, .atp-mr-drop-before, .atp-mr-drop-after').forEach(function (el) {
        el.classList.remove('atp-mr-dragging', 'atp-mr-drop-before', 'atp-mr-drop-after');
      });
    }

    function onDragOver(ev) {
      if (!dragSourceId || !state) return;
      ev.preventDefault();
      var row = ev.currentTarget;
      var targetId = row.getAttribute('data-task-id');
      if (!targetId || targetId === dragSourceId) return;
      var rect = row.getBoundingClientRect();
      var before = (ev.clientY - rect.top) < (rect.height / 2);
      row.classList.toggle('atp-mr-drop-before', before);
      row.classList.toggle('atp-mr-drop-after', !before);
    }

    function onDragLeave(ev) {
      var row = ev.currentTarget;
      row.classList.remove('atp-mr-drop-before', 'atp-mr-drop-after');
    }

    function onDrop(ev) {
      ev.preventDefault();
      if (!dragSourceId || !state) return;
      var row = ev.currentTarget;
      var targetId = row.getAttribute('data-task-id');
      row.classList.remove('atp-mr-drop-before', 'atp-mr-drop-after');
      if (!targetId || targetId === dragSourceId) return;
      var rect = row.getBoundingClientRect();
      var before = (ev.clientY - rect.top) < (rect.height / 2);
      var motor = getMotor();
      var out = before
        ? motor.moveBefore(state, dragSourceId, targetId)
        : motor.moveAfter(state, dragSourceId, targetId);
      dragSourceId = null;
      if (out.result && out.result.ok && out.result.changed) {
        state = out.state;
        renderEditStopList();
      }
    }

    function buildContextUrl(planId) {
      var q = CONTEXT_URL + '?plan_id=' + encodeURIComponent(planId);
      var date = deps.getPlanDate();
      var vid = deps.getVehicleId();
      if (date) q += '&date=' + encodeURIComponent(date);
      if (vid) q += '&vehicle_id=' + encodeURIComponent(vid);
      return q;
    }

    function fetchJson(url, opts) {
      fetchLog.push({ url: url, method: (opts && opts.method) || 'GET' });
      if (!deps.fetch) return Promise.reject(new Error('fetch unavailable'));
      return deps.fetch(url, Object.assign({ credentials: 'same-origin' }, opts || {}))
        .then(function (r) {
          if (r && typeof r.json === 'function') {
            return r.json().then(function (body) {
              return { ok: r.ok, status: r.status, body: body };
            });
          }
          if (r && r.body !== undefined) {
            return {
              ok: r.ok !== false,
              status: r.status != null ? r.status : 200,
              body: r.body,
            };
          }
          return { ok: false, status: 0, body: null };
        });
    }

    function fetchContext(planId, vehicleId) {
      if (!motorReady()) return Promise.resolve({ ok: false, error: 'motor_missing' });
      if (activeContextReq) return Promise.resolve({ ok: false, error: 'duplicate_request' });
      var seq = ++contextReqSeq;
      var url = buildContextUrl(planId);
      setMsg('Sıralama bilgisi yükleniyor…', 'loading');
      activeContextReq = seq;
      return fetchJson(url).then(function (res) {
        activeContextReq = null;
        if (seq !== contextReqSeq) return { ok: false, error: 'stale_response' };
        if (String(deps.getVehicleId() || '') !== String(vehicleId || '')) {
          return { ok: false, error: 'stale_vehicle' };
        }
        if (!res.ok || !res.body || res.body.ok !== true) {
          setMsg((res.body && (res.body.error || res.body.message)) || 'Sıralama yüklenemedi.', 'error');
          return { ok: false, error: 'bad_context', status: res.status, body: res.body };
        }
        return { ok: true, context: res.body, seq: seq };
      }).catch(function (err) {
        activeContextReq = null;
        if (seq !== contextReqSeq) return { ok: false, error: 'stale_response' };
        setMsg('Bağlantı hatası: sıralama yüklenemedi.', 'error');
        return { ok: false, error: err && err.message ? err.message : 'network' };
      });
    }

    function enterEditMode() {
      if (!motorReady()) return Promise.resolve(failClosed('Manuel sıralama kullanılamıyor.'));
      var planId = deps.getPlanId();
      var vid = deps.getVehicleId();
      if (!planId || !vid) return Promise.resolve(failClosed('Plan veya araç seçili değil.'));
      lastTasks = deps.getTasksForVehicle(vid) || [];
      boundPlanId = planId;
      boundVehicleId = vid;
      return fetchContext(planId, vid).then(function (result) {
        if (!result.ok) return false;
        try {
          state = getMotor().createState(result.context);
        } catch (e) {
          setMsg('Sıralama verisi geçersiz.', 'error');
          return false;
        }
        editMode = true;
        setMsg('', '');
        renderEditStopList();
        restorePanelTitle();
        return true;
      });
    }

    function exitEditMode() {
      editMode = false;
      state = null;
      boundPlanId = null;
      boundVehicleId = null;
      dragSourceId = null;
      setMsg('', '');
      restorePanelTitle();
      var wrap = qs('atpStopListWrap');
      if (wrap) wrap.classList.remove('atp-mr-editing');
      renderToolbar();
    }

    function discardDraft() {
      if (!state || !motorReady()) {
        exitEditMode();
        return Promise.resolve(true);
      }
      state = getMotor().discardDraft(state);
      exitEditMode();
      return Promise.resolve(true);
    }

    function validateSaveSideEffects(body) {
      if (!body || body.ok !== true) return false;
      if (typeof body.route_state_invalidated !== 'boolean') return false;
      if (typeof body.snapshot_deactivated !== 'boolean') return false;
      if (typeof body.etas_cleared !== 'boolean') return false;
      return true;
    }

    function applySave() {
      if (!state || !motorReady()) return Promise.resolve(false);
      var motor = getMotor();
      if (!motor.isDirty(state)) return Promise.resolve(false);
      if (state.conflicted) return Promise.resolve({ ok: false, conflict: true });
      if (state.saving) return Promise.resolve(false);
      var payloadWrap = motor.buildApplyPayload(state);
      if (!payloadWrap.ok) return Promise.resolve(false);
      var begin = motor.beginSave(state);
      if (!begin.result.ok) return Promise.resolve(false);
      state = begin.state;
      renderToolbar();
      var body = Object.assign({}, payloadWrap.payload, {
        date: deps.getPlanDate() || undefined,
        vehicle_id: deps.getVehicleId() || undefined,
      });
      return fetchJson(APPLY_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }).then(function (res) {
        if (res.status === 409) {
          var code = res.body && (res.body.code || (res.body.error && res.body.error.code));
          if (code === 'PLAN_STATE_CONFLICT') {
            state = motor.applyConflict(state, {
              code: code,
              message: CONFLICT_MSG,
            });
            renderEditStopList();
            return { ok: false, conflict: true, body: res.body };
          }
          var policyMsg = (res.body && (res.body.error || res.body.message)) || 'Sıralama kaydedilemedi.';
          state = motor.applySaveFailure(state, { code: code || 'POLICY_ERROR', message: policyMsg });
          setMsg(String(policyMsg), 'error');
          renderToolbar();
          return { ok: false, body: res.body, status: res.status };
        }
        if (!res.ok || !validateSaveSideEffects(res.body)) {
          state = motor.applySaveFailure(state, {
            code: motor.CODES.INVALID_SAVE_RESPONSE,
            message: (res.body && (res.body.error || res.body.message)) || 'Kayıt başarısız',
          });
          setMsg(String(state.lastError.message), 'error');
          renderToolbar();
          return { ok: false, body: res.body, status: res.status };
        }
        var saved = motor.applySaveSuccess(state, res.body);
        if (!saved.result.ok) {
          state = saved.state;
          setMsg(saved.result.message || 'Kayıt yanıtı geçersiz.', 'error');
          renderToolbar();
          return { ok: false, body: res.body };
        }
        state = saved.state;
        deps.toast(SUCCESS_MSG);
        exitEditMode();
        return deps.loadOps().then(function () {
          return { ok: true, body: res.body };
        });
      }).catch(function (err) {
        state = motor.applySaveFailure(state, { message: err && err.message ? err.message : 'network' });
        setMsg('Bağlantı hatası.', 'error');
        renderToolbar();
        return { ok: false, error: err };
      });
    }

    function reloadAfterConflict() {
      if (!boundPlanId) return Promise.resolve(false);
      return fetchContext(boundPlanId, boundVehicleId).then(function (result) {
        if (!result.ok) return false;
        state = getMotor().replaceFromContext(state, result.context);
        setMsg('', '');
        renderEditStopList();
        return true;
      });
    }

    function guardDirtyNavigation() {
      if (!editMode || !isDirty()) return true;
      return deps.confirmFn(NAV_GUARD_MSG);
    }

    function guardNavigation(kind, nextId) {
      if (!editMode) return true;
      if (kind === 'vehicle' && String(nextId) === String(boundVehicleId)) return true;
      if (kind === 'plan' && String(nextId) === String(boundPlanId)) return true;
      if (!isDirty()) {
        exitEditMode();
        return true;
      }
      if (!guardDirtyNavigation()) return false;
      exitEditMode();
      return true;
    }

    function cleanup() {
      contextReqSeq += 1;
      activeContextReq = null;
      exitEditMode();
    }

    function onToolbarClick(ev) {
      var t = ev.target;
      if (!t || !t.id) return;
      if (t.id === 'atpBtnManualReorderEdit') {
        enterEditMode();
      } else if (t.id === 'atpBtnManualReorderApply') {
        if (t.disabled) return;
        applySave();
      } else if (t.id === 'atpBtnManualReorderDiscard') {
        discardDraft().then(function () {
          if (deps.onDiscard) deps.onDiscard(lastTasks, lastPlate);
        });
      } else if (t.id === 'atpBtnManualReorderReload') {
        reloadAfterConflict();
      }
    }

    function bindChromeEvents() {
      if (eventsBound || !deps.document) return;
      eventsBound = true;
      deps.document.addEventListener('click', function (ev) {
        var t = ev.target;
        if (!t) return;
        if (t.id === 'atpBtnManualReorderEdit' ||
            t.id === 'atpBtnManualReorderApply' ||
            t.id === 'atpBtnManualReorderDiscard' ||
            t.id === 'atpBtnManualReorderReload') {
          onToolbarClick(ev);
        }
      });
    }

    function afterBaseRender(tasks, plate) {
      lastTasks = tasks || [];
      lastPlate = plate || '';
      if (editMode) {
        if (String(deps.getVehicleId()) !== String(boundVehicleId) ||
            String(deps.getPlanId()) !== String(boundPlanId)) {
          cleanup();
        } else {
          renderEditStopList();
          return;
        }
      }
      var wrap = qs('atpStopListWrap');
      if (wrap) wrap.classList.remove('atp-mr-editing');
      renderToolbar();
      bindChromeEvents();
    }

    function init() {
      bindChromeEvents();
      renderToolbar();
    }

    return {
      init: init,
      isEditMode: isEditMode,
      isDirty: isDirty,
      afterBaseRender: afterBaseRender,
      guardNavigation: guardNavigation,
      guardDirtyNavigation: guardDirtyNavigation,
      cleanup: cleanup,
      enterEditMode: enterEditMode,
      exitEditMode: exitEditMode,
      discardDraft: discardDraft,
      applySave: applySave,
      reloadAfterConflict: reloadAfterConflict,
      fetchContext: fetchContext,
      renderEditStopList: renderEditStopList,
      lockLabel: lockLabel,
      escHtml: escHtml,
      _internal: {
        getState: function () { return state; },
        setState: function (s) { state = s; editMode = !!s; },
        getFetchLog: function () { return fetchLog.slice(); },
        resetFetchLog: function () { fetchLog = []; },
        tasksInDraftOrder: tasksInDraftOrder,
        buildStopRowHtml: buildStopRowHtml,
        rowMeta: rowMeta,
        CONTEXT_URL: CONTEXT_URL,
        APPLY_URL: APPLY_URL,
        SUCCESS_MSG: SUCCESS_MSG,
        CONFLICT_MSG: CONFLICT_MSG,
        EDIT_HINT: EDIT_HINT,
        DIRTY_INFO: DIRTY_INFO,
        getDomStopIds: function () {
          var wrap = qs('atpStopListWrap');
          if (!wrap) return [];
          var nodes = wrap.querySelectorAll('.stop-item[data-item-id]');
          return Array.prototype.map.call(nodes, function (n) { return n.getAttribute('data-item-id'); });
        },
      },
    };
  }

  var singleton = null;

  return {
    init: function (deps) {
      singleton = createController(deps);
      singleton.init();
      return singleton;
    },
    createController: createController,
    lockLabel: lockLabel,
    escHtml: escHtml,
    isEditMode: function () { return singleton ? singleton.isEditMode() : false; },
    afterBaseRender: function (tasks, plate) {
      if (singleton) singleton.afterBaseRender(tasks, plate);
    },
    guardNavigation: function (kind, nextId) {
      return singleton ? singleton.guardNavigation(kind, nextId) : true;
    },
    guardDirtyNavigation: function () {
      return singleton ? singleton.guardDirtyNavigation() : true;
    },
    cleanup: function () {
      if (singleton) singleton.cleanup();
    },
  };
}));
