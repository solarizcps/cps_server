# -*- coding: utf-8 -*-
"""GPS P2 — route apply hook, deviation engine, worker (temp DB)."""
from __future__ import annotations

import hashlib
import importlib.util
import io
import os
import sqlite3
import sys
import tempfile
import threading
import subprocess
from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest.mock import patch

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(ROOT, 'app')
CANONICAL_DB = os.path.join(APP, 'mock_data.db')
CANONICAL_SHA = hashlib.sha256(open(CANONICAL_DB, 'rb').read()).hexdigest() if os.path.isfile(CANONICAL_DB) else ''
sys.path.insert(0, APP)
os.chdir(APP)

PASS = 0
FAIL = 0
YK = frozenset({'planlama:can_view', 'planlama:can_update', 'planlama:can_create'})


def ok(name: str) -> None:
    global PASS
    PASS += 1
    print(f'  PASS {name}')


def bad(name: str, detail: str = '') -> None:
    global FAIL
    FAIL += 1
    print(f'  FAIL {name} {detail}')


def _run_migration(db_path: str, filename: str) -> None:
    spec = importlib.util.spec_from_file_location(
        filename, os.path.join(APP, 'migrations', filename),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.run(db_path)


@contextmanager
def temp_p2_db():
    tmpdir = tempfile.mkdtemp(prefix='gps_p2_')
    db_path = os.path.join(tmpdir, 'gps_p2.db')
    for mig in (
        '176_arac_takip_v13.py', '177_arac_operasyon_ayar.py',
        '178_arac_is_talebi_ux_v2_fields.py', '179_arac_gps_snapshot_p1.py',
    ):
        _run_migration(db_path, mig)
    con = sqlite3.connect(db_path)
    now = '2026-12-20 08:00:00'
    con.execute(
        """
        INSERT INTO arac_operasyon_ayar (
            base_name, base_latitude, base_longitude, base_address, base_maps_url,
            aktif, created_at, updated_at, updated_by
        ) VALUES ('Base',41.0,29.0,'Adres','https://maps.google.com/?q=41,29',1,?,?,1)
        """,
        (now, now),
    )
    cur = con.execute(
        """
        INSERT INTO arac_gunluk_plan (
            plan_tarihi, arac_provider, arac_external_id, arac_plaka_snapshot,
            sofor_id, sofor_adi_snapshot, durum, created_at, created_by, updated_at, updated_by
        ) VALUES ('2026-12-20','TURKCELL_FILOM','45077045','34 MOR 049',1,'Oktay','AKTIF',?,?,?,?)
        """,
        (now, 1, now, 1),
    )
    plan_id = int(cur.lastrowid)
    for i, (lat, lng) in enumerate([(40.99, 28.89), (40.98, 28.88), (40.97, 28.87)], 1):
        tcur = con.execute(
            """
            INSERT INTO arac_is_talebi (
                talep_no, talep_eden_user_id, talep_eden_adi_snapshot, talep_tarihi,
                firma_adi, adres, yapilacak_is, oncelik, durum,
                latitude, longitude, created_at, created_by, updated_at, updated_by
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (f'P2-{i}', 1, 'Test', '2026-12-20', f'Co{i}', f'Ad{i}', f'Is{i}', 'NORMAL',
             'PLANA_ALINDI', lat, lng, now, 1, now, 1),
        )
        con.execute(
            """
            INSERT INTO arac_gunluk_plan_is (
                plan_id, is_talebi_id, sira, planlanan_saat, durum, created_at, created_by
            ) VALUES (?,?,?,?,?,?,?)
            """,
            (plan_id, int(tcur.lastrowid), i, f'0{8+i}:00', 'PLANLANDI', now, 1),
        )
    con.commit()
    con.close()
    import config
    with patch.object(config.Config, 'MOCK_DB_PATH', db_path):
        print(f'  [DB-PATH-TEMP] {db_path}')
        yield db_path, plan_id


def _route_dto(order_count: int = 3) -> dict:
    pts = [[41.0, 29.0], [40.99, 28.89], [40.98, 28.88], [40.97, 28.87]][: order_count + 1]
    return {
        'status': 'OK',
        'current': {
            'provider': 'mock',
            'geometry': pts,
            'distance_m': 12000.0,
            'duration_s': 1800.0,
            'order_labels': '1 → 2 → 3',
        },
    }


def test_geojson_contract() -> None:
    print('GEOJSON')
    from modules.planlama.arac_route_geometry import (
        GeometryError, latlng_pairs_to_geojson, validate_geojson_linestring,
    )
    gj = latlng_pairs_to_geojson([[41.0, 29.0], [40.99, 28.89]])
    coords = validate_geojson_linestring(gj)
    if coords[0] == [29.0, 41.0]:
        ok('latlng_to_lonlat')
    else:
        bad('latlng_to_lonlat', str(coords))
    try:
        validate_geojson_linestring({'type': 'LineString', 'coordinates': [[41.0, 29.0]]})
        bad('reject_short_geometry')
    except GeometryError:
        ok('reject_short_geometry')
    try:
        validate_geojson_linestring({'type': 'LineString', 'coordinates': [[29.0, 95.0], [29.1, 96.0]]})
        bad('reject_invalid_lat')
    except GeometryError:
        ok('reject_invalid_lat')


def test_distance_algo() -> None:
    print('DISTANCE')
    from modules.planlama.arac_geo_distance import point_to_linestring_distance_m
    line = [[29.0, 41.0], [29.01, 41.0], [29.02, 41.0]]
    d0 = point_to_linestring_distance_m(41.0, 29.005, line)
    d200 = point_to_linestring_distance_m(41.0018, 29.005, line)
    if d0 is not None and d0 < 50:
        ok('on_route_near_zero')
    else:
        bad('on_route_near_zero', str(d0))
    if d200 is not None and 150 < d200 < 250:
        ok('offset_about_200m')
    else:
        bad('offset_about_200m', str(d200))


def test_route_apply_hook(db_path: str, plan_id: int) -> None:
    print('ROUTE_APPLY')
    from modules.planlama.arac_route_apply_service import apply_route_order_and_snapshot
    from modules.planlama.arac_takip_repo import list_plan_tasks
    from modules.planlama.arac_gps_snapshot_repo import get_active_plan_rota_snapshot

    tasks = list_plan_tasks('2026-12-20', '45077045')
    ids = [t['id'] for t in sorted(tasks, key=lambda x: x['order_no'])]
    with patch('modules.planlama.road_routing.route_planner_service.build_plan_route_dto', return_value=_route_dto()):
        r1 = apply_route_order_and_snapshot(
            1, '2026-12-20', '45077045', ids, user_id=1,
            route_dto_builder=lambda _b, _t: _route_dto(),
        )
    if r1.route_version == 1 and not r1.deduplicated and r1.applied:
        ok('apply_snapshot_v1')
    else:
        bad('apply_snapshot_v1', str(r1))
    rev = list(reversed(ids))
    with patch('modules.planlama.road_routing.route_planner_service.build_plan_route_dto', return_value=_route_dto()):
        r2 = apply_route_order_and_snapshot(
            1, '2026-12-20', '45077045', rev, user_id=1,
            route_dto_builder=lambda _b, _t: _route_dto(),
        )
    active = get_active_plan_rota_snapshot(plan_id)
    con = sqlite3.connect(db_path)
    old = con.execute(
        'SELECT route_version, is_active FROM arac_plan_rota_snapshot WHERE plan_id=? AND route_version=1',
        (plan_id,),
    ).fetchone()
    con.close()
    if r2.route_version == 2:
        ok('apply_snapshot_v2')
    else:
        bad('apply_snapshot_v2', str(r2))
    if old and old[1] == 0:
        ok('v1_deactivated')
    else:
        bad('v1_deactivated', str(old))
    with patch('modules.planlama.road_routing.route_planner_service.build_plan_route_dto', return_value=_route_dto()):
        r3 = apply_route_order_and_snapshot(
            1, '2026-12-20', '45077045', rev, user_id=1,
            route_dto_builder=lambda _b, _t: _route_dto(),
        )
    if r3.deduplicated:
        ok('same_route_dedup')
    else:
        bad('same_route_dedup', str(r3))
    from modules.planlama.arac_route_apply_service import RouteApplyRouteError
    try:
        with patch('modules.planlama.road_routing.route_planner_service.build_plan_route_dto', return_value={'status': 'NO_ROUTE'}):
            apply_route_order_and_snapshot(
                1, '2026-12-20', '45077045', rev, user_id=1,
                route_dto_builder=lambda _b, _t: {'status': 'NO_ROUTE'},
            )
        bad('failed_route_no_reorder')
    except RouteApplyRouteError:
        ok('failed_route_no_reorder')


def _insert_gps(gps_id: str, lat: float, lon: float, ts: str, *, stale: bool = False) -> dict:
    from modules.planlama.arac_gps_poll_service import persist_vehicle_snapshot
    v = {
        'id': '45077045', 'latitude': lat, 'longitude': lon,
        'has_valid_location': True, 'last_seen_at': ts,
        'is_stale_data': stale, 'last_seen_label': '1 Yıl' if stale else '1 dk.',
        'speed_kmh': 20, 'activity_status': 'HAREKETLI', 'ignition': 'Açık',
        'total_distance_km': 100.0, 'plate_display': '34 MOR 049',
    }
    dt = datetime.strptime(ts, '%Y-%m-%d %H:%M:%S')
    persist_vehicle_snapshot(v, now=dt)
    from modules.planlama.arac_gps_snapshot_repo import list_gps_snapshots_ordered
    rows = list_gps_snapshots_ordered('45077045')
    return rows[-1]


def test_deviation_state_machine(plan_id: int) -> None:
    print('DEVIATION')
    from modules.planlama.arac_rota_deviation_service import (
        STATE_DEVIATING, STATE_ON_ROUTE, process_gps_snapshot_for_deviation,
    )
    from modules.planlama.arac_rota_deviation_repo import count_plan_events, get_deviation_state

    line_lat = 41.0
    base_ts = datetime(2026, 12, 20, 10, 0, 0)
    r1 = process_gps_snapshot_for_deviation(
        _insert_gps('1', line_lat, 29.005, '2026-12-20 10:00:00'), plan_date='2026-12-20',
    )
    if r1.get('state') == STATE_ON_ROUTE:
        ok('200m_on_route')
    else:
        bad('200m_on_route', str(r1))
    r_h = process_gps_snapshot_for_deviation(
        _insert_gps('2', line_lat + 0.0036, 29.005, '2026-12-20 10:01:00'), plan_date='2026-12-20',
    )
    st = get_deviation_state(plan_id)
    if st and st.get('state') in (STATE_ON_ROUTE, 'DEVIATION_CANDIDATE'):
        ok('400m_hysteresis')
    else:
        bad('400m_hysteresis', str(st))
    r_jump = process_gps_snapshot_for_deviation(
        _insert_gps('3', line_lat + 0.009, 29.005, '2026-12-20 10:02:00'), plan_date='2026-12-20',
    )
    if r_jump.get('state') != STATE_DEVIATING:
        ok('single_600m_no_alarm')
    else:
        bad('single_600m_no_alarm', str(r_jump))
    for i in range(3):
        process_gps_snapshot_for_deviation(
            _insert_gps(f'4{i}', line_lat + 0.009, 29.005 + i * 0.0001,
                        f'2026-12-20 10:0{3+i}:00'),
            plan_date='2026-12-20',
        )
    st_dev = get_deviation_state(plan_id)
    if st_dev and st_dev.get('state') == STATE_DEVIATING:
        ok('three_consecutive_deviating')
    else:
        bad('three_consecutive_deviating', str(st_dev))
    if count_plan_events(plan_id, 'ROTA_SAPMA_BASLADI') == 1:
        ok('deviation_event_once')
    else:
        bad('deviation_event_once', str(count_plan_events(plan_id, 'ROTA_SAPMA_BASLADI')))
    process_gps_snapshot_for_deviation(
        _insert_gps('stale', line_lat, 29.005, '2026-12-20 10:10:00', stale=True),
        plan_date='2026-12-20',
    )
    st_after_stale = get_deviation_state(plan_id)
    if st_after_stale and st_after_stale.get('state') == STATE_DEVIATING:
        ok('stale_does_not_advance')
    else:
        bad('stale_does_not_advance', str(st_after_stale))
    for i in range(2):
        process_gps_snapshot_for_deviation(
            _insert_gps(f'rec{i}', 41.0, 29.0 + i * 0.00001, f'2026-12-20 10:1{i}:00'),
            plan_date='2026-12-20',
        )
    st_rec = get_deviation_state(plan_id)
    if st_rec and st_rec.get('state') == STATE_ON_ROUTE:
        ok('recovery_two_points')
    else:
        bad('recovery_two_points', str(st_rec))
    if count_plan_events(plan_id, 'ROTA_GERI_DONDU') == 1:
        ok('recovery_event_once')
    else:
        bad('recovery_event_once', str(count_plan_events(plan_id, 'ROTA_GERI_DONDU')))


def test_no_plan_no_route() -> None:
    print('NO_PLAN_ROUTE')
    from modules.planlama.arac_rota_deviation_service import STATE_NO_PLAN, STATE_NO_ROUTE
    from modules.planlama.arac_rota_deviation_service import process_gps_snapshot_for_deviation
    row = {
        'id': 999, 'arac_external_id': 'NOPLAN99', 'latitude': 41.0, 'longitude': 29.0,
        'gps_timestamp': '2026-12-20 11:00:00', 'is_stale': 0,
    }
    r = process_gps_snapshot_for_deviation(row, plan_date='2026-12-20')
    if r.get('state') == STATE_NO_PLAN:
        ok('no_active_plan')
    else:
        bad('no_active_plan', str(r))


def test_worker_lock_and_smoke(db_path: str) -> None:
    print('WORKER')
    lock_path = os.path.join(tempfile.gettempdir(), f'gps_p2_lock_{os.getpid()}.lock')
    env = os.environ.copy()
    env['CPS_MOCK_DB_PATH'] = db_path
    env['ARAC_GPS_POLL_LOCK_PATH'] = lock_path
    worker = os.path.join(APP, 'tools', 'arac_gps_poll_worker.py')
    mock_fetch = (
        "import json; "
        "from modules.planlama.arac_gps_poll_service import poll_once; "
        "print(json.dumps(poll_once(lambda: {'ok': True, 'vehicles': []}, "
        "now=__import__('datetime').datetime(2026,12,20,12,0,0))))"
    )
    p1 = subprocess.Popen(
        [sys.executable, worker, '--once'], env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    p2 = subprocess.Popen(
        [sys.executable, worker, '--once'], env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    out1, err1 = p1.communicate(timeout=30)
    out2, err2 = p2.communicate(timeout=30)
    combined = (out1 or '') + (err2 or '') + (err1 or '') + (out2 or '')
    if 'another worker instance' in combined:
        ok('worker_single_instance')
    else:
        bad('worker_single_instance', combined[:200])
    if p1.returncode == 0 or p2.returncode == 0:
        ok('worker_smoke_exit')
    else:
        bad('worker_smoke_exit', f'{p1.returncode}/{p2.returncode}')


def test_canonical_hash() -> None:
    print('CANONICAL')
    if os.path.isfile(CANONICAL_DB):
        h = hashlib.sha256(open(CANONICAL_DB, 'rb').read()).hexdigest()
        if h == CANONICAL_SHA:
            ok('canonical_unchanged')
        else:
            bad('canonical_unchanged', h)
    else:
        ok('canonical_absent_skip')


def main() -> int:
    print('=' * 72)
    print('GPS P2 — worker + route hook + deviation engine')
    print('=' * 72)
    with temp_p2_db() as (db_path, plan_id):
        with patch('modules.planlama.road_routing.route_planner_service.get_routing_provider') as _:
            os.environ['ARAC_ROUTING_PROVIDER'] = 'mock'
            test_geojson_contract()
            test_distance_algo()
            test_route_apply_hook(db_path, plan_id)
            test_deviation_state_machine(plan_id)
            test_no_plan_no_route()
            test_worker_lock_and_smoke(db_path)
    test_canonical_hash()
    print(f'\nTOTAL {PASS} pass / {FAIL} fail')
    return 0 if FAIL == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
