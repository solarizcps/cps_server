'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const vm = require('node:vm');

const PLAN_MAP_PATH = path.resolve(
  __dirname,
  '../../app/static/js/planlama_arac_takip_plan_map.js',
);
const MR = require(path.resolve(
  __dirname,
  '../../app/static/js/planlama_arac_takip_manual_reorder.js',
));

let layerSeq = 0;

function createMockLeaflet() {
  function latLng(lat, lng) {
    return { lat: Number(lat), lng: Number(lng) };
  }

  function latLngBounds(points) {
    var lats = points.map((p) => p.lat);
    var lngs = points.map((p) => p.lng);
    return {
      getNorth: () => Math.max(...lats),
      getSouth: () => Math.min(...lats),
      getEast: () => Math.max(...lngs),
      getWest: () => Math.min(...lngs),
      pad: () => this,
    };
  }

  function polyline(latlngs, opts) {
    var id = ++layerSeq;
    var layer = {
      _atpId: id,
      latlngs: latlngs.map((p) => [p[0], p[1]]),
      opts: Object.assign({}, opts),
      _halo: null,
      _map: null,
      getLatLngs() {
        return this.latlngs.map((p) => latLng(p[0], p[1]));
      },
      bringToFront() {},
      addTo(map) {
        map._addLayer(this);
        this._map = map;
        if (this.opts && this.opts.weight >= 9 && this.opts.color === '#fff') {
          this._atpKind = 'halo';
        } else if (this.opts && this.opts.dashArray === '10 6') {
          this._atpKind = 'suggested';
        } else if (this.opts && this.opts.color === '#16a34a') {
          this._atpKind = 'suggested';
        } else if (this.opts && this.opts.color === '#1d4ed8') {
          this._atpKind = 'current';
        }
        return this;
      },
    };
    return layer;
  }

  function marker(latlng, opts) {
    return {
      _atpKind: 'marker',
      _opts: opts || {},
      _latlng: latLng(latlng[0], latlng[1]),
      getLatLng() { return this._latlng; },
      bindPopup() { return this; },
      addTo(map) {
        map._addLayer(this);
        return this;
      },
    };
  }

  function createMap() {
    var active = new Set();
    var registry = [];
    var mapObj = {
      __atpLayerRegistry: registry,
      _addLayer(layer) {
        active.add(layer);
        registry.push(layer);
      },
      hasLayer(layer) {
        return active.has(layer);
      },
      removeLayer(layer) {
        active.delete(layer);
      },
      whenReady(fn) { fn(); },
      invalidateSize() {},
      setView() { return mapObj; },
      fitBounds() { return mapObj; },
    };
    return mapObj;
  }

  return {
    latLng,
    latLngBounds,
    polyline,
    marker,
    divIcon: (opts) => opts || {},
    map: () => createMap(),
    tileLayer: () => ({ addTo() {} }),
  };
}

function loadPlanMapModule() {
  layerSeq = 0;
  const sandbox = {
    console,
    setTimeout,
    clearTimeout,
    requestAnimationFrame: (fn) => fn(),
    module: { exports: {} },
    exports: {},
  };

  const container = {
    style: { display: 'block', visibility: 'visible' },
    offsetWidth: 800,
    offsetHeight: 400,
    innerHTML: '',
  };
  const mapEl = {
    style: { display: 'block' },
    offsetWidth: 800,
    offsetHeight: 400,
    innerHTML: '',
  };
  const emptyEl = {
    style: { display: 'none' },
    querySelector: () => ({ textContent: '' }),
  };

  sandbox.window = sandbox;
  sandbox.document = {
    getElementById(id) {
      if (id === 'atp-plan-map-container') return container;
      if (id === 'atpPlanLeafletMap') return mapEl;
      if (id === 'atpPlanMapEmpty') return emptyEl;
      if (id === 'atpPlanMapCompleteness') return { innerHTML: '' };
      return null;
    },
    querySelector: () => null,
  };
  sandbox.window.getComputedStyle = () => ({ display: 'block', visibility: 'visible' });
  sandbox.L = createMockLeaflet();
  sandbox.AtpRoute = { getLastRoute: () => null };

  const code = require('node:fs').readFileSync(PLAN_MAP_PATH, 'utf8');
  vm.runInNewContext(code, sandbox, { filename: PLAN_MAP_PATH });

  const exported = sandbox.module.exports || {};
  return {
    AtpPlanMap: exported.AtpPlanMap || sandbox.AtpPlanMap,
    pure: exported.pure || sandbox.__atpPlanMapPure,
    sandbox,
  };
}

