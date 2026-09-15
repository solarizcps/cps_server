'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const MR = require(path.resolve(
  __dirname,
  '../../app/static/js/planlama_arac_takip_manual_reorder.js',
));

const C = MR.CODES;
const PY = process.env.PYTHON || 'python';
const HELPER = path.resolve(__dirname, '_parity_helper.py');
const REPO = path.resolve(__dirname, '../..');
const APP_ROOT = path.join(REPO, 'app');

function py(op, payload) {
  const res = spawnSync(PY, [HELPER], {
    cwd: REPO,
    env: Object.assign({}, process.env, { PYTHONPATH: APP_ROOT }),
    input: JSON.stringify(Object.assign({ op }, payload)),
    encoding: 'utf8',
  });
  assert.equal(res.status, 0, res.stderr || res.stdout);
  return JSON.parse(res.stdout.trim());
}

function jsContextFromPyTasks(tasks, token) {
  return py('context', { tasks, token: token || 'parity' });
}

function backendValidate(tasks, proposed) {
  return py('validate', { tasks, proposed });
}

function applyMoves(context, moves) {
  let state = MR.createState(context);
  const before = MR.getStateSnapshot(state);
  const results = [];
  moves.forEach((move) => {
    const fn = MR[move.fn];
    assert.ok(fn, `unknown move fn ${move.fn}`);
    const out = fn(state, move.id, move.target);
    results.push(out.result);
    state = out.state;
  });
  return { state, before, results, proposed: state.draftOrder.slice() };
}

function pt(id, opts = {}) {
  const row = { id, status: opts.status || 'PLANLANDI', priority: opts.priority || 'NORMAL' };
  if (opts.visit_state != null) row.visit_state = opts.visit_state;
  if (opts.arrived_at != null) row.arrived_at = opts.arrived_at;
  if (opts.departed_at != null) row.departed_at = opts.departed_at;
  if (opts.visible != null) row.visible = opts.visible;
  return row;
}

function parityScenario(name, tasks, spec) {
  test(`P ${name}`, () => {
    const context = jsContextFromPyTasks(tasks, name);
    let jsOk = true;
    let jsCode = null;
    let proposed = spec.proposed;

    if (spec.moves) {
      const run = applyMoves(context, spec.moves);
      proposed = run.proposed;
      const last = run.results[run.results.length - 1];
      jsOk = !!(last && last.ok !== false);
      if (!jsOk) jsCode = last && last.code;
      if (spec.expectReject) {
        assert.equal(last.changed, false, `${name}: move should not change draft`);
        assert.deepEqual(proposed, context.ordered_item_ids, `${name}: reject must preserve order`);
        const beCanonical = backendValidate(tasks, proposed);
        assert.equal(beCanonical.ok, true, `${name}: canonical draft must stay valid`);
        if (spec.invalidProposed) {
          const bad = backendValidate(tasks, spec.invalidProposed);
          assert.equal(bad.ok, false, `${name}: invalid order should fail backend`);
          if (spec.expectCode) assert.equal(bad.code, spec.expectCode, `${name}: backend code`);
        }
        assert.notEqual(jsOk && last.changed, true, `${name}: frontend must reject cross-boundary move`);
        return;
      }
    }

    const be = backendValidate(tasks, proposed);
    if (spec.expectOk) {
      assert.equal(be.ok, true, `${name}: backend rejected ${be.code}`);
      if (spec.moves && spec.expectChanged !== false) {
        assert.notDeepEqual(proposed, context.ordered_item_ids, `${name}: expected dirty draft`);
      }
    } else {
      assert.equal(be.ok, false, `${name}: backend should reject`);
      if (spec.expectCode) assert.equal(be.code, spec.expectCode, `${name}: backend code`);
    }

    if (spec.moves) {
      assert.equal(jsOk, spec.expectOk !== false, `${name}: frontend/backend move parity`);
    }
  });
}

parityScenario('01 all movable reverse', [pt('a'), pt('b'), pt('c')], {
  proposed: ['c', 'b', 'a'],
  expectOk: true,
});

parityScenario('02 completed prefix swap', [pt('a', { status: 'TAMAMLANDI' }), pt('b'), pt('c')], {
  proposed: ['a', 'c', 'b'],
  expectOk: true,
});

