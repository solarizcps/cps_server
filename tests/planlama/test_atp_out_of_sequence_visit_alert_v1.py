# -*- coding: utf-8 -*-
"""R13 — out-of-sequence visit alert emission and dedupe (TEMP DB only)."""
from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'app'
MIGRATIONS = APP / 'migrations'
CANONICAL = Path(r'C:\Solariz_CPS_SERVER\app\mock_data.db')
_P0_MIGRATIONS = (
    '176_arac_takip_v13.py',
    '177_arac_operasyon_ayar.py',
    '178_arac_is_talebi_ux_v2_fields.py',
    '179_arac_gps_snapshot_p1.py',
    '180_arac_plan_ziyaret_durum.py',
    '191_arac_plan_olay_auto_tamamlandi.py',
)


def _run_migration(db_path: str, filename: str) -> None:
    spec = importlib.util.spec_from_file_location(filename, MIGRATIONS / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.run(db_path)


@pytest.fixture()
def geo_db(monkeypatch):
    saved = {
        k: sys.modules[k]
        for k in list(sys.modules)
        if k == 'db' or k.startswith('modules.planlama')
    }
    db_path = os.path.join(tempfile.gettempdir(), 'atp_r13_alert_test.db')
    if os.path.isfile(db_path):
        os.remove(db_path)
    for mig in _P0_MIGRATIONS:
        _run_migration(db_path, mig)
    assert os.path.abspath(db_path) != os.path.abspath(CANONICAL)
    monkeypatch.setenv('CPS_MOCK_DB_PATH', db_path)
    monkeypatch.setenv('CPS_TEST_DB_GUARD', '0')
    monkeypatch.delenv('CPS_DB_PATH', raising=False)
    import config
    config.Config.MOCK_DB_PATH = db_path
    for mod_name in list(sys.modules):
        if mod_name == 'db' or mod_name.startswith('modules.planlama'):
            sys.modules.pop(mod_name, None)
    yield db_path
    for k, mod in saved.items():
        sys.modules[k] = mod
    for k in list(sys.modules):
        if (k == 'db' or k.startswith('modules.planlama')) and k not in saved:
            sys.modules.pop(k, None)


def _setup_fixture(con: sqlite3.Connection, plan_date: str = '2026-09-14') -> dict:
    now = '2026-09-14 10:00:00'
    con.execute("DELETE FROM arac_plan_is_ziyaret_durum WHERE arac_external_id='TEST_R13_VEHICLE'")
    con.execute("DELETE FROM arac_plan_olay WHERE arac_external_id='TEST_R13_VEHICLE'")
    con.execute(
        "DELETE FROM arac_gunluk_plan_is WHERE plan_id IN "
        "(SELECT id FROM arac_gunluk_plan WHERE arac_external_id='TEST_R13_VEHICLE')"
    )
    con.execute("DELETE FROM arac_gunluk_plan WHERE arac_external_id='TEST_R13_VEHICLE'")
    con.execute("DELETE FROM arac_is_talebi WHERE talep_eden_adi_snapshot='TEST_R13_FIXTURE'")
    con.commit()
    con.execute(
        "INSERT INTO arac_gunluk_plan (plan_tarihi, arac_provider, arac_external_id, "
        "arac_plaka_snapshot, sofor_id, sofor_adi_snapshot, durum, created_at, created_by, updated_at, updated_by) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (plan_date, 'TURKCELL_FILOM', 'TEST_R13_VEHICLE', '34 R13 001', 1, 'Test', 'AKTIF', now, 1, now, 1),
    )
    plan_id = con.execute(
        "SELECT id FROM arac_gunluk_plan WHERE arac_external_id='TEST_R13_VEHICLE' AND plan_tarihi=?",
        (plan_date,),
    ).fetchone()[0]
    year = '2026'
    talep_violet = con.execute(
        "INSERT INTO arac_is_talebi (talep_no, talep_eden_user_id, talep_eden_adi_snapshot, talep_tarihi, "
        "firma_adi, oncelik, latitude, longitude, adres, yapilacak_is, durum, created_at, created_by, updated_at, updated_by) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (f'AIT-{year}-R1301', 1, 'TEST_R13_FIXTURE', plan_date, 'Violet Etiket', 'NORMAL', 41.0, 28.7, 'V', 'Z', 'PLANA_ALINDI', now, 1, now, 1),
    ).lastrowid
    talep_beyazit = con.execute(
        "INSERT INTO arac_is_talebi (talep_no, talep_eden_user_id, talep_eden_adi_snapshot, talep_tarihi, "
        "firma_adi, oncelik, latitude, longitude, adres, yapilacak_is, durum, created_at, created_by, updated_at, updated_by) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (f'AIT-{year}-R1302', 1, 'TEST_R13_FIXTURE', plan_date, 'Beyazit Tekstil', 'ACIL', 41.01, 28.72, 'B', 'Z', 'PLANA_ALINDI', now, 1, now, 1),
    ).lastrowid
    con.execute("INSERT INTO arac_gunluk_plan_is (plan_id, is_talebi_id, sira, durum, created_at, created_by) VALUES (?,?,?,?,?,?)", (plan_id, talep_violet, 1, 'PLANLANDI', now, 1))
    pi_violet = con.execute("SELECT id FROM arac_gunluk_plan_is WHERE plan_id=? AND sira=1", (plan_id,)).fetchone()[0]
    for sira in range(2, 9):
        tid = con.execute(
            "INSERT INTO arac_is_talebi (talep_no, talep_eden_user_id, talep_eden_adi_snapshot, talep_tarihi, "
            "firma_adi, oncelik, latitude, longitude, adres, yapilacak_is, durum, created_at, created_by, updated_at, updated_by) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f'AIT-{year}-R13{sira}', 1, 'TEST_R13_FIXTURE', plan_date, f'Dummy {sira}', 'NORMAL', None, None, 'D', 'Z', 'PLANA_ALINDI', now, 1, now, 1),
        ).lastrowid
        con.execute("INSERT INTO arac_gunluk_plan_is (plan_id, is_talebi_id, sira, durum, created_at, created_by) VALUES (?,?,?,?,?,?)", (plan_id, tid, sira, 'PLANLANDI', now, 1))
    con.execute("INSERT INTO arac_gunluk_plan_is (plan_id, is_talebi_id, sira, durum, created_at, created_by) VALUES (?,?,?,?,?,?)", (plan_id, talep_beyazit, 9, 'PLANLANDI', now, 1))
    pi_beyazit = con.execute("SELECT id FROM arac_gunluk_plan_is WHERE plan_id=? AND sira=9", (plan_id,)).fetchone()[0]
    con.commit()
    return {'plan_id': plan_id, 'pi_violet': pi_violet, 'pi_beyazit': pi_beyazit, 'plan_date': plan_date}


def _gps(lat, lon, ts, snap_id=1):
    return {
        'id': snap_id,
        'arac_external_id': 'TEST_R13_VEHICLE',
        'gps_timestamp': ts,
        'received_at': ts,
        'latitude': lat,
        'longitude': lon,
        'speed_kmh': 10.0,
        'activity_status': 'HAREKETLI',
        'ignition_status': 'ON',
        'is_stale': 0,
    }


def _run_oos_arrived_only(geo_db):
    """Two GPS confirmations at wrong stop — alert before departure."""
    from datetime import datetime
    from modules.planlama import arac_geofence_service as svc

    con = sqlite3.connect(geo_db)
    con.row_factory = sqlite3.Row
    fx = _setup_fixture(con, '2026-09-14')
    con.close()
    pd = fx['plan_date']
    for i, ts in enumerate(['2026-09-14 10:00:00', '2026-09-14 10:01:00'], start=1):
        row = _gps(41.0101, 28.7201, ts, i)
        dt = datetime.strptime(ts, '%Y-%m-%d %H:%M:%S')
        svc.process_gps_snapshot_for_geofence(row, plan_date=pd, now=dt)
    return fx


def _run_oos_visit(geo_db):
    from datetime import datetime
    from modules.planlama import arac_geofence_service as svc

    con = sqlite3.connect(geo_db)
    con.row_factory = sqlite3.Row
    fx = _setup_fixture(con, '2026-09-14')
    con.close()
    pd = fx['plan_date']
    for i, ts in enumerate(['2026-09-14 10:00:00', '2026-09-14 10:01:00'], start=1):
        row = _gps(41.0101, 28.7201, ts, i)
        dt = datetime.strptime(ts, '%Y-%m-%d %H:%M:%S')
        svc.process_gps_snapshot_for_geofence(row, plan_date=pd, now=dt)
    for i, ts in enumerate(['2026-09-14 10:30:00', '2026-09-14 10:31:00'], start=3):
        row = _gps(41.015, 28.725, ts, i)
        dt = datetime.strptime(ts, '%Y-%m-%d %H:%M:%S')
        svc.process_gps_snapshot_for_geofence(row, plan_date=pd, now=dt)
    return fx


def test_out_of_sequence_visit_alert_on_arrived_only(geo_db):
    fx = _run_oos_arrived_only(geo_db)
    from modules.planlama.arac_geofence_repo import list_out_of_sequence_visit_alerts_for_date

    rows = list_out_of_sequence_visit_alerts_for_date(fx['plan_date'])
    assert len(rows) == 1
    assert rows[0]['expected_stop'] == 'Violet Etiket'
    assert rows[0]['actual_stop'] == 'Beyazit Tekstil'
    con = sqlite3.connect(geo_db)
    n_visit_alert = 0
    for r in con.execute(
        "SELECT metadata_json FROM arac_plan_olay WHERE plan_id=? AND olay_turu='NOT'",
        (fx['plan_id'],),
    ):
        m = json.loads(r[0] or '{}')
        if m.get('geofence_kind') == 'OUT_OF_SEQUENCE_VISIT_ALERT':
            n_visit_alert += 1
    st_b = con.execute('SELECT durum FROM arac_gunluk_plan_is WHERE id=?', (fx['pi_beyazit'],)).fetchone()[0]
    con.close()
    assert n_visit_alert == 1
    assert st_b == 'PLANLANDI'


def test_out_of_sequence_visit_alert_created(geo_db):
    fx = _run_oos_visit(geo_db)
    con = sqlite3.connect(geo_db)
    con.row_factory = sqlite3.Row
    st_v = con.execute('SELECT durum FROM arac_gunluk_plan_is WHERE id=?', (fx['pi_violet'],)).fetchone()[0]
    st_b = con.execute('SELECT durum FROM arac_gunluk_plan_is WHERE id=?', (fx['pi_beyazit'],)).fetchone()[0]
    alerts = []
    for r in con.execute("SELECT metadata_json FROM arac_plan_olay WHERE plan_id=? AND olay_turu='NOT'", (fx['plan_id'],)):
        m = json.loads(r[0] or '{}')
        if m.get('geofence_kind') == 'OUT_OF_SEQUENCE_VISIT_ALERT':
            alerts.append(m)
    con.close()
    assert st_v == 'PLANLANDI'
    assert st_b == 'TAMAMLANDI'
    assert len(alerts) == 1
    assert alerts[0]['expected_stop'] == 'Violet Etiket'
    assert alerts[0]['actual_stop'] == 'Beyazit Tekstil'
    assert alerts[0].get('acknowledged_at') is None


def test_out_of_sequence_daily_alert_plate_is_plan_snapshot(geo_db):
    fx = _run_oos_arrived_only(geo_db)
    from modules.planlama.arac_today_operations_service import get_today_vehicle_operations

    ops = get_today_vehicle_operations(fx['plan_date'], vehicle_id='TEST_R13_VEHICLE')
    oos = [a for a in (ops.get('alerts') or []) if a.get('type') == 'OUT_OF_SEQUENCE_VISIT']
    assert len(oos) == 1
    assert oos[0]['plate'] == '34 R13 001'
    assert oos[0]['vehicle_id'] == 'TEST_R13_VEHICLE'
    assert 'Plaka' not in (oos[0].get('message') or '') or 'TEST_R13_VEHICLE' not in oos[0]['plate']


def test_out_of_sequence_alert_list_and_sort(geo_db):
    fx = _run_oos_visit(geo_db)
    from modules.planlama.arac_geofence_repo import list_out_of_sequence_visit_alerts_for_date
    from modules.planlama.arac_today_operations_service import _sort_alerts_for_display

    rows = list_out_of_sequence_visit_alerts_for_date(fx['plan_date'])
    assert len(rows) == 1
    sorted_alerts = _sort_alerts_for_display([
        {'type': 'GPS_STALE', 'severity': 'warning'},
        {'type': 'OUT_OF_SEQUENCE_VISIT', 'severity': 'warning', 'event_id': rows[0]['event_id']},
        {'type': 'MISSING_LOCATION', 'severity': 'info'},
    ])
    assert sorted_alerts[0]['type'] == 'OUT_OF_SEQUENCE_VISIT'


def test_history_plan_detail_includes_oos_alerts(geo_db):
    fx = _run_oos_arrived_only(geo_db)
    from modules.planlama.arac_takip_repo import get_history_plan_detail

    detail = get_history_plan_detail(fx['plan_id'])
    assert detail.get('ok') is True
    alerts = detail.get('out_of_sequence_alerts') or []
    assert len(alerts) == 1
    assert alerts[0]['expected_stop'] == 'Violet Etiket'
    assert alerts[0]['actual_stop'] == 'Beyazit Tekstil'
    assert alerts[0].get('olay_zamani')


def test_out_of_sequence_alert_ack_dedupe(geo_db):
    fx = _run_oos_visit(geo_db)
    from modules.planlama.arac_geofence_repo import (
        acknowledge_geofence_event,
        list_out_of_sequence_visit_alerts_for_date,
    )

    rows = list_out_of_sequence_visit_alerts_for_date(fx['plan_date'])
    eid = rows[0]['event_id']
    assert acknowledge_geofence_event(eid, acknowledged_by='test') is True
    assert list_out_of_sequence_visit_alerts_for_date(fx['plan_date']) == []
    assert acknowledge_geofence_event(eid, acknowledged_by='test') is True
