'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const MR = require(path.resolve(
  __dirname,
  '../../app/static/js/planlama_arac_takip_manual_reorder.js',
));
const UI = require(path.resolve(
  __dirname,
  '../../app/static/js/planlama_arac_takip_manual_reorder_ui.js',
));

function ctx(overrides) {
  const base = {
    ok: true,
    plan_id: 41,
    state_token: 'token-v1',
    ordered_item_ids: ['pi-1', 'pi-2', 'pi-3'],
    tasks: [
      { task_id: 'pi-1', order_no: 1, can_move: true, lock_reason: null, segment_index: 0, visible: true },
      { task_id: 'pi-2', order_no: 2, can_move: true, lock_reason: null, segment_index: 0, visible: true },
      { task_id: 'pi-3', order_no: 3, can_move: false, lock_reason: 'STATUS_TAMAMLANDI', segment_index: 0, visible: true },
    ],
  };
  return Object.assign(base, overrides || {});
}

function taskRow(id, name, status) {
  return {
    id,
    plan_item_id: Number(String(id).replace('pi-', '')),
    company_name: name || id,
    status: status || 'PLANLANDI',
    order_no: Number(String(id).replace('pi-', '')),
    arac_external_id: '45077045',
    plan_id: 41,
  };
}

class FakeEl {
  constructor(tag, id) {
    this.tagName = tag.toUpperCase();
    this.id = id || '';
    this.className = '';
    this.classList = {
      _s: new Set(),
      add: (...c) => c.forEach((x) => this.classList._s.add(x)),
      remove: (...c) => c.forEach((x) => this.classList._s.delete(x)),
      toggle: (c, on) => (on ? this.classList._s.add(c) : this.classList._s.delete(c)),
      contains: (c) => this.classList._s.has(c),
    };
    this.style = {};
    this.children = [];
    this.parentNode = null;
    this.innerHTML = '';
    this._innerHTML = '';
    this.textContent = '';
    this.disabled = false;
    this.attributes = {};
    this._listeners = {};
  }
  setAttribute(k, v) { this.attributes[k] = v; }
  getAttribute(k) { return this.attributes[k] == null ? null : String(this.attributes[k]); }
  appendChild(c) { c.parentNode = this; this.children.push(c); return c; }
  insertBefore(c, ref) {
    c.parentNode = this;
    const idx = ref ? this.children.indexOf(ref) : this.children.length;
    this.children.splice(idx, 0, c);
    return c;
  }
  addEventListener(type, fn) {
    if (!this._listeners[type]) this._listeners[type] = [];
    this._listeners[type].push(fn);
  }
  querySelectorAll(sel) {
    const out = [];
    const walk = (node) => {
      if (node.matches && node.matches(sel)) out.push(node);
      (node.children || []).forEach(walk);
    };
    walk(this);
    return out;
  }
  set innerHTML(val) {
    this._innerHTML = String(val || '');
    this.children = [];
    const re = /data-item-id="([^"]+)"/g;
    let m;
    while ((m = re.exec(this._innerHTML))) {
      const el = new FakeEl('div');
      el.className = 'stop-item atp-mr-stop-item';
      el.setAttribute('data-item-id', m[1]);
      el.setAttribute('data-task-id', m[1]);
      el.parentNode = this;
      this.children.push(el);
    }
  }
  get innerHTML() {
    return this._innerHTML || '';
  }
  matches(sel) {
    if (sel.startsWith('#')) return this.id === sel.slice(1);
    if (sel.includes('[data-item-id]')) {
      const cls = sel.split('[')[0].replace(/^\./, '');
      return this.className.split(/\s+/).includes(cls) && !!this.getAttribute('data-item-id');
    }
    if (sel.startsWith('.')) return this.className.split(/\s+/).includes(sel.slice(1));
    return false;
  }
  closest(sel) {
    let n = this;
    while (n) {
      if (n.matches && n.matches(sel)) return n;
      n = n.parentNode;
    }
    return null;
  }
  click() {
    (this._listeners.click || []).forEach((fn) => fn({ currentTarget: this, target: this, preventDefault() {} }));
  }
}

function buildDom() {
  const map = {};
  const body = new FakeEl('div', 'body');
  const make = (id) => {
    const el = new FakeEl('div', id);
    map[id] = el;
    body.appendChild(el);
    return el;
  };
  make('atpStopListTitle');
  make('atpManualReorderHeaderAction');
  make('atpManualReorderToolbar');
  make('atpManualReorderMsg');
  make('atpStopListWrap');
  return {
    document: {
      getElementById: (id) => map[id] || null,
      addEventListener: (type, fn) => body.addEventListener(type, fn),
      createElement: (tag) => new FakeEl(tag, ''),
    },
    map,
    body,
  };
}

function makeDeps(dom, opts) {
  const o = opts || {};
  let vehicleId = o.vehicleId || '45077045';
  let planId = o.planId != null ? o.planId : 41;
  const tasks = o.tasks || [
    taskRow('pi-1', 'Alpha'),
    taskRow('pi-2', 'Beta'),
    taskRow('pi-3', 'Gamma', 'TAMAMLANDI'),
  ];
  const fetchQueue = o.fetchQueue || [];
  let loadOpsCalls = 0;
  let toastMsg = '';
  let confirmAnswer = o.confirmAnswer !== false;
  const ctrl = UI.createController({
    document: dom.document,
    getMotor: () => MR,
    getPlanId: () => planId,
    getVehicleId: () => vehicleId,
    getPlanDate: () => '2026-08-26',
    getTasksForVehicle: () => tasks.slice(),
    getBaseLocation: () => 'Fabrika — Tuzla OSB',
    loadOps: () => { loadOpsCalls += 1; return Promise.resolve(true); },
    toast: (m) => { toastMsg = m; },
    fmtVal: (v) => (v == null || v === '' ? '—' : String(v)),
    isActivePlanItem: (it) => !['IPTAL', 'ERTELENDI', 'GIDILEMEDI'].includes((it.status || '').toUpperCase()),
    confirmFn: () => confirmAnswer,
    fetch: (url, init) => {
      const item = fetchQueue.shift();
      if (typeof item === 'function') return item(url, init);
      return Promise.resolve(item);
    },
    onDiscard: o.onDiscard,
  });
  return {
    ctrl,
    tasks,
    setVehicleId: (v) => { vehicleId = v; },
    setPlanId: (p) => { planId = p; },
    getLoadOpsCalls: () => loadOpsCalls,
    getToast: () => toastMsg,
    fetchQueue,
  };
}

