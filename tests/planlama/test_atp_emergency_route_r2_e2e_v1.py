# -*- coding: utf-8 -*-
"""R2 E2E — emergency full route S8–S12 + mandatory extras (TEMP DB only)."""
from __future__ import annotations

import importlib.util
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'app'
_MIGRATIONS = APP / 'migrations'
PLAN_DATE = '2026-09-22'
VID = '991R2E2E01'
OTHER_VID = '991R2OTHER'
PLATE = '34 R2 E2E'
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

    tmpdir = tempfile.mkdtemp(prefix='r2_e2e_')
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


def _seed_plan_normals(temp_db: str, *, vehicle: str = VID, count: int = 4) -> dict:
    from modules.planlama.arac_takip_repo import (
        assign_to_plan,
        create_is_talebi,
        ensure_seed_locations,
        get_active_plan_row,
        list_plan_tasks,
    )

    ensure_seed_locations(USER_ID)
    for idx in range(count):
        name = f'Normal {idx}'
        t = create_is_talebi(
            USER_ID,
            {
                'tarih': PLAN_DATE,
                'is': name,
                'firma': name,
                'latitude': 41.0 + idx * 0.01,
                'longitude': 29.0 + idx * 0.01,
                'oncelik': 'NORMAL',
                'save_to_master': False,
            },
        )
        assign_to_plan(USER_ID, t['id'], PLAN_DATE, vehicle, PLATE, None, 'R2 E2E', '09:00', None)
    tasks = list_plan_tasks(PLAN_DATE, vehicle)
    plan_id = int(get_active_plan_row(PLAN_DATE, vehicle)['id'])
    return {'tasks': tasks, 'plan_id': plan_id}


def _seed_plan(temp_db: str, *, vehicle: str = VID) -> dict:
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
        assign_to_plan(USER_ID, t['id'], PLAN_DATE, vehicle, PLATE, None, 'R2 E2E', '09:00', None)
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
                (name, vehicle, PLAN_DATE),
            ).fetchone()
            con.execute("UPDATE arac_gunluk_plan_is SET durum=? WHERE id=?", (st, row['id']))
            con.commit()
            con.close()

    tasks = list_plan_tasks(PLAN_DATE, vehicle)
    plan_id = int(get_active_plan_row(PLAN_DATE, vehicle)['id'])
    return {'tasks': tasks, 'plan_id': plan_id}


def _proposal(temp_db: str, seeded: dict, *, vehicle: str = VID):
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
                vehicle_id=vehicle,
                plan_id=seeded['plan_id'],
                matrix_provider_fn=_matrix_fn,
                ors_provider_fn=lambda: MockRoadRoutingProvider(),
            )


def _mock_route_dto(base, tasks):
    from modules.planlama.road_routing.mock_provider import MockRoadRoutingProvider
    from modules.planlama.road_routing.route_planner_service import build_plan_route_dto

    with patch('modules.planlama.road_routing.route_planner_service.get_routing_provider', return_value=MockRoadRoutingProvider()):
        return build_plan_route_dto(base, tasks)


def _apply(temp_db: str, seeded: dict, proposal: dict, *, client_submit_id: str | None = None, vehicle: str = VID):
    from modules.planlama.arac_route_apply_service import apply_route_order_and_snapshot

    return apply_route_order_and_snapshot(
        USER_ID,
        PLAN_DATE,
        vehicle,
        proposal['suggested_task_ids'],
        proposal_hash=proposal['proposal_hash'],
        proposal_expires_at=proposal.get('expires_at'),
        client_submit_id=client_submit_id,
        route_dto_builder=_mock_route_dto,
    )


def _item_order(temp_db: str, vehicle: str = VID) -> list[int]:
    from modules.planlama.arac_takip_repo import list_plan_tasks

    return [int(t['plan_item_id']) for t in list_plan_tasks(PLAN_DATE, vehicle)]


def _plan_state_fingerprint(temp_db: str, vehicle: str = VID) -> tuple:
    con = _conn(temp_db)
    order = tuple(
        con.execute(
            """
            SELECT pi.id, pi.sira, pi.durum FROM arac_gunluk_plan_is pi
            JOIN arac_gunluk_plan p ON p.id = pi.plan_id
            WHERE p.plan_tarihi=? AND p.arac_external_id=?
            ORDER BY pi.sira, pi.id
            """,
            (PLAN_DATE, vehicle),
        ).fetchall()
    )
    snap_n = con.execute('SELECT COUNT(*) AS c FROM arac_plan_rota_snapshot').fetchone()['c']
    evt_n = con.execute('SELECT COUNT(*) AS c FROM arac_plan_is_degisim').fetchone()['c']
    con.close()
    return (order, snap_n, evt_n)


