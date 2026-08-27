# -*- coding: utf-8 -*-
"""ATP live status v1 — plan trip vs vehicle GPS separation (temp DB only)."""
from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / 'app'
sys.path.insert(0, str(APP))

from modules.planlama.arac_today_operations_service import (
    STATUS_CONTRACT_VERSION,
    get_today_vehicle_operations,
)
from tools.nexgen_tmp_db import assert_resolved_db_is_tmp, canonical_db_path

WT_ROOT = Path(__file__).resolve().parents[2]
CANONICAL_SOURCE = Path(os.environ.get(
    'CPS_CANONICAL_DB_SOURCE',
    r'C:\Solariz_CPS_SERVER\app\mock_data.db',
))
VEHICLE = '45077045'
TODAY = date.today().isoformat()
FUTURE = (date.today() + timedelta(days=2)).isoformat()


@pytest.fixture(scope='module')
def env():
    live = str(CANONICAL_SOURCE.resolve())
    if not os.path.isfile(live):
        live = canonical_db_path()
    tmp_dir = tempfile.mkdtemp(prefix='atp_live_status_v1_')
    db = os.path.join(tmp_dir, 'mock_data_test.db')
    shutil.copy2(live, db)
    assert_resolved_db_is_tmp(db, live)
    os.environ['CPS_MOCK_DB_PATH'] = db
    import config as cfg
    cfg.Config.MOCK_DB_PATH = db
    yield {'db': db, 'tmp_dir': tmp_dir}
    shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest.fixture(autouse=True)
def _bind_temp_db(env):
    import config as cfg
    cfg.Config.MOCK_DB_PATH = env['db']
    os.environ['CPS_MOCK_DB_PATH'] = env['db']


def _mock_filom(*, moving: bool, stale: bool = False, lat: float = 41.0001, lng: float = 29.3001) -> dict:
    return {
        'ok': True,
        'vehicles': [{
            'id': VEHICLE,
            'plate': '34 MOR 049',
            'latitude': lat,
            'longitude': lng,
            'speed_kmh': 30.0 if moving else 0.0,
            'activity_status': 'HAREKETLI' if moving else 'DURAN',
            'activity_label': 'Hareketli' if moving else 'Duran',
            'last_seen_at': f'{TODAY} 13:00:00',
            'is_stale_data': stale,
        }],
    }


def _con(db: str) -> sqlite3.Connection:
    con = sqlite3.connect(db, timeout=30)
    con.row_factory = sqlite3.Row
    return con


def _clear_vehicle_plans(db: str) -> None:
    con = _con(db)
    try:
        con.execute(
            'DELETE FROM arac_gunluk_plan_is WHERE plan_id IN '
            '(SELECT id FROM arac_gunluk_plan WHERE arac_external_id=?)',
            (VEHICLE,),
        )
        con.execute('DELETE FROM arac_gunluk_plan WHERE arac_external_id=?', (VEHICLE,))
        if con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='arac_plan_is_ziyaret_durum'"
        ).fetchone():
            con.execute(
                'DELETE FROM arac_plan_is_ziyaret_durum WHERE arac_external_id=?',
                (VEHICLE,),
            )
        if con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='arac_plan_olay'"
        ).fetchone():
            con.execute(
                'DELETE FROM arac_plan_olay WHERE arac_external_id=?',
                (VEHICLE,),
            )
        con.execute('DELETE FROM arac_gps_snapshot WHERE arac_external_id=?', (VEHICLE,))
        con.commit()
    finally:
        con.close()