function denseOrsFixture() {
  const pts = [];
  for (let i = 0; i < 120; i++) {
    pts.push([40.99 + i * 0.0001, 28.69 + i * 0.00008]);
  }
  return pts;
}

function sparseLongChordFixture() {
  return [
    [40.825, 29.372],
    [40.900, 29.100],
    [40.970, 28.850],
    [40.994, 28.700],
  ];
}

function shortLocalFixture() {
  return [
    [40.993, 28.695],
    [40.994, 28.696],
    [40.995, 28.697],
  ];
}

function samplePayload(overrides) {
  return Object.assign({
    vehicle_id: 991002,
    plan_date: '2026-09-01',
    plan_id: 3,
    base: {
      has_coordinates: true,
      latitude: 40.993,
      longitude: 28.695,
      base_name: 'Fabrika',
      base_address: 'Base',
    },
    stops: [{
      has_coordinates: true,
      latitude: 40.994,
      longitude: 28.700,
      order_no: 1,
      display_order_no: 1,
      company_name: 'Stop A',
    }],
    completeness: { total_stops: 1, ready: 1, missing: 0 },
  }, overrides || {});
}

function routeLine(geometry) {
  return geometry.map((p) => [p[0], p[1]]);
}

function identicalDenseFixture() {
  return denseOrsFixture();
}

function differentDenseFixture() {
  return denseOrsFixture().map((p, i) => [p[0] + (i * 0.00001), p[1] + (i * 0.000008)]);
}

function sameDistanceDifferentPathFixture() {
  const base = denseOrsFixture();
  const alt = base.map((p) => [p[0], p[1]]);
  const last = alt.length - 1;
  alt[last] = [alt[last][0] + 0.0005, alt[last][1] + 0.0003];
  return alt;
}

function dashedSuggestedLayers(AtpPlanMap) {
  return AtpPlanMap._testLayerKinds().filter((l) => l.dashArray === '10 6');
}

function totalActivePolylineLayers(AtpPlanMap) {
  return AtpPlanMap._testLayerKinds().filter((l) => l.kind === 'current' || l.kind === 'suggested' || l.kind === 'halo').length;
}

function setLastRoute(sandbox, currentGeom, suggestedGeom) {
  sandbox.AtpRoute.getLastRoute = () => ({
    current: { geometry: routeLine(currentGeom || []) },
    suggested: { geometry: routeLine(suggestedGeom != null ? suggestedGeom : []) },
  });
}

test('RL01 first current route → 1 halo + 1 current', () => {
  const { AtpPlanMap } = loadPlanMapModule();
  AtpPlanMap.ensurePlanMap();
  AtpPlanMap.setCurrentRouteGeometry(denseOrsFixture());
  assert.equal(AtpPlanMap.routeLayerCount(), 1);
  assert.equal(AtpPlanMap.haloLayerCount(), 1);
  assert.equal(AtpPlanMap.hasCurrentRoute(), true);
  AtpPlanMap._testReset();
});

test('RL02 same route second render → still 1 halo + 1 current', () => {
  const { AtpPlanMap } = loadPlanMapModule();
  AtpPlanMap.ensurePlanMap();
  const geom = denseOrsFixture();
  AtpPlanMap.setCurrentRouteGeometry(geom);
  AtpPlanMap.setCurrentRouteGeometry(geom);
  assert.equal(AtpPlanMap.routeLayerCount(), 1);
  assert.equal(AtpPlanMap.haloLayerCount(), 1);
  assert.equal(AtpPlanMap.orphanHaloCount(), 0);
  AtpPlanMap._testReset();
});

test('RL03 different route replace → old halo and route removed', () => {
  const { AtpPlanMap } = loadPlanMapModule();
  AtpPlanMap.ensurePlanMap();
  AtpPlanMap.setCurrentRouteGeometry(denseOrsFixture());
  const alt = denseOrsFixture().map((p) => [p[0] + 0.01, p[1] + 0.01]);
  AtpPlanMap.setCurrentRouteGeometry(alt);
  assert.equal(AtpPlanMap.routeLayerCount(), 1);
  assert.equal(AtpPlanMap.haloLayerCount(), 1);
  assert.equal(AtpPlanMap.orphanHaloCount(), 0);
  AtpPlanMap._testReset();
});

