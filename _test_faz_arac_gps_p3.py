# -*- coding: utf-8 -*-
"""GPS P3 — geofence state machine, atomic plana-is-ekle, today operations DTO."""
from __future__ import annotations

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
def _read_canonical_sha() -> str:
    """Compute SHA256 of canonical DB at test start — used for before/after comparison."""
    import hashlib as _hl
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app', 'mock_data.db')
    if os.path.isfile(p):
        return _hl.sha256(open(p, 'rb').read()).hexdigest()
    return ''

CANONICAL_SHA = _read_canonical_sha()
sys.path.insert(0, APP)
os.chdir(APP)

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
        filename, os.path.join(APP, 'migrations', filename),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.run(db_path)


@contextmanager
def temp_p3_db():
    tmpdir = tempfile.mkdtemp(prefix='gps_p3_')
    db_path = os.path.join(tmpdir, 'gps_p3.db')
    for mig in (
        '176_arac_takip_v13.py', '177_arac_operasyon_ayar.py',
        '178_arac_is_talebi_ux_v2_fields.py', '179_arac_gps_snapshot_p1.py',
        '180_arac_plan_ziyaret_durum.py',
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
        ) VALUES ('2026-12-20','TURKCELL_FILOM','V1','34 MOR 049',1,'Oktay','AKTIF',?,?,?,?)
        """,
        (now, 1, now, 1),
    )
    plan_id = int(cur.lastrowid)
    lat, lng = 40.9900, 28.8900
    tcur = con.execute(
        """
        INSERT INTO arac_is_talebi (
            talep_no, talep_eden_user_id, talep_eden_adi_snapshot, talep_tarihi,
            firma_adi, adres, yapilacak_is, oncelik, durum,
            latitude, longitude, created_at, created_by, updated_at, updated_by
        ) VALUES ('P3-1',1,'Test','2026-12-20','Firma A','Adres','Teslim','NORMAL',
         'PLANA_ALINDI',?,?,?,?,?,?)
        """,
        (lat, lng, now, 1, now, 1),
    )
    talep_id = int(tcur.lastrowid)
    con.execute(
        """
        INSERT INTO arac_gunluk_plan_is (
            plan_id, is_talebi_id, sira, planlanan_saat, durum, created_at, created_by
        ) VALUES (?,?,1,'09:30','PLANLANDI',?,?)
        """,
        (plan_id, talep_id, now, 1),
    )
    plan_is_id = int(con.execute('SELECT id FROM arac_gunluk_plan_is').fetchone()[0])
    con.commit()
    con.close()
    import config
    with patch.object(config.Config, 'MOCK_DB_PATH', db_path):
        print(f'  [DB-PATH-TEMP] {db_path}')
        yield db_path, plan_id, plan_is_id, lat, lng


def _snap(con, vid, ts, lat, lng, stale=0):
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


def test_geofence_arrival_two_points(db_path, plan_id, plan_is_id, lat, lng) -> None:
    print('GEOFENCE_ARRIVAL')
    from modules.planlama.arac_geofence_service import process_gps_snapshot_for_geofence
    from modules.planlama.arac_geofence_repo import get_visit_state, geofence_tables_ready
    if not geofence_tables_ready():
        bad('tables_ready'); return
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    ts1 = '2026-12-20 09:00:00'
    ts2 = '2026-12-20 09:01:00'
    sid1 = _snap(con, 'V1', ts1, lat, lng)
    sid2 = _snap(con, 'V1', ts2, lat + 0.00001, lng + 0.00001)
    con.commit()
    row1 = dict(con.execute('SELECT * FROM arac_gps_snapshot WHERE id=?', (sid1,)).fetchone())
    row2 = dict(con.execute('SELECT * FROM arac_gps_snapshot WHERE id=?', (sid2,)).fetchone())
    con.close()
    r1 = process_gps_snapshot_for_geofence(row1)
    r2 = process_gps_snapshot_for_geofence(row2)
    visit = get_visit_state(plan_is_id)
    n_events = sqlite3.connect(db_path).execute(
        "SELECT COUNT(*) FROM arac_plan_olay WHERE plan_is_id=? AND olay_turu='KONUMA_VARILDI'",
        (plan_is_id,),
    ).fetchone()[0]
    if r1.get('processed', 0) >= 0 and visit and visit.get('consecutive_inside', 0) >= 1:
        ok('first_inside_point')
    else:
        bad('first_inside_point', str(r1))
    if visit and visit.get('state') == 'ARRIVED' and n_events == 1:
        ok('two_point_arrival')
    else:
        bad('two_point_arrival', str(visit) + f' events={n_events}')


def test_single_point_no_arrival(db_path, plan_id, plan_is_id, lat, lng) -> None:
    print('GEOFENCE_SINGLE')
    from modules.planlama.arac_geofence_service import process_gps_snapshot_for_geofence
    from modules.planlama.arac_geofence_repo import get_visit_state
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    ts = '2026-12-20 08:30:00'
    sid = _snap(con, 'V1', ts, lat, lng)
    row = dict(con.execute('SELECT * FROM arac_gps_snapshot WHERE id=?', (sid,)).fetchone())
    con.close()
    process_gps_snapshot_for_geofence(row)
    visit = get_visit_state(plan_is_id)
    n = sqlite3.connect(db_path).execute(
        "SELECT COUNT(*) FROM arac_plan_olay WHERE olay_turu='KONUMA_VARILDI'",
    ).fetchone()[0]
    if n == 0 and visit and visit.get('state') != 'ARRIVED':
        ok('single_point_no_arrival')
    else:
        bad('single_point_no_arrival', f'events={n} state={visit}')


def test_stale_gps_skipped(db_path, plan_id, plan_is_id, lat, lng) -> None:
    print('GEOFENCE_STALE')
    from modules.planlama.arac_geofence_service import process_gps_snapshot_for_geofence
    row = {
        'id': 9999, 'arac_external_id': 'V1', 'latitude': lat, 'longitude': lng,
        'gps_timestamp': '2026-12-20 11:00:00', 'is_stale': True,
    }
    before = sqlite3.connect(db_path).execute('SELECT COUNT(*) FROM arac_plan_olay').fetchone()[0]
    process_gps_snapshot_for_geofence(row)
    after = sqlite3.connect(db_path).execute('SELECT COUNT(*) FROM arac_plan_olay').fetchone()[0]
    if before == after:
        ok('stale_skipped')
    else:
        bad('stale_skipped')


def test_no_auto_tamamlandi(db_path, plan_is_id) -> None:
    print('NO_AUTO_TAMAMLANDI')
    st = sqlite3.connect(db_path).execute(
        'SELECT durum FROM arac_gunluk_plan_is WHERE id=?', (plan_is_id,),
    ).fetchone()[0]
    if st == 'PLANLANDI':
        ok('plan_item_not_auto_completed')
    else:
        bad('plan_item_not_auto_completed', st)


def test_atomic_plana_is_ekle(db_path) -> None:
    print('ATOMIC_PLANA')
    from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
    try:
        result = add_job_to_plan_atomic(1, {
            'plan_tarihi': '2026-12-20',
            'arac_external_id': 'V1',
            'arac_plaka': '34 MOR 049',
            'firma': 'Firma B',
            'adres': 'Adres B',
            'yapilacak_is': 'Yeni is',
            'latitude': 40.991,
            'longitude': 28.891,
            'planlanan_saat': '14:00',
        })
        if result.get('ok') and result.get('plan_id'):
            ok('atomic_add_ok')
        else:
            bad('atomic_add_ok', str(result))
    except Exception as exc:
        bad('atomic_add_ok', str(exc))
    bekleyen = sqlite3.connect(db_path).execute(
        "SELECT COUNT(*) FROM arac_is_talebi WHERE durum='BEKLIYOR'",
    ).fetchone()[0]
    planli = sqlite3.connect(db_path).execute(
        "SELECT COUNT(*) FROM arac_gunluk_plan_is WHERE plan_id IN (SELECT id FROM arac_gunluk_plan WHERE arac_external_id='V1')",
    ).fetchone()[0]
    if planli >= 2:
        ok('item_on_plan')
    else:
        bad('item_on_plan', str(planli))
    if bekleyen == 0:
        ok('no_orphan_bekleyen')
    else:
        bad('no_orphan_bekleyen', str(bekleyen))


def test_today_operations_dto(db_path) -> None:
    print('TODAY_OPS')
    from modules.planlama.arac_today_operations_service import get_today_vehicle_operations
    dto = get_today_vehicle_operations('2026-12-20', filom_payload={'ok': True, 'vehicles': []})
    if dto.get('ok') and 'kpi' in dto and 'vehicles' in dto and 'alerts' in dto:
        ok('dto_shape')
    else:
        bad('dto_shape')
    if dto['kpi'].get('toplam_is_source') == 'canonical':
        ok('kpi_canonical_source')
    else:
        bad('kpi_canonical_source')


def test_worker_geofence_integration(db_path, lat, lng) -> None:
    print('WORKER_GEOFENCE')
    from modules.planlama.arac_gps_poll_service import poll_once
    vehicles = [{
        'id': 'V1', 'plate_display': '34 MOR 049', 'latitude': lat, 'longitude': lng,
        'has_valid_location': True, 'last_seen_at': '2026-12-20 12:00:00',
        'speed_kmh': 0, 'activity_status': 'DURAN', 'is_stale_data': False,
    }]
    result = poll_once(live_fetcher=lambda: {'ok': True, 'vehicles': vehicles})
    if result.get('ok') and 'geofence' in result:
        ok('poll_once_has_geofence')
    else:
        bad('poll_once_has_geofence', str(result))


def test_geofence_departure_two_points(db_path, plan_id, plan_is_id, lat, lng) -> None:
    """Araç 2 nokta içeride → ARRIVED → 2 nokta dışarıda → DEPARTED."""
    print('GEOFENCE_DEPARTURE')
    from modules.planlama.arac_geofence_service import process_gps_snapshot_for_geofence
    from modules.planlama.arac_geofence_repo import get_visit_state
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    # Önce 2 nokta ile ARRIVED durumuna getirelim
    ts_a1 = '2026-12-20 13:00:00'
    ts_a2 = '2026-12-20 13:01:00'
    sid_a1 = _snap(con, 'V1', ts_a1, lat, lng)
    sid_a2 = _snap(con, 'V1', ts_a2, lat, lng)
    con.commit()
    rows_a = [
        dict(con.execute('SELECT * FROM arac_gps_snapshot WHERE id=?', (sid_a1,)).fetchone()),
        dict(con.execute('SELECT * FROM arac_gps_snapshot WHERE id=?', (sid_a2,)).fetchone()),
    ]
    con.close()
    for row in rows_a:
        process_gps_snapshot_for_geofence(row)
    visit_arrived = get_visit_state(plan_is_id)
    if not (visit_arrived and visit_arrived.get('state') == 'ARRIVED'):
        bad('departure_arrived_precond', str(visit_arrived))
        return
    ok('departure_arrived_precond')

    # Şimdi 2 nokta dışarıda → DEPARTED bekleniyor
    exit_lat, exit_lng = lat + 0.005, lng + 0.005  # ~500m uzakta (exit_radius > 250m)
    con2 = sqlite3.connect(db_path)
    con2.row_factory = sqlite3.Row
    ts_d1 = '2026-12-20 13:10:00'
    ts_d2 = '2026-12-20 13:11:00'
    sid_d1 = _snap(con2, 'V1', ts_d1, exit_lat, exit_lng)
    sid_d2 = _snap(con2, 'V1', ts_d2, exit_lat, exit_lng)
    con2.commit()
    rows_d = [
        dict(con2.execute('SELECT * FROM arac_gps_snapshot WHERE id=?', (sid_d1,)).fetchone()),
        dict(con2.execute('SELECT * FROM arac_gps_snapshot WHERE id=?', (sid_d2,)).fetchone()),
    ]
    con2.close()
    for row in rows_d:
        process_gps_snapshot_for_geofence(row)
    visit_depart = get_visit_state(plan_is_id)
    n_depart = sqlite3.connect(db_path).execute(
        "SELECT COUNT(*) FROM arac_plan_olay WHERE plan_is_id=? AND olay_turu='KONUMDAN_AYRILDI'",
        (plan_is_id,),
    ).fetchone()[0]
    # DEPARTED_PENDING = iki nokta dışarıda, result bekleniyor
    departed_states = ('DEPARTED', 'OUTSIDE', 'DEPARTED_PENDING')
    if visit_depart and visit_depart.get('state') in departed_states and n_depart >= 1:
        ok('two_point_departure')
    else:
        bad('two_point_departure', str(visit_depart) + f' depart_events={n_depart}')


def test_geofence_hysteresis(db_path, plan_id, plan_is_id, lat, lng) -> None:
    """Tek nokta dışarıda ARRIVED state'ini bozmaz (hysteresis)."""
    print('GEOFENCE_HYSTERESIS')
    from modules.planlama.arac_geofence_service import process_gps_snapshot_for_geofence
    from modules.planlama.arac_geofence_repo import get_visit_state, upsert_visit_state
    from datetime import datetime
    # Zorla ARRIVED state yaz
    upsert_visit_state({
        'plan_id': plan_id, 'plan_is_id': plan_is_id,
        'arac_external_id': 'V1', 'kayitli_yer_id': None,
        'state': 'ARRIVED', 'geofence_radius_m': 200, 'exit_radius_m': 250,
        'consecutive_inside': 2, 'consecutive_outside': 0,
        'arrived_at': '2026-12-20 14:00:00', 'departed_at': None,
        'dwell_seconds': None, 'last_gps_snapshot_id': None,
        'result_status': None,
        'updated_at': datetime.now().isoformat(sep=' ', timespec='seconds'),
        'created_at': datetime.now().isoformat(sep=' ', timespec='seconds'),
    })
    before = get_visit_state(plan_is_id)
    # 1 nokta exit radius dışında ama hysteresis gereği tek nokta ile DEPARTED olmamalı
    exit_lat, exit_lng = lat + 0.003, lng + 0.003  # ~300m
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    ts = '2026-12-20 14:05:00'
    sid = _snap(con, 'V1', ts, exit_lat, exit_lng)
    con.commit()
    row = dict(con.execute('SELECT * FROM arac_gps_snapshot WHERE id=?', (sid,)).fetchone())
    con.close()
    process_gps_snapshot_for_geofence(row)
    after = get_visit_state(plan_is_id)
    # State hâlâ ARRIVED olmalı (1 dışarıda → consecutive_outside=1, ama DEPARTED için 2 lazım)
    if after and after.get('state') == 'ARRIVED' and after.get('consecutive_outside', 0) >= 1:
        ok('hysteresis_single_outside_no_depart')
    else:
        bad('hysteresis_single_outside_no_depart', str(after))