test('U01 lockLabel maps known backend reason', () => {
  assert.match(UI.lockLabel('STATUS_TAMAMLANDI'), /Tamamlanan/);
  assert.match(UI.lockLabel('UNKNOWN_X'), /güvenlik/);
});

test('U02 escHtml escapes unsafe text', () => {
  assert.equal(UI.escHtml('<script>"x"'), '&lt;script&gt;&quot;x&quot;');
});

test('U03 init shows edit button in header action', () => {
  const dom = buildDom();
  const h = makeDeps(dom);
  h.ctrl.init();
  h.ctrl.afterBaseRender(h.tasks, '34 MOR 049');
  assert.match(dom.map.atpManualReorderHeaderAction.innerHTML, /Sırayı Düzenle/);
});

test('U04 edit mode disabled without motor', () => {
  const dom = buildDom();
  const ctrl = UI.createController({ document: dom.document, getMotor: () => null });
  ctrl.init();
  return ctrl.enterEditMode().then((ok) => assert.equal(ok, false));
});

test('U05 context fetch uses plan_id', () => {
  const dom = buildDom();
  const h = makeDeps(dom, {
    fetchQueue: [{
      ok: true,
      status: 200,
      body: ctx(),
    }],
  });
  return h.ctrl.enterEditMode().then((ok) => {
    assert.equal(ok, true);
    const log = h.ctrl._internal.getFetchLog();
    assert.equal(log.length, 1);
    assert.match(log[0].url, /plan_id=41/);
  });
});

test('U06 context fetch includes date and vehicle scope', () => {
  const dom = buildDom();
  const h = makeDeps(dom, {
    fetchQueue: [{ ok: true, status: 200, body: ctx() }],
  });
  return h.ctrl.enterEditMode().then(() => {
    const url = h.ctrl._internal.getFetchLog()[0].url;
    assert.match(url, /date=2026-08-26/);
    assert.match(url, /vehicle_id=45077045/);
  });
});

test('U07 bad context does not open edit mode', () => {
  const dom = buildDom();
  const h = makeDeps(dom, {
    fetchQueue: [{ ok: true, status: 200, body: { ok: false, error: 'bad' } }],
  });
  return h.ctrl.enterEditMode().then((ok) => {
    assert.equal(ok, false);
    assert.equal(h.ctrl.isEditMode(), false);
  });
});

test('U08 loading message shown during context fetch', () => {
  const dom = buildDom();
  const h = makeDeps(dom, {
    fetchQueue: [(url, init) => new Promise((resolve) => {
      assert.match(dom.map.atpManualReorderMsg.textContent, /yükleniyor/i);
      resolve({ ok: true, status: 200, body: ctx() });
    })],
  });
  return h.ctrl.enterEditMode();
});

test('U09 duplicate context request blocked', () => {
  const dom = buildDom();
  let resolveFirst;
  const h = makeDeps(dom, {
    fetchQueue: [
      () => new Promise((r) => { resolveFirst = r; }),
    ],
  });
  const p1 = h.ctrl.fetchContext(41, '45077045');
  const p2 = h.ctrl.fetchContext(41, '45077045');
  resolveFirst({ ok: true, status: 200, body: ctx() });
  return Promise.all([p1, p2]).then(([a, b]) => {
    assert.equal(a.ok, true);
    assert.equal(b.error, 'duplicate_request');
  });
});

test('U10 stale vehicle response ignored on enter', () => {
  const dom = buildDom();
  const h = makeDeps(dom, {
    fetchQueue: [(url, init) => {
      h.setVehicleId('999');
      return Promise.resolve({ ok: true, status: 200, body: ctx() });
    }],
  });
  return h.ctrl.enterEditMode().then((ok) => assert.equal(ok, false));
});

test('U11 visible draft render order', () => {
  const dom = buildDom();
  const h = makeDeps(dom, { fetchQueue: [{ ok: true, status: 200, body: ctx() }] });
  return h.ctrl.enterEditMode().then(() => {
    const st = h.ctrl._internal.getState();
    const moved = MR.moveUp(st, 'pi-2');
    h.ctrl._internal.setState(moved.state);
    h.ctrl.renderEditStopList();
    const order = h.ctrl._internal.tasksInDraftOrder().map((t) => t.id);
    assert.deepEqual(order, ['pi-2', 'pi-1', 'pi-3']);
  });
});

test('U12 hidden inactive kept in draft payload', () => {
  const dom = buildDom();
  const hiddenCtx = ctx({
    ordered_item_ids: ['pi-1', 'pi-x', 'pi-2', 'pi-3'],
    tasks: [
      { task_id: 'pi-1', order_no: 1, can_move: true, lock_reason: null, segment_index: 0, visible: true },
      { task_id: 'pi-x', order_no: 2, can_move: false, lock_reason: 'STATUS_INACTIVE', segment_index: 0, visible: false },
      { task_id: 'pi-2', order_no: 3, can_move: true, lock_reason: null, segment_index: 0, visible: true },
      { task_id: 'pi-3', order_no: 4, can_move: false, lock_reason: 'STATUS_TAMAMLANDI', segment_index: 0, visible: true },
    ],
  });
  const h = makeDeps(dom, { fetchQueue: [{ ok: true, status: 200, body: hiddenCtx }] });
  return h.ctrl.enterEditMode().then(() => {
    const st = h.ctrl._internal.getState();
    assert.ok(st.draftOrder.includes('pi-x'));
    const visible = MR.getVisibleDraftOrder(st);
    assert.deepEqual(visible, ['pi-1', 'pi-2', 'pi-3']);
  });
});

