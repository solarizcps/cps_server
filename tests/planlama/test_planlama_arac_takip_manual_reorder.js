'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const MR = require(path.resolve(
  __dirname,
  '../../app/static/js/planlama_arac_takip_manual_reorder.js',
));

const C = MR.CODES;

function ctx(overrides) {
  const base = {
    plan_id: 41,
    state_token: 'token-v1',
    ordered_item_ids: ['pi-1', 'pi-2', 'pi-3'],
    tasks: [
      { task_id: 'pi-1', order_no: 1, can_move: true, lock_reason: null, segment_index: 0 },
      { task_id: 'pi-2', order_no: 2, can_move: true, lock_reason: null, segment_index: 0 },
      { task_id: 'pi-3', order_no: 3, can_move: true, lock_reason: null, segment_index: 0 },
    ],
  };
  return Object.assign(base, overrides || {});
}

function task(id, opts) {
  return Object.assign({
    task_id: id,
    order_no: 1,
    can_move: true,
    lock_reason: null,
    segment_index: 0,
  }, opts || {});
}

function segContext(ids, taskDefs) {
  return {
    plan_id: 99,
    state_token: 'tok',
    ordered_item_ids: ids,
    tasks: taskDefs,
  };
}

test('A01 valid context creates state', () => {
  const state = MR.createState(ctx());
  assert.equal(state.planId, 41);
  assert.equal(state.stateToken, 'token-v1');
  assert.deepEqual(state.persistedOrder, ['pi-1', 'pi-2', 'pi-3']);
  assert.deepEqual(state.draftOrder, ['pi-1', 'pi-2', 'pi-3']);
  assert.equal(state.dirty, false);
});

test('A02 createState does not mutate input context', () => {
  const input = ctx();
  const copy = JSON.parse(JSON.stringify(input));
  MR.createState(input);
  assert.deepEqual(input, copy);
});

test('A03 canonical order preserved', () => {
  const state = MR.createState(ctx({
    ordered_item_ids: ['pi-3', 'pi-1', 'pi-2'],
    tasks: [
      task('pi-3', { order_no: 1 }),
      task('pi-1', { order_no: 2 }),
      task('pi-2', { order_no: 3 }),
    ],
  }));
  assert.deepEqual(state.persistedOrder, ['pi-3', 'pi-1', 'pi-2']);
});

test('A04 draft equals persisted initially', () => {
  const state = MR.createState(ctx());
  assert.deepEqual(state.draftOrder, state.persistedOrder);
});

test('A05 token stored', () => {
  const state = MR.createState(ctx({ state_token: 'abc' }));
  assert.equal(state.stateToken, 'abc');
});

test('A06 tasks map built', () => {
  const state = MR.createState(ctx());
  assert.ok(state.tasksById['pi-2']);
  assert.equal(state.tasksById['pi-2'].can_move, true);
});

test('A07 invalid context throws', () => {
  assert.throws(() => MR.createState(null), (err) => err.code === C.INVALID_CONTEXT);
});

test('A08 missing plan throws', () => {
  const bad = ctx();
  delete bad.plan_id;
  assert.throws(() => MR.createState(bad), (err) => err.code === C.INVALID_CONTEXT);
});

test('A09 missing token throws', () => {
  assert.throws(() => MR.createState(ctx({ state_token: '' })), (err) => err.code === C.MISSING_STATE_TOKEN);
});

test('A10 duplicate ordered id throws', () => {
  assert.throws(
    () => MR.createState(ctx({ ordered_item_ids: ['pi-1', 'pi-1'] })),
    (err) => err.code === C.INVALID_CONTEXT,
  );
});

test('A11 task set mismatch throws', () => {
  assert.throws(
    () => MR.createState(ctx({ ordered_item_ids: ['pi-1', 'pi-2'] })),
    (err) => err.code === C.TASK_SET_MISMATCH,
  );
});

test('A12 unknown task in context throws', () => {
  assert.throws(
    () => MR.createState(ctx({ tasks: [task('pi-9')] })),
    (err) => err.code === C.TASK_SET_MISMATCH,
  );
});

test('B13 moveUp swaps with previous movable', () => {
  let state = MR.createState(ctx());
  const out = MR.moveUp(state, 'pi-2');
  assert.equal(out.result.ok, true);
  assert.equal(out.result.changed, true);
  assert.deepEqual(out.state.draftOrder, ['pi-2', 'pi-1', 'pi-3']);
});