test('RL04 clearRouteLayers → halo/current/suggested all removed', () => {
  const { AtpPlanMap } = loadPlanMapModule();
  AtpPlanMap.ensurePlanMap();
  AtpPlanMap.setCurrentRouteGeometry(denseOrsFixture());
  AtpPlanMap.setSuggestedRouteGeometry(denseOrsFixture().slice(0, 40));
  AtpPlanMap.clearRouteLayers();
  assert.equal(AtpPlanMap.routeLayerCount(), 0);
  assert.equal(AtpPlanMap.haloLayerCount(), 0);
  assert.equal(AtpPlanMap.hasCurrentRoute(), false);
  assert.equal(AtpPlanMap.hasSuggestedRoute(), false);
  AtpPlanMap._testReset();
});

test('RL05 empty geometry → old layer cleared', () => {
  const { AtpPlanMap } = loadPlanMapModule();
  AtpPlanMap.ensurePlanMap();
  AtpPlanMap.setCurrentRouteGeometry(denseOrsFixture());
  AtpPlanMap.setCurrentRouteGeometry([]);
  assert.equal(AtpPlanMap.hasCurrentRoute(), false);
  assert.equal(AtpPlanMap.haloLayerCount(), 0);
  AtpPlanMap._testReset();
});

test('RL06 dense ORS fixture → drawn', () => {
  const { AtpPlanMap, pure } = loadPlanMapModule();
  const geom = denseOrsFixture();
  assert.equal(pure.isDrawableRouteGeometry(geom), true);
  AtpPlanMap.ensurePlanMap();
  AtpPlanMap.setCurrentRouteGeometry(geom);
  assert.equal(AtpPlanMap.hasCurrentRoute(), true);
  assert.ok(AtpPlanMap.getCurrentRoutePointCount() >= 100);
  AtpPlanMap._testReset();
});

test('RL07 4-point long sparse geometry → not drawn', () => {
  const { AtpPlanMap, pure } = loadPlanMapModule();
  const geom = sparseLongChordFixture();
  assert.equal(pure.isDrawableRouteGeometry(geom), false);
  AtpPlanMap.ensurePlanMap();
  AtpPlanMap.setCurrentRouteGeometry(geom);
  assert.equal(AtpPlanMap.hasCurrentRoute(), false);
  assert.equal(AtpPlanMap.haloLayerCount(), 0);
  AtpPlanMap._testReset();
});

test('RL08 short low-point valid geometry → not wrongly blocked', () => {
  const { AtpPlanMap, pure } = loadPlanMapModule();
  const geom = shortLocalFixture();
  assert.equal(pure.isDrawableRouteGeometry(geom), true);
  AtpPlanMap.ensurePlanMap();
  AtpPlanMap.setCurrentRouteGeometry(geom);
  assert.equal(AtpPlanMap.hasCurrentRoute(), true);
  AtpPlanMap._testReset();
});

test('RL09 suggested replace → only one suggested layer', () => {
  const { AtpPlanMap } = loadPlanMapModule();
  AtpPlanMap.ensurePlanMap();
  const g1 = denseOrsFixture().slice(0, 30);
  const g2 = denseOrsFixture().slice(10, 50);
  AtpPlanMap.setSuggestedRouteGeometry(g1);
  AtpPlanMap.setSuggestedRouteGeometry(g2);
  assert.equal(AtpPlanMap.hasSuggestedRoute(), true);
  assert.equal(AtpPlanMap.routeLayerCount(), 1);
  assert.equal(AtpPlanMap.haloLayerCount(), 1);
  AtpPlanMap._testReset();
});

test('RL10 suggested empty → old suggested removed', () => {
  const { AtpPlanMap } = loadPlanMapModule();
  AtpPlanMap.ensurePlanMap();
  AtpPlanMap.setSuggestedRouteGeometry(denseOrsFixture().slice(0, 30));
  AtpPlanMap.clearSuggestedRouteGeometry();
  assert.equal(AtpPlanMap.hasSuggestedRoute(), false);
  assert.equal(AtpPlanMap.haloLayerCount(), 0);
  AtpPlanMap._testReset();
});