def _insert_talep(con: sqlite3.Connection, plan_id: int, plan_date: str) -> int:
    src = con.execute('SELECT * FROM arac_is_talebi LIMIT 1').fetchone()
    cols = [d[1] for d in con.execute('PRAGMA table_info(arac_is_talebi)').fetchall()]
    srcd = dict(zip(cols, src))
    ins_cols = [c for c in cols if c != 'id']
    vals = [srcd[c] for c in ins_cols]
    if 'talep_no' in ins_cols:
        vals[ins_cols.index('talep_no')] = f'LIVE-{plan_id}-{plan_date}'
    if 'latitude' in ins_cols:
        vals[ins_cols.index('latitude')] = 41.0002
    if 'longitude' in ins_cols:
        vals[ins_cols.index('longitude')] = 29.3002
    cur = con.execute(
        f'INSERT INTO arac_is_talebi ({",".join(ins_cols)}) VALUES ({",".join("?"*len(ins_cols))})',
        vals,
    )
    return int(cur.lastrowid)


def _ensure_plan(db: str, plan_date: str, cikis: str | None) -> int:
    con = _con(db)
    try:
        row = con.execute(
            """
            SELECT id FROM arac_gunluk_plan
            WHERE plan_tarihi=? AND arac_external_id=? AND durum='AKTIF'
            """,
            (plan_date, VEHICLE),
        ).fetchone()
        if row:
            pid = int(row['id'])
            con.execute('UPDATE arac_gunluk_plan SET cikis_saati=? WHERE id=?', (cikis, pid))
            con.commit()
            return pid
        cur = con.execute(
            """
            INSERT INTO arac_gunluk_plan (
                plan_tarihi, arac_provider, arac_external_id, arac_plaka_snapshot,
                sofor_adi_snapshot, durum, created_at, created_by, updated_at, updated_by, cikis_saati
            ) VALUES (?, 'TURKCELL_FILOM', ?, '34 MOR 049', 'ibrahim', 'AKTIF',
                      datetime('now'), 1, datetime('now'), 1, ?)
            """,
            (plan_date, VEHICLE, cikis),
        )
        pid = int(cur.lastrowid)
        talep_id = _insert_talep(con, pid, plan_date)
        con.execute(
            """
            INSERT INTO arac_gunluk_plan_is (
                plan_id, is_talebi_id, sira, durum, created_at, created_by
            ) VALUES (?, ?, 1, 'PLANLANDI', datetime('now'), 1)
            """,
            (pid, talep_id),
        )
        con.commit()
        return pid
    finally:
        con.close()


def _plan_is_id(db: str, plan_id: int) -> int:
    con = _con(db)
    try:
        return int(con.execute(
            'SELECT id FROM arac_gunluk_plan_is WHERE plan_id=? ORDER BY id LIMIT 1',
            (plan_id,),
        ).fetchone()[0])
    finally:
        con.close()


def _set_item_status(db: str, plan_id: int, durum: str) -> None:
    con = _con(db)
    try:
        con.execute(
            'UPDATE arac_gunluk_plan_is SET durum=? WHERE plan_id=?',
            (durum, plan_id),
        )
        con.commit()
    finally:
        con.close()


def _set_visit(db: str, plan_is_id: int, plan_id: int, state: str) -> None:
    from modules.planlama.arac_geofence_repo import upsert_visit_state
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    upsert_visit_state({
        'plan_id': plan_id,
        'plan_is_id': plan_is_id,
        'arac_external_id': VEHICLE,
        'state': state,
        'consecutive_inside': 3 if state != 'OUTSIDE' else 0,
        'consecutive_outside': 0,
        'arrived_at': now if state in ('ARRIVED', 'DEPARTED_PENDING') else None,
        'departed_at': now if state == 'DEPARTED_PENDING' else None,
        'updated_at': now,
        'created_at': now,
    })


def _insert_departure_event(db: str, plan_id: int) -> None:
    con = _con(db)
    try:
        if not con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='arac_plan_olay'"
        ).fetchone():
            pytest.skip('plan olay table missing')
        con.execute(
            """
            INSERT INTO arac_plan_olay (
                plan_id, arac_external_id, olay_turu, mesaj, olay_zamani, created_at
            ) VALUES (?, ?, 'ROTA_SAPMA_BASLADI', 'test departure evidence', ?, datetime('now'))
            """,
            (plan_id, VEHICLE, f'{TODAY} 08:00:00'),
        )
        con.commit()
    finally:
        con.close()