test('B14 moveDown swaps with next movable', () => {
  let state = MR.createState(ctx());
  const out = MR.moveDown(state, 'pi-2');
  assert.equal(out.result.ok, true);
  assert.deepEqual(out.state.draftOrder, ['pi-1', 'pi-3', 'pi-2']);
});

test('B15 moveBefore inserts before target', () => {
  const state = MR.createState(ctx());
  const out = MR.moveBefore(state, 'pi-3', 'pi-1');
  assert.equal(out.result.changed, true);
  assert.deepEqual(out.state.draftOrder, ['pi-3', 'pi-1', 'pi-2']);
});

test('B16 moveAfter inserts after target', () => {
  const state = MR.createState(ctx());
  const out = MR.moveAfter(state, 'pi-1', 'pi-3');
  assert.equal(out.result.changed, true);
  assert.deepEqual(out.state.draftOrder, ['pi-2', 'pi-3', 'pi-1']);
});

test('B17 source equals target is no-op', () => {
  const state = MR.createState(ctx());
  const out = MR.moveBefore(state, 'pi-2', 'pi-2');
  assert.equal(out.result.ok, true);
  assert.equal(out.result.changed, false);
  assert.equal(out.result.reason, C.NO_MOVEMENT);
});

test('B18 first element moveUp no-op', () => {
  const state = MR.createState(ctx());
  const out = MR.moveUp(state, 'pi-1');
  assert.equal(out.result.changed, false);
});

test('B19 last element moveDown no-op', () => {
  const state = MR.createState(ctx());
  const out = MR.moveDown(state, 'pi-3');
  assert.equal(out.result.changed, false);
});

test('B20 sequential moves can reverse order', () => {
  let state = MR.createState(ctx());
  state = MR.moveDown(state, 'pi-1').state;
  state = MR.moveDown(state, 'pi-1').state;
  assert.deepEqual(state.draftOrder, ['pi-2', 'pi-3', 'pi-1']);
});

test('C21 locked source cannot move', () => {
  const state = MR.createState(ctx({
    tasks: [
      task('pi-1', { can_move: false, lock_reason: 'STATUS_TAMAMLANDI' }),
      task('pi-2'),
      task('pi-3'),
    ],
  }));
  const out = MR.moveBefore(state, 'pi-1', 'pi-2');
  assert.equal(out.result.ok, false);
  assert.equal(out.result.code, C.TASK_LOCKED);
});

test('C22 arrived-like locked source blocked', () => {
  const state = MR.createState(ctx({
    tasks: [
      task('pi-1'),
      task('pi-2', { can_move: false, lock_reason: 'VISIT_ARRIVED', segment_index: 1 }),
      task('pi-3', { segment_index: 2 }),
    ],
    ordered_item_ids: ['pi-1', 'pi-2', 'pi-3'],
  }));
  const out = MR.moveDown(state, 'pi-2');
  assert.equal(out.result.code, C.TASK_LOCKED);
});

test('C23 segment crossing before blocked', () => {
  const state = MR.createState(segContext(['pi-1', 'pi-2', 'pi-3'], [
    task('pi-1', { segment_index: 0 }),
    task('pi-2', { can_move: false, lock_reason: 'VISIT_ARRIVED', segment_index: 1 }),
    task('pi-3', { segment_index: 2 }),
  ]));
  const out = MR.moveBefore(state, 'pi-3', 'pi-1');
  assert.equal(out.result.code, C.SEGMENT_BOUNDARY);
});

test('C24 segment crossing after blocked', () => {
  const state = MR.createState(segContext(['pi-1', 'pi-2', 'pi-3'], [
    task('pi-1', { segment_index: 0 }),
    task('pi-2', { can_move: false, lock_reason: 'VISIT_ARRIVED', segment_index: 1 }),
    task('pi-3', { segment_index: 2 }),
  ]));
  const out = MR.moveAfter(state, 'pi-1', 'pi-3');
  assert.equal(out.result.code, C.SEGMENT_BOUNDARY);
});