parityScenario('03 arrived middle boundary', [pt('a'), pt('b', { visit_state: 'ARRIVED' }), pt('c')], {
  proposed: ['c', 'b', 'a'],
  expectOk: false,
  expectCode: 'SEGMENT_BOUNDARY_CROSS',
});

parityScenario('04 basladi middle locked', [pt('a'), pt('b', { status: 'BASLADI' }), pt('c')], {
  proposed: ['a', 'c', 'b'],
  expectOk: false,
  expectCode: 'LOCKED_TASK_MOVE',
});

parityScenario('05 departed pending middle', [pt('a'), pt('b', { visit_state: 'DEPARTED_PENDING' }), pt('c')], {
  proposed: ['c', 'b', 'a'],
  expectOk: false,
  expectCode: 'SEGMENT_BOUNDARY_CROSS',
});

parityScenario('06 inactive hidden middle', [pt('a'), pt('b', { status: 'IPTAL' }), pt('c')], {
  proposed: ['b', 'a', 'c'],
  expectOk: false,
  expectCode: 'LOCKED_TASK_MOVE',
});

parityScenario('07 multiple locked boundaries valid', [
  pt('a', { status: 'TAMAMLANDI' }), pt('b'), pt('c'), pt('d', { visit_state: 'ARRIVED' }), pt('e'), pt('f'),
], {
  proposed: ['a', 'c', 'b', 'd', 'f', 'e'],
  expectOk: true,
});

parityScenario('08 same segment up', [pt('a'), pt('b'), pt('c', { status: 'TAMAMLANDI' })], {
  moves: [{ fn: 'moveUp', id: 'b' }],
  expectOk: true,
});

parityScenario('09 same segment down', [pt('a'), pt('b'), pt('c', { status: 'TAMAMLANDI' })], {
  moves: [{ fn: 'moveDown', id: 'a' }],
  expectOk: true,
});

parityScenario('10 same segment before', [pt('a', { status: 'TAMAMLANDI' }), pt('b'), pt('c'), pt('d')], {
  moves: [{ fn: 'moveBefore', id: 'd', target: 'b' }],
  expectOk: true,
});

parityScenario('11 same segment after', [pt('a'), pt('b'), pt('c', { status: 'TAMAMLANDI' }), pt('d')], {
  moves: [{ fn: 'moveAfter', id: 'a', target: 'b' }],
  expectOk: true,
});

parityScenario('12 cross boundary up reject', [pt('a'), pt('b', { visit_state: 'ARRIVED' }), pt('c')], {
  moves: [{ fn: 'moveUp', id: 'c' }],
  expectReject: true,
  invalidProposed: ['c', 'b', 'a'],
  expectCode: 'SEGMENT_BOUNDARY_CROSS',
});

parityScenario('13 cross boundary down reject', [pt('a'), pt('b'), pt('c', { status: 'TAMAMLANDI' }), pt('d')], {
  moves: [{ fn: 'moveDown', id: 'b' }],
  expectReject: true,
  invalidProposed: ['a', 'c', 'd', 'b'],
  expectCode: 'LOCKED_TASK_MOVE',
});

parityScenario('14 cross boundary before reject', [pt('a'), pt('b', { visit_state: 'ARRIVED' }), pt('c')], {
  moves: [{ fn: 'moveBefore', id: 'c', target: 'a' }],
  expectReject: true,
  invalidProposed: ['c', 'a', 'b'],
  expectCode: 'LOCKED_TASK_MOVE',
});

parityScenario('15 cross boundary after reject', [pt('a'), pt('b', { visit_state: 'ARRIVED' }), pt('c')], {
  moves: [{ fn: 'moveAfter', id: 'a', target: 'c' }],
  expectReject: true,
  invalidProposed: ['b', 'c', 'a'],
  expectCode: 'LOCKED_TASK_MOVE',
});

parityScenario('16 acil same segment swap', [pt('a', { priority: 'ACIL' }), pt('b')], {
  moves: [{ fn: 'moveDown', id: 'a' }],
  expectOk: true,
});

parityScenario('17 acil cross boundary reject', [pt('a', { priority: 'ACIL' }), pt('b', { visit_state: 'ARRIVED' }), pt('c')], {
  moves: [{ fn: 'moveDown', id: 'a' }],
  expectReject: true,
  invalidProposed: ['b', 'a', 'c'],
  expectCode: 'LOCKED_TASK_MOVE',
});

