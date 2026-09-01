# -*- coding: utf-8 -*-
"""ATP Geofence A3 — real worker chain, replay, API readback, worker integration."""
from __future__ import annotations

import io
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

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
    item_from_today_ops,
    m_offset,
    plan_date_today,
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


def _setup_db() -> tuple[str, dict]:
    tmp = tempfile.mkdtemp(prefix='a3_int_')
    db = os.path.join(tmp, 'mock_data_geofence_a3.db')
    sqlite3.connect(db).close()
    run_migration_set(db)
    bind_temp_db_path(db)
    meta = seed_a3_plan(db)
    meta['db_path'] = db
    meta['tmpdir'] = tmp
    return db, meta


def test_worker_chain_calls_geofence() -> None:
    print('A3_CHAIN_POLL_GEOFENCE')
    db, meta = _setup_db()
    pd = meta['plan_date']
    lat, lng = meta['base_lat'], meta['base_lng']
    ts = f'{pd} 10:00:00'
    la, ln = m_offset(lat, lng, 450)
    r = poll_fixture(la, ln, ts)
    assert r.get('ok'), r
    gf = r.get('geofence') or {}
    if gf.get('processed', 0) >= 1:
        ok('poll_once_invokes_geofence')
    else:
        bad('poll_once_invokes_geofence', str(gf))
    v = visit_row(db, meta['plan_is_ids'][0])
    if v and v.get('state') == 'APPROACHING':
        ok('geofence_after_poll')
    else:
        bad('geofence_after_poll', str(v))


def test_duplicate_snapshot_skips_geofence() -> None:
    print('A3_DUP_SNAPSHOT')
    db, meta = _setup_db()
    pd, lat, lng = meta['plan_date'], meta['base_lat'], meta['base_lng']
    ts = f'{pd} 10:05:00'
    la, ln = m_offset(lat, lng, 450)
    r1 = poll_fixture(la, ln, ts)
    r2 = poll_fixture(la, ln, ts)
    if r1.get('inserted', 0) == 1 and r2.get('skipped_dedup', 0) == 1:
        ok('dedup_at_poll')
    else:
        bad('dedup_at_poll', f'{r1} {r2}')
    n = count_events(db, meta['plan_is_ids'][0], 'GEOFENCE_GIRIS')
    if n == 1:
        ok('no_duplicate_geofence_event')
    else:
        bad('no_duplicate_geofence_event', str(n))


def test_replay_r1_r9() -> None:
    print('A3_REPLAY_R1_R9')
    db, meta = _setup_db()
    pd = meta['plan_date']
    pid = meta['plan_is_ids'][0]
    lat, lng = meta['base_lat'], meta['base_lng']
    steps = [
        ('R1', 800, 'OUTSIDE', 0, 'GEOFENCE_GIRIS'),
        ('R2', 450, 'APPROACHING', 1, 'GEOFENCE_GIRIS'),
        ('R3', 430, 'APPROACHING', 1, 'GEOFENCE_GIRIS'),
        ('R4', 190, 'APPROACHING', 0, 'KONUMA_VARILDI'),
        ('R5', 180, 'ARRIVED', 1, 'KONUMA_VARILDI'),
        ('R6', 250, 'ARRIVED', 1, 'KONUMA_VARILDI'),
        ('R7', 310, 'ARRIVED', 0, 'KONUMDAN_AYRILDI'),
        ('R8', 320, 'DEPARTED_PENDING', 1, 'KONUMDAN_AYRILDI'),
        ('R9', 320, 'DEPARTED_PENDING', 1, 'KONUMDAN_AYRILDI'),
    ]
    base_min = 10
    last_ts = ''
    last_la = last_ln = 0.0
    for idx, (name, dist, exp_state, exp_ev, ev_type) in enumerate(steps):
        mm = base_min + idx
        ts = f'{pd} 10:{mm:02d}:00'
        la, ln = m_offset(lat, lng, dist)
        if name == 'R9':
            ts = last_ts
            la, ln = last_la, last_ln
        else:
            last_ts, last_la, last_ln = ts, la, ln
        poll_fixture(la, ln, ts)
        v = visit_row(db, pid)
        n = count_events(db, pid, ev_type)
        if v and v.get('state') == exp_state and n == exp_ev:
            ok(name)
        else:
            bad(name, f'state={v} {ev_type}={n}')
        api = item_from_today_ops(pd, pid)
        if api and api.get('visit_state') == exp_state:
            ok(f'{name}_api')
        else:
            bad(f'{name}_api', str(api))