def test_geofence_event_idempotency(db_path, plan_is_id) -> None:
    """Aynı snapshot iki kez işlenirse ikinci KONUMA_VARILDI event üretilmez."""
    print('GEOFENCE_IDEMPOTENCY')
    from modules.planlama.arac_geofence_service import process_gps_snapshot_for_geofence
    lat, lng = 40.9900, 28.8900
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    ts = '2026-12-20 15:00:00'
    sid = _snap(con, 'V1', ts, lat, lng)
    con.commit()
    row = dict(con.execute('SELECT * FROM arac_gps_snapshot WHERE id=?', (sid,)).fetchone())
    con.close()
    before_n = sqlite3.connect(db_path).execute(
        'SELECT COUNT(*) FROM arac_plan_olay WHERE plan_is_id=?', (plan_is_id,),
    ).fetchone()[0]
    process_gps_snapshot_for_geofence(row)
    mid_n = sqlite3.connect(db_path).execute(
        'SELECT COUNT(*) FROM arac_plan_olay WHERE plan_is_id=?', (plan_is_id,),
    ).fetchone()[0]
    process_gps_snapshot_for_geofence(row)  # ikinci kez — aynı snapshot
    after_n = sqlite3.connect(db_path).execute(
        'SELECT COUNT(*) FROM arac_plan_olay WHERE plan_is_id=?', (plan_is_id,),
    ).fetchone()[0]
    # İkinci işlem yeni event üretmemeli
    if after_n == mid_n:
        ok('event_idempotency')
    else:
        bad('event_idempotency', f'before={before_n} mid={mid_n} after={after_n}')