parityScenario('18 two acil swap', [pt('a', { priority: 'ACIL' }), pt('b', { priority: 'ACIL' })], {
  moves: [{ fn: 'moveDown', id: 'a' }],
  expectOk: true,
});

parityScenario('19 locked source', [pt('a', { status: 'TAMAMLANDI' }), pt('b')], {
  moves: [{ fn: 'moveDown', id: 'a' }],
  expectReject: true,
  invalidProposed: ['b', 'a'],
  expectCode: 'LOCKED_TASK_MOVE',
});

parityScenario('20 locked target', [pt('a'), pt('b', { status: 'TAMAMLANDI' }), pt('c')], {
  moves: [{ fn: 'moveBefore', id: 'c', target: 'b' }],
  expectReject: true,
  invalidProposed: ['a', 'c', 'b'],
  expectCode: 'LOCKED_TASK_MOVE',
});

parityScenario('21 unknown visit state', [pt('a'), pt('b', { visit_state: 'ALIEN' }), pt('c')], {
  proposed: ['a', 'c', 'b'],
  expectOk: false,
  expectCode: 'LOCKED_TASK_MOVE',
});

parityScenario('22 unknown plan status', [pt('a', { status: 'MYSTERY' }), pt('b')], {
  proposed: ['b', 'a'],
  expectOk: false,
  expectCode: 'LOCKED_TASK_MOVE',
});

parityScenario('23 arrived_at lock', [pt('a'), pt('b', { arrived_at: '2026-08-26 10:00:00' }), pt('c')], {
  proposed: ['c', 'b', 'a'],
  expectOk: false,
  expectCode: 'SEGMENT_BOUNDARY_CROSS',
});

parityScenario('24 departed_at lock', [pt('a'), pt('b', { departed_at: '2026-08-26 11:00:00' }), pt('c')], {
  proposed: ['c', 'b', 'a'],
  expectOk: false,
  expectCode: 'SEGMENT_BOUNDARY_CROSS',
});

parityScenario('25 input mutation none', [pt('a'), pt('b')], {
  proposed: ['b', 'a'],
  expectOk: true,
});

test('P 25 input mutation none verifies copy', () => {
  const tasks = [pt('a'), pt('b')];
  const copy = JSON.parse(JSON.stringify(tasks));
  backendValidate(tasks, ['b', 'a']);
  assert.deepEqual(tasks, copy);
});

parityScenario('26 hidden inactive preserved in payload', [
  pt('a'), pt('b', { status: 'IPTAL', visible: false }), pt('c'),
], {
  proposed: ['a', 'b', 'c'],
  expectOk: true,
});

parityScenario('27 full task set preserved', [pt('a'), pt('b'), pt('c')], {
  proposed: ['c', 'a', 'b'],
  expectOk: true,
});

test('P 28 duplicate id fail backend', () => {
  const tasks = [pt('a'), pt('b')];
  const be = backendValidate(tasks, ['a', 'a']);
  assert.equal(be.ok, false);
});

test('P 29 missing id fail backend', () => {
  const tasks = [pt('a'), pt('b')];
  const be = backendValidate(tasks, ['a']);
  assert.equal(be.ok, false);
});

test('P 30 deterministic repeat', () => {
  const tasks = [pt('a'), pt('b', { status: 'TAMAMLANDI' }), pt('c'), pt('d')];
  const context = jsContextFromPyTasks(tasks, 'det');
  const run1 = applyMoves(context, [{ fn: 'moveDown', id: 'c' }]);
  const run2 = applyMoves(context, [{ fn: 'moveDown', id: 'c' }]);
  assert.deepEqual(run1.proposed, run2.proposed);
  assert.deepEqual(backendValidate(tasks, run1.proposed), backendValidate(tasks, run2.proposed));
});

test('P fixture bug scenario parity', () => {
  const tasks = [pt('a', { priority: 'ACIL' }), pt('b'), pt('c', { status: 'TAMAMLANDI' }), pt('d')];
  const context = jsContextFromPyTasks(tasks, 'fixture-bug');
  const run = applyMoves(context, [{ fn: 'moveDown', id: 'b' }]);
  assert.deepEqual(run.proposed, context.ordered_item_ids);
  const be = backendValidate(tasks, ['a', 'c', 'd', 'b']);
  assert.equal(be.ok, false);
  assert.equal(be.code, 'LOCKED_TASK_MOVE');
});
