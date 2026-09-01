# -*- coding: utf-8 -*-
"""ATP Geofence A2 — APPROACHING, order block, EXIT 300m, atomic transaction."""
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
from pathlib import Path
from unittest.mock import patch

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

_REPO = Path(__file__).resolve().parents[2]
_APP = _REPO / 'app'
_PLANLAMA_TESTS = Path(__file__).resolve().parent
CANONICAL_PATH = _APP / 'mock_data.db'
CANONICAL_SHA = (
    hashlib.sha256(CANONICAL_PATH.read_bytes()).hexdigest()
    if CANONICAL_PATH.is_file() else ''
)
for _p in (str(_APP), str(_PLANLAMA_TESTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ.setdefault('CPS_TEST_DB_GUARD', '1')
from tools.atp_test_db_guard import install_atp_test_db_guard  # noqa: E402

install_atp_test_db_guard(str(CANONICAL_PATH))

FIXED_NOW = datetime(2026, 12, 20, 12, 0, 0)
PASS = FAIL = 0


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
        filename, _APP / 'migrations' / filename,
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.run(db_path)


def _m_offset(lat: float, lng: float, meters: float) -> tuple[float, float]:
    return lat + (meters / 111320.0), lng


def _run_migration_set(db_path: str) -> None:
    for mig in (
        '176_arac_takip_v13.py', '177_arac_operasyon_ayar.py',
        '178_arac_is_talebi_ux_v2_fields.py', '179_arac_gps_snapshot_p1.py',
        '180_arac_plan_ziyaret_durum.py',
    ):
        _run_migration(db_path, mig)


@contextmanager
def temp_a2_db(*, stops: int = 1, second_offset_m: float = 800.0):
    tmpdir = tempfile.mkdtemp(prefix='gps_a2_')
    db_path = os.path.join(tmpdir, 'gps_a2.db')
    _run_migration_set(db_path)
    con = sqlite3.connect(db_path)
    now = '2026-12-20 08:00:00'
    lat, lng = 40.9900, 28.8900
    con.execute(
        """
        INSERT INTO arac_operasyon_ayar (
            base_name, base_latitude, base_longitude, base_address, base_maps_url,
            aktif, created_at, updated_at, updated_by
        ) VALUES ('Base',41.0,29.0,'Adres','https://maps.google.com/?q=41,29',1,?,?,1)
        """,
        (now, now),
    )
    con.execute(
        """
        INSERT INTO arac_gunluk_plan (
            plan_tarihi, arac_provider, arac_external_id, arac_plaka_snapshot,
            sofor_id, sofor_adi_snapshot, durum, created_at, created_by, updated_at, updated_by
        ) VALUES ('2026-12-20','TURKCELL_FILOM','V1','34 MOR 049',1,'Oktay','AKTIF',?,?,?,?)
        """,
        (now, 1, now, 1),
    )
    plan_id = int(con.execute('SELECT last_insert_rowid()').fetchone()[0])
    plan_is_ids: list[int] = []
    coords: list[tuple[float, float]] = [(lat, lng)]
    for s in range(stops):
        if s == 0:
            slat, slng = lat, lng
        else:
            slat, slng = _m_offset(lat, lng, second_offset_m)
            coords.append((slat, slng))
        con.execute(
            """
            INSERT INTO arac_is_talebi (
                talep_no, talep_eden_user_id, talep_eden_adi_snapshot, talep_tarihi,
                firma_adi, adres, yapilacak_is, oncelik, durum,
                latitude, longitude, created_at, created_by, updated_at, updated_by
            ) VALUES (?,1,'Test','2026-12-20',?,?,?,'NORMAL','PLANA_ALINDI',?,?,?,?,?,?)
            """,
            (f'A2-{s+1}', f'Firma {s+1}', f'Adres {s+1}', f'Is {s+1}', slat, slng, now, 1, now, 1),
        )
        tid = int(con.execute('SELECT last_insert_rowid()').fetchone()[0])
        con.execute(
            """
            INSERT INTO arac_gunluk_plan_is (
                plan_id, is_talebi_id, sira, planlanan_saat, durum, created_at, created_by
            ) VALUES (?,?,?,?,'PLANLANDI',?,?)
            """,
            (plan_id, tid, s + 1, f'0{9+s}:30', now, 1),
        )
        plan_is_ids.append(int(con.execute('SELECT last_insert_rowid()').fetchone()[0]))
    con.commit()
    con.close()
    import config
    with patch.object(config.Config, 'MOCK_DB_PATH', db_path):
        if CANONICAL_PATH.is_file():
            bad('canonical_guard', f'unexpected canonical db at {CANONICAL_PATH}')
        yield db_path, plan_id, plan_is_ids, lat, lng, coords


def _snap(con, vid, ts, lat, lng, *, stale=0):
    from modules.planlama.arac_gps_poll_service import make_dedup_key
    dk = make_dedup_key(ts, lat, lng)
    con.execute(
        """
        INSERT INTO arac_gps_snapshot (
            arac_provider, arac_external_id, plate_snapshot, gps_timestamp, received_at,
            latitude, longitude, speed_kmh, is_stale, dedup_key, created_at
        ) VALUES ('TURKCELL_FILOM',?,?,?,?,?,?,?,?,?,?)
        """,
        (vid, '34 MOR 049', ts, ts, lat, lng, 30, stale, dk, ts),
    )
    return int(con.execute('SELECT last_insert_rowid()').fetchone()[0])


def _row(con, sid):
    con.row_factory = sqlite3.Row
    return dict(con.execute('SELECT * FROM arac_gps_snapshot WHERE id=?', (sid,)).fetchone())


def _process(db_path, lat, lng, ts, *, stale=0):
    from modules.planlama.arac_geofence_service import process_gps_snapshot_for_geofence
    ts_dt = datetime.strptime(ts, '%Y-%m-%d %H:%M:%S')
    now = ts_dt + timedelta(seconds=30)
    con = sqlite3.connect(db_path)
    sid = _snap(con, 'V1', ts, lat, lng, stale=stale)
    con.commit()
    row = _row(con, sid)
    con.close()
    return process_gps_snapshot_for_geofence(row, now=now)


def _visit(db_path, plan_is_id):
    from modules.planlama.arac_geofence_repo import get_visit_state
    return get_visit_state(plan_is_id)


def _count_events(db_path, plan_is_id, olay_turu):
    return sqlite3.connect(db_path).execute(
        'SELECT COUNT(*) FROM arac_plan_olay WHERE plan_is_id=? AND olay_turu=?',
        (plan_is_id, olay_turu),
    ).fetchone()[0]


def _count_meta_kind(db_path, plan_is_id, kind):
    import json
    rows = sqlite3.connect(db_path).execute(
        "SELECT metadata_json FROM arac_plan_olay WHERE plan_is_id=? AND olay_turu='NOT'",
        (plan_is_id,),
    ).fetchall()
    n = 0
    for (raw,) in rows:
        try:
            meta = json.loads(raw or '{}')
        except (TypeError, ValueError):
            meta = {}
        if meta.get('geofence_kind') == kind:
            n += 1
    return n


def test_gf01_outside_600m(db_path, plan_is_ids, lat, lng) -> None:
    print('GF01')
    la, ln = _m_offset(lat, lng, 600)
    _process(db_path, la, ln, '2026-12-20 10:00:00')
    v = _visit(db_path, plan_is_ids[0])
    if v is None or v.get('state') in (None, 'OUTSIDE'):
        ok('GF01')
    else:
        bad('GF01', str(v))


def test_gf02_approaching(db_path, plan_is_ids, lat, lng) -> None:
    print('GF02')
    la, ln = _m_offset(lat, lng, 450)
    _process(db_path, la, ln, '2026-12-20 10:05:00')
    v = _visit(db_path, plan_is_ids[0])
    n = _count_events(db_path, plan_is_ids[0], 'GEOFENCE_GIRIS')
    if v and v.get('state') == 'APPROACHING' and n == 1:
        ok('GF02')
    else:
        bad('GF02', f'state={v} events={n}')


def test_gf03_no_duplicate_approaching(db_path, plan_is_ids, lat, lng) -> None:
    print('GF03')
    la, ln = _m_offset(lat, lng, 450)
    _process(db_path, la, ln, '2026-12-20 10:06:00')
    n = _count_events(db_path, plan_is_ids[0], 'GEOFENCE_GIRIS')
    if n == 1:
        ok('GF03')
    else:
        bad('GF03', f'events={n}')


def test_gf04_first_inside_no_arrived(db_path, plan_is_ids, lat, lng) -> None:
    print('GF04')
    la, ln = _m_offset(lat, lng, 190)
    _process(db_path, la, ln, '2026-12-20 10:10:00')
    v = _visit(db_path, plan_is_ids[0])
    n = _count_events(db_path, plan_is_ids[0], 'KONUMA_VARILDI')
    if v and v.get('state') != 'ARRIVED' and n == 0:
        ok('GF04')
    else:
        bad('GF04', f'state={v} events={n}')


def test_gf05_two_point_arrived(db_path, plan_is_ids, lat, lng) -> None:
    print('GF05')
    la, ln = _m_offset(lat, lng, 180)
    _process(db_path, la, ln, '2026-12-20 10:11:00')
    v = _visit(db_path, plan_is_ids[0])
    n = _count_events(db_path, plan_is_ids[0], 'KONUMA_VARILDI')
    if v and v.get('state') == 'ARRIVED' and n == 1:
        ok('GF05')
    else:
        bad('GF05', f'state={v} events={n}')


def test_gf06_direct_arrived(db_path, plan_id, lat, lng) -> None:
    print('GF06')
    with temp_a2_db(stops=1) as (db2, pid, pids, la, ln, _):
        ts_dt = datetime.strptime('2026-12-20 11:00:00', '%Y-%m-%d %H:%M:%S')
        now = ts_dt + timedelta(seconds=30)
        a1, b1 = _m_offset(la, ln, 190)
        _process(db2, a1, b1, '2026-12-20 11:00:00')
        a2, b2 = _m_offset(la, ln, 180)
        _process(db2, a2, b2, '2026-12-20 11:01:00')
        v = _visit(db2, pids[0])
        if v and v.get('state') == 'ARRIVED':
            ok('GF06')
        else:
            bad('GF06', str(v))


def test_gf07_arrived_hysteresis_band(db_path, plan_is_ids, lat, lng) -> None:
    print('GF07')
    la, ln = _m_offset(lat, lng, 250)
    _process(db_path, la, ln, '2026-12-20 10:20:00')
    v = _visit(db_path, plan_is_ids[0])
    if v and v.get('state') == 'ARRIVED':
        ok('GF07')
    else:
        bad('GF07', str(v))


def test_gf08_depart_first_outside(db_path, plan_is_ids, lat, lng) -> None:
    print('GF08')
    la, ln = _m_offset(lat, lng, 310)
    _process(db_path, la, ln, '2026-12-20 10:21:00')
    v = _visit(db_path, plan_is_ids[0])
    n = _count_events(db_path, plan_is_ids[0], 'KONUMDAN_AYRILDI')
    if v and v.get('state') == 'ARRIVED' and n == 0:
        ok('GF08')
    else:
        bad('GF08', f'state={v} depart={n}')


def test_gf09_depart_two_outside(db_path, plan_is_ids, lat, lng) -> None:
    print('GF09')
    la, ln = _m_offset(lat, lng, 320)
    _process(db_path, la, ln, '2026-12-20 10:22:00')
    v = _visit(db_path, plan_is_ids[0])
    n = _count_events(db_path, plan_is_ids[0], 'KONUMDAN_AYRILDI')
    if v and v.get('state') == 'DEPARTED_PENDING' and n == 1:
        ok('GF09')
    else:
        bad('GF09', f'state={v} depart={n}')


def test_gf10_outside_counter_reset(db_path, plan_is_ids, lat, lng) -> None:
    print('GF10')
    with temp_a2_db(stops=1) as (db2, _pid, pids, la, ln, _):
        a, b = _m_offset(la, ln, 180)
        _process(db2, a, b, '2026-12-20 10:10:00')
        _process(db2, a, b, '2026-12-20 10:11:00')
        la1, ln1 = _m_offset(la, ln, 310)
        _process(db2, la1, ln1, '2026-12-20 10:12:00')
        v1 = _visit(db2, pids[0])
        la2, ln2 = _m_offset(la, ln, 280)
        _process(db2, la2, ln2, '2026-12-20 10:13:00')
        v2 = _visit(db2, pids[0])
        if v1 and v2 and v2.get('consecutive_outside', 99) == 0 and v2.get('state') == 'ARRIVED':
            ok('GF10')
        else:
            bad('GF10', f'v1={v1} v2={v2}')


def test_gf11_stale_31min(db_path, plan_is_ids, lat, lng) -> None:
    print('GF11')
    with temp_a2_db(stops=1) as (db2, pid, pids, la, ln, _):
        from modules.planlama.arac_geofence_service import process_gps_snapshot_for_geofence
        old_ts = (datetime.now() - timedelta(minutes=31)).strftime('%Y-%m-%d %H:%M:%S')
        row = {
            'id': 99999, 'arac_external_id': 'V1',
            'latitude': la, 'longitude': ln,
            'gps_timestamp': old_ts, 'is_stale': False,
        }
        before = sqlite3.connect(db2).execute('SELECT COUNT(*) FROM arac_plan_olay').fetchone()[0]
        process_gps_snapshot_for_geofence(row, now=datetime.now())
        after = sqlite3.connect(db2).execute('SELECT COUNT(*) FROM arac_plan_olay').fetchone()[0]
        if before == after:
            ok('GF11')
        else:
            bad('GF11', f'events {before}->{after}')


def test_gf12_order_block(db_path, plan_id, plan_is_ids, coords) -> None:
    print('GF12')
    with temp_a2_db(stops=2, second_offset_m=800.0) as (db2, pid, pids, la, ln, cs):
        second_lat, second_lng = cs[1]
        s_lat, s_lng = _m_offset(second_lat, second_lng, 190)
        _process(db2, s_lat, s_lng, '2026-12-20 12:00:00')
        v2 = _visit(db2, pids[1])
        n_arr = _count_events(db2, pids[1], 'KONUMA_VARILDI')
        n_oos = _count_meta_kind(db2, pids[1], 'OUT_OF_SEQUENCE_GEOFENCE')
        if (v2 is None or v2.get('state') in (None, 'OUTSIDE')) and n_arr == 0 and n_oos >= 1:
            ok('GF12')
        else:
            bad('GF12', f'v2={v2} arr={n_arr} oos={n_oos}')


def test_gf14_complete_enables_second(db_path) -> None:
    print('GF14')
    with temp_a2_db(stops=2, second_offset_m=800.0) as (db2, pid, pids, la, ln, cs):
        from modules.planlama.arac_plan_change_service import apply_plan_job_change
        con = sqlite3.connect(db2)
        con.execute(
            'UPDATE arac_gunluk_plan_is SET durum=? WHERE id=?',
            ('BASLADI', pids[0]),
        )
        con.commit()
        con.close()
        apply_plan_job_change(pids[0], 1, {'action': 'complete', 'reason': 'test'})
        second_lat, second_lng = cs[1]
        s_lat, s_lng = _m_offset(second_lat, second_lng, 180)
        _process(db2, s_lat, s_lng, '2026-12-20 12:05:00')
        _process(db2, s_lat, s_lng, '2026-12-20 12:06:00')
        v2 = _visit(db2, pids[1])
        if v2 and v2.get('state') == 'ARRIVED':
            ok('GF14')
        else:
            bad('GF14', str(v2))


def test_gf15_ambiguous_same_coord(db_path) -> None:
    print('GF15')
    with temp_a2_db(stops=2, second_offset_m=0.0) as (db2, pid, pids, la, ln, _):
        inside_lat, inside_lng = _m_offset(la, ln, 50)
        _process(db2, inside_lat, inside_lng, '2026-12-20 13:00:00')
        n_amb = sqlite3.connect(db2).execute(
            "SELECT COUNT(*) FROM arac_plan_olay WHERE olay_turu='AMBIGUOUS_STOP'",
        ).fetchone()[0]
        n_arr = _count_events(db2, pids[0], 'KONUMA_VARILDI') + _count_events(db2, pids[1], 'KONUMA_VARILDI')
        if n_amb >= 1 and n_arr == 0:
            ok('GF15')
        else:
            bad('GF15', f'amb={n_amb} arr={n_arr}')


def test_gf16_duplicate_snapshot(db_path, plan_is_ids, lat, lng) -> None:
    print('GF16')
    from modules.planlama.arac_geofence_service import process_gps_snapshot_for_geofence
    con = sqlite3.connect(db_path)
    la, ln = _m_offset(lat, lng, 180)
    sid = _snap(con, 'V1', '2026-12-20 14:00:00', la, ln)
    con.commit()
    row = _row(con, sid)
    con.close()
    ts_dt = datetime.strptime('2026-12-20 14:00:00', '%Y-%m-%d %H:%M:%S')
    now = ts_dt + timedelta(seconds=30)
    process_gps_snapshot_for_geofence(row, now=now)
    n1 = sqlite3.connect(db_path).execute(
        'SELECT COUNT(*) FROM arac_plan_olay WHERE plan_is_id=?', (plan_is_ids[0],),
    ).fetchone()[0]
    process_gps_snapshot_for_geofence(row, now=now)
    n2 = sqlite3.connect(db_path).execute(
        'SELECT COUNT(*) FROM arac_plan_olay WHERE plan_is_id=?', (plan_is_ids[0],),
    ).fetchone()[0]
    if n2 == n1:
        ok('GF16')
    else:
        bad('GF16', f'{n1}->{n2}')


def test_gf17_restart_recovery(db_path, plan_is_ids, lat, lng) -> None:
    print('GF17')
    with temp_a2_db(stops=1) as (db2, _pid, pids, la, ln, _):
        a, b = _m_offset(la, ln, 180)
        _process(db2, a, b, '2026-12-20 10:10:00')
        _process(db2, a, b, '2026-12-20 10:11:00')
        v0 = _visit(db2, pids[0])
        n0 = _count_events(db2, pids[0], 'KONUMA_VARILDI')
        la250, ln250 = _m_offset(la, ln, 250)
        _process(db2, la250, ln250, '2026-12-20 10:12:00')
        v1 = _visit(db2, pids[0])
        n1 = _count_events(db2, pids[0], 'KONUMA_VARILDI')
        if v0 and v1 and v0.get('state') == 'ARRIVED' and v1.get('state') == 'ARRIVED' and n0 == 1 and n1 == 1:
            ok('GF17')
        else:
            bad('GF17', f'v0={v0} v1={v1} n={n1}')


def test_gf18_no_auto_complete(db_path, plan_is_ids) -> None:
    print('GF18')
    st = sqlite3.connect(db_path).execute(
        'SELECT durum FROM arac_gunluk_plan_is WHERE id=?', (plan_is_ids[0],),
    ).fetchone()[0]
    if st != 'TAMAMLANDI':
        ok('GF18')
    else:
        bad('GF18', st)


def test_gf19_event_insert_rollback(db_path, plan_id, lat, lng) -> None:
    print('GF19')
    from modules.planlama import arac_geofence_repo as repo
    from modules.planlama import arac_geofence_service as svc
    with temp_a2_db(stops=1) as (db2, pid, pids, la, ln, _):
        real_insert = repo.insert_geofence_event_conn
        calls = {'n': 0}

        def boom(con, **kwargs):
            calls['n'] += 1
            if kwargs.get('olay_turu') == 'KONUMA_VARILDI':
                raise RuntimeError('forced_event_fail')
            return real_insert(con, **kwargs)

        con = sqlite3.connect(db2)
        a1, b1 = _m_offset(la, ln, 180)
        ts1 = '2026-12-20 15:00:00'
        ts2 = '2026-12-20 15:01:00'
        sid1 = _snap(con, 'V1', ts1, a1, b1)
        sid2 = _snap(con, 'V1', ts2, a1 + 0.00001, b1 + 0.00001)
        con.commit()
        rows = [_row(con, sid1), _row(con, sid2)]
        con.close()
        now1 = datetime.strptime(ts1, '%Y-%m-%d %H:%M:%S') + timedelta(seconds=30)
        now2 = datetime.strptime(ts2, '%Y-%m-%d %H:%M:%S') + timedelta(seconds=30)
        svc.process_gps_snapshot_for_geofence(rows[0], now=now1)
        with patch.object(svc, 'insert_geofence_event_conn', side_effect=boom):
            try:
                svc.process_gps_snapshot_for_geofence(rows[1], now=now2)
            except RuntimeError:
                pass
        v = _visit(db2, pids[0])
        n = _count_events(db2, pids[0], 'KONUMA_VARILDI')
        if v and v.get('state') != 'ARRIVED' and n == 0:
            ok('GF19')
        else:
            bad('GF19', f'state={v} events={n}')


def test_gf13_oos_no_arrived_at(db_path) -> None:
    print('GF13')
    with temp_a2_db(stops=2, second_offset_m=800.0) as (db2, _pid, pids, la, ln, cs):
        second_lat, second_lng = cs[1]
        s_lat, s_lng = _m_offset(second_lat, second_lng, 180)
        _process(db2, s_lat, s_lng, '2026-12-20 12:10:00')
        _process(db2, s_lat, s_lng, '2026-12-20 12:11:00')
        v2 = _visit(db2, pids[1])
        row = sqlite3.connect(db2).execute(
            'SELECT arrived_at FROM arac_plan_is_ziyaret_durum WHERE plan_is_id=?', (pids[1],),
        ).fetchone()
        arrived_at = row[0] if row else None
        n_arr = _count_events(db2, pids[1], 'KONUMA_VARILDI')
        if (v2 is None or v2.get('state') in (None, 'OUTSIDE', 'APPROACHING')) and arrived_at is None and n_arr == 0:
            ok('GF13')
        else:
            bad('GF13', f'v2={v2} arrived_at={arrived_at} n={n_arr}')


def test_gf20_visit_update_rollback(db_path, plan_id, lat, lng) -> None:
    print('GF20')
    from modules.planlama import arac_geofence_repo as repo
    from modules.planlama import arac_geofence_service as svc
    with temp_a2_db(stops=1) as (db2, _pid, pids, la, ln, _):
        real_upsert = repo.upsert_visit_state_conn

        def boom_upsert(con, row):
            if row.get('state') == 'ARRIVED':
                raise RuntimeError('forced_upsert_fail')
            return real_upsert(con, row)

        con = sqlite3.connect(db2)
        a1, b1 = _m_offset(la, ln, 180)
        ts1 = '2026-12-20 15:30:00'
        ts2 = '2026-12-20 15:31:00'
        sid1 = _snap(con, 'V1', ts1, a1, b1)
        sid2 = _snap(con, 'V1', ts2, a1 + 0.00001, b1 + 0.00001)
        con.commit()
        rows = [_row(con, sid1), _row(con, sid2)]
        con.close()
        now1 = datetime.strptime(ts1, '%Y-%m-%d %H:%M:%S') + timedelta(seconds=30)
        now2 = datetime.strptime(ts2, '%Y-%m-%d %H:%M:%S') + timedelta(seconds=30)
        svc.process_gps_snapshot_for_geofence(rows[0], now=now1)
        with patch.object(svc, 'upsert_visit_state_conn', side_effect=boom_upsert):
            try:
                svc.process_gps_snapshot_for_geofence(rows[1], now=now2)
            except RuntimeError:
                pass
        v = _visit(db2, pids[0])
        n = _count_events(db2, pids[0], 'KONUMA_VARILDI')
        if (v is None or v.get('state') != 'ARRIVED') and n == 0:
            ok('GF20')
        else:
            bad('GF20', f'state={v} events={n}')


def test_gf22_completed_task_skipped(db_path) -> None:
    print('GF22')
    with temp_a2_db(stops=2, second_offset_m=800.0) as (db2, _pid, pids, la, ln, cs):
        con = sqlite3.connect(db2)
        con.execute(
            'UPDATE arac_gunluk_plan_is SET durum=? WHERE id=?',
            ('TAMAMLANDI', pids[0]),
        )
        con.commit()
        con.close()
        second_lat, second_lng = cs[1]
        s_lat, s_lng = _m_offset(second_lat, second_lng, 180)
        _process(db2, s_lat, s_lng, '2026-12-20 12:20:00')
        _process(db2, s_lat, s_lng, '2026-12-20 12:21:00')
        v1 = _visit(db2, pids[0])
        v2 = _visit(db2, pids[1])
        if (v1 is None or v1.get('state') in (None, 'OUTSIDE')) and v2 and v2.get('state') == 'ARRIVED':
            ok('GF22')
        else:
            bad('GF22', f'v1={v1} v2={v2}')


def test_gf23_wrong_plan_date(db_path, lat, lng) -> None:
    print('GF23')
    from modules.planlama.arac_geofence_service import process_gps_snapshot_for_geofence
    with temp_a2_db(stops=1) as (db2, _pid, pids, la, ln, _):
        row = {
            'id': 7777, 'arac_external_id': 'V1',
            'latitude': la, 'longitude': ln,
            'gps_timestamp': '2026-12-21 10:00:00', 'is_stale': False,
        }
        now = datetime.strptime(row['gps_timestamp'], '%Y-%m-%d %H:%M:%S') + timedelta(seconds=30)
        before = sqlite3.connect(db2).execute('SELECT COUNT(*) FROM arac_plan_is_ziyaret_durum').fetchone()[0]
        r = process_gps_snapshot_for_geofence(row, now=now)
        after = sqlite3.connect(db2).execute('SELECT COUNT(*) FROM arac_plan_is_ziyaret_durum').fetchone()[0]
        if r.get('skipped') and after == before:
            ok('GF23')
        else:
            bad('GF23', f'r={r} visits {before}->{after}')


def test_gf26_u_policy_regression() -> None:
    print('GF26')
    from modules.planlama.arac_route_order_policy import (
        can_move_task,
        classify_order_tasks,
        compute_first_safe_insert_index,
        validate_manual_reorder,
    )
    tasks = [
        {'id': 'a', 'status': 'PLANLANDI', 'visit_state': 'OUTSIDE'},
        {'id': 'b', 'status': 'PLANLANDI', 'visit_state': 'OUTSIDE'},
        {'id': 'c', 'status': 'PLANLANDI', 'visit_state': 'OUTSIDE'},
    ]
    ok1 = validate_manual_reorder(tasks, ['a', 'b', 'c']) == ['a', 'b', 'c']
    locked = [
        {'id': 'a', 'status': 'BASLADI', 'visit_state': 'ARRIVED'},
        {'id': 'b', 'status': 'PLANLANDI', 'visit_state': 'OUTSIDE'},
    ]
    ok2 = can_move_task(locked[0]) is False
    ok3 = compute_first_safe_insert_index(locked) == 1
    if ok1 and ok2 and ok3:
        ok('GF26')
    else:
        bad('GF26', f'ok1={ok1} ok2={ok2} ok3={ok3}')


def test_gf21_order_unchanged(db_path, plan_is_ids) -> None:
    print('GF21')
    rows = sqlite3.connect(db_path).execute(
        'SELECT id, sira FROM arac_gunluk_plan_is ORDER BY sira',
    ).fetchall()
    if len(rows) >= 1 and rows[0][1] == 1:
        ok('GF21')
    else:
        bad('GF21', str(rows))


def test_gf24_no_plan(db_path, lat, lng) -> None:
    print('GF24')
    from modules.planlama.arac_geofence_service import process_gps_snapshot_for_geofence
    row = {
        'id': 1, 'arac_external_id': 'NOPLAN',
        'latitude': lat, 'longitude': lng,
        'gps_timestamp': '2026-12-20 16:00:00', 'is_stale': False,
    }
    now = datetime.strptime('2026-12-20 16:00:00', '%Y-%m-%d %H:%M:%S') + timedelta(seconds=30)
    r = process_gps_snapshot_for_geofence(row, now=now)
    if r.get('skipped') and r.get('reason') == 'no_active_plan':
        ok('GF24')
    else:
        bad('GF24', str(r))


def test_gf25_input_immutable(db_path, lat, lng) -> None:
    print('GF25')
    from modules.planlama.arac_geofence_service import process_gps_snapshot_for_geofence
    row = {
        'id': 8888, 'arac_external_id': 'V1',
        'latitude': lat, 'longitude': lng,
        'gps_timestamp': '2026-12-20 16:30:00', 'is_stale': False,
    }
    snap = dict(row)
    now = datetime.strptime(row['gps_timestamp'], '%Y-%m-%d %H:%M:%S') + timedelta(seconds=30)
    process_gps_snapshot_for_geofence(row, now=now)
    if row == snap:
        ok('GF25')
    else:
        bad('GF25', 'row mutated')


def test_canonical_unchanged() -> None:
    print('CANONICAL_GUARD')
    if not CANONICAL_SHA:
        ok('canonical_skip')
        return
    if CANONICAL_PATH.is_file():
        h = hashlib.sha256(CANONICAL_PATH.read_bytes()).hexdigest()
        if h == CANONICAL_SHA:
            ok('canonical_unchanged')
        else:
            bad('canonical_unchanged', 'hash mismatch')
    else:
        ok('canonical_absent_ok')


def main() -> int:
    os.chdir(_APP)
    print('=' * 60)
    print('ATP GEOFENCE A2 TEST SUITE')
    test_canonical_unchanged()
    with temp_a2_db(stops=1) as (db_path, plan_id, plan_is_ids, lat, lng, coords):
        test_gf01_outside_600m(db_path, plan_is_ids, lat, lng)
        test_gf02_approaching(db_path, plan_is_ids, lat, lng)
        test_gf03_no_duplicate_approaching(db_path, plan_is_ids, lat, lng)
        test_gf04_first_inside_no_arrived(db_path, plan_is_ids, lat, lng)
        test_gf05_two_point_arrived(db_path, plan_is_ids, lat, lng)
        test_gf06_direct_arrived(db_path, plan_id, lat, lng)
        test_gf07_arrived_hysteresis_band(db_path, plan_is_ids, lat, lng)
        test_gf08_depart_first_outside(db_path, plan_is_ids, lat, lng)
        test_gf09_depart_two_outside(db_path, plan_is_ids, lat, lng)
        test_gf10_outside_counter_reset(db_path, plan_is_ids, lat, lng)
        test_gf11_stale_31min(db_path, plan_is_ids, lat, lng)
        test_gf12_order_block(db_path, plan_id, plan_is_ids, coords)
        test_gf13_oos_no_arrived_at(db_path)
        test_gf14_complete_enables_second(db_path)
        test_gf15_ambiguous_same_coord(db_path)
        test_gf16_duplicate_snapshot(db_path, plan_is_ids, lat, lng)
        test_gf17_restart_recovery(db_path, plan_is_ids, lat, lng)
        test_gf18_no_auto_complete(db_path, plan_is_ids)
        test_gf19_event_insert_rollback(db_path, plan_id, lat, lng)
        test_gf20_visit_update_rollback(db_path, plan_id, lat, lng)
        test_gf22_completed_task_skipped(db_path)
        test_gf23_wrong_plan_date(db_path, lat, lng)
        test_gf21_order_unchanged(db_path, plan_is_ids)
        test_gf24_no_plan(db_path, lat, lng)
        test_gf25_input_immutable(db_path, lat, lng)
    test_gf26_u_policy_regression()
    test_canonical_unchanged()
    print('=' * 60)
    print(f'RESULT {PASS}/{PASS + FAIL} PASS, {FAIL} FAIL')
    return 0 if FAIL == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