test('RL11 vehicle change → old geometry does not remain', () => {
  const { AtpPlanMap, sandbox } = loadPlanMapModule();
  AtpPlanMap.ensurePlanMap();
  sandbox.AtpRoute.getLastRoute = () => ({
    current: { geometry: routeLine(sparseLongChordFixture()) },
  });
  AtpPlanMap.renderPlanMap(samplePayload({ vehicle_id: 991002 }));
  assert.equal(AtpPlanMap.hasCurrentRoute(), false);

  sandbox.AtpRoute.getLastRoute = () => ({
    current: { geometry: routeLine(denseOrsFixture()) },
  });
  AtpPlanMap.renderPlanMap(samplePayload({ vehicle_id: 991003 }));
  assert.equal(AtpPlanMap.hasCurrentRoute(), true);
  assert.equal(AtpPlanMap.haloLayerCount(), 1);
  AtpPlanMap._testReset();
});

test('RL12 date change → old geometry does not remain', () => {
  const { AtpPlanMap, sandbox } = loadPlanMapModule();
  AtpPlanMap.ensurePlanMap();
  sandbox.AtpRoute.getLastRoute = () => ({
    current: { geometry: routeLine(denseOrsFixture()) },
  });
  AtpPlanMap.renderPlanMap(samplePayload({ plan_date: '2026-09-01' }));
  const firstSig = AtpPlanMap.getCurrentRoutePointCount();
  assert.ok(firstSig > 0);

  sandbox.AtpRoute.getLastRoute = () => ({ current: { geometry: [] } });
  AtpPlanMap.renderPlanMap(samplePayload({ plan_date: '2026-09-02' }));
  assert.equal(AtpPlanMap.hasCurrentRoute(), false);
  assert.equal(AtpPlanMap.haloLayerCount(), 0);
  AtpPlanMap._testReset();
});

test('RL13 stale async response → does not overwrite active plan', () => {
  const { AtpPlanMap } = loadPlanMapModule();
  AtpPlanMap.ensurePlanMap();
  AtpPlanMap.renderPlanMap(samplePayload({ vehicle_id: 100, plan_date: '2026-09-01' }));
  const activeSeq = AtpPlanMap.getRouteContextSeq();
  AtpPlanMap.setCurrentRouteGeometry(denseOrsFixture(), { contextSeq: activeSeq - 1 });
  assert.equal(AtpPlanMap.hasCurrentRoute(), false);
  AtpPlanMap.setCurrentRouteGeometry(denseOrsFixture(), { contextSeq: activeSeq });
  assert.equal(AtpPlanMap.hasCurrentRoute(), true);
  AtpPlanMap._testReset();
});

test('RL14 invalid lat/lng → safely rejected', () => {
  const { pure } = loadPlanMapModule();
  assert.equal(pure.isDrawableRouteGeometry([[91, 0], [0, 0]]), false);
  assert.equal(pure.isDrawableRouteGeometry([[40, 200], [41, 29]]), false);
  assert.equal(pure.isDrawableRouteGeometry('not-array'), false);
  assert.equal(pure.isDrawableRouteGeometry(null), false);
});

test('RL15 input geometry is not mutated', () => {
  const { pure } = loadPlanMapModule();
  const input = [[40.993, 28.695], [40.994, 28.700], [40.995, 28.705]];
  const copy = JSON.stringify(input);
  pure.normalizeValidLatLngs(input);
  pure.isDrawableRouteGeometry(input);
  assert.equal(JSON.stringify(input), copy);
});

test('RL16 manual reorder namespace unaffected', () => {
  assert.ok(typeof MR.createState === 'function');
  assert.ok(typeof MR.moveUp === 'function');
  const state = MR.createState({
    plan_id: 41,
    state_token: 'tok',
    ordered_item_ids: ['a', 'b'],
    tasks: [
      { task_id: 'a', order_no: 1, can_move: true, lock_reason: null, segment_index: 0 },
      { task_id: 'b', order_no: 2, can_move: true, lock_reason: null, segment_index: 0 },
    ],
  });
  assert.equal(state.draftOrder.length, 2);
});

test('RL17 GPS history layer not touched by plan map route fix', () => {
  const src = require('node:fs').readFileSync(PLAN_MAP_PATH, 'utf8');
  assert.ok(!src.includes('gpsHistory'), 'plan map must not reference GPS history layers');
  assert.ok(!src.includes('GpsTrail'), 'plan map must not reference GPS trail layers');
});