test('C25 hidden inactive anchor preserved', () => {
  const state = MR.createState(segContext(['pi-1', 'pi-2', 'pi-3'], [
    task('pi-1', { segment_index: 0 }),
    task('pi-2', { can_move: false, lock_reason: 'STATUS_INACTIVE', segment_index: 1, visible: false }),
    task('pi-3', { segment_index: 2 }),
  ]));
  assert.equal(state.draftOrder[1], 'pi-2');
  const out = MR.moveBefore(state, 'pi-3', 'pi-2');
  assert.equal(out.result.code, C.TASK_LOCKED);
});

test('C26 hidden anchor index unchanged on failed move', () => {
  const state = MR.createState(segContext(['pi-1', 'pi-2', 'pi-3'], [
    task('pi-1', { segment_index: 0 }),
    task('pi-2', { can_move: false, lock_reason: 'STATUS_INACTIVE', segment_index: 1, visible: false }),
    task('pi-3', { segment_index: 2 }),
  ]));
  const out = MR.moveUp(state, 'pi-3');
  assert.equal(out.state.draftOrder.indexOf('pi-2'), 1);
});

test('C27 multi-segment only target segment changes', () => {
  const state = MR.createState(segContext(['pi-1', 'pi-2', 'pi-3', 'pi-4'], [
    task('pi-1', { can_move: false, lock_reason: 'STATUS_TAMAMLANDI', segment_index: 0 }),
    task('pi-2', { segment_index: 1 }),
    task('pi-3', { segment_index: 1 }),
    task('pi-4', { can_move: false, lock_reason: 'VISIT_ARRIVED', segment_index: 2 }),
  ]));
  const out = MR.moveDown(state, 'pi-2');
  assert.deepEqual(out.state.draftOrder, ['pi-1', 'pi-3', 'pi-2', 'pi-4']);
});

test('C28 other segment locked positions unchanged', () => {
  const state = MR.createState(segContext(['pi-1', 'pi-2', 'pi-3', 'pi-4'], [
    task('pi-1', { can_move: false, lock_reason: 'STATUS_TAMAMLANDI', segment_index: 0 }),
    task('pi-2', { segment_index: 1 }),
    task('pi-3', { segment_index: 1 }),
    task('pi-4', { can_move: false, lock_reason: 'VISIT_ARRIVED', segment_index: 2 }),
  ]));
  const out = MR.moveDown(state, 'pi-2');
  assert.equal(out.state.draftOrder.indexOf('pi-1'), 0);
  assert.equal(out.state.draftOrder.indexOf('pi-4'), 3);
});

test('C29 single-item movable segment moveUp no-op', () => {
  const state = MR.createState(segContext(['pi-1', 'pi-2'], [
    task('pi-1', { can_move: false, lock_reason: 'STATUS_TAMAMLANDI', segment_index: 0 }),
    task('pi-2', { segment_index: 1 }),
  ]));
  const out = MR.moveUp(state, 'pi-2');
  assert.equal(out.result.changed, false);
});

test('C30 missing segment recomputed on createState', () => {
  const state = MR.createState(ctx({
    tasks: [
      task('pi-1', { segment_index: null }),
      task('pi-2'),
      task('pi-3'),
    ],
  }));
  assert.equal(state.tasksById['pi-1'].segment_index, 0);
  const out = MR.moveUp(state, 'pi-1');
  assert.equal(out.result.changed, false);
});

test('D31 ACIL moveUp in same segment', () => {
  const state = MR.createState(ctx({
    tasks: [
      task('pi-1', { priority: 'ACIL' }),
      task('pi-2', { priority: 'NORMAL' }),
      task('pi-3', { priority: 'YUKSEK' }),
    ],
  }));
  const out = MR.moveDown(state, 'pi-1');
  assert.equal(out.result.changed, true);
});

test('D32 ACIL moveDown in same segment', () => {
  const state = MR.createState(ctx({
    tasks: [
      task('pi-1', { priority: 'ACIL' }),
      task('pi-2', { priority: 'NORMAL' }),
      task('pi-3', { priority: 'ACIL' }),
    ],
  }));
  const out = MR.moveDown(state, 'pi-1');
  assert.equal(out.result.changed, true);
});

test('D33 two ACIL swap', () => {
  const state = MR.createState(ctx({
    ordered_item_ids: ['pi-1', 'pi-2', 'pi-3'],
    tasks: [
      task('pi-1', { priority: 'ACIL' }),
      task('pi-2', { priority: 'ACIL' }),
      task('pi-3', { priority: 'NORMAL' }),
    ],
  }));
  const out = MR.moveDown(state, 'pi-1');
  assert.deepEqual(out.state.draftOrder, ['pi-2', 'pi-1', 'pi-3']);
});