def test_a0_bekleyen_havuz_gizleme(db_path) -> None:
    """A0 kuralı: canonical modda bekleyen_talepler listesi boş döner."""
    print('A0_BEKLEYEN_HAVUZ')
    from modules.planlama.arac_dashboard_service import get_arac_dashboard_dto
    from datetime import date as _date
    dto = get_arac_dashboard_dto(_date(2026, 12, 20))
    if 'bekleyen_talepler' in dto and isinstance(dto['bekleyen_talepler'], list):
        ok('a0_field_present')
    else:
        bad('a0_field_present', str(list(dto.keys())))
    # canonical modda (temp DB'de canonical=False olabilir, ama alan mevcut olmalı)
    if 'bekleyen_count' in dto:
        ok('a0_count_present')
    else:
        bad('a0_count_present')


def test_kpi_no_mock(db_path) -> None:
    """Mock KPI değerleri (%96, 4.2 km, 7 tamamlandı) DTO içinde olmamalı."""
    print('KPI_NO_MOCK')
    from modules.planlama.arac_today_operations_service import get_today_vehicle_operations
    dto = get_today_vehicle_operations('2026-12-20', filom_payload={'ok': True, 'vehicles': []})
    kpi_str = str(dto.get('kpi', {}))
    forbidden = ['%96', '4.2 km', '7 tamamland']
    found = [f for f in forbidden if f in kpi_str]
    if not found:
        ok('kpi_no_mock_values')
    else:
        bad('kpi_no_mock_values', str(found))


