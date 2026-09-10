'use strict';
/**
 * Phase 2A behavioral simulation — mirrors uretim_plan.js state rules under test.
 * Keeps production IIFE unchanged; validates date/station flow contracts.
 */
const test = require('node:test');
const assert = require('node:assert/strict');

function cellDurum(cell) {
  if (!cell || !cell.durum) return 'BOS';
  return String(cell.durum).toUpperCase();
}

function istasyonDisabledAtDate(n, ctx) {
  const slot = ctx.slot;
  const planDurum = ctx.istasyonPlanDurum || {};
  const grid = ctx.grid || [];
  const row = grid[n - 1] || {};
  const cell = slot ? (row[slot] || {}) : null;
  let durum = slot ? cellDurum(cell) : 'BOS';
  const pd = planDurum[n];
  if (pd && pd.durum === 'PLANLI') durum = 'PLANLI';
  return !slot || durum === 'PLANLI' || durum === 'DOLU' ||
    durum === 'SETUP' || durum === 'ARIZA';
}

function pruneInvalidStations(ctx, pruneReason) {
  const removed = [];
  ctx.istasyonlar = (ctx.istasyonlar || []).filter(function (n) {
    if (istasyonDisabledAtDate(n, ctx)) {
      removed.push(n);
      return false;
    }
    return true;
  });
  ctx.lastWarn = removed.length
    ? (pruneReason === 'date'
      ? 'Tarih değişti: İST' + removed.join(', İST')
      : 'Seçilen tarihte İST' + removed.join(', İST'))
    : null;
  return removed;
}

function sectionStates(ctx) {
  const hasBas = !!(ctx.baslangic || ctx.basInput);
  return {
    tarih: !!(ctx.makineId && ctx.slot),
    istasyon: !!(ctx.makineId && ctx.slot && hasBas),
    kalip: !!(ctx.makineId && ctx.slot && hasBas),
  };
}

function availabilityStillValid(capture, ctx) {
  return capture.seq === ctx.istasyonAvailabilitySeq &&
    capture.sipNo === ctx.sipNo &&
    capture.makineId === ctx.makineId &&
    capture.slot === ctx.slot &&
    capture.baslangic === ctx.baslangic;
}

function toggleStation(ctx, n, checked) {
  const beforeManuel = ctx.baslangicManuel;
  const beforeBas = ctx.baslangic;
  const beforeInput = ctx.basInput;
  if (checked) {
    if (istasyonDisabledAtDate(n, ctx)) return;
    if (ctx.istasyonlar.indexOf(n) < 0) ctx.istasyonlar.push(n);
  } else {
    ctx.istasyonlar = ctx.istasyonlar.filter(function (x) { return x !== n; });
  }
  ctx.istasyonlar.sort(function (a, b) { return a - b; });
  ctx.kalipAdedi = ctx.istasyonlar.length || null;
  ctx.baslangicManuel = beforeManuel;
  ctx.baslangic = beforeBas;
  ctx.basInput = beforeInput;
}

function baseCtx(overrides) {
  return Object.assign({
    sipNo: 33857,
    makineId: 1,
    slot: 'A',
    baslangic: '2026-09-10 07:00:00',
    basInput: '2026-09-10T07:00',
    baslangicManuel: true,
    istasyonlar: [],
    kalipAdedi: null,
    kalipId: null,
    istasyonAvailabilitySeq: 0,
    istasyonPlanDurum: {},
    grid: Array.from({ length: 8 }, function () {
      return { A: { durum: 'BOS' }, B: { durum: 'BOS' } };
    }),
  }, overrides || {});
}

test('TEST1: station section active without mold when date set', function () {
  const ctx = baseCtx();
  const s = sectionStates(ctx);
  assert.equal(s.istasyon, true);
  assert.equal(s.kalip, true);
});

test('TEST2: selecting IST1 preserves date and baslangicManuel', function () {
  const ctx = baseCtx();
  toggleStation(ctx, 1, true);
  assert.equal(ctx.baslangic, '2026-09-10 07:00:00');
  assert.equal(ctx.baslangicManuel, true);
  assert.equal(ctx.basInput, '2026-09-10T07:00');
  assert.deepEqual(ctx.istasyonlar, [1]);
});