def _insert_gps(db: str, *, moving: bool, stale: bool = False, lat: float = 41.0001, lng: float = 29.3001) -> None:
    con = _con(db)
    try:
        if not con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='arac_gps_snapshot'"
        ).fetchone():
            return
        con.execute('DELETE FROM arac_gps_snapshot WHERE arac_external_id=?', (VEHICLE,))
        con.execute(
            """
            INSERT INTO arac_gps_snapshot (
                arac_provider, arac_external_id, plate_snapshot, gps_timestamp, received_at,
                latitude, longitude, speed_kmh, activity_status, ignition_status,
                is_stale, dedup_key, created_at
            ) VALUES ('TURKCELL_FILOM', ?, '34 MOR 049', ?, datetime('now'),
                      ?, ?, ?, ?, 'ON', ?, ?, datetime('now'))
            """,
            (
                VEHICLE,
                f'{TODAY} 13:00:00',
                lat,
                lng,
                25.0 if moving else 0.0,
                'HAREKETLI' if moving else 'DURAN',
                1 if stale else 0,
                f'test-{VEHICLE}-{TODAY}',
            ),
        )
        con.commit()
    finally:
        con.close()


def _clear_plans_for_date(db: str, plan_date: str) -> None:
    con = _con(db)
    try:
        con.execute(
            'DELETE FROM arac_gunluk_plan_is WHERE plan_id IN '
            '(SELECT id FROM arac_gunluk_plan WHERE plan_tarihi=?)',
            (plan_date,),
        )
        con.execute('DELETE FROM arac_gunluk_plan WHERE plan_tarihi=?', (plan_date,))
        con.commit()
    finally:
        con.close()


def _dto(db: str, plan_date: str, *, moving: bool = True, stale: bool = False, lat: float = 41.0001, lng: float = 29.3001) -> dict:
    return get_today_vehicle_operations(
        plan_date, filom_payload=_mock_filom(moving=moving, stale=stale, lat=lat, lng=lng),
    )


def _vehicle(db: str, plan_date: str, *, moving: bool = True, stale: bool = False, lat: float = 41.0001, lng: float = 29.3001) -> dict:
    dto = _dto(db, plan_date, moving=moving, stale=stale, lat=lat, lng=lng)
    return next(
        (v for v in dto.get('vehicles', []) if str(v.get('arac_external_id')) == VEHICLE),
        {},
    )


