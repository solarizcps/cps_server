# -*- coding: utf-8 -*-
"""ATP Geofence A3.1 — explicit out-of-order GPS snapshot guard evidence."""
from __future__ import annotations

import io
import json
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

_REPO = Path(__file__).resolve().parents[2]
_APP = _REPO / 'app'
_PLANLAMA_TESTS = Path(__file__).resolve().parent
for _p in (str(_APP), str(_PLANLAMA_TESTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ['CPS_TEST_DB_GUARD'] = '1'
from tools.atp_test_db_guard import bind_temp_db_path, install_atp_test_db_guard  # noqa: E402

install_atp_test_db_guard(str(_APP / 'mock_data.db'))

from atp_geofence_a3_common import (  # noqa: E402
    A3_VEHICLE,
    count_events,
    m_offset,
    poll_fixture,
    run_migration_set,
    seed_a3_plan,
    visit_row,
)

PASS = FAIL = 0


def ok(name: str) -> None:
    global PASS
    PASS += 1
    print(f'  PASS {name}')


def bad(name: str, detail: str = '') -> None:
    global FAIL
    FAIL += 1
    print(f'  FAIL {name} {detail}')


def _event_snapshot(db_path: str, plan_is_id: int) -> dict[str, int]:
    con = sqlite3.connect(db_path)
    rows = con.execute(
        """
        SELECT olay_turu, COUNT(*) c
        FROM arac_plan_olay
        WHERE plan_is_id=?
        GROUP BY olay_turu
        """,
        (plan_is_id,),
    ).fetchall()
    con.close()
    return {str(r[0]): int(r[1]) for r in rows}


def _insert_manual_snapshot(
    db_path: str,
    *,
    gps_timestamp: str,
    lat: float,
    lng: float,
) -> dict:
    from modules.planlama.arac_gps_poll_service import make_dedup_key
    from modules.planlama.arac_gps_snapshot_repo import get_gps_snapshot_by_id, insert_gps_snapshot

    received = gps_timestamp
    created = gps_timestamp
    dedup = make_dedup_key(gps_timestamp, lat, lng)
    status = insert_gps_snapshot({
        'arac_provider': 'TURKCELL_FILOM',
        'arac_external_id': A3_VEHICLE,
        'plate_snapshot': '34 A3 001',
        'gps_timestamp': gps_timestamp,
        'received_at': received,
        'latitude': lat,
        'longitude': lng,
        'speed_kmh': 30,
        'activity_status': 'HAREKETLI',
        'ignition_status': None,
        'odometer_km': None,
        'is_stale': False,
        'dedup_key': dedup,
        'created_at': created,
    })
    con = sqlite3.connect(db_path)
    row_id = con.execute(
        """
        SELECT id FROM arac_gps_snapshot
        WHERE arac_external_id=? AND gps_timestamp=?
        ORDER BY id DESC LIMIT 1
        """,
        (A3_VEHICLE, gps_timestamp),
    ).fetchone()[0]
    con.close()
    row = get_gps_snapshot_by_id(int(row_id))
    if status != 'inserted' or not row:
        raise RuntimeError(f'manual snapshot insert failed: {status} id={row_id}')
    return row


def test_out_of_order_gps_ignored_then_worker_continues() -> None:
    print('A3_1_OUT_OF_ORDER_GPS')
    tmp = tempfile.mkdtemp(prefix='a3_ooo_')
    db = os.path.join(tmp, 'mock_data_geofence_ooo.db')
    sqlite3.connect(db).close()
    run_migration_set(db)
    bind_temp_db_path(db)
    meta = seed_a3_plan(db)
    pd = meta['plan_date']
    lat, lng = meta['base_lat'], meta['base_lng']
    plan_is_id = meta['plan_is_ids'][0]

    ts_new = f'{pd} 10:10:00'
    ts_old = f'{pd} 10:05:00'
    ts_next = f'{pd} 10:20:00'
    la, ln = m_offset(lat, lng, 450.0)

    r_new = poll_fixture(la, ln, ts_new)
    if not r_new.get('ok'):
        bad('newer_snapshot_poll_ok', str(r_new))
        return
    ok('newer_snapshot_processed')

    before = visit_row(db, plan_is_id) or {}
    if before.get('state') != 'APPROACHING':
        bad('newer_snapshot_approaching', str(before))
        return
    ok('newer_snapshot_approaching')

    snap_before = {
        'state': before.get('state'),
        'consecutive_inside': before.get('consecutive_inside'),
        'consecutive_outside': before.get('consecutive_outside'),
        'arrived_at': before.get('arrived_at'),
        'departed_at': before.get('departed_at'),
        'last_gps_snapshot_id': before.get('last_gps_snapshot_id'),
    }
    events_before = _event_snapshot(db, plan_is_id)
    last_id_before = int(snap_before['last_gps_snapshot_id'] or 0)

    old_row = _insert_manual_snapshot(db, gps_timestamp=ts_old, lat=la, lng=ln)
    from modules.planlama.arac_geofence_service import process_gps_snapshot_for_geofence

    now_old = datetime.strptime(ts_old, '%Y-%m-%d %H:%M:%S') + timedelta(seconds=30)
    r_old = process_gps_snapshot_for_geofence(old_row, now=now_old)
    if r_old.get('skipped') is not True:
        bad('older_snapshot_skipped_flag', str(r_old))
    else:
        ok('older_snapshot_skipped_flag')

    after_old = visit_row(db, plan_is_id) or {}
    events_after_old = _event_snapshot(db, plan_is_id)

    unchanged = (
        after_old.get('state') == snap_before['state']
        and after_old.get('consecutive_inside') == snap_before['consecutive_inside']
        and after_old.get('consecutive_outside') == snap_before['consecutive_outside']
        and after_old.get('arrived_at') == snap_before['arrived_at']
        and after_old.get('departed_at') == snap_before['departed_at']
        and int(after_old.get('last_gps_snapshot_id') or 0) >= last_id_before
        and int(after_old.get('last_gps_snapshot_id') or 0) == last_id_before
        and events_after_old == events_before
    )
    if unchanged:
        ok('older_snapshot_no_state_mutation')
    else:
        bad(
            'older_snapshot_no_state_mutation',
            json.dumps({
                'before': snap_before,
                'after': {
                    k: after_old.get(k)
                    for k in (
                        'state', 'consecutive_inside', 'consecutive_outside',
                        'arrived_at', 'departed_at', 'last_gps_snapshot_id',
                    )
                },
                'events_before': events_before,
                'events_after': events_after_old,
            }, ensure_ascii=False),
        )

    for ev in ('GEOFENCE_GIRIS', 'KONUMA_VARILDI', 'KONUMDAN_AYRILDI'):
        if count_events(db, plan_is_id, ev) > events_before.get(ev, 0):
            bad(f'older_snapshot_no_{ev}', str(count_events(db, plan_is_id, ev)))
        else:
            ok(f'older_snapshot_no_{ev}')

    la_in, ln_in = m_offset(lat, lng, 50.0)
    r_next = poll_fixture(la_in, ln_in, ts_next)
    if not r_new.get('ok'):
        bad('next_snapshot_poll_ok', str(r_next))
    else:
        ok('next_snapshot_poll_ok')

    after_next = visit_row(db, plan_is_id) or {}
    if after_next.get('state') in ('ARRIVED', 'INSIDE') or after_next.get('arrived_at'):
        ok('worker_continues_after_out_of_order')
    else:
        bad('worker_continues_after_out_of_order', str(after_next))

    if int(after_next.get('last_gps_snapshot_id') or 0) > last_id_before:
        ok('last_gps_snapshot_id_advances_after_valid_snapshot')
    else:
        bad(
            'last_gps_snapshot_id_advances_after_valid_snapshot',
            f"before={last_id_before} after={after_next.get('last_gps_snapshot_id')}",
        )


def main() -> int:
    print('ATP_GEOFENCE_A3_1_OUT_OF_ORDER')
    test_out_of_order_gps_ignored_then_worker_continues()
    print(f'OUT_OF_ORDER: {PASS} PASS / {FAIL} FAIL / {PASS + FAIL} total')
    print(f'OUT_OF_ORDER_RESULT={"PASS" if FAIL == 0 else "FAIL"}')
    return 0 if FAIL == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