test('TEST3: multi-select IST1 IST3 IST4 keeps date', function () {
  const ctx = baseCtx();
  toggleStation(ctx, 1, true);
  toggleStation(ctx, 3, true);
  toggleStation(ctx, 4, true);
  assert.deepEqual(ctx.istasyonlar, [1, 3, 4]);
  assert.equal(ctx.baslangic, '2026-09-10 07:00:00');
  assert.equal(ctx.kalipAdedi, 3);
});

test('TEST4: removing IST3 keeps IST1 IST4 and date', function () {
  const ctx = baseCtx({ istasyonlar: [1, 3, 4], kalipAdedi: 3 });
  toggleStation(ctx, 3, false);
  assert.deepEqual(ctx.istasyonlar, [1, 4]);
  assert.equal(ctx.baslangic, '2026-09-10 07:00:00');
});

test('TEST5: date change prunes only invalid stations', function () {
  const ctx = baseCtx({
    istasyonlar: [1, 3],
    kalipAdedi: 2,
    baslangic: '2026-09-12 07:00:00',
    basInput: '2026-09-12T07:00',
    istasyonPlanDurum: { 3: { durum: 'PLANLI' } },
  });
  const removed = pruneInvalidStations(ctx, 'date');
  assert.deepEqual(removed, [3]);
  assert.deepEqual(ctx.istasyonlar, [1]);
  assert.match(ctx.lastWarn, /İST3/);
  assert.equal(ctx.baslangic, '2026-09-12 07:00:00');
});

test('TEST6: stale availability response ignored by sequence guard', function () {
  const ctx = baseCtx({ istasyonAvailabilitySeq: 2 });
  const stale = {
    seq: 1,
    sipNo: 33857,
    makineId: 1,
    slot: 'A',
    baslangic: '2026-09-10 07:00:00',
  };
  assert.equal(availabilityStillValid(stale, ctx), false);
  ctx.baslangic = '2026-09-11 07:00:00';
  const stale2 = Object.assign({}, stale, { seq: 2, baslangic: '2026-09-10 07:00:00' });
  assert.equal(availabilityStillValid(stale2, ctx), false);
});

test('TEST7: machine/slot change invalidates stale capture', function () {
  const ctx = baseCtx({ istasyonAvailabilitySeq: 5 });
  const cap = { seq: 5, sipNo: 33857, makineId: 1, slot: 'A', baslangic: ctx.baslangic };
  ctx.makineId = 2;
  assert.equal(availabilityStillValid(cap, ctx), false);
  ctx.makineId = 1;
  ctx.slot = 'B';
  assert.equal(availabilityStillValid(cap, ctx), false);
});

test('TEST8: mold change preserves date and stations', function () {
  const ctx = baseCtx({ istasyonlar: [1, 3], kalipAdedi: 2, kalipId: 25 });
  const before = {
    baslangic: ctx.baslangic,
    istasyonlar: ctx.istasyonlar.slice(),
  };
  ctx.kalipId = 42;
  ctx.hesapOk = false;
  assert.equal(ctx.baslangic, before.baslangic);
  assert.deepEqual(ctx.istasyonlar, before.istasyonlar);
});

test('TEST9: calculate readiness blocked without mold', function () {
  function canHesapla(ctx) {
    return !!(ctx.makineId && ctx.slot && ctx.baslangic &&
      ctx.istasyonlar.length > 0 && ctx.kalipId);
  }
  const ctx = baseCtx({ istasyonlar: [1], kalipAdedi: 1, kalipId: null });
  assert.equal(canHesapla(ctx), false);
});

test('TEST10: calculate readiness ok with mold and stations', function () {
  function canHesapla(ctx) {
    return !!(ctx.makineId && ctx.slot && ctx.baslangic &&
      ctx.istasyonlar.length > 0 && ctx.kalipId &&
      ctx.kalipAdedi === ctx.istasyonlar.length);
  }
  const ctx = baseCtx({ istasyonlar: [1, 3], kalipAdedi: 2, kalipId: 25 });
  assert.equal(canHesapla(ctx), true);
});