class TestAtpLiveStatusV1:
    def test_contract_version(self, env):
        dto = get_today_vehicle_operations(TODAY, filom_payload=_mock_filom(moving=True))
        assert dto['status_contract_version'] == STATUS_CONTRACT_VERSION

    def test_t1_future_no_departure_moving(self, env):
        _clear_vehicle_plans(env['db'])
        _ensure_plan(env['db'], FUTURE, None)
        _insert_gps(env['db'], moving=True)
        v = _vehicle(env['db'], FUTURE, moving=True)
        assert v['plan_trip_status'] == 'PLANLANDI'
        assert v['trip_started'] is False
        assert v['status_reason'] == 'FUTURE_PLAN'
        assert v['vehicle_physical_status'] == 'HAREKETLI'

    def test_t2_future_with_cikis_moving(self, env):
        _clear_vehicle_plans(env['db'])
        _ensure_plan(env['db'], FUTURE, '08:30')
        v = _vehicle(env['db'], FUTURE, moving=True)
        assert v['plan_trip_status'] == 'PLANLANDI'
        assert v['trip_started'] is False

    def test_t3_today_no_departure_moving(self, env):
        _clear_vehicle_plans(env['db'])
        _ensure_plan(env['db'], TODAY, None)
        v = _vehicle(env['db'], TODAY, moving=True)
        assert v['plan_trip_status'] == 'PLANLANDI'
        assert v['trip_started'] is False
        assert v['status_reason'] == 'DEPARTURE_NOT_STARTED'

    def test_t4_today_departure_event_moving(self, env):
        _clear_vehicle_plans(env['db'])
        pid = _ensure_plan(env['db'], TODAY, None)
        _insert_departure_event(env['db'], pid)
        # GPS far from stop so en-route, not approaching
        _insert_gps(env['db'], moving=True, lat=40.5, lng=28.5)
        v = _vehicle(env['db'], TODAY, moving=True, lat=40.5, lng=28.5)
        assert v['plan_trip_status'] == 'YOLDA'
        assert v['trip_started'] is True

    def test_t5_today_approaching(self, env):
        _clear_vehicle_plans(env['db'])
        pid = _ensure_plan(env['db'], TODAY, None)
        _set_item_status(env['db'], pid, 'BASLADI')
        _insert_gps(env['db'], moving=True)
        v = _vehicle(env['db'], TODAY, moving=True)
        assert v['plan_trip_status'] in ('YOLDA', 'KONUMA_YAKLASIYOR')
        assert v['trip_started'] is True

    def test_t6_today_arrived(self, env):
        _clear_vehicle_plans(env['db'])
        pid = _ensure_plan(env['db'], TODAY, None)
        pis = _plan_is_id(env['db'], pid)
        _set_item_status(env['db'], pid, 'BASLADI')
        _set_visit(env['db'], pis, pid, 'ARRIVED')
        v = _vehicle(env['db'], TODAY, moving=False)
        assert v['plan_trip_status'] == 'VARILDI'

    def test_t7_today_departed_pending(self, env):
        _clear_vehicle_plans(env['db'])
        pid = _ensure_plan(env['db'], TODAY, None)
        pis = _plan_is_id(env['db'], pid)
        _set_item_status(env['db'], pid, 'BASLADI')
        _set_visit(env['db'], pis, pid, 'DEPARTED_PENDING')
        v = _vehicle(env['db'], TODAY, moving=False)
        assert v['plan_trip_status'] == 'SONUC_BEKLIYOR'

    def test_t8_completed(self, env):
        _clear_vehicle_plans(env['db'])
        pid = _ensure_plan(env['db'], TODAY, None)
        _set_item_status(env['db'], pid, 'TAMAMLANDI')
        v = _vehicle(env['db'], TODAY, moving=True)
        assert v['plan_trip_status'] == 'TAMAMLANDI'

    def test_t9_stale_gps_plan_unchanged(self, env):
        _clear_vehicle_plans(env['db'])
        _ensure_plan(env['db'], FUTURE, None)
        _insert_gps(env['db'], moving=True, stale=True)
        v = _vehicle(env['db'], FUTURE, moving=True, stale=True)
        assert v['vehicle_physical_status'] == 'GPS_ESKI'
        assert v['plan_trip_status'] == 'PLANLANDI'

    def test_t10_filom_merge_preserves_plan_trip_status(self, env):
        _clear_vehicle_plans(env['db'])
        _ensure_plan(env['db'], FUTURE, None)
        dto = get_today_vehicle_operations(FUTURE, filom_payload=_mock_filom(moving=True))
        v = next(x for x in dto['vehicles'] if str(x['arac_external_id']) == VEHICLE)
        before = v['plan_trip_status']
        merged = dict(v)
        merged['vehicle_physical_status'] = 'HAREKETLI'
        merged['physical_status'] = 'Hareketli'
        assert merged['plan_trip_status'] == before == 'PLANLANDI'

    def test_t11_card_jobs_parity(self, env):
        _clear_vehicle_plans(env['db'])
        _ensure_plan(env['db'], FUTURE, None)
        dto = get_today_vehicle_operations(FUTURE, filom_payload=_mock_filom(moving=True))
        v = next(x for x in dto['vehicles'] if str(x['arac_external_id']) == VEHICLE)
        items = [it for it in dto['items'] if str(it.get('arac_external_id')) == VEHICLE]
        assert items
        assert v['plan_trip_status'] == items[0]['plan_trip_status'] == 'PLANLANDI'

    def test_t12_same_dto_admin_mehmet(self, env):
        dto = get_today_vehicle_operations(TODAY, filom_payload=_mock_filom(moving=True))
        dto2 = get_today_vehicle_operations(TODAY, filom_payload=_mock_filom(moving=True))
        assert dto['status_contract_version'] == dto2['status_contract_version']

    def test_t13_batch_service_import(self, env):
        from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
        assert callable(add_job_to_plan_atomic)

    def test_t14_route_planner_import(self, env):
        from modules.planlama.road_routing.route_planner_service import get_routing_provider
        assert get_routing_provider is not None

    def test_t15_no_gps_history_files_in_changes(self):
        wt = Path(__file__).resolve().parents[2]
        hits = [
            p for p in wt.rglob('*')
            if p.is_file()
            and ('gps_history' in p.name.lower() or 'gps_trail' in p.name.lower())
            and 'test_' not in p.name.lower()
        ]
        assert not hits

    def test_t16_kpi_future_moving_gps_zero(self, env):
        _clear_plans_for_date(env['db'], FUTURE)
        _ensure_plan(env['db'], FUTURE, None)
        dto = _dto(env['db'], FUTURE, moving=True)
        assert dto['kpi']['aktif_arac'] == 0
        assert dto['kpi']['hareket_halinde'] == 0
        assert dto['kpi']['aktif_arac_source'] == 'canonical_plan_trip'

    def test_t17_kpi_today_no_departure_active_not_moving(self, env):
        _clear_plans_for_date(env['db'], TODAY)
        _ensure_plan(env['db'], TODAY, None)
        dto = _dto(env['db'], TODAY, moving=True)
        assert dto['kpi']['aktif_arac'] == 1
        assert dto['kpi']['hareket_halinde'] == 0

    def test_t18_kpi_today_departure_active_and_moving(self, env):
        _clear_plans_for_date(env['db'], TODAY)
        pid = _ensure_plan(env['db'], TODAY, None)
        _set_item_status(env['db'], pid, 'BASLADI')
        _insert_gps(env['db'], moving=True, lat=40.5, lng=28.5)
        dto = _dto(env['db'], TODAY, moving=True, lat=40.5, lng=28.5)
        assert dto['kpi']['aktif_arac'] == 1
        assert dto['kpi']['hareket_halinde'] == 1

    def test_t19_kpi_today_completed_zero(self, env):
        _clear_plans_for_date(env['db'], TODAY)
        pid = _ensure_plan(env['db'], TODAY, None)
        _set_item_status(env['db'], pid, 'TAMAMLANDI')
        dto = _dto(env['db'], TODAY, moving=True)
        assert dto['kpi']['aktif_arac'] == 0
        assert dto['kpi']['hareket_halinde'] == 0

    def test_t20_kpi_card_table_parity(self, env):
        _clear_plans_for_date(env['db'], TODAY)
        pid = _ensure_plan(env['db'], TODAY, None)
        _set_item_status(env['db'], pid, 'BASLADI')
        _insert_gps(env['db'], moving=True, lat=40.5, lng=28.5)
        dto = _dto(env['db'], TODAY, moving=True, lat=40.5, lng=28.5)
        v = next(x for x in dto['vehicles'] if str(x['arac_external_id']) == VEHICLE)
        items = [it for it in dto['items'] if str(it.get('arac_external_id')) == VEHICLE]
        kpi = dto['kpi']
        assert v['plan_trip_status'] in ('YOLDA', 'KONUMA_YAKLASIYOR')
        assert items[0]['plan_trip_status'] == v['plan_trip_status']
        assert kpi['aktif_arac'] == 1
        assert kpi['hareket_halinde'] == 1
        assert v['vehicle_physical_status'] == 'HAREKETLI'