test('D34 ACIL cannot cross locked boundary', () => {
  const state = MR.createState(segContext(['pi-1', 'pi-2', 'pi-3'], [
    task('pi-1', { priority: 'ACIL', segment_index: 0 }),
    task('pi-2', { can_move: false, lock_reason: 'VISIT_ARRIVED', segment_index: 1 }),
    task('pi-3', { priority: 'NORMAL', segment_index: 2 }),
  ]));
  const out = MR.moveBefore(state, 'pi-3', 'pi-1');
  assert.equal(out.result.code, C.SEGMENT_BOUNDARY);
});

test('D35 priority field does not affect canMoveTask', () => {
  const state = MR.createState(ctx({
    tasks: [
      task('pi-1', { priority: 'DUSUK', can_move: true }),
      task('pi-2', { priority: 'ACIL', can_move: true }),
      task('pi-3', { priority: 'YUKSEK', can_move: true }),
    ],
  }));
  assert.equal(MR.canMoveTask(state, 'pi-1'), true);
  assert.equal(MR.canMoveTask(state, 'pi-2'), true);
});

test('E36 initial state is clean', () => {
  const state = MR.createState(ctx());
  assert.equal(MR.isDirty(state), false);
});

test('E37 valid move marks dirty', () => {
  const state = MR.moveUp(MR.createState(ctx()), 'pi-2').state;
  assert.equal(MR.isDirty(state), true);
});

test('E38 return to original order clears dirty', () => {
  let state = MR.createState(ctx());
  state = MR.moveUp(state, 'pi-2').state;
  state = MR.moveDown(state, 'pi-2').state;
  assert.equal(MR.isDirty(state), false);
});

test('E39 discard restores persisted', () => {
  let state = MR.moveUp(MR.createState(ctx()), 'pi-3').state;
  state = MR.discardDraft(state);
  assert.deepEqual(state.draftOrder, state.persistedOrder);
  assert.equal(state.dirty, false);
  assert.equal(state.conflicted, false);
});

test('E40 no-op move does not change dirty', () => {
  const base = MR.createState(ctx());
  const out = MR.moveUp(base, 'pi-1');
  assert.equal(MR.isDirty(out.state), false);
});

test('E41 multiple moves accumulate dirty', () => {
  let state = MR.createState(ctx());
  state = MR.moveDown(state, 'pi-1').state;
  state = MR.moveDown(state, 'pi-1').state;
  assert.equal(MR.isDirty(state), true);
});

test('E42 prior state not mutated after move', () => {
  const before = MR.createState(ctx());
  const copy = MR.getStateSnapshot(before);
  MR.moveUp(before, 'pi-2');
  assert.deepEqual(before.draftOrder, copy.draftOrder);
});

test('F43 payload contains full id set', () => {
  let state = MR.moveUp(MR.createState(ctx()), 'pi-2').state;
  const payload = MR.buildApplyPayload(state);
  assert.equal(payload.ok, true);
  assert.deepEqual(payload.payload.ordered_item_ids, state.draftOrder);
  assert.equal(payload.payload.ordered_item_ids.length, 3);
});

test('F44 hidden inactive id stays in payload', () => {
  const state = MR.createState(segContext(['pi-1', 'pi-2', 'pi-3', 'pi-4', 'pi-5'], [
    task('pi-1', { can_move: false, lock_reason: 'STATUS_TAMAMLANDI', segment_index: 0 }),
    task('pi-2', { segment_index: 1 }),
    task('pi-3', { segment_index: 1 }),
    task('pi-4', { can_move: false, lock_reason: 'STATUS_INACTIVE', segment_index: 2, visible: false }),
    task('pi-5', { segment_index: 3 }),
  ]));
  const moved = MR.moveDown(state, 'pi-2').state;
  const payload = MR.buildApplyPayload(moved);
  assert.equal(payload.ok, true);
  assert.ok(payload.payload.ordered_item_ids.includes('pi-4'));
});

test('F45 missing token blocks payload', () => {
  const state = MR.createState(ctx());
  state.stateToken = '';
  const payload = MR.buildApplyPayload(Object.assign({}, state, { dirty: true }));
  assert.equal(payload.code, C.MISSING_STATE_TOKEN);
});

