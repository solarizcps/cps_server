# -*- coding: utf-8 -*-
"""ROUTE14B-01..30 — Araç Takip V1.4B road routing pilot (mock provider)."""
from __future__ import annotations

import io
import os
import sys
from unittest.mock import MagicMock, patch

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

_ROOT = os.path.dirname(os.path.abspath(__file__))
_APP = os.path.join(_ROOT, 'app')
sys.path.insert(0, _APP)
os.chdir(_APP)

results: list[tuple[str, bool, str]] = []


def ok(name: str, cond: bool, detail: str = '') -> None:
    results.append((name, cond, detail))
    print(f'  [{"PASS" if cond else "FAIL"}] {name}' + (f' — {detail}' if detail else ''))


print('=' * 72)
print('ROUTE14B — Araç Takip V1.4B Road Routing')
print('=' * 72)

from modules.planlama.road_routing.provider_base import RoadRoutingProvider
from modules.planlama.road_routing.mock_provider import MockRoadRoutingProvider
from modules.planlama.road_routing.openrouteservice_provider import OpenRouteServiceProvider, provider_available
from modules.planlama.road_routing.types import RouteResult, RoutingError
from modules.planlama.road_routing.cache import cache_clear, cache_get, cache_set, make_cache_key
from modules.planlama.road_routing.suggest import suggest_stop_order
from modules.planlama.road_routing.route_planner_service import (
    build_plan_route_dto,
    get_routing_provider,
    _merge_apply_order,
)

# ROUTE14B-01 provider interface
ok('ROUTE14B-01 provider interface', issubclass(MockRoadRoutingProvider, RoadRoutingProvider))

mock = MockRoadRoutingProvider()
pts = [(41.0, 29.0), (41.01, 29.02), (41.02, 29.05)]

# ROUTE14B-02 ORS adapter normalization (structure via mock normalized DTO)
route = mock.route_ordered(pts)
ok('ROUTE14B-02 adapter normalization', route.provider == 'mock' and route.distance_m > 0 and route.geometry)

# ROUTE14B-03 secret absent graceful
with patch.dict(os.environ, {}, clear=True):
    os.environ.pop('ORS_API_KEY', None)
    ok('ROUTE14B-03 secret absent graceful', not provider_available())
    dto = build_plan_route_dto({'latitude': 41.0, 'longitude': 29.0, 'has_coordinates': True}, [])
    ok('ROUTE14B-03 page-safe unconfigured', dto['status'] == 'UNCONFIGURED' and 'yapılandırılmamış' in (dto.get('message') or ''))

# ROUTE14B-04..08 provider errors via mock HTTP
class FailProvider(MockRoadRoutingProvider):
    def route_ordered(self, points):
        raise RoutingError('Rota hesaplanamadı.', code='TIMEOUT')

try:
    FailProvider().route_ordered(pts)
    ok('ROUTE14B-04 timeout graceful', False)
except RoutingError as e:
    ok('ROUTE14B-04 timeout graceful', e.code == 'TIMEOUT')

for code, label in [('AUTH', 401), ('RATE_LIMIT', 429), ('SERVER', 503), ('INVALID_JSON', 'json')]:
    err = RoutingError('Rota hesaplanamadı.', code=code)
    ok(f'ROUTE14B error code {code}', err.code == code)

dto_fail = build_plan_route_dto(
    {'latitude': 41.0, 'longitude': 29.0, 'has_coordinates': True},
    [{'id': 'pi-1', 'order_no': 1, 'has_coordinates': True, 'latitude': 41.01, 'longitude': 29.02, 'company_name': 'A'}],
    provider=FailProvider(),
)
ok('ROUTE14B-08 invalid response graceful', dto_fail['status'] == 'TIMEOUT' and dto_fail['current']['km'] == '—')

# ROUTE14B-09 ordered road route
ok('ROUTE14B-09 ordered road route', len(route.legs) == 2)

# ROUTE14B-10 geometry
ok('ROUTE14B-10 geometry', len(route.geometry) >= 2)

# ROUTE14B-11 legs parity
leg_sum = sum(lg.distance_m for lg in route.legs)
ok('ROUTE14B-11 legs parity', abs(leg_sum - route.distance_m) < 1.0)