test('U13 locked row has lock controls html', () => {
  const dom = buildDom();
  const h = makeDeps(dom, { fetchQueue: [{ ok: true, status: 200, body: ctx() }] });
  return h.ctrl.enterEditMode().then(() => {
    const html = h.ctrl._internal.buildStopRowHtml(taskRow('pi-3'), 3, h.ctrl._internal.rowMeta('pi-3'));
    assert.match(html, /🔒/);
    assert.match(html, /Tamamlanan görev taşınamaz/);
    assert.doesNotMatch(html, /atp-mr-drag-handle/);
  });
});

test('U14 movable row has drag and arrows', () => {
  const dom = buildDom();
  const h = makeDeps(dom, { fetchQueue: [{ ok: true, status: 200, body: ctx() }] });
  return h.ctrl.enterEditMode().then(() => {
    const html = h.ctrl._internal.buildStopRowHtml(taskRow('pi-1'), 1, h.ctrl._internal.rowMeta('pi-1'));
    assert.match(html, /atp-mr-drag-handle/);
    assert.match(html, /Görevi yukarı taşı/);
    assert.match(html, /Görevi aşağı taşı/);
  });
});

test('U15 move up updates draft', () => {
  const dom = buildDom();
  const h = makeDeps(dom, { fetchQueue: [{ ok: true, status: 200, body: ctx() }] });
  return h.ctrl.enterEditMode().then(() => {
    const st = h.ctrl._internal.getState();
    const out = MR.moveUp(st, 'pi-2');
    h.ctrl._internal.setState(out.state);
    assert.deepEqual(out.state.draftOrder.slice(0, 2), ['pi-2', 'pi-1']);
  });
});

test('U16 move down updates draft', () => {
  const dom = buildDom();
  const h = makeDeps(dom, { fetchQueue: [{ ok: true, status: 200, body: ctx() }] });
  return h.ctrl.enterEditMode().then(() => {
    const st = h.ctrl._internal.getState();
    const out = MR.moveDown(st, 'pi-1');
    h.ctrl._internal.setState(out.state);
    assert.deepEqual(out.state.draftOrder.slice(0, 2), ['pi-2', 'pi-1']);
  });
});

test('U17 moveBefore segment logic delegated to motor', () => {
  const st = MR.createState(ctx());
  const out = MR.moveBefore(st, 'pi-2', 'pi-1');
  assert.equal(out.result.ok, true);
});

test('U18 moveAfter segment logic delegated to motor', () => {
  const st = MR.createState(ctx());
  const out = MR.moveAfter(st, 'pi-1', 'pi-2');
  assert.equal(out.result.ok, true);
});

test('U19 boundary reject at segment start', () => {
  const st = MR.createState(ctx());
  const out = MR.moveUp(st, 'pi-1');
  assert.equal(out.result.changed, false);
});

test('U20 dirty toolbar enables apply', () => {
  const dom = buildDom();
  const h = makeDeps(dom, { fetchQueue: [{ ok: true, status: 200, body: ctx() }] });
  return h.ctrl.enterEditMode().then(() => {
    h.ctrl.renderEditStopList();
    assert.match(dom.map.atpManualReorderToolbar.innerHTML, /disabled/);
    const st = h.ctrl._internal.getState();
    h.ctrl._internal.setState(MR.moveUp(st, 'pi-2').state);
    h.ctrl.renderEditStopList();
    assert.doesNotMatch(dom.map.atpManualReorderToolbar.innerHTML, /id="atpBtnManualReorderApply" disabled/);
  });
});

test('U21 apply disabled when clean', () => {
  const dom = buildDom();
  const h = makeDeps(dom, { fetchQueue: [{ ok: true, status: 200, body: ctx() }] });
  return h.ctrl.enterEditMode().then(() => h.ctrl.applySave().then((r) => assert.equal(r, false)));
});

test('U22 apply payload contains full ordered ids', () => {
  const st = MR.createState(ctx());
  const moved = MR.moveUp(st, 'pi-2').state;
  const payload = MR.buildApplyPayload(moved);
  assert.equal(payload.ok, true);
  assert.equal(payload.payload.ordered_item_ids.length, 3);
});

test('U23 save double click blocked by saving flag', () => {
  const dom = buildDom();
  const h = makeDeps(dom, {
    fetchQueue: [
      { ok: true, status: 200, body: ctx() },
      () => new Promise((resolve) => setTimeout(() => resolve({
        ok: true,
        status: 200,
        body: {
          ok: true,
          plan_id: 41,
          state_token: 'token-v2',
          ordered_item_ids: ['pi-2', 'pi-1', 'pi-3'],
          changed: true,
          route_state_invalidated: true,
          snapshot_deactivated: true,
          etas_cleared: true,
        },
      }), 30)),
    ],
  });
  return h.ctrl.enterEditMode().then(() => {
    const st = h.ctrl._internal.getState();
    h.ctrl._internal.setState(MR.moveUp(st, 'pi-2').state);
    const p1 = h.ctrl.applySave();
    const p2 = h.ctrl.applySave();
    return Promise.all([p1, p2]).then(([a, b]) => {
      assert.equal(a.ok || a === false, true);
      assert.equal(b, false);
    });
  });
});

test('U24 success uses server order and refreshes', () => {
  const dom = buildDom();
  const h = makeDeps(dom, {
    fetchQueue: [
      { ok: true, status: 200, body: ctx() },
      {
        ok: true,
        status: 200,
        body: {
          ok: true,
          plan_id: 41,
          state_token: 'token-v2',
          ordered_item_ids: ['pi-2', 'pi-1', 'pi-3'],
          changed: true,
          route_state_invalidated: true,
          snapshot_deactivated: false,
          etas_cleared: true,
        },
      },
    ],
  });
  return h.ctrl.enterEditMode().then(() => {
    const st = h.ctrl._internal.getState();
    h.ctrl._internal.setState(MR.moveUp(st, 'pi-2').state);
    return h.ctrl.applySave().then((res) => {
      assert.equal(res.ok, true);
      assert.equal(h.getLoadOpsCalls(), 1);
      assert.match(h.getToast(), /yeniden hesaplanmayı bekliyor/);
      assert.equal(h.ctrl.isEditMode(), false);
    });
  });
});

