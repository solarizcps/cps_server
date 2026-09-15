/**
 * ATP — Manual reorder pure state machine (U3D1).
 * No fetch, no DOM. Browser + Node compatible.
 */
(function (root, factory) {
  'use strict';
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.ATP_MANUAL_REORDER = factory();
  }
}(typeof globalThis !== 'undefined' ? globalThis : typeof window !== 'undefined' ? window : this, function () {
  'use strict';

  var CODES = {
    INVALID_CONTEXT: 'INVALID_CONTEXT',
    INVALID_TASK_ID: 'INVALID_TASK_ID',
    TASK_LOCKED: 'TASK_LOCKED',
    SEGMENT_BOUNDARY: 'SEGMENT_BOUNDARY',
    NO_MOVEMENT: 'NO_MOVEMENT',
    NOT_DIRTY: 'NOT_DIRTY',
    SAVE_IN_PROGRESS: 'SAVE_IN_PROGRESS',
    STATE_CONFLICT: 'STATE_CONFLICT',
    INVALID_SAVE_RESPONSE: 'INVALID_SAVE_RESPONSE',
    PLAN_MISMATCH: 'PLAN_MISMATCH',
    TASK_SET_MISMATCH: 'TASK_SET_MISMATCH',
    MISSING_STATE_TOKEN: 'MISSING_STATE_TOKEN',
  };

  function fail(code, message, extra) {
    var out = { ok: false, code: code, message: message || code, changed: false };
    if (extra) {
      Object.keys(extra).forEach(function (k) { out[k] = extra[k]; });
    }
    return out;
  }

  function okResult(changed, extra) {
    var out = { ok: true, changed: !!changed };
    if (extra) {
      Object.keys(extra).forEach(function (k) { out[k] = extra[k]; });
    }
    return out;
  }

  function cloneArray(arr) {
    return arr.slice();
  }

  function cloneTasksById(map) {
    var out = {};
    Object.keys(map).forEach(function (key) {
      var t = map[key];
      out[key] = {
        task_id: t.task_id,
        order_no: t.order_no,
        can_move: !!t.can_move,
        lock_reason: t.lock_reason == null ? null : t.lock_reason,
        segment_index: t.segment_index,
        visible: t.visible !== false,
        priority: t.priority || null,
      };
    });
    return out;
  }

  function cloneState(state) {
    return {
      planId: state.planId,
      stateToken: state.stateToken,
      persistedOrder: cloneArray(state.persistedOrder),
      draftOrder: cloneArray(state.draftOrder),
      tasksById: cloneTasksById(state.tasksById),
      dirty: !!state.dirty,
      saving: !!state.saving,
      conflicted: !!state.conflicted,
      lastError: state.lastError ? {
        code: state.lastError.code,
        message: state.lastError.message,
      } : null,
    };
  }

  function normalizeContext(context) {
    if (!context || typeof context !== 'object') {
      throw makeError(CODES.INVALID_CONTEXT, 'Context must be an object');
    }
    if (!context.plan_id && context.plan_id !== 0) {
      throw makeError(CODES.INVALID_CONTEXT, 'Missing plan_id');
    }
    if (!context.state_token || String(context.state_token).trim() === '') {
      throw makeError(CODES.MISSING_STATE_TOKEN, 'Missing state_token');
    }
    if (!Array.isArray(context.ordered_item_ids)) {
      throw makeError(CODES.INVALID_CONTEXT, 'ordered_item_ids must be an array');
    }
    if (!Array.isArray(context.tasks)) {
      throw makeError(CODES.INVALID_CONTEXT, 'tasks must be an array');
    }
    return context;
  }

  function makeError(code, message) {
    var err = new Error(message || code);
    err.code = code;
    return err;
  }

  function buildSegmentIndices(ordered, tasksById) {
    var segmentByTask = {};
    var segmentIndex = 0;
    var index = 0;
    while (index < ordered.length) {
      var tid = ordered[index];
      if (!tasksById[tid].can_move) {
        segmentByTask[tid] = segmentIndex;
        segmentIndex += 1;
        index += 1;
        continue;
      }
      while (index < ordered.length && tasksById[ordered[index]].can_move) {
        segmentByTask[ordered[index]] = segmentIndex;
        index += 1;
      }
      segmentIndex += 1;
    }
    return segmentByTask;
  }

  function applySegmentIndices(ordered, tasksById) {
    var segmentByTask = buildSegmentIndices(ordered, tasksById);
    ordered.forEach(function (id) {
      if (tasksById[id]) {
        tasksById[id].segment_index = segmentByTask[id];
      }
    });
  }

  function buildTasksById(context) {
    var ordered = context.ordered_item_ids.map(String);
    var seen = {};
    ordered.forEach(function (id) {
      if (seen[id]) {
        throw makeError(CODES.INVALID_CONTEXT, 'Duplicate ordered_item_ids: ' + id);
      }
      seen[id] = true;
    });

    var tasksById = {};
    context.tasks.forEach(function (task, index) {
      if (!task || typeof task !== 'object') {
        throw makeError(CODES.INVALID_CONTEXT, 'Task at index ' + index + ' must be object');
      }
      var tid = String(task.task_id || '');
      if (!tid) {
        throw makeError(CODES.INVALID_CONTEXT, 'Missing task_id at index ' + index);
      }
      if (tasksById[tid]) {
        throw makeError(CODES.INVALID_CONTEXT, 'Duplicate task_id: ' + tid);
      }
      tasksById[tid] = {
        task_id: tid,
        order_no: task.order_no,
        can_move: !!task.can_move,
        lock_reason: task.lock_reason == null ? null : String(task.lock_reason),
        segment_index: task.segment_index,
        visible: task.visible !== false,
        priority: task.priority || null,
      };
    });

    var orderedSet = {};
    ordered.forEach(function (id) { orderedSet[id] = true; });
    var taskIds = Object.keys(tasksById);
    if (taskIds.length !== ordered.length) {
      throw makeError(CODES.TASK_SET_MISMATCH, 'Task set mismatch between ordered_item_ids and tasks');
    }
    for (var i = 0; i < ordered.length; i += 1) {
      if (!tasksById[ordered[i]]) {
        throw makeError(CODES.TASK_SET_MISMATCH, 'Unknown task in ordered_item_ids: ' + ordered[i]);
      }
    }
    for (var j = 0; j < taskIds.length; j += 1) {
      if (!orderedSet[taskIds[j]]) {
        throw makeError(CODES.TASK_SET_MISMATCH, 'Task missing from ordered_item_ids: ' + taskIds[j]);
      }
    }
    return tasksById;
  }

  function createState(context) {
    var ctx = normalizeContext(context);
    var ordered = ctx.ordered_item_ids.map(String);
    var tasksById = buildTasksById(ctx);
    applySegmentIndices(ordered, tasksById);
    return {
      planId: Number(ctx.plan_id),
      stateToken: String(ctx.state_token),
      persistedOrder: cloneArray(ordered),
      draftOrder: cloneArray(ordered),
      tasksById: tasksById,
      dirty: false,
      saving: false,
      conflicted: false,
      lastError: null,
    };
  }

  function getStateSnapshot(state) {
    return cloneState(state);
  }

  function getTask(state, taskId) {
    var tid = String(taskId || '');
    if (!state.tasksById[tid]) {
      return null;
    }
    return cloneTasksById({ only: state.tasksById[tid] }).only;
  }

  function canMoveTask(state, taskId) {
    var task = state.tasksById[String(taskId || '')];
    if (!task) {
      return false;
    }
    return task.can_move === true && (task.lock_reason == null || task.lock_reason === '');
  }

  function isDirty(state) {
    if (!state.dirty) {
      return false;
    }
    return !arraysEqual(state.draftOrder, state.persistedOrder);
  }

  function arraysEqual(a, b) {
    if (!a || !b || a.length !== b.length) {
      return false;
    }
    for (var i = 0; i < a.length; i += 1) {
      if (a[i] !== b[i]) {
        return false;
      }
    }
    return true;
  }

  function recomputeDirty(next) {
    next.dirty = !arraysEqual(next.draftOrder, next.persistedOrder);
    return next;
  }

  function withDraftOrder(state, draftOrder) {
    var next = cloneState(state);
    next.draftOrder = cloneArray(draftOrder);
    recomputeDirty(next);
    return next;
  }

  function segmentOf(state, taskId) {
    var task = state.tasksById[String(taskId || '')];
    if (!task || task.segment_index == null || task.segment_index === undefined) {
      return null;
    }
    return Number(task.segment_index);
  }

  function assertMovableSource(state, sourceId) {
    var tid = String(sourceId || '');
    var task = state.tasksById[tid];
    if (!task) {
      return fail(CODES.INVALID_TASK_ID, 'Unknown source task', { task_id: tid });
    }
    if (!canMoveTask(state, tid)) {
      return fail(CODES.TASK_LOCKED, 'Source task is locked', { task_id: tid, lock_reason: task.lock_reason });
    }
    var seg = segmentOf(state, tid);
    if (seg == null) {
      return fail(CODES.SEGMENT_BOUNDARY, 'Source task has no segment', { task_id: tid });
    }
    return { ok: true, task: task, segment: seg };
  }

  function assertSameSegment(state, sourceId, targetId) {
    var sourceSeg = segmentOf(state, sourceId);
    var targetSeg = segmentOf(state, targetId);
    if (sourceSeg == null || targetSeg == null) {
      return fail(CODES.SEGMENT_BOUNDARY, 'Missing segment index', {
        task_id: String(sourceId),
        target_task_id: String(targetId),
      });
    }
    if (sourceSeg !== targetSeg) {
      return fail(CODES.SEGMENT_BOUNDARY, 'Cross-segment movement blocked', {
        task_id: String(sourceId),
        target_task_id: String(targetId),
        segment_index: sourceSeg,
      });
    }
    return okResult(false);
  }

  function removeAt(arr, index) {
    return arr.slice(0, index).concat(arr.slice(index + 1));
  }

  function insertAt(arr, index, value) {
    return arr.slice(0, index).concat([value], arr.slice(index));
  }

  function moveBefore(state, sourceId, targetId) {
    var source = String(sourceId || '');
    var target = String(targetId || '');
    if (source === target) {
      return { state: state, result: okResult(false, { reason: CODES.NO_MOVEMENT }) };
    }
    var check = assertMovableSource(state, source);
    if (!check.ok) {
      return { state: state, result: check };
    }
    if (!state.tasksById[target]) {
      return { state: state, result: fail(CODES.INVALID_TASK_ID, 'Unknown target task', { task_id: target }) };
    }
    if (!canMoveTask(state, target)) {
      return { state: state, result: fail(CODES.TASK_LOCKED, 'Target task is locked', { task_id: target }) };
    }
    var segCheck = assertSameSegment(state, source, target);
    if (!segCheck.ok) {
      return { state: state, result: segCheck };
    }

    var draft = cloneArray(state.draftOrder);
    var from = draft.indexOf(source);
    var to = draft.indexOf(target);
    if (from < 0 || to < 0) {
      return { state: state, result: fail(CODES.INVALID_TASK_ID, 'Task missing from draft order') };
    }
    if (from === to || from === to - 1) {
      return { state: state, result: okResult(false, { reason: CODES.NO_MOVEMENT }) };
    }

    draft = removeAt(draft, from);
    to = draft.indexOf(target);
    draft = insertAt(draft, to, source);

    if (arraysEqual(draft, state.draftOrder)) {
      return { state: state, result: okResult(false, { reason: CODES.NO_MOVEMENT }) };
    }
    return { state: withDraftOrder(state, draft), result: okResult(true) };
  }

  function moveAfter(state, sourceId, targetId) {
    var source = String(sourceId || '');
    var target = String(targetId || '');
    if (source === target) {
      return { state: state, result: okResult(false, { reason: CODES.NO_MOVEMENT }) };
    }
    var check = assertMovableSource(state, source);
    if (!check.ok) {
      return { state: state, result: check };
    }
    if (!state.tasksById[target]) {
      return { state: state, result: fail(CODES.INVALID_TASK_ID, 'Unknown target task', { task_id: target }) };
    }
    if (!canMoveTask(state, target)) {
      return { state: state, result: fail(CODES.TASK_LOCKED, 'Target task is locked', { task_id: target }) };
    }
    var segCheck = assertSameSegment(state, source, target);
    if (!segCheck.ok) {
      return { state: state, result: segCheck };
    }

    var draft = cloneArray(state.draftOrder);
    var from = draft.indexOf(source);
    var to = draft.indexOf(target);
    if (from < 0 || to < 0) {
      return { state: state, result: fail(CODES.INVALID_TASK_ID, 'Task missing from draft order') };
    }
    if (from === to || from === to + 1) {
      return { state: state, result: okResult(false, { reason: CODES.NO_MOVEMENT }) };
    }

    draft = removeAt(draft, from);
    to = draft.indexOf(target);
    draft = insertAt(draft, to + 1, source);

    if (arraysEqual(draft, state.draftOrder)) {
      return { state: state, result: okResult(false, { reason: CODES.NO_MOVEMENT }) };
    }
    return { state: withDraftOrder(state, draft), result: okResult(true) };
  }

  function findMovableNeighbor(state, taskId, direction) {
    var tid = String(taskId || '');
    var draft = state.draftOrder;
    var index = draft.indexOf(tid);
    if (index < 0) {
      return null;
    }
    var seg = segmentOf(state, tid);
    if (seg == null) {
      return null;
    }
    if (direction < 0) {
      for (var i = index - 1; i >= 0; i -= 1) {
        var prevId = draft[i];
        if (!canMoveTask(state, prevId)) {
          return null;
        }
        if (segmentOf(state, prevId) !== seg) {
          return null;
        }
        return prevId;
      }
      return null;
    }
    for (var j = index + 1; j < draft.length; j += 1) {
      var nextId = draft[j];
      if (!canMoveTask(state, nextId)) {
        return null;
      }
      if (segmentOf(state, nextId) !== seg) {
        return null;
      }
      return nextId;
    }
    return null;
  }

  function moveUp(state, taskId) {
    var check = assertMovableSource(state, taskId);
    if (!check.ok) {
      return { state: state, result: check };
    }
    var neighbor = findMovableNeighbor(state, taskId, -1);
    if (!neighbor) {
      return { state: state, result: okResult(false, { reason: CODES.NO_MOVEMENT }) };
    }
    return moveBefore(state, taskId, neighbor);
  }

  function moveDown(state, taskId) {
    var check = assertMovableSource(state, taskId);
    if (!check.ok) {
      return { state: state, result: check };
    }
    var neighbor = findMovableNeighbor(state, taskId, 1);
    if (!neighbor) {
      return { state: state, result: okResult(false, { reason: CODES.NO_MOVEMENT }) };
    }
    return moveAfter(state, taskId, neighbor);
  }

  function discardDraft(state) {
    var next = cloneState(state);
    next.draftOrder = cloneArray(state.persistedOrder);
    next.dirty = false;
    next.saving = false;
    next.conflicted = false;
    next.lastError = null;
    return next;
  }

  function getVisibleDraftOrder(state) {
    return state.draftOrder.filter(function (id) {
      var task = state.tasksById[id];
      return task && task.visible !== false;
    });
  }

  function buildApplyPayload(state) {
    if (!state.stateToken) {
      return fail(CODES.MISSING_STATE_TOKEN, 'Missing state token');
    }
    if (!state.planId && state.planId !== 0) {
      return fail(CODES.INVALID_CONTEXT, 'Missing plan id');
    }
    if (!isDirty(state)) {
      return fail(CODES.NOT_DIRTY, 'Draft is not dirty');
    }
    if (state.saving) {
      return fail(CODES.SAVE_IN_PROGRESS, 'Save already in progress');
    }
    if (state.conflicted) {
      return fail(CODES.STATE_CONFLICT, 'State conflict must be resolved before save');
    }
    return {
      ok: true,
      payload: {
        plan_id: state.planId,
        state_token: state.stateToken,
        ordered_item_ids: cloneArray(state.draftOrder),
      },
    };
  }

  function beginSave(state) {
    if (!isDirty(state)) {
      return { state: state, result: fail(CODES.NOT_DIRTY, 'Nothing to save') };
    }
    if (state.conflicted) {
      return { state: state, result: fail(CODES.STATE_CONFLICT, 'Conflict blocks save') };
    }
    if (state.saving) {
      return { state: state, result: fail(CODES.SAVE_IN_PROGRESS, 'Save already in progress') };
    }
    var next = cloneState(state);
    next.saving = true;
    next.lastError = null;
    return { state: next, result: okResult(true) };
  }

  function validateSaveResponse(state, response) {
    if (!response || typeof response !== 'object' || response.ok !== true) {
      return fail(CODES.INVALID_SAVE_RESPONSE, 'Invalid save response');
    }
    if (Number(response.plan_id) !== Number(state.planId)) {
      return fail(CODES.PLAN_MISMATCH, 'Response plan_id mismatch');
    }
    if (!Array.isArray(response.ordered_item_ids)) {
      return fail(CODES.INVALID_SAVE_RESPONSE, 'Response missing ordered_item_ids');
    }
    var respIds = response.ordered_item_ids.map(String);
    if (respIds.length !== state.persistedOrder.length) {
      return fail(CODES.TASK_SET_MISMATCH, 'Response task count mismatch');
    }
    var seen = {};
    for (var i = 0; i < respIds.length; i += 1) {
      if (seen[respIds[i]]) {
        return fail(CODES.INVALID_SAVE_RESPONSE, 'Duplicate response task id');
      }
      seen[respIds[i]] = true;
      if (!state.tasksById[respIds[i]]) {
        return fail(CODES.TASK_SET_MISMATCH, 'Unknown response task id');
      }
    }
    if (!response.state_token || String(response.state_token).trim() === '') {
      return fail(CODES.INVALID_SAVE_RESPONSE, 'Response missing state_token');
    }
    return {
      ok: true,
      ordered_item_ids: respIds,
      state_token: String(response.state_token),
      changed: response.changed !== false,
    };
  }

  function applySaveSuccess(state, response) {
    var valid = validateSaveResponse(state, response);
    if (!valid.ok) {
      var bad = cloneState(state);
      bad.saving = false;
      bad.lastError = { code: valid.code, message: valid.message };
      return { state: bad, result: valid };
    }
    var next = cloneState(state);
    next.persistedOrder = cloneArray(valid.ordered_item_ids);
    next.draftOrder = cloneArray(valid.ordered_item_ids);
    next.stateToken = valid.state_token;
    next.dirty = false;
    next.saving = false;
    next.conflicted = false;
    next.lastError = null;
    return { state: next, result: okResult(valid.changed) };
  }

  function applySaveFailure(state, error) {
    var next = cloneState(state);
    next.saving = false;
    next.lastError = {
      code: (error && error.code) || CODES.INVALID_SAVE_RESPONSE,
      message: (error && (error.message || error.code)) || 'Save failed',
    };
    return next;
  }

  function applyConflict(state, error) {
    var next = cloneState(state);
    next.saving = false;
    next.conflicted = true;
    next.lastError = {
      code: (error && error.code) || CODES.STATE_CONFLICT,
      message: (error && (error.message || error.code)) || 'Plan state conflict',
    };
    return next;
  }

  function replaceFromContext(state, newContext) {
    var fresh = createState(newContext);
    fresh.saving = false;
    fresh.conflicted = false;
    fresh.lastError = null;
    fresh.dirty = false;
    return fresh;
  }

  return {
    CODES: CODES,
    createState: createState,
    getStateSnapshot: getStateSnapshot,
    getTask: getTask,
    canMoveTask: canMoveTask,
    moveBefore: moveBefore,
    moveAfter: moveAfter,
    moveUp: moveUp,
    moveDown: moveDown,
    discardDraft: discardDraft,
    beginSave: beginSave,
    applySaveSuccess: applySaveSuccess,
    applySaveFailure: applySaveFailure,
    applyConflict: applyConflict,
    buildApplyPayload: buildApplyPayload,
    getVisibleDraftOrder: getVisibleDraftOrder,
    isDirty: isDirty,
    replaceFromContext: replaceFromContext,
    _internal: {
      arraysEqual: arraysEqual,
      cloneState: cloneState,
      buildSegmentIndices: buildSegmentIndices,
      applySegmentIndices: applySegmentIndices,
    },
  };
}));