test('RL18 optimizer current/suggested separation preserved', () => {
  const { AtpPlanMap } = loadPlanMapModule();
  AtpPlanMap.ensurePlanMap();
  AtpPlanMap.setCurrentRouteGeometry(denseOrsFixture());
  AtpPlanMap.setSuggestedRouteGeometry(denseOrsFixture().slice(0, 35));
  assert.equal(AtpPlanMap.hasCurrentRoute(), true);
  assert.equal(AtpPlanMap.hasSuggestedRoute(), true);
  assert.equal(AtpPlanMap.routeLayerCount(), 2);
  assert.equal(AtpPlanMap.haloLayerCount(), 2);
  AtpPlanMap.clearSuggestedRouteGeometry();
  assert.equal(AtpPlanMap.hasCurrentRoute(), true);
  assert.equal(AtpPlanMap.hasSuggestedRoute(), false);
  AtpPlanMap._testReset();
});

test('RL19 identical current/suggested → current=1 halo=1', () => {
  const { AtpPlanMap } = loadPlanMapModule();
  AtpPlanMap.ensurePlanMap();
  const geom = identicalDenseFixture();
  AtpPlanMap.setCurrentRouteGeometry(geom);
  AtpPlanMap.setSuggestedRouteGeometry(geom);
  assert.equal(AtpPlanMap.routeLayerCount(), 1);
  assert.equal(AtpPlanMap.haloLayerCount(), 1);
  assert.equal(AtpPlanMap.hasCurrentRoute(), true);
  AtpPlanMap._testReset();
});

test('RL20 identical current/suggested → suggested=0 suggested halo=0', () => {
  const { AtpPlanMap } = loadPlanMapModule();
  AtpPlanMap.ensurePlanMap();
  const geom = identicalDenseFixture();
  AtpPlanMap.setCurrentRouteGeometry(geom);
  AtpPlanMap.setSuggestedRouteGeometry(geom);
  assert.equal(AtpPlanMap.hasSuggestedRoute(), false);
  assert.equal(dashedSuggestedLayers(AtpPlanMap).length, 0);
  AtpPlanMap._testReset();
});

test('RL21 identical second render → suggested does not return', () => {
  const { AtpPlanMap, sandbox } = loadPlanMapModule();
  AtpPlanMap.ensurePlanMap();
  const geom = identicalDenseFixture();
  setLastRoute(sandbox, geom, geom);
  AtpPlanMap.setCurrentRouteGeometry(geom);
  AtpPlanMap.setSuggestedRouteGeometry(geom);
  AtpPlanMap.setSuggestedRouteGeometry(geom);
  AtpPlanMap.syncRouteFromLast();
  assert.equal(AtpPlanMap.hasSuggestedRoute(), false);
  assert.equal(AtpPlanMap.routeLayerCount(), 1);
  AtpPlanMap._testReset();
});

test('RL22 identical date roundtrip → suggested stays suppressed', () => {
  const { AtpPlanMap, sandbox } = loadPlanMapModule();
  AtpPlanMap.ensurePlanMap();
  const geom = identicalDenseFixture();
  setLastRoute(sandbox, geom, geom);
  AtpPlanMap.renderPlanMap(samplePayload({ plan_date: '2026-09-01' }));
  assert.equal(AtpPlanMap.hasSuggestedRoute(), false);
  AtpPlanMap.renderPlanMap(samplePayload({ plan_date: '2026-09-02' }));
  AtpPlanMap.renderPlanMap(samplePayload({ plan_date: '2026-09-01' }));
  assert.equal(AtpPlanMap.hasSuggestedRoute(), false);
  assert.equal(AtpPlanMap.routeLayerCount(), 1);
  AtpPlanMap._testReset();
});

test('RL23 identical vehicle roundtrip → suggested stays suppressed', () => {
  const { AtpPlanMap, sandbox } = loadPlanMapModule();
  AtpPlanMap.ensurePlanMap();
  const geom = identicalDenseFixture();
  setLastRoute(sandbox, geom, geom);
  AtpPlanMap.renderPlanMap(samplePayload({ vehicle_id: 991002 }));
  assert.equal(AtpPlanMap.hasSuggestedRoute(), false);
  AtpPlanMap.renderPlanMap(samplePayload({ vehicle_id: 991003 }));
  setLastRoute(sandbox, geom, geom);
  AtpPlanMap.renderPlanMap(samplePayload({ vehicle_id: 991002 }));
  assert.equal(AtpPlanMap.hasSuggestedRoute(), false);
  AtpPlanMap._testReset();
});