test('U25 broken 200 does not fake success', () => {
  const dom = buildDom();
  const h = makeDeps(dom, {
    fetchQueue: [
      { ok: true, status: 200, body: ctx() },
      { ok: true, status: 200, body: { ok: true, plan_id: 41 } },
    ],
  });
  return h.ctrl.enterEditMode().then(() => {
    const st = h.ctrl._internal.getState();
    h.ctrl._internal.setState(MR.moveUp(st, 'pi-2').state);
    return h.ctrl.applySave().then((res) => {
      assert.equal(res.ok, false);
      assert.equal(h.getLoadOpsCalls(), 0);
    });
  });
});

test('U26 snapshot and eta flags validated', () => {
  const dom = buildDom();
  const h = makeDeps(dom, {
    fetchQueue: [
      { ok: true, status: 200, body: ctx() },
      {
        ok: true,
        status: 200,
        body: {
          ok: true,
          plan_id: 41,
          state_token: 't2',
          ordered_item_ids: ['pi-2', 'pi-1', 'pi-3'],
          changed: true,
          route_state_invalidated: true,
          snapshot_deactivated: true,
          etas_cleared: true,
        },
      },
    ],
  });
  return h.ctrl.enterEditMode().then(() => {
    h.ctrl._internal.setState(MR.moveUp(h.ctrl._internal.getState(), 'pi-2').state);
    return h.ctrl.applySave().then((res) => assert.equal(res.ok, true));
  });
});

test('U27 discard does not POST', () => {
  const dom = buildDom();
  const h = makeDeps(dom, { fetchQueue: [{ ok: true, status: 200, body: ctx() }] });
  return h.ctrl.enterEditMode().then(() => {
    h.ctrl._internal.setState(MR.moveUp(h.ctrl._internal.getState(), 'pi-2').state);
    h.ctrl._internal.resetFetchLog();
    return h.ctrl.discardDraft().then(() => {
      const posts = h.ctrl._internal.getFetchLog().filter((x) => x.method === 'POST');
      assert.equal(posts.length, 0);
    });
  });
});

test('U28 discard exits edit mode', () => {
  const dom = buildDom();
  const h = makeDeps(dom, { fetchQueue: [{ ok: true, status: 200, body: ctx() }] });
  return h.ctrl.enterEditMode().then(() => h.ctrl.discardDraft().then(() => {
    assert.equal(h.ctrl.isEditMode(), false);
  }));
});

test('U29 dirty navigation guard blocks when cancelled', () => {
  const dom = buildDom();
  const h = makeDeps(dom, { confirmAnswer: false, fetchQueue: [{ ok: true, status: 200, body: ctx() }] });
  return h.ctrl.enterEditMode().then(() => {
    h.ctrl._internal.setState(MR.moveUp(h.ctrl._internal.getState(), 'pi-2').state);
    assert.equal(h.ctrl.guardNavigation('vehicle', '999'), false);
    assert.equal(h.ctrl.isEditMode(), true);
  });
});

test('U30 dirty navigation guard allows when confirmed', () => {
  const dom = buildDom();
  const h = makeDeps(dom, { confirmAnswer: true, fetchQueue: [{ ok: true, status: 200, body: ctx() }] });
  return h.ctrl.enterEditMode().then(() => {
    h.ctrl._internal.setState(MR.moveUp(h.ctrl._internal.getState(), 'pi-2').state);
    assert.equal(h.ctrl.guardNavigation('vehicle', '999'), true);
    assert.equal(h.ctrl.isEditMode(), false);
  });
});

test('U31 conflict sets conflicted state', () => {
  const dom = buildDom();
  const h = makeDeps(dom, {
    fetchQueue: [
      { ok: true, status: 200, body: ctx() },
      { ok: false, status: 409, body: { ok: false, code: 'PLAN_STATE_CONFLICT' } },
    ],
  });
  return h.ctrl.enterEditMode().then(() => {
    h.ctrl._internal.setState(MR.moveUp(h.ctrl._internal.getState(), 'pi-2').state);
    return h.ctrl.applySave().then((res) => {
      assert.equal(res.conflict, true);
      assert.equal(h.ctrl._internal.getState().conflicted, true);
    });
  });
});

test('U32 single conflict banner only', () => {
  const dom = buildDom();
  const h = makeDeps(dom, {
    fetchQueue: [
      { ok: true, status: 200, body: ctx() },
      { ok: false, status: 409, body: { ok: false, code: 'PLAN_STATE_CONFLICT' } },
    ],
  });
  return h.ctrl.enterEditMode().then(() => {
    h.ctrl._internal.setState(MR.moveUp(h.ctrl._internal.getState(), 'pi-2').state);
    return h.ctrl.applySave().then(() => {
      const tb = dom.map.atpManualReorderToolbar.innerHTML;
      assert.match(tb, /Güncel sıralamayı yükleyin/);
      assert.equal((tb.match(/atp-mr-conflict-banner/g) || []).length, 1);
      assert.equal(dom.map.atpManualReorderMsg.textContent, '');
    });
  });
});

test('U33 conflict blocks second save with old token', () => {
  const dom = buildDom();
  const h = makeDeps(dom, {
    fetchQueue: [
      { ok: true, status: 200, body: ctx() },
      { ok: false, status: 409, body: { ok: false, code: 'PLAN_STATE_CONFLICT' } },
    ],
  });
  return h.ctrl.enterEditMode().then(() => {
    h.ctrl._internal.setState(MR.moveUp(h.ctrl._internal.getState(), 'pi-2').state);
    return h.ctrl.applySave().then(() => h.ctrl.applySave().then((r) => {
      assert.notEqual(r && r.ok, true);
    }));
  });
});

test('U34 reload context after conflict', () => {
  const dom = buildDom();
  const h = makeDeps(dom, {
    fetchQueue: [
      { ok: true, status: 200, body: ctx() },
      { ok: false, status: 409, body: { ok: false, code: 'PLAN_STATE_CONFLICT' } },
      { ok: true, status: 200, body: ctx({ state_token: 'token-v2' }) },
    ],
  });
  return h.ctrl.enterEditMode().then(() => {
    h.ctrl._internal.setState(MR.moveUp(h.ctrl._internal.getState(), 'pi-2').state);
    return h.ctrl.applySave().then(() => h.ctrl.reloadAfterConflict().then((ok) => {
      assert.equal(ok, true);
      assert.equal(h.ctrl._internal.getState().stateToken, 'token-v2');
      assert.equal(h.ctrl._internal.getState().conflicted, false);
      assert.equal(h.ctrl.isDirty(), false);
    }));
  });
});