def _assert_global_sira_1_to_n(temp_db: str, vehicle: str = VID) -> None:
    con = _conn(temp_db)
    rows = con.execute(
        """
        SELECT pi.sira FROM arac_gunluk_plan_is pi
        JOIN arac_gunluk_plan p ON p.id = pi.plan_id
        WHERE p.plan_tarihi=? AND p.arac_external_id=?
          AND pi.durum NOT IN ('IPTAL', 'ERTELENDI', 'GIDILEMEDI')
        ORDER BY pi.sira
        """,
        (PLAN_DATE, vehicle),
    ).fetchall()
    con.close()
    siras = [int(r['sira']) for r in rows]
    assert siras == list(range(1, len(siras) + 1))


# ── S8 departure recalc ───────────────────────────────────────────────────────

def test_s8_departure_time_recalcs_traffic_and_factory_return():
    from modules.planlama.arac_google_route_options_service import compute_google_route_options
    from modules.planlama.road_routing.google_routes_provider import (
        GoogleLeg,
        GoogleRouteResult,
        PROFILE_TRAFFIC_FAST,
        PROFILE_TRAFFIC_FREE,
    )
    from modules.planlama.road_routing.types import RoutingError

    stops = [
        {'id': 'pi-1', 'order_no': 1, 'status': 'PLANLANDI', 'priority': 'NORMAL',
         'company_name': 'A', 'latitude': 41.01, 'longitude': 29.01, 'has_coordinates': True},
        {'id': 'pi-2', 'order_no': 2, 'status': 'PLANLANDI', 'priority': 'NORMAL',
         'company_name': 'B', 'latitude': 41.02, 'longitude': 29.02, 'has_coordinates': True},
    ]

    def _res(drive_s: float) -> GoogleRouteResult:
        legs = [GoogleLeg(0, 1, drive_s * 0.4, 0, 0), GoogleLeg(1, 2, drive_s * 0.6, 0, 0)]
        return GoogleRouteResult(
            profile=PROFILE_TRAFFIC_FAST,
            profile_label='En Hızlı',
            distance_m=100000,
            drive_seconds=drive_s,
            static_seconds=drive_s * 0.9,
            traffic_delta_seconds=drive_s * 0.1,
            encoded_polyline='x',
            toll_present=False,
            toll_info={},
            route_labels=[],
            legs=legs,
        )

    def _route_google(self, points):
        dep = getattr(self, '_departure_utc', '') or ''
        base_drive = 7200.0 if '05:00' in dep else 5400.0
        if self.profile == PROFILE_TRAFFIC_FREE:
            return _res(base_drive + 300)
        return _res(base_drive)

    with patch('modules.planlama.arac_google_route_options_service.GoogleRoutesProvider.route_google', _route_google):
        d1 = compute_google_route_options(
            plan_date='2026-08-27', departure_hhmm='08:00', base=BASE, tasks=stops,
            departure_utc='2026-08-27T05:00:00Z',
        )
        d2 = compute_google_route_options(
            plan_date='2026-08-27', departure_hhmm='11:00', base=BASE, tasks=stops,
            departure_utc='2026-08-27T08:00:00Z',
        )
    assert d1.current.fastest.drive_seconds != d2.current.fastest.drive_seconds
    assert d1.current.fastest.return_display != d2.current.fastest.return_display


# ── S9 traffic failure zero-write ───────────────────────────────────────────

def test_s9_traffic_failure_apply_disabled_order_unchanged(temp_db):
    seeded = _seed_plan(temp_db)
    before = _item_order(temp_db)
    from modules.planlama.arac_google_route_options_service import compute_google_route_options
    from modules.planlama.road_routing.types import RoutingError

    tasks = seeded['tasks']
    with patch(
        'modules.planlama.arac_google_route_options_service.GoogleRoutesProvider.route_google',
        side_effect=RoutingError('fail', code='TIMEOUT'),
    ):
        dto = compute_google_route_options(
            plan_date=PLAN_DATE,
            departure_hhmm='09:00',
            base=BASE,
            tasks=tasks,
            departure_utc=f'{PLAN_DATE}T06:00:00Z',
        )
    assert dto.apply_enabled is False
    assert dto.order_changed is False
    assert dto.apply_blocked_message == 'Google trafik verisi alınamadı; mevcut plan değiştirilmedi.'
    assert _item_order(temp_db) == before