test('RL24 different suggested compare → green dashed suggested drawn', () => {
  const { AtpPlanMap } = loadPlanMapModule();
  AtpPlanMap.ensurePlanMap();
  AtpPlanMap.setCurrentRouteGeometry(denseOrsFixture());
  AtpPlanMap.setSuggestedRouteGeometry(differentDenseFixture());
  assert.equal(AtpPlanMap.hasSuggestedRoute(), true);
  assert.equal(AtpPlanMap.routeLayerCount(), 2);
  assert.equal(AtpPlanMap.haloLayerCount(), 2);
  assert.equal(dashedSuggestedLayers(AtpPlanMap).length, 1);
  AtpPlanMap._testReset();
});

test('RL25 same distance different geometry → suggested preserved', () => {
  const { AtpPlanMap, pure } = loadPlanMapModule();
  const current = denseOrsFixture();
  const suggested = sameDistanceDifferentPathFixture();
  assert.equal(pure.isIdenticalRouteGeometry(current, suggested), false);
  AtpPlanMap.ensurePlanMap();
  AtpPlanMap.setCurrentRouteGeometry(current);
  AtpPlanMap.setSuggestedRouteGeometry(suggested);
  assert.equal(AtpPlanMap.hasSuggestedRoute(), true);
  AtpPlanMap._testReset();
});

test('RL26 current signature change re-evaluates identical compare', () => {
  const { AtpPlanMap } = loadPlanMapModule();
  AtpPlanMap.ensurePlanMap();
  const suggested = differentDenseFixture();
  AtpPlanMap.setCurrentRouteGeometry(denseOrsFixture());
  AtpPlanMap.setSuggestedRouteGeometry(suggested);
  assert.equal(AtpPlanMap.hasSuggestedRoute(), true);
  AtpPlanMap.setCurrentRouteGeometry(suggested);
  AtpPlanMap.setSuggestedRouteGeometry(suggested);
  assert.equal(AtpPlanMap.hasSuggestedRoute(), false);
  AtpPlanMap._testReset();
});

test('RL27 suggested empty → old suggested cleared', () => {
  const { AtpPlanMap } = loadPlanMapModule();
  AtpPlanMap.ensurePlanMap();
  AtpPlanMap.setCurrentRouteGeometry(denseOrsFixture());
  AtpPlanMap.setSuggestedRouteGeometry(differentDenseFixture());
  AtpPlanMap.setSuggestedRouteGeometry([]);
  assert.equal(AtpPlanMap.hasSuggestedRoute(), false);
  AtpPlanMap._testReset();
});

test('RL28 current empty → old current and halo cleared', () => {
  const { AtpPlanMap, sandbox } = loadPlanMapModule();
  AtpPlanMap.ensurePlanMap();
  setLastRoute(sandbox, denseOrsFixture(), differentDenseFixture());
  AtpPlanMap.renderPlanMap(samplePayload());
  assert.equal(AtpPlanMap.hasCurrentRoute(), true);
  setLastRoute(sandbox, [], []);
  AtpPlanMap.syncRouteFromLast();
  assert.equal(AtpPlanMap.hasCurrentRoute(), false);
  assert.equal(AtpPlanMap.hasSuggestedRoute(), false);
  assert.equal(AtpPlanMap.haloLayerCount(), 0);
  AtpPlanMap._testReset();
});

test('RL29 sparse suggested → not drawn', () => {
  const { AtpPlanMap } = loadPlanMapModule();
  AtpPlanMap.ensurePlanMap();
  AtpPlanMap.setCurrentRouteGeometry(denseOrsFixture());
  AtpPlanMap.setSuggestedRouteGeometry(sparseLongChordFixture());
  assert.equal(AtpPlanMap.hasSuggestedRoute(), false);
  AtpPlanMap._testReset();
});

test('RL30 dense identical ORS fixture → dedup suggested overlay', () => {
  const { AtpPlanMap, sandbox } = loadPlanMapModule();
  AtpPlanMap.ensurePlanMap();
  const geom = identicalDenseFixture();
  setLastRoute(sandbox, geom, geom);
  AtpPlanMap.renderPlanMap(samplePayload());
  assert.equal(AtpPlanMap.getCurrentRoutePointCount(), geom.length);
  assert.equal(AtpPlanMap.hasSuggestedRoute(), false);
  assert.equal(totalActivePolylineLayers(AtpPlanMap), 2);
  AtpPlanMap._testReset();
});

