# -*- coding: utf-8 -*-
"""Araç Takip GPS P1 — snapshot persistence + plan rota referansı (temp DB)."""
from __future__ import annotations

import hashlib
import importlib.util
import io
import os
import sqlite3
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest.mock import patch

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(ROOT, 'app')
CANONICAL_DB = os.path.join(APP, 'mock_data.db')
CANONICAL_SHA = 'b79bb0da49c884d8dd5330810469bab85f73e78db1f7be8eb57a95a7951dd51b'
sys.path.insert(0, APP)
os.chdir(APP)

PASS = 0
FAIL = 0


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


def _canonical_hash() -> str:
    return hashlib.sha256(open(CANONICAL_DB, 'rb').read()).hexdigest()


@contextmanager
def temp_gps_db():
    tmpdir = tempfile.mkdtemp(prefix='gps_p1_')
    db_path = os.path.join(tmpdir, 'gps_p1.db')
    for mig in (
        '176_arac_takip_v13.py',
        '177_arac_operasyon_ayar.py',
        '178_arac_is_talebi_ux_v2_fields.py',
        '179_arac_gps_snapshot_p1.py',
    ):
        _run_migration(db_path, mig)
    import config
    with patch.object(config.Config, 'MOCK_DB_PATH', db_path):
        print(f'  [DB-PATH-TEMP] {db_path}')
        yield db_path


def _vehicle(
    vid: str,
    lat: float,
    lon: float,
    ts: str,
    *,
    stale: bool = False,
    speed: int = 10,
) -> dict:
    stale_label = '1 Yıl' if stale else '1 dk.'
    return {
        'id': vid,
        'plate': f'PLATE-{vid}',
        'plate_display': f'34 GPS {vid[-2:]}',
        'latitude': lat,
        'longitude': lon,
        'has_valid_location': True,
        'last_seen_at': ts,
        'last_seen_label': stale_label,
        'is_stale_data': stale,
        'speed_kmh': speed,
        'activity_status': 'HAREKETLI' if not stale else 'PASIF',
        'activity_status_label': 'Hareketli',
        'ignition': 'Açık',
        'total_distance_km': 1000.0,
        'in_use': True,
    }


def _seed_plan(db_path: str) -> int:
    con = sqlite3.connect(db_path)
    now = '2026-12-20 08:00:00'
    cur = con.execute(
        """
        INSERT INTO arac_gunluk_plan (
            plan_tarihi, arac_provider, arac_external_id, arac_plaka_snapshot,
            sofor_id, sofor_adi_snapshot, durum, created_at, created_by, updated_at, updated_by
        ) VALUES ('2026-12-20','TURKCELL_FILOM','45077045','34 MOR 049',1,'Oktay', 'AKTIF',?,?,?,?)
        """,
        (now, 1, now, 1),
    )
    plan_id = int(cur.lastrowid)
    con.commit()
    con.close()
    return plan_id


def test_migration_and_integrity(db_path: str) -> None:
    print('MIGRATION')
    con = sqlite3.connect(db_path)
    tables = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'",
    ).fetchall()}
    needed = {'arac_gps_snapshot', 'arac_plan_rota_snapshot', 'arac_plan_olay'}
    if needed <= tables:
        ok('tables_created')
    else:
        bad('tables_created', str(tables))
    integrity = con.execute('PRAGMA integrity_check').fetchone()[0]
    if integrity == 'ok':
        ok('integrity_check')
    else:
        bad('integrity_check', integrity)
    con.close()


def test_single_insert(db_path: str) -> None:
    print('SNAPSHOT_INSERT')
    from modules.planlama.arac_gps_poll_service import poll_once
    ts = '2026-12-20 10:00:00'
    mock = lambda: {
        'ok': True,
        'vehicles': [_vehicle('45077045', 40.98, 28.89, ts)],
    }
    r1 = poll_once(mock, now=datetime(2026, 12, 20, 10, 1, 0))
    if r1['inserted'] == 1 and r1['vehicles_total'] == 1:
        ok('single_vehicle_insert')
    else:
        bad('single_vehicle_insert', str(r1))


def test_four_vehicles(db_path: str) -> None:
    print('FOUR_VEHICLES')
    from modules.planlama.arac_gps_poll_service import poll_once
    base = datetime(2026, 12, 20, 11, 0, 0)
    vehicles = [
        _vehicle('45077045', 40.984, 28.893, '2026-12-20 11:00:01'),
        _vehicle('45074345', 40.983, 28.726, '2026-12-20 11:00:02'),
        _vehicle('45077046', 38.444, 27.197, '2026-12-20 11:00:03'),
        _vehicle('43567534', 40.980, 28.707, '2026-12-20 11:00:04', stale=True),
    ]
    r = poll_once(lambda: {'ok': True, 'vehicles': vehicles}, now=base)
    if r['inserted'] == 4 and r['stale_marked'] == 1:
        ok('four_vehicle_insert')
    else:
        bad('four_vehicle_insert', str(r))