# ── S10 cancel modal zero-write ───────────────────────────────────────────────

def test_s10_cancel_modal_no_db_writes(temp_db):
    seeded = _seed_plan(temp_db)
    _proposal(temp_db, seeded)
    fp_before = _plan_state_fingerprint(temp_db)
    from modules.planlama.arac_whatsapp_message_service import load_whatsapp_plan_context

    with patch(
        'modules.planlama.arac_timeline_service.build_timeline_for_plan',
        return_value={
            'estimated_return_time': '18:00',
            'timeline_complete': True,
            'status': 'HESAPLANDI',
            'plan_departure_time': '09:00',
        },
    ):
        wa1 = load_whatsapp_plan_context(PLAN_DATE, VID)
        wa2 = load_whatsapp_plan_context(PLAN_DATE, VID)
    fp_after = _plan_state_fingerprint(temp_db)
    assert fp_before == fp_after
    assert wa1 is not None and wa2 is not None
    assert [s['plan_item_id'] for s in wa1['stops']] == [s['plan_item_id'] for s in wa2['stops']]


# ── S11 apply / readback / F5 / whatsapp ──────────────────────────────────────

def test_s11_atomic_apply_global_order_readback_f5_whatsapp(temp_db):
    seeded = _seed_plan_normals(temp_db)
    p = _proposal(temp_db, seeded)
    assert p.get('apply_enabled') is True or p.get('changed') is False
    _apply(temp_db, seeded, p, client_submit_id='r2-s11')
    from modules.planlama.arac_takip_repo import list_plan_tasks

    db_task_ids = [t['id'] for t in list_plan_tasks(PLAN_DATE, VID)]
    assert db_task_ids == p['suggested_task_ids']
    db_order = _item_order(temp_db)
    _assert_global_sira_1_to_n(temp_db)

    from modules.planlama.arac_driver_map_service import build_driver_map_dto
    from modules.planlama.arac_takip_repo import list_plan_tasks
    from modules.planlama.arac_whatsapp_message_service import build_whatsapp_plan_message_v2, load_whatsapp_plan_context

    tasks_f5 = list_plan_tasks(PLAN_DATE, VID)
    tasks_f5b = list_plan_tasks(PLAN_DATE, VID)
    assert [t['plan_item_id'] for t in tasks_f5] == [t['plan_item_id'] for t in tasks_f5b] == db_order
    dto = build_driver_map_dto(PLAN_DATE, VID)
    map_order = [int(x) if not str(x).startswith('pi-') else int(str(x)[3:]) for x in dto['item_id_order']]
    assert map_order == db_order
    ret_time = '17:45'
    with patch(
        'modules.planlama.arac_timeline_service.build_timeline_for_plan',
        return_value={
            'estimated_return_time': ret_time,
            'timeline_complete': True,
            'status': 'HESAPLANDI',
            'plan_departure_time': '09:00',
        },
    ):
        ctx = load_whatsapp_plan_context(PLAN_DATE, VID)
    msg = build_whatsapp_plan_message_v2(ctx)
    assert 'Tahmini Fabrika Varışı' in msg
    assert ret_time in msg
    stop_ids_wa = [int(s.get('plan_item_id') or s.get('id', '').replace('pi-', '')) for s in ctx['stops']]
    assert stop_ids_wa == db_order


def test_s11_fault_injection_full_rollback(temp_db):
    seeded = _seed_plan_normals(temp_db)
    p = _proposal(temp_db, seeded)
    before = _item_order(temp_db)

    def boom(*args, **kwargs):
        raise RuntimeError('injected snapshot failure')

    with patch('modules.planlama.arac_route_apply_service._save_plan_rota_snapshot_conn', side_effect=boom):
        from modules.planlama.arac_route_apply_service import RouteApplyPersistenceError

        with pytest.raises(RouteApplyPersistenceError):
            _apply(temp_db, seeded, p, client_submit_id='r2-rollback')
    assert _item_order(temp_db) == before