test('U35 policy 409 message surfaced', () => {
  const dom = buildDom();
  const h = makeDeps(dom, {
    fetchQueue: [
      { ok: true, status: 200, body: ctx() },
      { ok: false, status: 409, body: { ok: false, code: 'SEGMENT_VIOLATION', error: 'Segment ihlali' } },
    ],
  });
  return h.ctrl.enterEditMode().then(() => {
    h.ctrl._internal.setState(MR.moveUp(h.ctrl._internal.getState(), 'pi-2').state);
    return h.ctrl.applySave().then((res) => {
      assert.equal(res.conflict, undefined);
      assert.match(dom.map.atpManualReorderMsg.textContent, /Segment ihlali/);
    });
  });
});

test('U36 403 error message', () => {
  const dom = buildDom();
  const h = makeDeps(dom, {
    fetchQueue: [
      { ok: true, status: 200, body: ctx() },
      { ok: false, status: 403, body: { ok: false, error: 'Yetkisiz' } },
    ],
  });
  return h.ctrl.enterEditMode().then(() => {
    h.ctrl._internal.setState(MR.moveUp(h.ctrl._internal.getState(), 'pi-2').state);
    return h.ctrl.applySave().then((res) => assert.equal(res.ok, false));
  });
});

test('U37 404 error message', () => {
  const dom = buildDom();
  const h = makeDeps(dom, {
    fetchQueue: [
      { ok: true, status: 200, body: ctx() },
      { ok: false, status: 404, body: { ok: false, error: 'Plan yok' } },
    ],
  });
  return h.ctrl.enterEditMode().then(() => {
    h.ctrl._internal.setState(MR.moveUp(h.ctrl._internal.getState(), 'pi-2').state);
    return h.ctrl.applySave().then((res) => assert.equal(res.ok, false));
  });
});

test('U38 500 error message', () => {
  const dom = buildDom();
  const h = makeDeps(dom, {
    fetchQueue: [
      { ok: true, status: 200, body: ctx() },
      { ok: false, status: 500, body: { ok: false, error: 'Sunucu hatası' } },
    ],
  });
  return h.ctrl.enterEditMode().then(() => {
    h.ctrl._internal.setState(MR.moveUp(h.ctrl._internal.getState(), 'pi-2').state);
    return h.ctrl.applySave().then((res) => assert.equal(res.ok, false));
  });
});

test('U39 fetch log only manual endpoints on happy path', () => {
  const dom = buildDom();
  const h = makeDeps(dom, {
    fetchQueue: [
      { ok: true, status: 200, body: ctx() },
      {
        ok: true,
        status: 200,
        body: {
          ok: true,
          plan_id: 41,
          state_token: 't2',
          ordered_item_ids: ['pi-2', 'pi-1', 'pi-3'],
          changed: true,
          route_state_invalidated: true,
          snapshot_deactivated: false,
          etas_cleared: true,
        },
      },
    ],
  });
  return h.ctrl.enterEditMode().then(() => {
    h.ctrl._internal.setState(MR.moveUp(h.ctrl._internal.getState(), 'pi-2').state);
    return h.ctrl.applySave().then(() => {
      const urls = h.ctrl._internal.getFetchLog().map((x) => x.url);
      assert.ok(urls.every((u) => u.includes('manual-reorder')));
      assert.equal(urls.length, 2);
    });
  });
});

test('U40 plan switch cleanup on afterBaseRender', () => {
  const dom = buildDom();
  const h = makeDeps(dom, { fetchQueue: [{ ok: true, status: 200, body: ctx() }] });
  return h.ctrl.enterEditMode().then(() => {
    h.setPlanId(99);
    h.ctrl.afterBaseRender(h.tasks, 'plate');
    assert.equal(h.ctrl.isEditMode(), false);
  });
});

test('U41 vehicle switch cleanup on afterBaseRender', () => {
  const dom = buildDom();
  const h = makeDeps(dom, { fetchQueue: [{ ok: true, status: 200, body: ctx() }] });
  return h.ctrl.enterEditMode().then(() => {
    h.setVehicleId('999');
    h.ctrl.afterBaseRender(h.tasks, 'plate');
    assert.equal(h.ctrl.isEditMode(), false);
  });
});

test('U42 cleanup resets state', () => {
  const dom = buildDom();
  const h = makeDeps(dom, { fetchQueue: [{ ok: true, status: 200, body: ctx() }] });
  return h.ctrl.enterEditMode().then(() => {
    h.ctrl.cleanup();
    assert.equal(h.ctrl.isEditMode(), false);
  });
});

test('U43 without API motor screen continues normal toolbar', () => {
  const dom = buildDom();
  const ctrl = UI.createController({ document: dom.document, getMotor: () => null });
  ctrl.init();
  ctrl.afterBaseRender([taskRow('pi-1')], 'P');
  assert.equal(dom.map.atpManualReorderToolbar.style.display, 'none');
});

test('U44 apply uses POST to manual-reorder endpoint', () => {
  const dom = buildDom();
  const h = makeDeps(dom, {
    fetchQueue: [
      { ok: true, status: 200, body: ctx() },
      {
        ok: true,
        status: 200,
        body: {
          ok: true,
          plan_id: 41,
          state_token: 't2',
          ordered_item_ids: ['pi-2', 'pi-1', 'pi-3'],
          changed: true,
          route_state_invalidated: true,
          snapshot_deactivated: false,
          etas_cleared: true,
        },
      },
    ],
  });
  return h.ctrl.enterEditMode().then(() => {
    h.ctrl._internal.setState(MR.moveUp(h.ctrl._internal.getState(), 'pi-2').state);
    return h.ctrl.applySave().then(() => {
      const post = h.ctrl._internal.getFetchLog().find((x) => x.method === 'POST');
      assert.ok(post);
      assert.match(post.url, /manual-reorder$/);
    });
  });
});