test('F46 not dirty blocks payload', () => {
  const payload = MR.buildApplyPayload(MR.createState(ctx()));
  assert.equal(payload.code, C.NOT_DIRTY);
});

test('F47 beginSave sets saving', () => {
  let state = MR.moveUp(MR.createState(ctx()), 'pi-2').state;
  const out = MR.beginSave(state);
  assert.equal(out.result.ok, true);
  assert.equal(out.state.saving, true);
});

test('F48 double save blocked', () => {
  let state = MR.beginSave(MR.moveUp(MR.createState(ctx()), 'pi-2').state).state;
  const payload = MR.buildApplyPayload(state);
  assert.equal(payload.code, C.SAVE_IN_PROGRESS);
});

test('F49 applySaveSuccess updates persisted', () => {
  let state = MR.beginSave(MR.moveUp(MR.createState(ctx()), 'pi-2').state).state;
  const out = MR.applySaveSuccess(state, {
    ok: true,
    plan_id: 41,
    state_token: 'token-v2',
    ordered_item_ids: ['pi-2', 'pi-1', 'pi-3'],
    changed: true,
  });
  assert.equal(out.result.ok, true);
  assert.deepEqual(out.state.persistedOrder, ['pi-2', 'pi-1', 'pi-3']);
  assert.equal(out.state.stateToken, 'token-v2');
});

test('F50 success stores new token', () => {
  const state = MR.beginSave(MR.moveDown(MR.createState(ctx()), 'pi-1').state).state;
  const out = MR.applySaveSuccess(state, {
    ok: true,
    plan_id: 41,
    state_token: 'new-token',
    ordered_item_ids: ['pi-2', 'pi-1', 'pi-3'],
    changed: true,
  });
  assert.equal(out.state.stateToken, 'new-token');
});

test('F51 bad success response fail-closed', () => {
  const state = MR.beginSave(MR.moveUp(MR.createState(ctx()), 'pi-2').state).state;
  const out = MR.applySaveSuccess(state, { ok: true, plan_id: 41 });
  assert.equal(out.result.code, C.INVALID_SAVE_RESPONSE);
  assert.equal(out.state.saving, false);
});

test('F52 plan mismatch rejected', () => {
  const state = MR.beginSave(MR.moveUp(MR.createState(ctx()), 'pi-2').state).state;
  const out = MR.applySaveSuccess(state, {
    ok: true,
    plan_id: 999,
    state_token: 'x',
    ordered_item_ids: ['pi-2', 'pi-1', 'pi-3'],
  });
  assert.equal(out.result.code, C.PLAN_MISMATCH);
});

test('F53 task set mismatch on response', () => {
  const state = MR.beginSave(MR.moveUp(MR.createState(ctx()), 'pi-2').state).state;
  const out = MR.applySaveSuccess(state, {
    ok: true,
    plan_id: 41,
    state_token: 'x',
    ordered_item_ids: ['pi-2', 'pi-1'],
  });
  assert.equal(out.result.code, C.TASK_SET_MISMATCH);
});

test('F54 failure keeps draft', () => {
  let state = MR.moveUp(MR.createState(ctx()), 'pi-2').state;
  const draft = state.draftOrder.slice();
  state = MR.beginSave(state).state;
  const after = MR.applySaveFailure(state, { code: 'NETWORK', message: 'fail' });
  assert.deepEqual(after.draftOrder, draft);
});

test('F55 failure keeps persisted', () => {
  const base = MR.createState(ctx());
  let state = MR.moveUp(base, 'pi-2').state;
  state = MR.beginSave(state).state;
  const after = MR.applySaveFailure(state, { code: 'NETWORK', message: 'fail' });
  assert.deepEqual(after.persistedOrder, base.persistedOrder);
});

test('G56 conflict marks conflicted', () => {
  let state = MR.beginSave(MR.moveUp(MR.createState(ctx()), 'pi-2').state).state;
  const after = MR.applyConflict(state, { code: C.STATE_CONFLICT, message: 'stale' });
  assert.equal(after.conflicted, true);
  assert.equal(after.lastError.code, C.STATE_CONFLICT);
});

test('G57 conflict blocks save', () => {
  let state = MR.applyConflict(MR.moveUp(MR.createState(ctx()), 'pi-2').state, { code: C.STATE_CONFLICT });
  const payload = MR.buildApplyPayload(state);
  assert.equal(payload.code, C.STATE_CONFLICT);
});