def test_dedup_and_new_timestamp(db_path: str) -> None:
    print('DEDUP')
    from modules.planlama.arac_gps_poll_service import poll_once
    from modules.planlama.arac_gps_snapshot_repo import count_gps_snapshots
    vid = '991DEDUP01'
    ts = '2026-12-20 12:00:00'
    v = _vehicle(vid, 40.984, 28.893, ts)
    now = datetime(2026, 12, 20, 12, 1, 0)
    before = count_gps_snapshots(vid)
    r1 = poll_once(lambda: {'ok': True, 'vehicles': [v]}, now=now)
    r2 = poll_once(lambda: {'ok': True, 'vehicles': [v]}, now=now + timedelta(seconds=30))
    if r1['inserted'] == 1 and r2['skipped_dedup'] == 1:
        ok('same_snapshot_dedup')
    else:
        bad('same_snapshot_dedup', f'{r1} {r2}')
    v2 = _vehicle(vid, 40.985, 28.894, '2026-12-20 12:05:00')
    r3 = poll_once(lambda: {'ok': True, 'vehicles': [v2]}, now=now + timedelta(minutes=5))
    cnt = count_gps_snapshots(vid)
    if r3['inserted'] == 1 and cnt == before + 2:
        ok('new_timestamp_new_row')
    else:
        bad('new_timestamp_new_row', f'{r3} cnt={cnt} before={before}')


def test_reject_invalid(db_path: str) -> None:
    print('REJECT')
    from modules.planlama.arac_gps_poll_service import poll_once, persist_vehicle_snapshot
    now = datetime(2026, 12, 20, 13, 0, 0)
    invalid_cases = [
        _vehicle('X1', 0.0, 0.0, '2026-12-20 13:00:00'),
        {**_vehicle('X2', 40.1, 29.1, ''), 'last_seen_at': ''},
        _vehicle('X3', 40.1, 29.1, '2099-01-01 00:00:00'),
    ]
    invalid_cases[0]['has_valid_location'] = False
    invalid_cases[0]['latitude'] = None
    invalid_cases[0]['longitude'] = None
    r = poll_once(lambda: {'ok': True, 'vehicles': invalid_cases}, now=now)
    if r['rejected'] == 3 and r['inserted'] == 0:
        ok('invalid_coordinates_and_timestamp_reject')
    else:
        bad('invalid_coordinates_and_timestamp_reject', str(r))
    null_speed = _vehicle('X4', 40.2, 29.2, '2026-12-20 13:01:00')
    null_speed['speed_kmh'] = None
    null_speed['total_distance_km'] = None
    out = persist_vehicle_snapshot(null_speed, now=now)
    if out['status'] == 'inserted':
        ok('null_speed_odometer_safe')
    else:
        bad('null_speed_odometer_safe', str(out))


def test_partial_failure(db_path: str) -> None:
    print('PARTIAL_FAILURE')
    from modules.planlama.arac_gps_poll_service import poll_once
    from modules.planlama.arac_gps_snapshot_repo import count_gps_snapshots
    now = datetime(2026, 12, 20, 14, 0, 0)
    mix = [
        _vehicle('45077045', 40.984, 28.893, '2026-12-20 14:00:01'),
        _vehicle('BAD1', 0, 0, '2026-12-20 14:00:02'),
    ]
    mix[1]['has_valid_location'] = False
    mix[1]['latitude'] = None
    mix[1]['longitude'] = None
    before = count_gps_snapshots()
    r = poll_once(lambda: {'ok': True, 'vehicles': mix}, now=now)
    after = count_gps_snapshots()
    if r['inserted'] == 1 and r['rejected'] == 1 and after == before + 1:
        ok('one_bad_one_good')
    else:
        bad('one_bad_one_good', str(r))


def test_fetch_error_no_write(db_path: str) -> None:
    print('FETCH_ERROR')
    from modules.planlama.arac_gps_poll_service import poll_once
    from modules.planlama.arac_gps_snapshot_repo import count_gps_snapshots
    before = count_gps_snapshots()
    r = poll_once(lambda: {
        'ok': False,
        'error': 'timeout',
        'error_category': 'timeout',
        'vehicles': [],
    })
    after = count_gps_snapshots()
    if not r['ok'] and before == after and r['inserted'] == 0:
        ok('api_error_no_db_write')
    else:
        bad('api_error_no_db_write', str(r))