test('RL31 identical path input geometries are not mutated', () => {
  const { AtpPlanMap, pure } = loadPlanMapModule();
  const current = identicalDenseFixture();
  const suggested = current.map((p) => [p[0], p[1]]);
  const copyCur = JSON.stringify(current);
  const copySug = JSON.stringify(suggested);
  AtpPlanMap.ensurePlanMap();
  AtpPlanMap.setCurrentRouteGeometry(current);
  AtpPlanMap.setSuggestedRouteGeometry(suggested);
  pure.geometrySignature(current);
  pure.geometrySignature(suggested);
  assert.equal(JSON.stringify(current), copyCur);
  assert.equal(JSON.stringify(suggested), copySug);
  AtpPlanMap._testReset();
});

test('RL32 identical dedup preserves halo lifecycle without orphans', () => {
  const { AtpPlanMap } = loadPlanMapModule();
  AtpPlanMap.ensurePlanMap();
  const geom = identicalDenseFixture();
  AtpPlanMap.setCurrentRouteGeometry(geom);
  AtpPlanMap.setSuggestedRouteGeometry(geom);
  AtpPlanMap.setSuggestedRouteGeometry(differentDenseFixture());
  AtpPlanMap.setSuggestedRouteGeometry(geom);
  assert.equal(AtpPlanMap.haloLayerCount(), 1);
  assert.equal(AtpPlanMap.orphanHaloCount(), 0);
  AtpPlanMap._testReset();
});

test('RL33 stale seq guard still blocks identical suggested replay', () => {
  const { AtpPlanMap } = loadPlanMapModule();
  AtpPlanMap.ensurePlanMap();
  AtpPlanMap.renderPlanMap(samplePayload({ vehicle_id: 200, plan_date: '2026-09-01' }));
  const activeSeq = AtpPlanMap.getRouteContextSeq();
  const geom = identicalDenseFixture();
  AtpPlanMap.setCurrentRouteGeometry(geom, { contextSeq: activeSeq });
  AtpPlanMap.setSuggestedRouteGeometry(geom, { contextSeq: activeSeq - 1 });
  assert.equal(AtpPlanMap.hasCurrentRoute(), true);
  assert.equal(AtpPlanMap.hasSuggestedRoute(), false);
  AtpPlanMap._testReset();
});

test('RL34 dashArray 10 6 preserved for different suggested route', () => {
  const { AtpPlanMap } = loadPlanMapModule();
  AtpPlanMap.ensurePlanMap();
  AtpPlanMap.setCurrentRouteGeometry(denseOrsFixture());
  AtpPlanMap.setSuggestedRouteGeometry(differentDenseFixture());
  const dashed = dashedSuggestedLayers(AtpPlanMap);
  assert.equal(dashed.length, 1);
  assert.equal(dashed[0].dashArray, '10 6');
  assert.equal(dashed[0].color, '#16a34a');
  AtpPlanMap._testReset();
});

test('RL35 Öneri=Mevcut model → only two route SVG paths (current+halo)', () => {
  const { AtpPlanMap, sandbox } = loadPlanMapModule();
  AtpPlanMap.ensurePlanMap();
  const geom = identicalDenseFixture();
  setLastRoute(sandbox, geom, geom);
  AtpPlanMap.renderPlanMap(samplePayload());
  assert.equal(AtpPlanMap.routeLayerCount(), 1);
  assert.equal(AtpPlanMap.haloLayerCount(), 1);
  assert.equal(totalActivePolylineLayers(AtpPlanMap), 2);
  assert.equal(dashedSuggestedLayers(AtpPlanMap).length, 0);
  AtpPlanMap._testReset();
});

test('RL36 manual reorder optimizer GPS namespaces unaffected by U4F dedup', () => {
  assert.ok(typeof MR.createState === 'function');
  const src = require('node:fs').readFileSync(PLAN_MAP_PATH, 'utf8');
  assert.ok(!src.includes('gpsHistory'));
  assert.ok(!src.includes('ATP_MANUAL_REORDER'));
  assert.ok(src.includes('isIdenticalRouteGeometry'));
  assert.ok(!src.includes('AtpRouteOptimizer'));
});