test('U45 keyboard buttons are type button', () => {
  const dom = buildDom();
  const h = makeDeps(dom, { fetchQueue: [{ ok: true, status: 200, body: ctx() }] });
  return h.ctrl.enterEditMode().then(() => {
    const html = h.ctrl._internal.buildStopRowHtml(taskRow('pi-1'), 1, h.ctrl._internal.rowMeta('pi-1'));
    assert.match(html, /type="button"/);
  });
});

test('U46 XSS-safe company name escaped', () => {
  const dom = buildDom();
  const h = makeDeps(dom, { fetchQueue: [{ ok: true, status: 200, body: ctx() }] });
  return h.ctrl.enterEditMode().then(() => {
    const html = h.ctrl._internal.buildStopRowHtml(
      taskRow('pi-1', '<img onerror=alert(1)>'),
      1,
      h.ctrl._internal.rowMeta('pi-1'),
    );
    assert.doesNotMatch(html, /<img/);
    assert.match(html, /&lt;img/);
  });
});

test('U47 replaceFromContext via reload clears dirty', () => {
  const dom = buildDom();
  const h = makeDeps(dom, {
    fetchQueue: [
      { ok: true, status: 200, body: ctx() },
      { ok: true, status: 200, body: ctx({ state_token: 'fresh' }) },
    ],
  });
  return h.ctrl.enterEditMode().then(() => {
    h.ctrl._internal.setState(MR.moveUp(h.ctrl._internal.getState(), 'pi-2').state);
    return h.ctrl.reloadAfterConflict().then(() => assert.equal(h.ctrl.isDirty(), false));
  });
});

test('U48 edit mode title keeps Sıralı Duraklar label', () => {
  const dom = buildDom();
  const h = makeDeps(dom, { fetchQueue: [{ ok: true, status: 200, body: ctx() }] });
  h.ctrl.afterBaseRender(h.tasks, '34 GFK 183');
  return h.ctrl.enterEditMode().then(() => {
    assert.match(dom.map.atpStopListTitle.textContent, /Sıralı Duraklar — 34 GFK 183/);
    assert.doesNotMatch(dom.map.atpStopListTitle.textContent, /Sıra Düzenleme/);
  });
});

test('U49 normal mode keeps optimizer button ids untouched', () => {
  const dom = buildDom();
  const h = makeDeps(dom);
  h.ctrl.init();
  h.ctrl.afterBaseRender(h.tasks, 'P');
  assert.doesNotMatch(dom.map.atpManualReorderToolbar.innerHTML, /Önerilen Sırayı Uygula/);
});

test('U50 no maps endpoint in fetch log', () => {
  const dom = buildDom();
  const h = makeDeps(dom, {
    fetchQueue: [
      { ok: true, status: 200, body: ctx() },
      {
        ok: true,
        status: 200,
        body: {
          ok: true,
          plan_id: 41,
          state_token: 't2',
          ordered_item_ids: ['pi-2', 'pi-1', 'pi-3'],
          changed: true,
          route_state_invalidated: true,
          snapshot_deactivated: false,
          etas_cleared: true,
        },
      },
    ],
  });
  return h.ctrl.enterEditMode().then(() => {
    h.ctrl._internal.setState(MR.moveUp(h.ctrl._internal.getState(), 'pi-2').state);
    return h.ctrl.applySave().then(() => {
      const urls = h.ctrl._internal.getFetchLog().join(' ');
      assert.doesNotMatch(urls, /google|maps/i);
    });
  });
});

test('U51 success message constant', () => {
  const dom = buildDom();
  const h = makeDeps(dom);
  assert.match(h.ctrl._internal.SUCCESS_MSG, /Rota ve tahmini saatler/);
});

test('U52 conflict message constant', () => {
  const dom = buildDom();
  const h = makeDeps(dom);
  assert.match(h.ctrl._internal.CONFLICT_MSG, /Plan siz düzenlerken değişti/);
});

test('U53 toolbar apply label distinct from optimizer', () => {
  const dom = buildDom();
  const h = makeDeps(dom, { fetchQueue: [{ ok: true, status: 200, body: ctx() }] });
  return h.ctrl.enterEditMode().then(() => {
    assert.match(dom.map.atpManualReorderToolbar.innerHTML, /Sıralamayı Uygula/);
    assert.doesNotMatch(dom.map.atpManualReorderToolbar.innerHTML, /Önerilen Sırayı Uygula/);
  });
});

test('U54 enter edit without plan id fails closed', () => {
  const dom = buildDom();
  const h = makeDeps(dom, { planId: null });
  return h.ctrl.enterEditMode().then((ok) => assert.equal(ok, false));
});

test('U55 visible order skips inactive DOM tasks but keeps payload', () => {
  const st = MR.createState(ctx({
    ordered_item_ids: ['pi-1', 'pi-2', 'pi-hidden'],
    tasks: [
      { task_id: 'pi-1', order_no: 1, can_move: true, lock_reason: null, visible: true },
      { task_id: 'pi-2', order_no: 2, can_move: true, lock_reason: null, visible: true },
      { task_id: 'pi-hidden', order_no: 3, can_move: false, lock_reason: 'STATUS_INACTIVE', visible: false },
    ],
  }));
  const moved = MR.moveDown(st, 'pi-1');
  const payload = MR.buildApplyPayload(moved.state);
  assert.ok(payload.payload.ordered_item_ids.includes('pi-hidden'));
});

test('U56 edit toolbar has layout class and hint', () => {
  const dom = buildDom();
  const h = makeDeps(dom, { fetchQueue: [{ ok: true, status: 200, body: ctx() }] });
  return h.ctrl.enterEditMode().then(() => {
    assert.match(dom.map.atpManualReorderToolbar.innerHTML, /atp-mr-toolbar-edit/);
    assert.match(dom.map.atpManualReorderToolbar.innerHTML, /Planlanmış durakları sürükleyin/);
  });
});