def test_poll_once_idempotency(db_path: str) -> None:
    print('IDEMPOTENCY')
    from modules.planlama.arac_gps_poll_service import poll_once
    from modules.planlama.arac_gps_snapshot_repo import count_gps_snapshots
    vid = '991IDEM01'
    ts = '2026-12-20 15:00:00'
    payload = {'ok': True, 'vehicles': [_vehicle(vid, 40.984, 28.893, ts)]}
    now = datetime(2026, 12, 20, 15, 0, 30)
    before = count_gps_snapshots(vid)
    poll_once(lambda: payload, now=now)
    poll_once(lambda: payload, now=now + timedelta(seconds=10))
    poll_once(lambda: payload, now=now + timedelta(seconds=20))
    cnt = count_gps_snapshots(vid)
    if cnt == before + 1:
        ok('poll_once_idempotent_dedup')
    else:
        bad('poll_once_idempotent_dedup', f'cnt={cnt} before={before}')


def test_plan_rota_versioning(db_path: str) -> None:
    print('PLAN_ROTA')
    from modules.planlama.arac_plan_rota_snapshot_service import (
        get_applied_route_for_plan,
        get_route_version_for_plan,
        persist_plan_route_from_dto,
    )
    plan_id = _seed_plan(db_path)
    tasks_v1 = [
        {'id': 'pi1', 'order_no': 1, 'company_name': 'A', 'latitude': 40.1, 'longitude': 29.1},
        {'id': 'pi2', 'order_no': 2, 'company_name': 'B', 'latitude': 40.2, 'longitude': 29.2},
    ]
    route_v1 = {
        'status': 'OK',
        'current': {
            'provider': 'mock',
            'geometry': [[41.0, 29.0], [40.1, 29.1], [40.2, 29.2]],
            'distance_m': 12000.0,
            'duration_s': 1800.0,
            'order_labels': '1 → 2',
        },
    }
    s1 = persist_plan_route_from_dto(plan_id, route_v1, tasks_v1, created_at='2026-12-20 09:00:00')
    route_v2 = {
        'status': 'OK',
        'current': {
            'provider': 'mock',
            'geometry': [[41.0, 29.0], [40.2, 29.2], [40.1, 29.1]],
            'distance_m': 11500.0,
            'duration_s': 1700.0,
            'order_labels': '2 → 1',
        },
    }
    tasks_v2 = list(reversed(tasks_v1))
    s2 = persist_plan_route_from_dto(plan_id, route_v2, tasks_v2, created_at='2026-12-20 09:30:00')
    active = get_applied_route_for_plan(plan_id)
    old = get_route_version_for_plan(plan_id, 1)
    if s1 and s2 and s2['route_version'] == 2:
        ok('route_version_increment')
    else:
        bad('route_version_increment', f'{s1} {s2}')
    if active and active['route_version'] == 2:
        coords = active['geometry'].get('coordinates') if isinstance(active.get('geometry'), dict) else active.get('geometry')
        if coords and len(coords) >= 3:
            ok('active_route_is_latest')
        else:
            bad('active_route_is_latest', str(active))
    else:
        bad('active_route_is_latest', str(active))
    if old and old['is_active'] == 0:
        coords = old['geometry'].get('coordinates') if isinstance(old.get('geometry'), dict) else old.get('geometry')
        if coords and coords[1] == [29.1, 40.1]:
            ok('prior_route_geometry_preserved')
        else:
            bad('prior_route_geometry_preserved', str(old.get('geometry')))


def test_canonical_unchanged() -> None:
    print('CANONICAL_GUARD')
    if os.path.isfile(CANONICAL_DB):
        h = _canonical_hash()
        if h == CANONICAL_SHA:
            ok(f'canonical_hash={h[:16]}')
        else:
            bad('canonical_hash', h)
    else:
        ok('canonical_db_absent_skip')


def test_deviation_inputs_ready(db_path: str) -> None:
    print('DEVIATION_CONTRACT')
    from modules.planlama.arac_gps_snapshot_repo import list_gps_snapshots_ordered
    from modules.planlama.arac_plan_rota_snapshot_service import get_applied_route_for_plan
    plan_id = 1
    active = get_applied_route_for_plan(plan_id)
    points = list_gps_snapshots_ordered('45077045')
    ready = (
        active is not None
        and len(active.get('geometry') or []) >= 2
        and active.get('stop_order')
        and len(points) >= 1
        and all(p.get('gps_timestamp') for p in points)
    )
    if ready:
        ok('deviation_inputs_available')
    else:
        bad('deviation_inputs_available', f'active={bool(active)} pts={len(points)}')


def main() -> int:
    print('=' * 72)
    print('GPS P1 — Snapshot persistence + plan rota referansı')
    print('=' * 72)
    with temp_gps_db() as db_path:
        test_migration_and_integrity(db_path)
        test_single_insert(db_path)
        test_four_vehicles(db_path)
        test_dedup_and_new_timestamp(db_path)
        test_reject_invalid(db_path)
        test_partial_failure(db_path)
        test_fetch_error_no_write(db_path)
        test_poll_once_idempotency(db_path)
        test_plan_rota_versioning(db_path)
        test_deviation_inputs_ready(db_path)
    test_canonical_unchanged()
    print(f'\nTOTAL {PASS} pass / {FAIL} fail')
    return 0 if FAIL == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