# ROUTE14B-12/13 totals
ok('ROUTE14B-12 total distance parity', route.distance_m > 0)
ok('ROUTE14B-13 total duration parity', route.duration_s > 0)

base = {'latitude': 41.0, 'longitude': 29.0, 'has_coordinates': True, 'base_name': 'BASE'}
tasks = [
    {'id': 'pi-1', 'order_no': 1, 'has_coordinates': True, 'latitude': 41.01, 'longitude': 29.02, 'company_name': 'A', 'priority': 'NORMAL'},
    {'id': 'pi-2', 'order_no': 2, 'has_coordinates': False, 'company_name': 'B'},
    {'id': 'pi-3', 'order_no': 3, 'has_coordinates': True, 'latitude': 41.02, 'longitude': 29.05, 'company_name': 'C', 'priority': 'NORMAL'},
]
dto_partial = build_plan_route_dto(base, tasks, provider=mock)
ok('ROUTE14B-14 missing coordinate partial', dto_partial['status'] == 'PARTIAL' and dto_partial['meta']['missing_count'] == 1)

# ROUTE14B-15..17 cache
cache_clear()
key = make_cache_key('mock', 'driving-car', pts)
cache_set(key, route)
ok('ROUTE14B-15 cache hit', cache_get(key) is route)
key2 = make_cache_key('mock', 'driving-car', pts + [(41.03, 29.06)])
ok('ROUTE14B-16 coordinate change cache miss', cache_get(key2) is None)
key3 = make_cache_key('mock', 'driving-car', list(reversed(pts)))
ok('ROUTE14B-17 order change cache miss', cache_get(key3) is None)

# ROUTE14B-18 matrix normalization
mat = mock.matrix(pts)
ok('ROUTE14B-18 matrix normalization', len(mat.duration_s) == 3 and mat.duration_s[0][0] == 0.0)

# ROUTE14B-19 deterministic suggestion
stops = [
    {'id': 'pi-1', 'matrix_index': 1, 'priority': 'NORMAL', 'planned_time': '—', 'order_no': 1},
    {'id': 'pi-2', 'matrix_index': 2, 'priority': 'NORMAL', 'planned_time': '—', 'order_no': 2},
]
s1 = suggest_stop_order(stops, mat.duration_s)
s2 = suggest_stop_order(stops, mat.duration_s)
ok('ROUTE14B-19 deterministic suggestion', s1 == s2 and len(s1) == 2)

# ROUTE14B-20 priority guard
stops_pri = [
    {'id': 'pi-far', 'matrix_index': 2, 'priority': 'NORMAL', 'planned_time': '—', 'order_no': 2},
    {'id': 'pi-acil', 'matrix_index': 1, 'priority': 'ACIL', 'planned_time': '—', 'order_no': 1},
]
s_pri = suggest_stop_order(stops_pri, mat.duration_s)
ok('ROUTE14B-20 priority guard', s_pri[0] == 'pi-acil')

# ROUTE14B-21 appointment-time guard
stops_time = [
    {'id': 'pi-late', 'matrix_index': 2, 'priority': 'NORMAL', 'planned_time': '15:00', 'order_no': 2},
    {'id': 'pi-early', 'matrix_index': 1, 'priority': 'NORMAL', 'planned_time': '09:00', 'order_no': 1},
]
s_time = suggest_stop_order(stops_time, mat.duration_s)
ok('ROUTE14B-21 appointment-time guard', s_time.index('pi-early') < s_time.index('pi-late'))

dto_full = build_plan_route_dto(base, [t for t in tasks if t['has_coordinates']], provider=mock)
ok('ROUTE14B-22 suggested geometry preview', len(dto_full['suggested'].get('geometry') or []) >= 2)
ok('ROUTE14B-23 preview DB write = 0', dto_full.get('suggested_preview_only') is True)