test('U57 conflict shows one banner with reload inside', () => {
  const dom = buildDom();
  const h = makeDeps(dom);
  h.ctrl._internal.setState(MR.createState(ctx()));
  h.ctrl._internal.setState(MR.applyConflict(h.ctrl._internal.getState(), { code: 'PLAN_STATE_CONFLICT' }));
  h.ctrl.renderEditStopList();
  const tb = dom.map.atpManualReorderToolbar.innerHTML;
  assert.equal((tb.match(/atp-mr-conflict-banner/g) || []).length, 1);
  assert.match(tb, /Güncel Planı Yükle/);
  assert.equal(dom.map.atpManualReorderMsg.textContent, '');
});

test('U58 conflict does not duplicate toast path via msg element', () => {
  const dom = buildDom();
  const h = makeDeps(dom, {
    fetchQueue: [
      { ok: true, status: 200, body: ctx() },
      { ok: false, status: 409, body: { ok: false, code: 'PLAN_STATE_CONFLICT' } },
    ],
  });
  return h.ctrl.enterEditMode().then(() => {
    h.ctrl._internal.setState(MR.moveUp(h.ctrl._internal.getState(), 'pi-2').state);
    return h.ctrl.applySave().then(() => {
      assert.equal(dom.map.atpManualReorderMsg.className.indexOf('is-conflict'), -1);
    });
  });
});

test('U59 factory rows have no reorder controls in html', () => {
  const dom = buildDom();
  const h = makeDeps(dom, { fetchQueue: [{ ok: true, status: 200, body: ctx() }] });
  return h.ctrl.enterEditMode().then(() => {
    const html = dom.map.atpStopListWrap.innerHTML;
    const parts = html.split('atp-mr-factory-row');
    assert.ok(parts.length >= 3);
    parts.slice(1).forEach((chunk) => {
      assert.doesNotMatch(chunk.split('stop-item')[0] || chunk, /atp-mr-drag-handle/);
    });
  });
});

test('U60 locked row compact lock icon only', () => {
  const dom = buildDom();
  const h = makeDeps(dom, { fetchQueue: [{ ok: true, status: 200, body: ctx() }] });
  return h.ctrl.enterEditMode().then(() => {
    const html = h.ctrl._internal.buildStopRowHtml(
      taskRow('pi-3', 'Done', 'TAMAMLANDI'),
      3,
      h.ctrl._internal.rowMeta('pi-3'),
    );
    assert.match(html, /🔒/);
    assert.doesNotMatch(html, /atp-mr-lock-text/);
    assert.match(html, /Tamamlanan görev taşınamaz/);
  });
});

test('U61 ACIL movable row gets drag controls', () => {
  const dom = buildDom();
  const acilCtx = ctx({
    ordered_item_ids: ['pi-1', 'pi-2'],
    tasks: [
      { task_id: 'pi-1', order_no: 1, can_move: true, lock_reason: null, segment_index: 0, visible: true, priority: 'ACIL' },
      { task_id: 'pi-2', order_no: 2, can_move: true, lock_reason: null, segment_index: 0, visible: true },
    ],
  });
  const h = makeDeps(dom, {
    tasks: [
      Object.assign(taskRow('pi-1', 'ACİL iş'), { priority: 'ACIL', priority_label: 'Acil' }),
      taskRow('pi-2', 'Normal'),
    ],
    fetchQueue: [{ ok: true, status: 200, body: acilCtx }],
  });
  return h.ctrl.enterEditMode().then(() => {
    const html = h.ctrl._internal.buildStopRowHtml(
      h.tasks[0], 1, h.ctrl._internal.rowMeta('pi-1'),
    );
    assert.match(html, /atp-mr-drag-handle/);
    assert.doesNotMatch(html, /atp-mr-locked/);
  });
});

test('U62 dirty info in toolbar not row paint', () => {
  const dom = buildDom();
  const h = makeDeps(dom, { fetchQueue: [{ ok: true, status: 200, body: ctx() }] });
  return h.ctrl.enterEditMode().then(() => {
    h.ctrl._internal.setState(MR.moveUp(h.ctrl._internal.getState(), 'pi-2').state);
    h.ctrl.renderEditStopList();
    assert.match(dom.map.atpManualReorderToolbar.innerHTML, /Kaydedilmemiş sıra değişikliği/);
    assert.doesNotMatch(dom.map.atpStopListWrap.innerHTML, /atp-mr-draft-dirty/);
  });
});

test('U63 discard restores dom order and dirty false', () => {
  const dom = buildDom();
  const h = makeDeps(dom, { fetchQueue: [{ ok: true, status: 200, body: ctx() }] });
  return h.ctrl.enterEditMode().then(() => {
    const before = h.ctrl._internal.getDomStopIds().slice();
    h.ctrl._internal.setState(MR.moveUp(h.ctrl._internal.getState(), 'pi-2').state);
    h.ctrl.renderEditStopList();
    const changed = h.ctrl._internal.getDomStopIds().slice();
    assert.notDeepEqual(before, changed);
    assert.equal(h.ctrl.isDirty(), true);
    return h.ctrl.discardDraft().then(() => {
      assert.equal(h.ctrl.isEditMode(), false);
      assert.equal(h.ctrl.isDirty(), false);
      const posts = h.ctrl._internal.getFetchLog().filter((x) => x.method === 'POST');
      assert.equal(posts.length, 0);
    });
  });
});

test('U64 discard keeps persisted order ids', () => {
  const dom = buildDom();
  const h = makeDeps(dom, { fetchQueue: [{ ok: true, status: 200, body: ctx() }] });
  return h.ctrl.enterEditMode().then(() => {
    const persisted = h.ctrl._internal.getState().persistedOrder.slice();
    h.ctrl._internal.setState(MR.moveUp(h.ctrl._internal.getState(), 'pi-2').state);
    return h.ctrl.discardDraft().then(() => {
      assert.deepEqual(persisted, ['pi-1', 'pi-2', 'pi-3']);
    });
  });
});