def test_api_approaching_label() -> None:
    print('A3_API_APPROACHING')
    db, meta = _setup_db()
    pd, lat, lng = meta['plan_date'], meta['base_lat'], meta['base_lng']
    ts = f'{pd} 11:00:00'
    la, ln = m_offset(lat, lng, 450)
    poll_fixture(la, ln, ts)
    it = item_from_today_ops(pd, meta['plan_is_ids'][0])
    if it and it.get('visit_state') == 'APPROACHING':
        ok('api_visit_state')
    else:
        bad('api_visit_state', str(it))


def test_out_of_sequence_chain() -> None:
    print('A3_OOS_CHAIN')
    db, meta = _setup_db()
    pd = meta['plan_date']
    t2 = meta['plan_is_ids'][1]
    t2_lat, t2_lng = meta['coords'][1]
    ts1 = f'{pd} 12:00:00'
    ts2 = f'{pd} 12:01:00'
    la, ln = m_offset(t2_lat, t2_lng, 190)
    poll_fixture(la, ln, ts1)
    poll_fixture(la, ln, ts2)
    v2 = visit_row(db, t2)
    n_arr = count_events(db, t2, 'KONUMA_VARILDI')
    sira = sqlite3.connect(db).execute(
        'SELECT sira FROM arac_gunluk_plan_is WHERE id=?', (t2,),
    ).fetchone()[0]
    if (v2 is None or v2.get('state') in (None, 'OUTSIDE', 'APPROACHING')) and n_arr == 0 and sira == 2:
        ok('oos_block')
    else:
        bad('oos_block', f'v2={v2} arr={n_arr} sira={sira}')
    api = item_from_today_ops(pd, t2)
    if api and api.get('visit_state') not in ('ARRIVED', 'DEPARTED_PENDING'):
        ok('oos_api_not_arrived')
    else:
        bad('oos_api_not_arrived', str(api))


def test_complete_enables_task2() -> None:
    print('A3_COMPLETE_ENABLES_T2')
    db, meta = _setup_db()
    pd = meta['plan_date']
    from modules.planlama.arac_plan_change_service import apply_plan_job_change
    apply_plan_job_change(meta['plan_is_ids'][0], 1, {'action': 'complete', 'reason': 'a3 test'})
    t2 = meta['plan_is_ids'][1]
    t2_lat, t2_lng = meta['coords'][1]
    la, ln = m_offset(t2_lat, t2_lng, 450)
    poll_fixture(la, ln, f'{pd} 12:10:00')
    v = visit_row(db, t2)
    if v and v.get('state') == 'APPROACHING':
        ok('task2_approaching')
    else:
        bad('task2_approaching', str(v))
    la2, ln2 = m_offset(t2_lat, t2_lng, 180)
    poll_fixture(la2, ln2, f'{pd} 12:11:00')
    poll_fixture(la2, ln2, f'{pd} 12:12:00')
    v2 = visit_row(db, t2)
    if v2 and v2.get('state') == 'ARRIVED':
        ok('task2_arrived')
    else:
        bad('task2_arrived', str(v2))


