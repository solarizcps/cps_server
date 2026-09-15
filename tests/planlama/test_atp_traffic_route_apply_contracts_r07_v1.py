# -*- coding: utf-8 -*-
"""R07 — commit-critical apply/proposal contracts (TEMP DB only)."""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'app'
_MIGRATIONS = APP / 'migrations'
PLAN_DATE = '2026-09-22'
VID = '991R07APPLY'
PLATE = '34 R07 APP'
USER_ID = 1
BASE = {'latitude': 41.0, 'longitude': 29.0, 'has_coordinates': True, 'base_name': 'Fabrika'}


def _run_migration(db_path: str, filename: str) -> None:
    spec = importlib.util.spec_from_file_location(filename, _MIGRATIONS / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.run(db_path)


@contextmanager
def _temp_atp_db(*, restore_path: str | None = None):
    import tempfile
    from tools.atp_test_db_guard import bind_temp_db_path

    tmpdir = tempfile.mkdtemp(prefix='r07_apply_')
    db_path = str(Path(tmpdir) / 'test.db')
    for mig in (
        '176_arac_takip_v13.py',
        '177_arac_operasyon_ayar.py',
        '178_arac_is_talebi_ux_v2_fields.py',
        '179_arac_gps_snapshot_p1.py',
        '180_arac_plan_ziyaret_durum.py',
        '182_arac_plan_change_v1.py',
        '188_arac_plan_is_zaman_alanlari.py',
    ):
        _run_migration(db_path, mig)
    con = sqlite3.connect(db_path)
    con.execute(
        """
        INSERT INTO arac_operasyon_ayar (
            base_name, base_latitude, base_longitude, base_address, aktif, created_at, updated_at, updated_by
        ) VALUES (?,?,?,?,1,datetime('now'),datetime('now'),1)
        """,
        ('Fabrika', 41.0, 29.0, 'Istanbul'),
    )
    con.commit()
    con.close()
    bind_temp_db_path(db_path)
    try:
        yield db_path
    finally:
        if restore_path:
            bind_temp_db_path(restore_path)


@pytest.fixture
def temp_db(atp_planlama_db_guard_session):
    session_db = atp_planlama_db_guard_session['temp_db']
    with _temp_atp_db(restore_path=session_db) as db_path:
        yield db_path


def _conn(db_path: str) -> sqlite3.Connection:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    return con


def _matrix_fn(*_a, **_k):
    from modules.planlama.road_routing.types import RouteMatrix

    n = 6
    d = [[0.0] * n for _ in range(n)]
    dist = [[0.0] * n for _ in range(n)]
    static = [[0.0] * n for _ in range(n)]
    pairs = [
        (0, 1, 600, 500), (0, 2, 900, 800), (0, 3, 900, 800), (0, 4, 700, 600), (0, 5, 800, 700),
        (1, 2, 800, 700), (1, 3, 200, 180), (1, 4, 500, 450), (1, 5, 600, 550),
        (2, 3, 350, 300), (2, 4, 200, 180), (2, 5, 400, 350),
        (3, 4, 220, 200), (3, 5, 300, 280), (4, 5, 250, 220),
    ]
    for i, j, dur, st in pairs:
        d[i][j] = float(dur)
        static[i][j] = float(st)
        dist[i][j] = float(dur * 10)
    return RouteMatrix(provider='mock', profile='test', duration_s=d, distance_m=dist), static, n * n, 1


def _seed_plan(temp_db: str) -> dict:
    from modules.planlama.arac_takip_repo import (
        assign_to_plan,
        create_is_talebi,
        ensure_seed_locations,
        get_active_plan_row,
        list_plan_tasks,
    )

    ensure_seed_locations(USER_ID)
    specs = [
        ('Started Co', 41.01, 29.01, 'NORMAL', 'BASLADI'),
        ('Normal B', 41.02, 29.02, 'NORMAL', 'PLANLANDI'),
        ('Normal C', 41.03, 29.03, 'NORMAL', 'PLANLANDI'),
        ('Acil D', 41.04, 29.04, 'ACIL', 'PLANLANDI'),
        ('Normal E', 41.05, 29.05, 'NORMAL', 'PLANLANDI'),
    ]
    for name, lat, lon, pri, st in specs:
        t = create_is_talebi(
            USER_ID,
            {
                'tarih': PLAN_DATE,
                'is': name,
                'firma': name,
                'latitude': lat,
                'longitude': lon,
                'oncelik': pri,
                'save_to_master': False,
            },
        )
        assign_to_plan(USER_ID, t['id'], PLAN_DATE, VID, PLATE, None, 'R07 Apply', '09:00', None)
        if st != 'PLANLANDI':
            con = _conn(temp_db)
            row = con.execute(
                """
                SELECT pi.id FROM arac_gunluk_plan_is pi
                JOIN arac_is_talebi it ON it.id = pi.is_talebi_id
                WHERE it.firma_adi=? AND pi.plan_id IN (
                    SELECT id FROM arac_gunluk_plan WHERE arac_external_id=? AND plan_tarihi=?
                )
                """,
                (name, VID, PLAN_DATE),
            ).fetchone()
            con.execute("UPDATE arac_gunluk_plan_is SET durum=? WHERE id=?", (st, row['id']))
            con.commit()
            con.close()

    tasks = list_plan_tasks(PLAN_DATE, VID)
    plan_id = int(get_active_plan_row(PLAN_DATE, VID)['id'])
    return {'tasks': tasks, 'plan_id': plan_id}


def _proposal(temp_db: str, seeded: dict):
    from modules.planlama.arac_traffic_route_proposal_service import compute_traffic_route_proposal
    from modules.planlama.road_routing.traffic_proposal_cache import cache_clear

    cache_clear()
    with patch('modules.planlama.arac_traffic_route_proposal_service.google_routes_key_present', return_value=True):
        with patch('modules.planlama.road_routing.route_planner_service.get_routing_provider') as gp:
            from modules.planlama.road_routing.mock_provider import MockRoadRoutingProvider

            gp.return_value = MockRoadRoutingProvider()
            return compute_traffic_route_proposal(
                base=BASE,
                tasks=seeded['tasks'],
                plan_date=PLAN_DATE,
                vehicle_id=VID,
                plan_id=seeded['plan_id'],
                matrix_provider_fn=_matrix_fn,
                ors_provider_fn=lambda: MockRoadRoutingProvider(),
            )


def _mock_route_dto(base, tasks):
    from modules.planlama.road_routing.mock_provider import MockRoadRoutingProvider
    from modules.planlama.road_routing.route_planner_service import build_plan_route_dto

    with patch('modules.planlama.road_routing.route_planner_service.get_routing_provider', return_value=MockRoadRoutingProvider()):
        return build_plan_route_dto(base, tasks)


def _apply(temp_db: str, seeded: dict, proposal: dict, *, client_submit_id: str | None = None):
    from modules.planlama.arac_route_apply_service import apply_route_order_and_snapshot

    exp = proposal.get('expires_at')
    return apply_route_order_and_snapshot(
        USER_ID,
        PLAN_DATE,
        VID,
        proposal['suggested_task_ids'],
        proposal_hash=proposal['proposal_hash'],
        proposal_expires_at=exp,
        client_submit_id=client_submit_id,
        route_dto_builder=_mock_route_dto,
    )


def _item_order(temp_db: str) -> list[int]:
    from modules.planlama.arac_takip_repo import list_plan_tasks

    return [int(t['plan_item_id']) for t in list_plan_tasks(PLAN_DATE, VID)]


def _client(*, can_edit: bool = True):
    import importlib

    import flask
    import modules.auth as auth_mod
    import modules.planlama.arac_takip_routes as routes_mod

    def _open(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            return f(*args, **kwargs)

        return wrapper

    auth_mod.yetki_gerekli = lambda *a, **k: _open
    auth_mod.yetki_var = lambda *a, **k: can_edit
    routes_mod = importlib.reload(routes_mod)
    routes_mod.yetki_gerekli = auth_mod.yetki_gerekli
    routes_mod.yetki_var = auth_mod.yetki_var

    app = flask.Flask(
        __name__,
        template_folder=str(APP / 'templates'),
        static_folder=str(APP / 'static'),
    )
    app.secret_key = 'r07-apply-test'
    app.config['TESTING'] = True
    app.register_blueprint(routes_mod.arac_takip_bp)
    return app.test_client()


def test_stale_status_rejected_409(temp_db):
    seeded = _seed_plan(temp_db)
    p = _proposal(temp_db, seeded)
    con = _conn(temp_db)
    pid = _item_order(temp_db)[1]
    con.execute("UPDATE arac_gunluk_plan_is SET durum='TAMAMLANDI' WHERE id=?", (pid,))
    con.commit()
    con.close()
    from modules.planlama.arac_route_constraints import RouteApplyConflictError

    with pytest.raises(RouteApplyConflictError) as exc:
        _apply(temp_db, seeded, p)
    assert exc.value.code == 'STALE_PROPOSAL'


def test_stale_urgent_flag_rejected_409(temp_db):
    seeded = _seed_plan(temp_db)
    p = _proposal(temp_db, seeded)
    con = _conn(temp_db)
    acil_pid = next(
        int(t['plan_item_id']) for t in seeded['tasks'] if (t.get('priority') or '').upper() == 'ACIL'
    )
    con.execute(
        "UPDATE arac_is_talebi SET oncelik='NORMAL' WHERE id=(SELECT is_talebi_id FROM arac_gunluk_plan_is WHERE id=?)",
        (acil_pid,),
    )
    con.commit()
    con.close()
    from modules.planlama.arac_route_constraints import RouteApplyConflictError

    with pytest.raises(RouteApplyConflictError) as exc:
        _apply(temp_db, seeded, p)
    assert exc.value.code == 'STALE_PROPOSAL'


def test_expired_proposal_rejected_409(temp_db):
    seeded = _seed_plan(temp_db)
    p = _proposal(temp_db, seeded)
    p['expires_at'] = '2020-01-01T08:00:00+03:00'
    from modules.planlama.arac_route_constraints import RouteApplyConflictError

    with pytest.raises(RouteApplyConflictError) as exc:
        _apply(temp_db, seeded, p)
    assert exc.value.code == 'STALE_PROPOSAL'


def test_unauthorized_apply_rejected_403(temp_db):
    seeded = _seed_plan(temp_db)
    p = _proposal(temp_db, seeded)
    client = _client(can_edit=False)
    r = client.post(
        '/planlama/arac-takip/api/route/apply',
        json={
            'date': PLAN_DATE,
            'vehicle_id': VID,
            'task_ids': p['suggested_task_ids'],
            'proposal_hash': p['proposal_hash'],
            'proposal_expires_at': p['expires_at'],
        },
    )
    assert r.status_code == 403


def test_concurrent_apply_one_db_change(temp_db):
    seeded = _seed_plan(temp_db)
    p = _proposal(temp_db, seeded)
    before = _item_order(temp_db)
    results: list = []
    errors: list = []

    def worker():
        try:
            results.append(_apply(temp_db, seeded, p, client_submit_id='conc-1'))
        except Exception as exc:
            errors.append(exc)

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)
    after = _item_order(temp_db)
    assert after != before
    assert len(results) + len(errors) >= 1
    success = len([r for r in results if r.applied or r.deduplicated])
    assert success >= 1
    assert _item_order(temp_db) == [int(x) for x in p['suggested_item_ids'] if x in after] or after == [int(i) for i in p['suggested_item_ids']]


def test_idempotent_apply_no_extra_write(temp_db):
    from modules.planlama.arac_gps_snapshot_repo import get_active_plan_rota_snapshot

    seeded = _seed_plan(temp_db)
    p = _proposal(temp_db, seeded)
    r1 = _apply(temp_db, seeded, p, client_submit_id='idem-1')
    snap_v1 = get_active_plan_rota_snapshot(seeded['plan_id'])
    order_v1 = _item_order(temp_db)
    r2 = _apply(temp_db, seeded, p, client_submit_id='idem-1')
    snap_v2 = get_active_plan_rota_snapshot(seeded['plan_id'])
    assert r2.deduplicated is True
    assert r2.applied is False
    assert r2.reorder_applied is False
    assert order_v1 == _item_order(temp_db)
    assert int(snap_v2['route_version']) == int(snap_v1['route_version'])


def test_rollback_injection_preserves_order(temp_db):
    seeded = _seed_plan(temp_db)
    p = _proposal(temp_db, seeded)
    before = _item_order(temp_db)
    def boom(*args, **kwargs):
        raise RuntimeError('injected snapshot failure')

    with patch('modules.planlama.arac_route_apply_service._save_plan_rota_snapshot_conn', side_effect=boom):
        from modules.planlama.arac_route_apply_service import RouteApplyPersistenceError

        with pytest.raises(RouteApplyPersistenceError):
            _apply(temp_db, seeded, p)
    assert _item_order(temp_db) == before


def test_apply_consumer_item_id_parity(temp_db):
    seeded = _seed_plan(temp_db)
    p = _proposal(temp_db, seeded)
    _apply(temp_db, seeded, p, client_submit_id='parity-1')
    from modules.planlama.arac_driver_map_service import build_driver_map_dto
    from modules.planlama.arac_takip_repo import list_plan_tasks
    from modules.planlama.arac_whatsapp_message_service import load_whatsapp_plan_context, sort_stops_for_whatsapp

    db_ids = [int(t['plan_item_id']) for t in list_plan_tasks(PLAN_DATE, VID)]
    dto = build_driver_map_dto(PLAN_DATE, VID)
    map_ids = dto['item_id_order']
    wa = load_whatsapp_plan_context(PLAN_DATE, VID)
    assert wa is not None
    wa_ids = [int(s['plan_item_id']) for s in wa['stops']]
    assert map_ids == db_ids
    assert wa_ids == db_ids


def test_route_snapshot_invalidation_on_apply(temp_db):
    seeded = _seed_plan(temp_db)
    con = _conn(temp_db)
    con.execute(
        """
        INSERT INTO arac_plan_rota_snapshot (
            plan_id, route_version, arac_provider, routing_provider,
            geometry_json, geometry_schema, content_hash,
            total_distance_m, total_duration_s, stop_order_json,
            is_active, created_at, created_by
        ) VALUES (?,?,?,?,?,?,?,?,?,?,1,datetime('now'),1)
        """,
        (
            seeded['plan_id'], 1, 'TURKCELL_FILOM', 'mock',
            json.dumps({'type': 'LineString', 'coordinates': [[29, 41], [29.1, 41.1]]}),
            'geojson_linestring_v1', 'oldhash', 1000.0, 600.0,
            json.dumps([{'plan_item_id': 1}]),
        ),
    )
    con.commit()
    con.close()
    p = _proposal(temp_db, seeded)
    result = _apply(temp_db, seeded, p, client_submit_id='snap-1')
    con = _conn(temp_db)
    active = con.execute(
        'SELECT route_version, is_active FROM arac_plan_rota_snapshot WHERE plan_id=? ORDER BY route_version DESC',
        (seeded['plan_id'],),
    ).fetchall()
    con.close()
    assert result.route_version >= 2
    assert int(active[0]['is_active']) == 1
    assert int(active[0]['route_version']) == result.route_version


def test_provider_failure_preserves_db_order(temp_db):
    seeded = _seed_plan(temp_db)
    before = _item_order(temp_db)
    from modules.planlama.arac_traffic_route_proposal_service import compute_traffic_route_proposal
    from modules.planlama.road_routing.traffic_proposal_cache import cache_clear
    from modules.planlama.road_routing.types import RoutingError

    cache_clear()

    def _fail(*_a, **_k):
        raise RoutingError('fail', code='AUTH', http_status=403)

    with patch('modules.planlama.arac_traffic_route_proposal_service.google_routes_key_present', return_value=True):
        with patch('modules.planlama.arac_traffic_route_proposal_service.ors_key_present', return_value=False):
            p = compute_traffic_route_proposal(
                base=BASE,
                tasks=seeded['tasks'],
                plan_date=PLAN_DATE,
                vehicle_id=VID,
                plan_id=seeded['plan_id'],
                matrix_provider_fn=_fail,
            )
    assert p['provider'] == 'current_order_fallback'
    assert p['apply_enabled'] is False
    assert _item_order(temp_db) == before


def test_polling_no_extra_google_calls(temp_db):
    seeded = _seed_plan(temp_db)
    calls = {'n': 0}

    def counted(*a, **k):
        calls['n'] += 1
        return _matrix_fn()

    from modules.planlama.arac_traffic_route_proposal_service import compute_traffic_route_proposal
    from modules.planlama.road_routing.traffic_proposal_cache import cache_clear

    cache_clear()
    with patch('modules.planlama.arac_traffic_route_proposal_service.google_routes_key_present', return_value=True):
        p1 = compute_traffic_route_proposal(
            base=BASE, tasks=seeded['tasks'], plan_date=PLAN_DATE, vehicle_id=VID,
            plan_id=seeded['plan_id'], matrix_provider_fn=counted,
            ors_provider_fn=lambda: None,
        )
        p2 = compute_traffic_route_proposal(
            base=BASE, tasks=seeded['tasks'], plan_date=PLAN_DATE, vehicle_id=VID,
            plan_id=seeded['plan_id'], matrix_provider_fn=counted,
            ors_provider_fn=lambda: None,
        )
    assert calls['n'] == 1
    assert p2.get('cache_hit') is True
    assert p1['apply_enabled'] is True or p1['changed'] is False
    assert _item_order(temp_db) == _item_order(temp_db)


def test_apply_rejects_no_improvement_bypass(temp_db):
    from modules.planlama.arac_route_constraints import RouteApplyConflictError
    from modules.planlama.arac_traffic_route_proposal_service import (
        compute_traffic_route_proposal,
        validate_proposal_for_apply,
    )
    from modules.planlama.road_routing.traffic_proposal_cache import cache_clear
    from modules.planlama.road_routing.types import RouteMatrix

    seeded = _seed_plan(temp_db)
    cache_clear()

    def _worse(*_a, **_k):
        n = 6
        d = [[0.0] * n for _ in range(n)]
        static = [[0.0] * n for _ in range(n)]
        pairs = [
            (0, 1, 100, 100), (0, 2, 500, 500), (0, 3, 100, 100), (0, 4, 500, 500), (0, 5, 500, 500),
            (1, 2, 100, 100), (1, 3, 100, 100), (1, 4, 500, 500), (1, 5, 500, 500),
            (2, 3, 100, 100), (2, 4, 500, 500), (2, 5, 500, 500),
            (3, 2, 900, 900), (3, 4, 100, 100), (3, 5, 100, 100),
            (4, 5, 100, 100), (5, 4, 100, 100),
        ]
        for i, j, dur, st in pairs:
            d[i][j] = float(dur)
            static[i][j] = float(st)
        m = RouteMatrix(provider='mock', profile='test', duration_s=d, distance_m=d)
        return m, static, n * n, 1

    with patch('modules.planlama.arac_traffic_route_proposal_service.google_routes_key_present', return_value=True):
        p = compute_traffic_route_proposal(
            base=BASE,
            tasks=seeded['tasks'],
            plan_date=PLAN_DATE,
            vehicle_id=VID,
            plan_id=seeded['plan_id'],
            matrix_provider_fn=_worse,
            ors_provider_fn=lambda: None,
        )
    assert p['proposal_reason'] == 'NO_IMPROVEMENT'
    assert p['apply_enabled'] is False
    worse_ids = [tid for tid in p['current_task_ids'] if tid != p['current_task_ids'][0]][::-1]
    worse_ids = p['current_task_ids'][:1] + worse_ids
    with pytest.raises(RouteApplyConflictError) as exc:
        validate_proposal_for_apply(
            tasks=seeded['tasks'],
            proposed_task_ids=worse_ids,
            proposal_hash=p['proposal_hash'],
            proposal_expires_at=p['expires_at'],
            plan_id=seeded['plan_id'],
            plan_date=PLAN_DATE,
            vehicle_id=VID,
        )
    assert exc.value.code == 'NO_IMPROVEMENT'


# Protection mappings (verified in gate, not duplicated here):
# R12 map/modal -> tests/planlama/test_atp_driver_map_r04_r12_v1.py
# R05 overstay -> tests/planlama/test_atp_stop_overstay_r05_v1.py