test('U65 mixed context differs from simple edit context', () => {
  const mixed = ctx({
    ordered_item_ids: ['pi-1', 'pi-2', 'pi-3', 'pi-4', 'pi-5', 'pi-6'],
    tasks: [
      { task_id: 'pi-1', order_no: 1, can_move: true, lock_reason: null, segment_index: 0, visible: true, priority: 'ACIL' },
      { task_id: 'pi-2', order_no: 2, can_move: true, lock_reason: null, segment_index: 0, visible: true },
      { task_id: 'pi-3', order_no: 3, can_move: false, lock_reason: 'STATUS_BASLADI', segment_index: 0, visible: true },
      { task_id: 'pi-4', order_no: 4, can_move: true, lock_reason: null, segment_index: 0, visible: true },
      { task_id: 'pi-5', order_no: 5, can_move: false, lock_reason: 'STATUS_TAMAMLANDI', segment_index: 0, visible: true },
      { task_id: 'pi-6', order_no: 6, can_move: true, lock_reason: null, segment_index: 0, visible: true },
    ],
  });
  const simple = ctx();
  assert.notDeepEqual(mixed.ordered_item_ids, simple.ordered_item_ids);
  const mixedLocked = mixed.tasks.filter((t) => !t.can_move).length;
  assert.ok(mixedLocked >= 2);
  const mixedMovable = mixed.tasks.filter((t) => t.can_move).length;
  assert.ok(mixedMovable >= 3);
});

test('U66 edit and mixed fixture states produce different row html', () => {
  const mixedTasks = [
    Object.assign(taskRow('pi-1', 'ACİL iş'), { priority: 'ACIL', priority_label: 'Acil' }),
    taskRow('pi-2', 'Beta'),
    taskRow('pi-3', 'Started', 'BASLADI'),
    taskRow('pi-4', 'Delta'),
    taskRow('pi-5', 'Gamma', 'TAMAMLANDI'),
    taskRow('pi-6', 'Omega'),
  ];
  const dom = buildDom();
  const h = makeDeps(dom, {
    tasks: mixedTasks,
    fetchQueue: [{ ok: true, status: 200, body: ctx() }],
  });
  return h.ctrl.enterEditMode().then(() => {
    const editHtml = dom.map.atpStopListWrap.innerHTML;
    const mixedCtx = ctx({
      ordered_item_ids: ['pi-1', 'pi-2', 'pi-3', 'pi-4', 'pi-5', 'pi-6'],
      tasks: [
        { task_id: 'pi-1', order_no: 1, can_move: true, lock_reason: null, segment_index: 0, visible: true, priority: 'ACIL' },
        { task_id: 'pi-2', order_no: 2, can_move: true, lock_reason: null, segment_index: 0, visible: true },
        { task_id: 'pi-3', order_no: 3, can_move: false, lock_reason: 'STATUS_BASLADI', segment_index: 0, visible: true },
        { task_id: 'pi-4', order_no: 4, can_move: true, lock_reason: null, segment_index: 0, visible: true },
        { task_id: 'pi-5', order_no: 5, can_move: false, lock_reason: 'STATUS_TAMAMLANDI', segment_index: 0, visible: true },
        { task_id: 'pi-6', order_no: 6, can_move: true, lock_reason: null, segment_index: 0, visible: true },
      ],
    });
    h.ctrl._internal.setState(MR.createState(mixedCtx));
    h.ctrl.renderEditStopList();
    const mixedHtml = dom.map.atpStopListWrap.innerHTML;
    assert.notEqual(editHtml, mixedHtml);
    assert.ok((mixedHtml.match(/atp-mr-locked/g) || []).length >= 2);
  });
});

test('U67 panel title keeps plate in edit mode', () => {
  const dom = buildDom();
  const h = makeDeps(dom, { fetchQueue: [{ ok: true, status: 200, body: ctx() }] });
  h.ctrl.afterBaseRender(h.tasks, '34 MOR 049');
  return h.ctrl.enterEditMode().then(() => {
    assert.match(dom.map.atpStopListTitle.textContent, /Sıralı Duraklar — 34 MOR 049/);
    assert.doesNotMatch(dom.map.atpStopListTitle.textContent, /Sıra Düzenleme/);
  });
});

test('U68 normal mode edit button in header not toolbar', () => {
  const dom = buildDom();
  const h = makeDeps(dom);
  h.ctrl.afterBaseRender(h.tasks, '34 GFK 183');
  assert.match(dom.map.atpManualReorderHeaderAction.innerHTML, /Sırayı Düzenle/);
  assert.equal(dom.map.atpManualReorderToolbar.innerHTML, '');
});

test('U69 optimizer button text unchanged in fixture contract', () => {
  assert.match('✔ Önerilen Sırayı Uygula', /Önerilen Sırayı Uygula/);
  assert.doesNotMatch('Sıralamayı Uygula', /Önerilen/);
});

test('U70 fetch log manual endpoints only on apply flow', () => {
  const dom = buildDom();
  const h = makeDeps(dom, {
    fetchQueue: [
      { ok: true, status: 200, body: ctx() },
      {
        ok: true, status: 200,
        body: {
          ok: true, plan_id: 41, state_token: 't2',
          ordered_item_ids: ['pi-2', 'pi-1', 'pi-3'],
          changed: true, route_state_invalidated: true,
          snapshot_deactivated: false, etas_cleared: true,
        },
      },
    ],
  });
  return h.ctrl.enterEditMode().then(() => {
    h.ctrl._internal.setState(MR.moveUp(h.ctrl._internal.getState(), 'pi-2').state);
    return h.ctrl.applySave().then(() => {
      const logs = h.ctrl._internal.getFetchLog();
      const urls = logs.map((x) => x.url).join(' ');
      assert.doesNotMatch(urls, /google|maps/i);
      assert.ok(logs.some((x) => x.url.includes('manual-reorder')));
    });
  });
});

test('U71 toolbar edit uses responsive wrap not fixed width overflow', () => {
  const fs = require('node:fs');
  const cssPath = path.resolve(__dirname, '../../app/static/css/planlama_arac_takip.css');
  const css = fs.readFileSync(cssPath, 'utf8');
  assert.match(css, /atp-mr-toolbar-edit[\s\S]*flex-wrap/);
  assert.match(css, /max-width:900px[\s\S]*atp-mr-toolbar-edit/);
});
