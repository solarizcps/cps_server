# -*- coding: utf-8 -*-
"""R07 — traffic-aware constrained route proposal."""
from __future__ import annotations

import importlib.util
import os
import sqlite3
import tempfile
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'app'
MIGRATIONS = APP / 'migrations'
PLAN_DATE = '2026-09-22'
VID = '991R07VEH_A'
BASE = {'latitude': 41.0, 'longitude': 29.0, 'has_coordinates': True, 'base_name': 'Fabrika'}
_PID = 970000


def _pid(n: int) -> int:
    return _PID + n


def _run_migration(db_path: str, filename: str) -> None:
    spec = importlib.util.spec_from_file_location(filename, MIGRATIONS / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.run(db_path)


@pytest.fixture()
def r07_db(monkeypatch):
    import sys
    from tools.atp_test_db_guard import bind_temp_db_path

    saved = {k: sys.modules[k] for k in list(sys.modules) if k == 'db' or k.startswith('modules.planlama')}
    tmpdir = tempfile.mkdtemp(prefix='r07_')
    db_path = str(Path(tmpdir) / 'test.db')
    for mig in (
        '176_arac_takip_v13.py', '177_arac_operasyon_ayar.py', '178_arac_is_talebi_ux_v2_fields.py',
        '179_arac_gps_snapshot_p1.py', '180_arac_plan_ziyaret_durum.py', '182_arac_plan_change_v1.py',
    ):
        _run_migration(db_path, mig)
    bind_temp_db_path(db_path)
    monkeypatch.setenv('CPS_TEST_DB_GUARD', '0')
    for mod_name in list(sys.modules):
        if mod_name == 'db' or mod_name.startswith('modules.planlama'):
            sys.modules.pop(mod_name, None)
    try:
        yield db_path
    finally:
        for k, mod in saved.items():
            sys.modules[k] = mod


def _task(
    tid: str,
    *,
    plan_item_id: int,
    order_no: int,
    status: str = 'PLANLANDI',
    priority: str = 'NORMAL',
    lat: float = 41.01,
    lon: float = 29.01,
    company: str = 'Firma',
) -> dict:
    return {
        'id': tid,
        'plan_item_id': plan_item_id,
        'order_no': order_no,
        'status': status,
        'priority': priority,
        'latitude': lat,
        'longitude': lon,
        'has_coordinates': True,
        'company_name': company,
        'arac_external_id': VID,
    }


def _matrix_3point(*_args, **_kwargs) -> tuple:
    from modules.planlama.road_routing.types import RouteMatrix
    n = 4  # base + 3 stops
    d = [[0.0] * n for _ in range(n)]
    dist = [[0.0] * n for _ in range(n)]
    static = [[0.0] * n for _ in range(n)]
    # Current DB order 1->2->3 is suboptimal; traffic matrix prefers 1->3->2.
    pairs = [(0, 1, 600, 500), (0, 2, 900, 800), (0, 3, 900, 800),
             (1, 2, 800, 700), (1, 3, 200, 180), (2, 3, 200, 180),
             (2, 1, 850, 750), (3, 2, 200, 180), (3, 1, 220, 200),
             (1, 0, 610, 510), (2, 0, 200, 180), (3, 0, 800, 750)]
    for i, j, dur, st in pairs:
        d[i][j] = float(dur)
        static[i][j] = float(st)
        dist[i][j] = float(dur * 10)
    m = RouteMatrix(provider='mock', profile='test', duration_s=d, distance_m=dist)
    return m, static, n * n, 1


def _proposal(tasks: list[dict], **kw):
    from modules.planlama.arac_traffic_route_proposal_service import compute_traffic_route_proposal
    from modules.planlama.road_routing.traffic_proposal_cache import cache_clear
    cache_clear()
    with patch('modules.planlama.arac_traffic_route_proposal_service.google_routes_key_present', return_value=True):
        with patch('modules.planlama.arac_traffic_route_proposal_service.load_visit_states_for_tasks', return_value={}):
            return compute_traffic_route_proposal(
                base=BASE,
                tasks=tasks,
                plan_date=PLAN_DATE,
                vehicle_id=VID,
                plan_id=1,
                matrix_provider_fn=_matrix_3point,
                ors_provider_fn=lambda: None,
                **kw,
            )


def test_t01_google_traffic_success():
    p = _proposal([
        _task('pi-1', plan_item_id=_pid(1), order_no=1, lat=41.01, lon=29.01),
        _task('pi-2', plan_item_id=_pid(2), order_no=2, lat=41.02, lon=29.02),
        _task('pi-3', plan_item_id=_pid(3), order_no=3, lat=41.03, lon=29.03),
    ])
    assert p['provider'] == 'google_traffic'
    assert p['traffic_available'] is True
    assert p['traffic_model'] == 'TRAFFIC_AWARE_OPTIMAL'
    assert p['current_item_ids'] == [_pid(1), _pid(2), _pid(3)]
    assert p['suggested_item_ids'] == [_pid(1), _pid(3), _pid(2)]
    assert p['changed'] is True
    assert p['apply_enabled'] is True


def test_t02_google_unconfigured(monkeypatch):
    from modules.planlama.road_routing.traffic_proposal_cache import cache_clear
    from modules.planlama.road_routing.types import RouteMatrix
    from modules.planlama.road_routing.mock_provider import MockRoadRoutingProvider
    cache_clear()
    monkeypatch.setenv('GOOGLE_ROUTES_API_KEY', '')
    tasks = [_task('pi-1', plan_item_id=_pid(1), order_no=1), _task('pi-2', plan_item_id=_pid(2), order_no=2)]
    with patch('modules.planlama.arac_traffic_route_proposal_service.google_routes_key_present', return_value=False):
        with patch('modules.planlama.arac_traffic_route_proposal_service.ors_key_present', return_value=True):
            with patch('modules.planlama.arac_traffic_route_proposal_service.get_routing_provider') as gp:
                gp.return_value = MockRoadRoutingProvider()
                from modules.planlama.arac_traffic_route_proposal_service import compute_traffic_route_proposal
                p = compute_traffic_route_proposal(
                    base=BASE, tasks=tasks, plan_date=PLAN_DATE, vehicle_id=VID, plan_id=1,
                )
    assert p['provider'] == 'ors_no_traffic'
    assert p['traffic_available'] is False


def test_t03_google_timeout():
    from modules.planlama.road_routing.types import RoutingError
    from modules.planlama.road_routing.traffic_proposal_cache import cache_clear
    from modules.planlama.arac_traffic_route_proposal_service import compute_traffic_route_proposal

    cache_clear()
    tasks = [_task('pi-1', plan_item_id=_pid(1), order_no=1), _task('pi-2', plan_item_id=_pid(2), order_no=2, lat=41.02, lon=29.02)]

    def _fail(*a, **k):
        raise RoutingError('timeout', code='TIMEOUT')

    with patch('modules.planlama.arac_traffic_route_proposal_service.google_routes_key_present', return_value=True):
        with patch('modules.planlama.arac_traffic_route_proposal_service.ors_key_present', return_value=False):
            p = compute_traffic_route_proposal(
                base=BASE, tasks=tasks, plan_date=PLAN_DATE, vehicle_id=VID, plan_id=1,
                matrix_provider_fn=_fail,
            )
    assert p['provider'] == 'current_order_fallback'
    assert p['apply_enabled'] is False


def test_t14_acil_before_normals():
    tasks = [
        _task('pi-n1', plan_item_id=_pid(1), order_no=1, priority='NORMAL', lat=41.01, lon=29.01),
        _task('pi-a1', plan_item_id=_pid(2), order_no=2, priority='ACIL', lat=41.02, lon=29.02),
        _task('pi-n2', plan_item_id=_pid(3), order_no=3, priority='NORMAL', lat=41.03, lon=29.03),
    ]
    p = _proposal(tasks)
    order = p['suggested_task_ids']
    assert order.index('pi-a1') < order.index('pi-n1')
    assert order.index('pi-a1') < order.index('pi-n2')


def test_t15_multiple_acil_fifo():
    tasks = [
        _task('pi-n1', plan_item_id=_pid(1), order_no=1, priority='NORMAL'),
        _task('pi-a1', plan_item_id=_pid(2), order_no=2, priority='ACIL', company='A1'),
        _task('pi-a2', plan_item_id=_pid(3), order_no=3, priority='ACIL', company='A2'),
    ]
    p = _proposal(tasks)
    sub = [x for x in p['suggested_task_ids'] if x.startswith('pi-a')]
    assert sub == ['pi-a1', 'pi-a2']


def test_t12_completed_locked():
    from modules.planlama.arac_route_constraints import build_r07_constrained_full_order, classify_route_tasks
    from modules.planlama.road_routing.suggest import suggest_segment_order
    tasks = [
        _task('pi-done', plan_item_id=_pid(1), order_no=1, status='TAMAMLANDI'),
        _task('pi-n1', plan_item_id=_pid(2), order_no=2),
        _task('pi-n2', plan_item_id=_pid(3), order_no=3, lat=41.02, lon=29.02),
    ]
    routable = [
        {'id': 'pi-n1', 'matrix_index': 1, 'order_no': 2, 'priority': 'NORMAL', 'planned_time': None},
        {'id': 'pi-n2', 'matrix_index': 2, 'order_no': 3, 'priority': 'NORMAL', 'planned_time': None},
    ]
    c = classify_route_tasks(tasks)
    mat = [[0, 100, 200], [100, 0, 50], [200, 50, 0]]
    order, _ = build_r07_constrained_full_order(tasks, c, routable, mat, suggest_segment_order_fn=suggest_segment_order)
    assert order[0] == 'pi-done'


def test_t13_started_locked():
    tasks = [
        _task('pi-start', plan_item_id=_pid(1), order_no=1, status='BASLADI'),
        _task('pi-n1', plan_item_id=_pid(2), order_no=2),
        _task('pi-n2', plan_item_id=_pid(3), order_no=3, lat=41.02, lon=29.02),
    ]
    p = _proposal(tasks)
    assert p['suggested_task_ids'][0] == 'pi-start'


def test_t17_iptal_excluded():
    tasks = [
        _task('pi-n1', plan_item_id=_pid(1), order_no=1),
        _task('pi-x', plan_item_id=_pid(2), order_no=2, status='IPTAL'),
        _task('pi-n2', plan_item_id=_pid(3), order_no=3, lat=41.02, lon=29.02),
    ]
    p = _proposal(tasks)
    assert 'pi-x' not in p['suggested_task_ids']


def test_t18_missing_coordinates_preserved():
    tasks = [
        _task('pi-n1', plan_item_id=_pid(1), order_no=1),
        _task('pi-m', plan_item_id=_pid(2), order_no=2, lat=None, lon=None),
    ]
    tasks[1]['has_coordinates'] = False
    p = _proposal(tasks)
    assert _pid(2) in p['missing_location_item_ids']
    assert 'pi-m' in p['suggested_task_ids']


def test_t22_proposal_hash_stable():
    from modules.planlama.arac_traffic_route_proposal_service import build_proposal_state_hash
    tasks = [_task('pi-1', plan_item_id=_pid(1), order_no=1), _task('pi-2', plan_item_id=_pid(2), order_no=2)]
    h1 = build_proposal_state_hash(plan_id=1, plan_date=PLAN_DATE, vehicle_id=VID, tasks=tasks)
    h2 = build_proposal_state_hash(plan_id=1, plan_date=PLAN_DATE, vehicle_id=VID, tasks=tasks)
    assert h1 == h2


def test_t23_stale_proposal_rejected():
    from modules.planlama.arac_route_constraints import RouteApplyConflictError
    from modules.planlama.arac_traffic_route_proposal_service import validate_proposal_for_apply
    tasks = [_task('pi-1', plan_item_id=_pid(1), order_no=1), _task('pi-2', plan_item_id=_pid(2), order_no=2)]
    with pytest.raises(RouteApplyConflictError) as exc:
        validate_proposal_for_apply(
            tasks=tasks,
            proposed_task_ids=['pi-2', 'pi-1'],
            proposal_hash='deadbeef',
            proposal_expires_at=None,
            plan_id=1,
            plan_date=PLAN_DATE,
            vehicle_id=VID,
        )
    assert exc.value.code == 'STALE_PROPOSAL'


def test_t09_cache_hit():
    from modules.planlama.road_routing.traffic_proposal_cache import cache_clear
    tasks = [_task('pi-1', plan_item_id=_pid(1), order_no=1), _task('pi-2', plan_item_id=_pid(2), order_no=2, lat=41.02, lon=29.02)]
    cache_clear()
    p1 = _proposal(tasks)
    calls = {'n': 0}
    def counted(*a, **k):
        calls['n'] += 1
        return _matrix_3point()
    from modules.planlama.arac_traffic_route_proposal_service import compute_traffic_route_proposal
    p2 = compute_traffic_route_proposal(
        base=BASE, tasks=tasks, plan_date=PLAN_DATE, vehicle_id=VID, plan_id=1,
        matrix_provider_fn=counted, ors_provider_fn=lambda: None,
    )
    assert p2.get('cache_hit') is True
    assert calls['n'] == 0


def test_t08_traffic_duration_fields():
    p = _proposal([
        _task('pi-1', plan_item_id=_pid(1), order_no=1),
        _task('pi-2', plan_item_id=_pid(2), order_no=2, lat=41.02, lon=29.02),
    ])
    assert p['traffic_delay_seconds'] is not None
    assert p['static_duration_seconds'] is not None


def _google_fail(code: str, **extra):
    from modules.planlama.road_routing.types import RoutingError
    def _fn(*_a, **_k):
        raise RoutingError(f'fail {code}', code=code, **extra)
    return _fn


def test_t04_google_403():
    from modules.planlama.road_routing.traffic_proposal_cache import cache_clear
    cache_clear()
    tasks = [_task('pi-1', plan_item_id=_pid(1), order_no=1), _task('pi-2', plan_item_id=_pid(2), order_no=2, lat=41.02, lon=29.02)]
    with patch('modules.planlama.arac_traffic_route_proposal_service.google_routes_key_present', return_value=True):
        with patch('modules.planlama.arac_traffic_route_proposal_service.ors_key_present', return_value=False):
            from modules.planlama.arac_traffic_route_proposal_service import compute_traffic_route_proposal
            p = compute_traffic_route_proposal(
                base=BASE, tasks=tasks, plan_date=PLAN_DATE, vehicle_id=VID, plan_id=1,
                matrix_provider_fn=_google_fail('AUTH', http_status=403),
            )
    assert p['provider'] == 'current_order_fallback'
    assert p['apply_enabled'] is False


def test_t05_google_429():
    from modules.planlama.road_routing.traffic_proposal_cache import cache_clear
    cache_clear()
    tasks = [_task('pi-1', plan_item_id=_pid(1), order_no=1), _task('pi-2', plan_item_id=_pid(2), order_no=2, lat=41.02, lon=29.02)]
    with patch('modules.planlama.arac_traffic_route_proposal_service.google_routes_key_present', return_value=True):
        with patch('modules.planlama.arac_traffic_route_proposal_service.ors_key_present', return_value=False):
            from modules.planlama.arac_traffic_route_proposal_service import compute_traffic_route_proposal
            p = compute_traffic_route_proposal(
                base=BASE, tasks=tasks, plan_date=PLAN_DATE, vehicle_id=VID, plan_id=1,
                matrix_provider_fn=_google_fail('RATE_LIMIT', http_status=429),
            )
    assert p['provider'] == 'current_order_fallback'


def test_t06_google_5xx():
    from modules.planlama.road_routing.traffic_proposal_cache import cache_clear
    cache_clear()
    tasks = [_task('pi-1', plan_item_id=_pid(1), order_no=1), _task('pi-2', plan_item_id=_pid(2), order_no=2, lat=41.02, lon=29.02)]
    with patch('modules.planlama.arac_traffic_route_proposal_service.google_routes_key_present', return_value=True):
        with patch('modules.planlama.arac_traffic_route_proposal_service.ors_key_present', return_value=False):
            from modules.planlama.arac_traffic_route_proposal_service import compute_traffic_route_proposal
            p = compute_traffic_route_proposal(
                base=BASE, tasks=tasks, plan_date=PLAN_DATE, vehicle_id=VID, plan_id=1,
                matrix_provider_fn=_google_fail('SERVER', http_status=503),
            )
    assert p['provider'] == 'current_order_fallback'


def test_t07_malformed_matrix():
    from modules.planlama.road_routing.traffic_proposal_cache import cache_clear
    cache_clear()
    tasks = [_task('pi-1', plan_item_id=_pid(1), order_no=1), _task('pi-2', plan_item_id=_pid(2), order_no=2, lat=41.02, lon=29.02)]

    def _partial(*_a, **_k):
        from modules.planlama.road_routing.types import RouteMatrix
        d = [[0.0, None], [100.0, 0.0]]
        return RouteMatrix(provider='mock', profile='x', duration_s=d, distance_m=d), None, 4, 1

    with patch('modules.planlama.arac_traffic_route_proposal_service.google_routes_key_present', return_value=True):
        with patch('modules.planlama.arac_traffic_route_proposal_service.ors_key_present', return_value=False):
            from modules.planlama.arac_traffic_route_proposal_service import compute_traffic_route_proposal
            p = compute_traffic_route_proposal(
                base=BASE, tasks=tasks, plan_date=PLAN_DATE, vehicle_id=VID, plan_id=1,
                matrix_provider_fn=_partial,
            )
    assert p['suggested_item_ids'] == p['current_item_ids']


def test_t10_cache_expiry():
    from modules.planlama.arac_traffic_route_proposal_service import compute_traffic_route_proposal
    from modules.planlama.road_routing import traffic_proposal_cache as cache_mod
    cache_mod.cache_clear()
    tasks = [_task('pi-1', plan_item_id=_pid(1), order_no=1), _task('pi-2', plan_item_id=_pid(2), order_no=2, lat=41.02, lon=29.02)]
    calls = {'n': 0}

    def counted(*a, **k):
        calls['n'] += 1
        return _matrix_3point()

    with patch('modules.planlama.arac_traffic_route_proposal_service.google_routes_key_present', return_value=True):
        with patch.object(cache_mod, '_TTL_SEC', 1):
            p1 = compute_traffic_route_proposal(
                base=BASE, tasks=tasks, plan_date=PLAN_DATE, vehicle_id=VID, plan_id=1,
                matrix_provider_fn=counted, ors_provider_fn=lambda: None,
            )
            assert calls['n'] == 1
            time.sleep(1.2)
            p2 = compute_traffic_route_proposal(
                base=BASE, tasks=tasks, plan_date=PLAN_DATE, vehicle_id=VID, plan_id=1,
                matrix_provider_fn=counted, ors_provider_fn=lambda: None,
            )
    assert calls['n'] == 2
    assert p1['proposal_hash'] == p2['proposal_hash']


def test_t11_concurrent_single_flight():
    from modules.planlama.arac_traffic_route_proposal_service import compute_traffic_route_proposal
    from modules.planlama.road_routing.traffic_proposal_cache import cache_clear
    cache_clear()
    tasks = [_task('pi-1', plan_item_id=_pid(1), order_no=1), _task('pi-2', plan_item_id=_pid(2), order_no=2, lat=41.02, lon=29.02)]
    calls = {'n': 0}
    started = threading.Event()
    gate = threading.Event()

    def slow(*a, **k):
        calls['n'] += 1
        started.set()
        gate.wait(timeout=5)
        return _matrix_3point()

    results: list[dict] = []

    def worker():
        with patch('modules.planlama.arac_traffic_route_proposal_service.google_routes_key_present', return_value=True):
            results.append(compute_traffic_route_proposal(
                base=BASE, tasks=tasks, plan_date=PLAN_DATE, vehicle_id=VID, plan_id=1,
                matrix_provider_fn=slow, ors_provider_fn=lambda: None,
            ))

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start()
    assert started.wait(timeout=3)
    t2.start()
    time.sleep(0.2)
    gate.set()
    t1.join(timeout=10)
    t2.join(timeout=10)
    assert calls['n'] == 1
    assert len(results) == 2
    assert results[0]['proposal_hash'] == results[1]['proposal_hash']


def test_t16_normal_traffic_optimization():
    p = _proposal([
        _task('pi-1', plan_item_id=_pid(1), order_no=1, lat=41.01, lon=29.01),
        _task('pi-2', plan_item_id=_pid(2), order_no=2, lat=41.02, lon=29.02),
        _task('pi-3', plan_item_id=_pid(3), order_no=3, lat=41.03, lon=29.03),
    ])
    assert p['suggested_item_ids'] == [_pid(1), _pid(3), _pid(2)]
    assert p['time_saved_seconds'] is not None
    assert p['time_saved_seconds'] > 0


def test_t19_factory_start_end():
    from modules.planlama.road_routing.route_planner_service import _build_routable_points
    tasks = [_task('pi-1', plan_item_id=_pid(1), order_no=1), _task('pi-2', plan_item_id=_pid(2), order_no=2, lat=41.02, lon=29.02)]
    points, routable, *_ = _build_routable_points(BASE, tasks)
    assert points[0] == (BASE['latitude'], BASE['longitude'])
    assert len(routable) == 2


def test_t20_duplicate_coordinates_identity():
    tasks = [
        _task('pi-a', plan_item_id=_pid(1), order_no=1, lat=41.01, lon=29.01),
        _task('pi-b', plan_item_id=_pid(2), order_no=2, lat=41.01, lon=29.01),
    ]
    p = _proposal(tasks)
    assert set(p['suggested_task_ids']) == {'pi-a', 'pi-b'}
    assert len(p['suggested_task_ids']) == 2


def test_t21_deterministic_tie_break():
    p1 = _proposal([
        _task('pi-1', plan_item_id=_pid(1), order_no=1, lat=41.01, lon=29.01),
        _task('pi-2', plan_item_id=_pid(2), order_no=2, lat=41.02, lon=29.02),
    ])
    p2 = _proposal([
        _task('pi-1', plan_item_id=_pid(1), order_no=1, lat=41.01, lon=29.01),
        _task('pi-2', plan_item_id=_pid(2), order_no=2, lat=41.02, lon=29.02),
    ])
    assert p1['suggested_item_ids'] == p2['suggested_item_ids']


def test_t26_expired_proposal():
    from modules.planlama.arac_route_constraints import RouteApplyConflictError
    from modules.planlama.arac_traffic_route_proposal_service import validate_proposal_for_apply
    tasks = [_task('pi-1', plan_item_id=_pid(1), order_no=1), _task('pi-2', plan_item_id=_pid(2), order_no=2)]
    p = _proposal(tasks)
    with pytest.raises(RouteApplyConflictError) as exc:
        validate_proposal_for_apply(
            tasks=tasks,
            proposed_task_ids=p['suggested_task_ids'],
            proposal_hash=p['proposal_hash'],
            proposal_expires_at='2020-01-01T08:00:00+03:00',
            plan_id=1,
            plan_date=PLAN_DATE,
            vehicle_id=VID,
        )
    assert exc.value.code == 'STALE_PROPOSAL'


def test_t38_all_providers_fail():
    from modules.planlama.road_routing.traffic_proposal_cache import cache_clear
    cache_clear()
    tasks = [_task('pi-1', plan_item_id=_pid(1), order_no=1), _task('pi-2', plan_item_id=_pid(2), order_no=2, lat=41.02, lon=29.02)]
    with patch('modules.planlama.arac_traffic_route_proposal_service.google_routes_key_present', return_value=False):
        with patch('modules.planlama.arac_traffic_route_proposal_service.ors_key_present', return_value=False):
            from modules.planlama.arac_traffic_route_proposal_service import compute_traffic_route_proposal
            p = compute_traffic_route_proposal(
                base=BASE, tasks=tasks, plan_date=PLAN_DATE, vehicle_id=VID, plan_id=1,
            )
    assert p['provider'] == 'current_order_fallback'
    assert p['traffic_available'] is False
    assert p['fallback_reason'] is not None


def _matrix_current_better(*_args, **_kwargs) -> tuple:
    """Greedy segment order 1->3->2 is slower than current 1->2->3."""
    from modules.planlama.road_routing.types import RouteMatrix

    n = 4
    d = [[0.0] * n for _ in range(n)]
    dist = [[0.0] * n for _ in range(n)]
    static = [[0.0] * n for _ in range(n)]
    pairs = [
        (0, 1, 100, 100), (0, 2, 500, 500), (0, 3, 100, 100),
        (1, 2, 100, 100), (1, 3, 100, 100),
        (2, 3, 100, 100), (2, 1, 100, 100),
        (3, 2, 900, 900), (3, 1, 100, 100),
        (1, 0, 100, 100), (2, 0, 100, 100), (3, 0, 100, 100),
    ]
    for i, j, dur, st in pairs:
        d[i][j] = float(dur)
        static[i][j] = float(st)
        dist[i][j] = float(dur * 10)
    m = RouteMatrix(provider='mock', profile='test', duration_s=d, distance_m=dist)
    return m, static, n * n, 1


def _proposal_with_matrix(tasks, matrix_fn):
    from modules.planlama.arac_traffic_route_proposal_service import compute_traffic_route_proposal
    from modules.planlama.road_routing.traffic_proposal_cache import cache_clear

    cache_clear()
    with patch('modules.planlama.arac_traffic_route_proposal_service.google_routes_key_present', return_value=True):
        with patch('modules.planlama.arac_traffic_route_proposal_service.load_visit_states_for_tasks', return_value={}):
            return compute_traffic_route_proposal(
                base=BASE,
                tasks=tasks,
                plan_date=PLAN_DATE,
                vehicle_id=VID,
                plan_id=1,
                matrix_provider_fn=matrix_fn,
                ors_provider_fn=lambda: None,
            )


def test_normal_worse_proposal_blocked():
    tasks = [
        _task('pi-1', plan_item_id=_pid(1), order_no=1, lat=41.01, lon=29.01),
        _task('pi-2', plan_item_id=_pid(2), order_no=2, lat=41.02, lon=29.02),
        _task('pi-3', plan_item_id=_pid(3), order_no=3, lat=41.03, lon=29.03),
    ]
    p = _proposal_with_matrix(tasks, _matrix_current_better)
    assert p['proposal_reason'] == 'NO_IMPROVEMENT'
    assert p['changed'] is False
    assert p['apply_enabled'] is False
    assert p['suggested_item_ids'] == p['current_item_ids']
    assert p['time_saved_seconds'] == 0.0
    assert 'zaten uygun' in (p.get('user_message') or '')


def test_zero_improvement_blocked():
    tasks = [
        _task('pi-1', plan_item_id=_pid(1), order_no=1, lat=41.01, lon=29.01),
        _task('pi-2', plan_item_id=_pid(2), order_no=2, lat=41.02, lon=29.02),
    ]

    def _equal(*_a, **_k):
        from modules.planlama.road_routing.types import RouteMatrix

        n = 3
        d = [[0.0] * n for _ in range(n)]
        static = [[0.0] * n for _ in range(n)]
        for i in range(n):
            for j in range(n):
                if i != j:
                    d[i][j] = 100.0
                    static[i][j] = 100.0
        m = RouteMatrix(provider='mock', profile='test', duration_s=d, distance_m=d)
        return m, static, n * n, 1

    p = _proposal_with_matrix(tasks, _equal)
    assert p['proposal_reason'] == 'NO_IMPROVEMENT'
    assert p['apply_enabled'] is False
    assert p['changed'] is False


def test_positive_improvement_apply_enabled():
    p = _proposal([
        _task('pi-1', plan_item_id=_pid(1), order_no=1, lat=41.01, lon=29.01),
        _task('pi-2', plan_item_id=_pid(2), order_no=2, lat=41.02, lon=29.02),
        _task('pi-3', plan_item_id=_pid(3), order_no=3, lat=41.03, lon=29.03),
    ])
    assert p['proposal_reason'] == 'TRAFFIC_IMPROVEMENT'
    assert p['apply_enabled'] is True
    assert p['time_saved_seconds'] > 0


def test_urgent_priority_negative_explained():
    tasks = [
        _task('pi-n1', plan_item_id=_pid(1), order_no=1, priority='NORMAL', lat=41.01, lon=29.01),
        _task('pi-a1', plan_item_id=_pid(2), order_no=2, priority='ACIL', lat=41.02, lon=29.02),
        _task('pi-n2', plan_item_id=_pid(3), order_no=3, priority='NORMAL', lat=41.03, lon=29.03),
    ]
    p = _proposal_with_matrix(tasks, _matrix_current_better)
    assert p['proposal_reason'] == 'URGENT_PRIORITY'
    assert p['changed'] is True
    assert p['apply_enabled'] is True
    assert p['suggested_task_ids'].index('pi-a1') < p['suggested_task_ids'].index('pi-n1')
    if p['time_saved_seconds'] is not None and p['time_saved_seconds'] < 0:
        assert 'ACİL önceliği' in (p.get('user_message') or '')


def _matrix_return_flip(*_args, **_kwargs) -> tuple:
    """Factory return makes current 1->2->3 cheaper than greedy 1->3->2."""
    from modules.planlama.arac_traffic_route_proposal_service import _route_totals
    from modules.planlama.road_routing.types import RouteMatrix

    n = 4
    d = [[0.0] * n for _ in range(n)]
    static = [[0.0] * n for _ in range(n)]
    pairs = [
        (0, 1, 100, 100), (0, 2, 100, 100), (0, 3, 100, 100),
        (1, 2, 100, 100), (1, 3, 100, 100), (2, 3, 100, 100),
        (2, 1, 100, 100), (3, 2, 100, 100), (3, 1, 100, 100),
        (1, 0, 100, 100), (2, 0, 900, 900), (3, 0, 50, 50),
    ]
    for i, j, dur, st in pairs:
        d[i][j] = float(dur)
        static[i][j] = float(st)
    routable = {
        'pi-1': {'matrix_index': 1},
        'pi-2': {'matrix_index': 2},
        'pi-3': {'matrix_index': 3},
    }
    cur = _route_totals(['pi-1', 'pi-2', 'pi-3'], routable, d, None, static, 0)
    sug = _route_totals(['pi-1', 'pi-3', 'pi-2'], routable, d, None, static, 0)
    assert float(cur['total_duration_seconds']) < float(sug['total_duration_seconds'])
    m = RouteMatrix(provider='mock', profile='test', duration_s=d, distance_m=d)
    return m, static, n * n, 1


def test_factory_return_edge_included():
    from modules.planlama.arac_traffic_route_proposal_service import _route_totals

    d = [[0.0] * 3 for _ in range(3)]
    for i in range(3):
        for j in range(3):
            if i != j:
                d[i][j] = 100.0
    d[2][0] = 500.0
    routable = {'pi-1': {'matrix_index': 1}, 'pi-2': {'matrix_index': 2}}
    cheap_return = _route_totals(['pi-2', 'pi-1'], routable, d, None, None, 0)
    costly_return = _route_totals(['pi-1', 'pi-2'], routable, d, None, None, 0)
    assert cheap_return['total_duration_seconds'] == 300.0
    assert costly_return['total_duration_seconds'] == 700.0
    assert cheap_return['total_duration_seconds'] != costly_return['total_duration_seconds']


def test_return_edge_changes_improvement_outcome():
    tasks = [
        _task('pi-1', plan_item_id=_pid(1), order_no=1, lat=41.01, lon=29.01),
        _task('pi-2', plan_item_id=_pid(2), order_no=2, lat=41.02, lon=29.02),
        _task('pi-3', plan_item_id=_pid(3), order_no=3, lat=41.03, lon=29.03),
    ]
    p = _proposal_with_matrix(tasks, _matrix_return_flip)
    assert p['proposal_reason'] == 'NO_IMPROVEMENT'
    assert p['apply_enabled'] is False
    assert p['suggested_item_ids'] == p['current_item_ids']


def test_return_included_urgent_priority_duration():
    tasks = [
        _task('pi-n1', plan_item_id=_pid(1), order_no=1, priority='NORMAL', lat=41.01, lon=29.01),
        _task('pi-a1', plan_item_id=_pid(2), order_no=2, priority='ACIL', lat=41.02, lon=29.02),
        _task('pi-n2', plan_item_id=_pid(3), order_no=3, priority='NORMAL', lat=41.03, lon=29.03),
    ]
    p = _proposal_with_matrix(tasks, _matrix_current_better)
    assert p['proposal_reason'] == 'URGENT_PRIORITY'
    assert p['current_total_duration_seconds'] is not None
    assert p['suggested_total_duration_seconds'] is not None
    assert p['time_saved_seconds'] == round(
        float(p['current_total_duration_seconds']) - float(p['suggested_total_duration_seconds']), 1,
    )


def test_duration_same_matrix_for_current_and_suggested():
    p = _proposal([
        _task('pi-1', plan_item_id=_pid(1), order_no=1, lat=41.01, lon=29.01),
        _task('pi-2', plan_item_id=_pid(2), order_no=2, lat=41.02, lon=29.02),
        _task('pi-3', plan_item_id=_pid(3), order_no=3, lat=41.03, lon=29.03),
    ])
    assert p['current_total_duration_seconds'] is not None
    assert p['suggested_total_duration_seconds'] is not None
    assert p['time_saved_seconds'] == round(
        float(p['current_total_duration_seconds']) - float(p['suggested_total_duration_seconds']), 1,
    )


def test_t37_ors_fallback_label():
    from modules.planlama.road_routing.mock_provider import MockRoadRoutingProvider
    from modules.planlama.road_routing.traffic_proposal_cache import cache_clear
    cache_clear()
    tasks = [_task('pi-1', plan_item_id=_pid(1), order_no=1), _task('pi-2', plan_item_id=_pid(2), order_no=2, lat=41.02, lon=29.02)]
    with patch('modules.planlama.arac_traffic_route_proposal_service.google_routes_key_present', return_value=False):
        with patch('modules.planlama.arac_traffic_route_proposal_service.ors_key_present', return_value=True):
            with patch('modules.planlama.arac_traffic_route_proposal_service.get_routing_provider', return_value=MockRoadRoutingProvider()):
                from modules.planlama.arac_traffic_route_proposal_service import compute_traffic_route_proposal
                p = compute_traffic_route_proposal(
                    base=BASE, tasks=tasks, plan_date=PLAN_DATE, vehicle_id=VID, plan_id=1,
                )
    assert p['provider'] == 'ors_no_traffic'
    assert p['traffic_available'] is False