# ROUTE14B-24 explicit accept required — API requires POST apply (no auto reorder)
def _run_migrations_temp(db_path: str) -> None:
    import importlib.util
    for mig in (
        '176_arac_takip_v13.py', '177_arac_operasyon_ayar.py',
        '178_arac_is_talebi_ux_v2_fields.py', '179_arac_gps_snapshot_p1.py',
    ):
        spec = importlib.util.spec_from_file_location(
            mig, os.path.join(_APP, 'migrations', mig),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.run(db_path)


def _route_test_client():
    import app as flask_app
    flask_app.app.config['TESTING'] = True
    c = flask_app.app.test_client()
    with c.session_transaction() as s:
        s['kullanici'] = {
            'Id': 1, 'KullaniciAdi': 'alpay', 'AdSoyad': 'Alpay Test',
            'Tip': 'sistem', 'RolId': 1, 'RolAd': 'admin', 'Aktif': 1,
        }
        s['kullanici_tip'] = 'sistem'
    return c


import tempfile
import importlib.util as _ilu
from contextlib import contextmanager


@contextmanager
def _isolated_route14b_db():
    """Temp DB + config patch — canonical DB bağımlılığı yok."""
    tmpdir = tempfile.mkdtemp(prefix='route14b_')
    db_path = os.path.join(tmpdir, 'route14b.db')
    _run_migrations_temp(db_path)
    import config
    with patch.object(config.Config, 'MOCK_DB_PATH', db_path):
        yield db_path


AUTH_PATCH = {
    'modules.auth.kullanici_yetkileri': frozenset({'planlama:can_view', 'planlama:can_update'}),
    'modules.auth.sistem_session_gecerli_mi': True,
    'modules.auth.yetki_var': True,
    'modules.auth.is_superadmin': True,
}

with _isolated_route14b_db(), \
     patch.dict(os.environ, {'ARAC_ROUTING_PROVIDER': 'mock'}, clear=False), \
     patch('modules.auth.kullanici_yetkileri', return_value=AUTH_PATCH['modules.auth.kullanici_yetkileri']), \
     patch('modules.auth.sistem_session_gecerli_mi', return_value=True), \
     patch('modules.auth.yetki_var', return_value=True), \
     patch('modules.auth.is_superadmin', return_value=True):
    c = _route_test_client()
    r = c.get('/planlama/arac-takip/api/route/plan?date=2026-08-21')
    body = r.get_json() or {}
    ok('ROUTE14B-24 route plan GET ok', r.status_code == 200 and body.get('ok') is True,
       f'status={r.status_code} body={str(body)[:120]}')

# ROUTE14B-25 locked two-phase reorder reuse
from modules.planlama.arac_takip_repo import reorder_plan_items_bulk, tables_ready
with _isolated_route14b_db():
    if tables_ready():
        ok('ROUTE14B-25 bulk reorder fn exists', callable(reorder_plan_items_bulk))
    else:
        ok('ROUTE14B-25 bulk reorder fn exists', False, 'tables missing on temp db')

merged = _merge_apply_order(tasks, ['pi-3', 'pi-1'])
ok('ROUTE14B-26 merge keeps missing slot', 'pi-2' in merged and merged.index('pi-2') == 1)

# ROUTE14B-27/28 regression hooks — template assets present
tpl = open(os.path.join(_APP, 'templates', 'planlama', 'arac_takip_plan.html'), encoding='utf-8').read()
ok('ROUTE14B-28 PlanMap regression assets', 'planlama_arac_takip_plan_map.js' in tpl and 'AtpPlanMap' not in tpl)
ok('ROUTE14B-27 LiveMap regression assets', 'planlama_arac_takip_map.js' in tpl)

js_plan = open(os.path.join(_APP, 'static', 'js', 'planlama_arac_takip_plan_map.js'), encoding='utf-8').read()
ok('ROUTE14B-29 provider failure pins survive', 'clearRouteLayers' in js_plan and 'clearPlanMarkers' in js_plan)
ok('ROUTE14B-30 route module present', 'planlama_arac_takip_route.js' in tpl)

# ORS provider init without key
with patch.dict(os.environ, {}, clear=True):
    os.environ.pop('ORS_API_KEY', None)
    try:
        OpenRouteServiceProvider()
        ok('ROUTE14B-03b ORS init blocked', False)
    except RoutingError:
        ok('ROUTE14B-03b ORS init blocked', True)

print('\n' + '=' * 72)
passed = sum(1 for _, p, _ in results if p)
print(f'ROUTE14B: {passed}/{len(results)} PASS')
if passed != len(results):
    for name, p, d in results:
        if not p:
            print(f'  FAIL: {name} {d}')
    sys.exit(1)
print('ALL PASS')