def test_s11_idempotent_second_apply_no_extra_writes(temp_db):
    from modules.planlama.arac_gps_snapshot_repo import get_active_plan_rota_snapshot

    seeded = _seed_plan_normals(temp_db)
    p = _proposal(temp_db, seeded)
    r1 = _apply(temp_db, seeded, p, client_submit_id='r2-idem')
    snap_v1 = get_active_plan_rota_snapshot(seeded['plan_id'])
    order_v1 = _item_order(temp_db)
    r2 = _apply(temp_db, seeded, p, client_submit_id='r2-idem')
    snap_v2 = get_active_plan_rota_snapshot(seeded['plan_id'])
    assert r2.deduplicated is True
    assert order_v1 == _item_order(temp_db)
    assert int(snap_v2['route_version']) == int(snap_v1['route_version'])


def test_unauthorized_apply_zero_write(temp_db):
    seeded = _seed_plan_normals(temp_db)
    p = _proposal(temp_db, seeded)
    before = _item_order(temp_db)
    from functools import wraps

    import flask
    import importlib
    import modules.auth as auth_mod
    import modules.planlama.arac_takip_routes as routes_mod

    def _open(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            return f(*args, **kwargs)

        return wrapper

    auth_mod.yetki_gerekli = lambda *a, **k: _open
    auth_mod.yetki_var = lambda *a, **k: False
    routes_mod = importlib.reload(routes_mod)
    app = flask.Flask(__name__, template_folder=str(APP / 'templates'), static_folder=str(APP / 'static'))
    app.secret_key = 'r2-deny'
    app.config['TESTING'] = True
    app.register_blueprint(routes_mod.arac_takip_bp)
    client = app.test_client()
    r = client.post(
        '/planlama/arac-takip/api/route/apply',
        json={
            'date': PLAN_DATE,
            'vehicle_id': VID,
            'task_ids': p['suggested_task_ids'],
            'proposal_hash': p['proposal_hash'],
            'proposal_expires_at': p.get('expires_at'),
        },
    )
    assert r.status_code == 403
    assert _item_order(temp_db) == before


# ── S12 cross-plan ────────────────────────────────────────────────────────────

def _drop_plan_vehicle_unique(con: sqlite3.Connection) -> None:
    """Legacy cross-plan rows: temp DB only — remove UNIQUE(vehicle+day) for S12."""
    con.execute('PRAGMA foreign_keys=OFF')
    con.execute(
        """
        CREATE TABLE arac_gunluk_plan_multi (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_tarihi TEXT NOT NULL,
            arac_provider TEXT NOT NULL DEFAULT 'TURKCELL_FILOM',
            arac_external_id TEXT NOT NULL,
            arac_plaka_snapshot TEXT NOT NULL,
            sofor_id INTEGER,
            sofor_adi_snapshot TEXT,
            durum TEXT NOT NULL DEFAULT 'AKTIF',
            created_at TEXT NOT NULL,
            created_by INTEGER NOT NULL,
            updated_at TEXT NOT NULL,
            updated_by INTEGER NOT NULL
        )
        """
    )
    con.execute('INSERT INTO arac_gunluk_plan_multi SELECT * FROM arac_gunluk_plan')
    con.execute('DROP TABLE arac_gunluk_plan')
    con.execute('ALTER TABLE arac_gunluk_plan_multi RENAME TO arac_gunluk_plan')
    con.execute('PRAGMA foreign_keys=ON')


def _seed_cross_plan(temp_db: str) -> dict:
    from modules.planlama.arac_takip_repo import (
        assign_to_plan,
        create_is_talebi,
        ensure_seed_locations,
        list_plan_tasks,
    )

    ensure_seed_locations(USER_ID)
    plan_ids = []
    for idx, (name, pri) in enumerate(
        [('Cross A', 'NORMAL'), ('Cross B', 'ACIL'), ('Cross C', 'NORMAL'), ('Cross D', 'NORMAL')],
        start=1,
    ):
        t = create_is_talebi(
            USER_ID,
            {
                'tarih': PLAN_DATE,
                'is': name,
                'firma': name,
                'latitude': 41.0 + idx * 0.01,
                'longitude': 29.0 + idx * 0.01,
                'oncelik': pri,
                'save_to_master': False,
            },
        )
        assign_to_plan(USER_ID, t['id'], PLAN_DATE, VID, PLATE, None, '09:00', None)
    con = _conn(temp_db)
    _drop_plan_vehicle_unique(con)
    pid1 = con.execute(
        'SELECT id FROM arac_gunluk_plan WHERE arac_external_id=? AND plan_tarihi=? ORDER BY id LIMIT 1',
        (VID, PLAN_DATE),
    ).fetchone()['id']
    cur = con.execute(
        """
        INSERT INTO arac_gunluk_plan (
            plan_tarihi, arac_provider, arac_external_id, arac_plaka_snapshot,
            sofor_id, sofor_adi_snapshot, durum, created_at, created_by, updated_at, updated_by
        ) VALUES (?,'TURKCELL_FILOM',?,?,NULL,NULL,'AKTIF',datetime('now'),1,datetime('now'),1)
        """,
        (PLAN_DATE, VID, PLATE),
    )
    pid2 = int(cur.lastrowid)
    move = con.execute(
        'SELECT id FROM arac_gunluk_plan_is WHERE plan_id=? ORDER BY id DESC LIMIT 2',
        (pid1,),
    ).fetchall()
    for row in move:
        con.execute('UPDATE arac_gunluk_plan_is SET plan_id=? WHERE id=?', (pid2, row['id']))
    con.commit()
    con.close()
    plan_ids = [int(pid1), pid2]
    tasks = list_plan_tasks(PLAN_DATE, VID)
    return {'tasks': tasks, 'plan_id': int(pid1), 'plan_ids': plan_ids}


def test_s12_cross_plan_single_route_apply_global_order(temp_db):
    _seed_plan(temp_db, vehicle=OTHER_VID)
    seeded = _seed_cross_plan(temp_db)
    other_before = _item_order(temp_db, OTHER_VID)
    p = _proposal(temp_db, seeded)
    assert len(seeded['tasks']) >= 4
    _apply(temp_db, seeded, p, client_submit_id='r2-cross')
    _assert_global_sira_1_to_n(temp_db, VID)
    assert _item_order(temp_db, OTHER_VID) == other_before


# ── Extras ────────────────────────────────────────────────────────────────────

def test_midnight_factory_arrival_date_time_label():
    from datetime import datetime, timedelta

    from modules.planlama.arac_whatsapp_message_service import format_return_time_display

    display = format_return_time_display(
        PLAN_DATE,
        '23:30',
        '00:35',
        return_dt=datetime.fromisoformat(f'{PLAN_DATE} 23:30:00') + timedelta(hours=1, minutes=5),
    )
    assert display == '00:35 (ertesi gün)'


def test_bad_insertion_order_can_be_improved_by_proposal(temp_db):
    seeded = _seed_plan_normals(temp_db)
    from modules.planlama.arac_takip_repo import list_plan_tasks, reorder_plan_items_bulk

    good = [t['id'] for t in list_plan_tasks(PLAN_DATE, VID)]
    scrambled = list(reversed(good))
    reorder_plan_items_bulk(USER_ID, PLAN_DATE, VID, scrambled)
    p = _proposal(temp_db, {'tasks': list_plan_tasks(PLAN_DATE, VID), 'plan_id': seeded['plan_id']})
    if p.get('changed'):
        assert p['suggested_task_ids'] != scrambled
        assert p.get('apply_enabled') is True


def test_emergency_explanation_on_google_dto(temp_db):
    seeded = _seed_plan(temp_db)
    from modules.planlama.arac_google_route_options_service import compute_google_route_options
    from tests.planlama.test_google_route_options_service import _fake_google_result, _patch_route_google
    from modules.planlama.road_routing.google_routes_provider import PROFILE_TRAFFIC_FAST, PROFILE_TRAFFIC_FREE

    fast = _fake_google_result(PROFILE_TRAFFIC_FAST)
    free = _fake_google_result(PROFILE_TRAFFIC_FREE)
    with _patch_route_google({PROFILE_TRAFFIC_FAST: fast, PROFILE_TRAFFIC_FREE: free}):
        dto = compute_google_route_options(
            plan_date=PLAN_DATE,
            departure_hhmm='09:00',
            base=BASE,
            tasks=seeded['tasks'],
            departure_utc=f'{PLAN_DATE}T06:00:00Z',
        )
    if dto.order_changed and dto.emergency_priority_applied:
        assert dto.emergency_explanation == (
            'ACİL işler normal işlerden önce tamamlanacak şekilde rota optimize edildi.'
        )