test('G58 conflict preserves draft for comparison', () => {
  const moved = MR.moveUp(MR.createState(ctx()), 'pi-3').state;
  const after = MR.applyConflict(moved, { code: C.STATE_CONFLICT });
  assert.deepEqual(after.draftOrder, moved.draftOrder);
});

test('G59 replaceFromContext resets state', () => {
  let state = MR.applyConflict(MR.moveUp(MR.createState(ctx()), 'pi-2').state, { code: C.STATE_CONFLICT });
  const fresh = MR.replaceFromContext(state, ctx({
    state_token: 'token-v3',
    ordered_item_ids: ['pi-1', 'pi-3', 'pi-2'],
    tasks: [
      task('pi-1', { order_no: 1 }),
      task('pi-3', { order_no: 2 }),
      task('pi-2', { order_no: 3 }),
    ],
  }));
  assert.equal(fresh.conflicted, false);
  assert.deepEqual(fresh.draftOrder, ['pi-1', 'pi-3', 'pi-2']);
});

test('G60 replaceFromContext updates token', () => {
  const fresh = MR.replaceFromContext(MR.createState(ctx()), ctx({ state_token: 'fresh-token' }));
  assert.equal(fresh.stateToken, 'fresh-token');
});

test('G61 replaceFromContext uses canonical order', () => {
  const fresh = MR.replaceFromContext(MR.createState(ctx()), ctx({
    ordered_item_ids: ['pi-3', 'pi-1', 'pi-2'],
    tasks: [
      task('pi-3', { order_no: 1 }),
      task('pi-1', { order_no: 2 }),
      task('pi-2', { order_no: 3 }),
    ],
  }));
  assert.deepEqual(fresh.persistedOrder, ['pi-3', 'pi-1', 'pi-2']);
});

test('G62 replaceFromContext clears conflict', () => {
  const conflicted = MR.applyConflict(MR.createState(ctx()), { code: C.STATE_CONFLICT });
  const fresh = MR.replaceFromContext(conflicted, ctx({ state_token: 'new' }));
  assert.equal(fresh.conflicted, false);
  assert.equal(fresh.lastError, null);
});

test('Extra visible draft order hides inactive only', () => {
  const state = MR.createState(segContext(['pi-1', 'pi-2', 'pi-3'], [
    task('pi-1', { segment_index: 0 }),
    task('pi-2', { can_move: false, lock_reason: 'STATUS_INACTIVE', segment_index: 1, visible: false }),
    task('pi-3', { segment_index: 2 }),
  ]));
  assert.deepEqual(MR.getVisibleDraftOrder(state), ['pi-1', 'pi-3']);
});

test('Extra getTask unknown returns null', () => {
  const state = MR.createState(ctx());
  assert.equal(MR.getTask(state, 'pi-9'), null);
});

test('Extra snapshot is deep clone', () => {
  const state = MR.createState(ctx());
  const snap = MR.getStateSnapshot(state);
  snap.draftOrder.push('pi-9');
  assert.notDeepEqual(snap.draftOrder, state.draftOrder);
});

test('Extra segment indices recomputed from lock boundaries', () => {
  const state = MR.createState(segContext(['a', 'b', 'c', 'd'], [
    task('a', { segment_index: 0 }),
    task('b', { segment_index: 0 }),
    task('c', { can_move: false, lock_reason: 'STATUS_TAMAMLANDI', segment_index: 0 }),
    task('d', { segment_index: 0 }),
  ]));
  assert.equal(state.tasksById.c.segment_index, 1);
  assert.equal(state.tasksById.d.segment_index, 2);
});

test('Extra moveDown cannot cross middle locked task with bad fixture segments', () => {
  const state = MR.createState(segContext(['pi-1', 'pi-2', 'pi-3', 'pi-4'], [
    task('pi-1', { priority: 'ACIL', segment_index: 0 }),
    task('pi-2', { segment_index: 0 }),
    task('pi-3', { can_move: false, lock_reason: 'STATUS_TAMAMLANDI', segment_index: 0 }),
    task('pi-4', { segment_index: 0 }),
  ]));
  const before = state.draftOrder.slice();
  const out = MR.moveDown(state, 'pi-2');
  assert.equal(out.result.ok, true);
  assert.equal(out.result.changed, false);
  assert.deepEqual(out.state.draftOrder, before);
});