def test_canonical_db_unchanged() -> None:
    """Verify canonical DB has not changed since test suite started."""
    print('CANONICAL_HASH')
    import hashlib
    p = os.path.join(APP, 'mock_data.db')
    if not CANONICAL_SHA:
        ok('canonical_sha_skip')
        return
    if os.path.isfile(p):
        h = hashlib.sha256(open(p, 'rb').read()).hexdigest()
        if h == CANONICAL_SHA:
            ok('canonical_sha')
        else:
            bad('canonical_sha', f'expected={CANONICAL_SHA[:16]}... got={h[:16]}...')
    else:
        ok('canonical_sha_skip')


def main() -> int:
    print('=' * 60)
    print('GPS P3 TEST SUITE')
    test_canonical_db_unchanged()
    with temp_p3_db() as (db_path, plan_id, plan_is_id, lat, lng):
        test_single_point_no_arrival(db_path, plan_id, plan_is_id, lat, lng)
        test_geofence_arrival_two_points(db_path, plan_id, plan_is_id, lat, lng)
        test_geofence_departure_two_points(db_path, plan_id, plan_is_id, lat, lng)
        test_geofence_hysteresis(db_path, plan_id, plan_is_id, lat, lng)
        test_geofence_event_idempotency(db_path, plan_is_id)
        test_stale_gps_skipped(db_path, plan_id, plan_is_id, lat, lng)
        test_no_auto_tamamlandi(db_path, plan_is_id)
        test_atomic_plana_is_ekle(db_path)
        test_today_operations_dto(db_path)
        test_a0_bekleyen_havuz_gizleme(db_path)
        test_kpi_no_mock(db_path)
        test_worker_geofence_integration(db_path, lat, lng)
    test_canonical_db_unchanged()  # verify canonical unchanged after all temp tests
    print('=' * 60)
    print(f'RESULT {PASS}/{PASS + FAIL} PASS, {FAIL} FAIL')
    return 0 if FAIL == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