def test_stale_31min_no_mutation() -> None:
    print('A3_STALE_31MIN')
    db, meta = _setup_db()
    pd, lat, lng = meta['plan_date'], meta['base_lat'], meta['base_lng']
    old = (datetime.now() - timedelta(minutes=31)).strftime('%Y-%m-%d %H:%M:%S')
    before = sqlite3.connect(db).execute('SELECT COUNT(*) FROM arac_plan_olay').fetchone()[0]
    poll_fixture(lat, lng, old, now=datetime.now())
    after = sqlite3.connect(db).execute('SELECT COUNT(*) FROM arac_plan_olay').fetchone()[0]
    if before == after:
        ok('stale_no_events')
    else:
        bad('stale_no_events', f'{before}->{after}')


def test_worker_exception_isolated() -> None:
    print('A3_WORKER_EXCEPTION_ISOLATED')
    db, meta = _setup_db()
    pd, lat, lng = meta['plan_date'], meta['base_lat'], meta['base_lng']
    from modules.planlama import arac_geofence_service as svc
    real = svc.process_gps_snapshot_for_geofence

    def boom(row, **kw):
        if str(row.get('arac_external_id')) == A3_VEHICLE:
            raise RuntimeError('forced_vehicle_fail')
        return real(row, **kw)

    ts = f'{pd} 13:00:00'
    la, ln = m_offset(lat, lng, 450)
    with patch.object(svc, 'process_gps_snapshot_for_geofence', side_effect=boom):
        r = poll_fixture(la, ln, ts)
    if r.get('ok'):
        ok('poll_survives_geofence_error')
    else:
        bad('poll_survives_geofence_error', str(r))


def test_rollback_via_poll() -> None:
    print('A3_ROLLBACK_POLL')
    db, meta = _setup_db()
    pd, lat, lng = meta['plan_date'], meta['base_lat'], meta['base_lng']
    pid = meta['plan_is_ids'][0]
    from modules.planlama import arac_geofence_service as svc
    from modules.planlama import arac_geofence_repo as repo
    real_insert = repo.insert_geofence_event_conn
    ts1 = f'{pd} 14:00:00'
    ts2 = f'{pd} 14:01:00'
    la, ln = m_offset(lat, lng, 190)
    poll_fixture(la, ln, ts1)

    def boom(con, **kwargs):
        if kwargs.get('olay_turu') == 'KONUMA_VARILDI':
            raise RuntimeError('forced')
        return real_insert(con, **kwargs)

    with patch.object(svc, 'insert_geofence_event_conn', side_effect=boom):
        poll_fixture(la, ln, ts2)
    v = visit_row(db, pid)
    n = count_events(db, pid, 'KONUMA_VARILDI')
    if (v is None or v.get('state') != 'ARRIVED') and n == 0:
        ok('rollback_after_poll')
    else:
        bad('rollback_after_poll', f'v={v} n={n}')


def test_nested_transaction_absent() -> None:
    print('A3_NESTED_TX')
    db, meta = _setup_db()
    pd, lat, lng = meta['plan_date'], meta['base_lat'], meta['base_lng']
    r = poll_fixture(*m_offset(lat, lng, 450), f'{pd} 15:00:00')
    gf = r.get('geofence') or {}
    err = str(gf.get('error') or '')
    if 'transaction' not in err.lower() and 'locked' not in err.lower():
        ok('no_nested_begin')
    else:
        bad('no_nested_begin', err)


def main() -> int:
    os.chdir(_APP)
    print('=' * 60)
    print('ATP GEOFENCE A3 INTEGRATION')
    if not (_APP / 'mock_data.db').is_file():
        ok('worktree_canonical_absent')
    test_worker_chain_calls_geofence()
    test_duplicate_snapshot_skips_geofence()
    test_replay_r1_r9()
    test_api_approaching_label()
    test_out_of_sequence_chain()
    test_complete_enables_task2()
    test_stale_31min_no_mutation()
    test_worker_exception_isolated()
    test_rollback_via_poll()
    test_nested_transaction_absent()
    print('=' * 60)
    print(f'RESULT {PASS}/{PASS + FAIL} PASS, {FAIL} FAIL')
    return 0 if FAIL == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
