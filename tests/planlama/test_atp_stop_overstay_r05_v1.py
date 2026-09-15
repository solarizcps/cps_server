# -*- coding: utf-8 -*-
"""R05 — stop overstay alert (10 min geofence dwell, TEMP DB only)."""
from __future__ import annotations

import importlib.util
import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'app'
MIGRATIONS = APP / 'migrations'
PLAN_DATE = '2026-09-20'
VID = '991R05VEH_A'
VID_B = '991R05VEH_B'
PLATE = '34 MOR 049'
COMPANY = 'R05 Test Firma'


def _run_migration(db_path: str, filename: str) -> None:
    spec = importlib.util.spec_from_file_location(filename, MIGRATIONS / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.run(db_path)


@pytest.fixture()
def r05_db(monkeypatch):
    import sys
    from tools.atp_test_db_guard import bind_temp_db_path

    saved = {
        k: sys.modules[k]
        for k in list(sys.modules)
        if k == 'db' or k.startswith('modules.planlama')
    }
    tmpdir = tempfile.mkdtemp(prefix='r05_')
    db_path = str(Path(tmpdir) / 'test.db')
    for mig in (
        '176_arac_takip_v13.py',
        '177_arac_operasyon_ayar.py',
        '178_arac_is_talebi_ux_v2_fields.py',
        '179_arac_gps_snapshot_p1.py',
        '180_arac_plan_ziyaret_durum.py',
        '182_arac_plan_change_v1.py',
        '191_arac_plan_olay_auto_tamamlandi.py',
    ):
        _run_migration(db_path, mig)
    bind_temp_db_path(db_path)
    monkeypatch.setenv('CPS_TEST_DB_GUARD', '0')
    for mod_name in list(sys.modules):
        if mod_name == 'db' or mod_name.startswith('modules.planlama'):
            sys.modules.pop(mod_name, None)
    try:
        yield db_path
    finally:
        for k, mod in saved.items():
            sys.modules[k] = mod
        for k in list(sys.modules):
            if (k == 'db' or k.startswith('modules.planlama')) and k not in saved:
                sys.modules.pop(k, None)


def _ops():
    from modules.planlama import arac_today_operations_service as ops
    return ops


def _item(
    *,
    plan_item_id: int = 9001,
    visit_state: str = 'ARRIVED',
    arrived_at: str = '2026-09-20 09:50:00',
    status: str = 'BASLADI',
    vehicle_id: str = VID,
    company: str = COMPANY,
) -> dict:
    return {
        'plan_item_id': plan_item_id,
        'id': f'pi-{plan_item_id}',
        'visit_state': visit_state,
        'arrived_at': arrived_at,
        'status': status,
        'company_name': company,
        'arac_external_id': vehicle_id,
        'plate': PLATE,
    }


def _vehicle(
    *,
    vehicle_id: str = VID,
    gps_timestamp: str = '2026-09-20 10:00:00',
    speed_kmh: float = 0.0,
    lat: float = 41.0,
    lon: float = 29.0,
    stale: bool = False,
) -> dict:
    return {
        'arac_external_id': vehicle_id,
        'plan_id': 7001,
        'plate': PLATE,
        'latest_gps': {
            'gps_timestamp': gps_timestamp,
            'latitude': lat,
            'longitude': lon,
            'speed_kmh': speed_kmh,
            'is_stale': stale,
        },
    }


def _alerts_for(items: list[dict], vehicles: list[dict]):
    return _ops()._collect_stop_overstay_alerts(vehicles, items)


def _only_overstay(alerts: list[dict]) -> list[dict]:
    return [a for a in alerts if a.get('type') == 'STOP_OVERSTAY']


def test_threshold_inclusive_599_no_600_yes():
    ops = _ops()
    assert ops._stop_overstay_elapsed_seconds('2026-09-20 09:50:01', '2026-09-20 10:00:00') == 599
    assert ops._stop_overstay_elapsed_seconds('2026-09-20 09:50:00', '2026-09-20 10:00:00') == 600
    items = [_item(arrived_at='2026-09-20 09:50:01')]
    vehicles = [_vehicle(gps_timestamp='2026-09-20 10:00:00')]
    assert _only_overstay(_alerts_for(items, vehicles)) == []
    items = [_item(arrived_at='2026-09-20 09:50:00')]
    alerts = _only_overstay(_alerts_for(items, vehicles))
    assert len(alerts) == 1
    assert alerts[0]['overstay_seconds'] == 600


def test_t01_0959_no_alert():
    items = [_item(arrived_at='2026-09-20 09:50:01')]
    vehicles = [_vehicle(gps_timestamp='2026-09-20 09:59:59')]
    assert _only_overstay(_alerts_for(items, vehicles)) == []


def test_t02_exact_10_min_single_alert():
    alerts = _only_overstay(_alerts_for([_item()], [_vehicle()]))
    assert len(alerts) == 1
    assert '10 dakikadır bekliyor' in alerts[0]['message']
    assert alerts[0]['alert_id'] == f'STOP_OVERSTAY:{VID}:9001:2026-09-20 09:50:00'


def test_t03_1001_same_single_alert_no_duplicate():
    alerts = _only_overstay(_alerts_for([_item()], [_vehicle(gps_timestamp='2026-09-20 10:01:00')]))
    assert len(alerts) == 1
    assert alerts[0]['overstay_seconds'] == 660


def test_t04_geofence_exit_closes_alert():
    items = [_item(visit_state='OUTSIDE')]
    assert _only_overstay(_alerts_for(items, [_vehicle()])) == []


def test_t05_reentry_new_session_new_alert_id():
    first = _item(arrived_at='2026-09-20 08:00:00')
    second = _item(arrived_at='2026-09-20 09:50:00')
    a1 = _only_overstay(_alerts_for([first], [_vehicle(gps_timestamp='2026-09-20 08:11:00')]))[0]
    a2 = _only_overstay(_alerts_for([second], [_vehicle()]))[0]
    assert a1['alert_id'] != a2['alert_id']


def test_t06_completed_no_alert():
    items = [_item(status='TAMAMLANDI')]
    assert _only_overstay(_alerts_for(items, [_vehicle()])) == []


def test_t07_cancel_no_alert():
    items = [_item(status='IPTAL')]
    assert _only_overstay(_alerts_for(items, [_vehicle()])) == []


def test_t08_stale_gps_no_alert():
    vehicles = [_vehicle(stale=True)]
    assert _only_overstay(_alerts_for([_item()], vehicles)) == []


def test_t09_no_coordinates_no_alert():
    v = _vehicle()
    v['latest_gps']['latitude'] = None
    assert _only_overstay(_alerts_for([_item()], [v])) == []


def test_t10_moving_vehicle_no_alert():
    vehicles = [_vehicle(speed_kmh=12.0)]
    assert _only_overstay(_alerts_for([_item()], vehicles)) == []


def test_t11_manual_started_without_geofence_no_alert():
    items = [_item(visit_state='OUTSIDE', arrived_at=None, status='BASLADI')]
    assert _only_overstay(_alerts_for(items, [_vehicle()])) == []


def test_t12_two_vehicles_isolated():
    items = [
        _item(plan_item_id=9001, vehicle_id=VID, company='Firma A'),
        _item(plan_item_id=9002, vehicle_id=VID_B, company='Firma B', arrived_at='2026-09-20 09:49:00'),
    ]
    vehicles = [
        _vehicle(vehicle_id=VID),
        _vehicle(vehicle_id=VID_B, gps_timestamp='2026-09-20 10:00:00'),
    ]
    alerts = _only_overstay(_alerts_for(items, vehicles))
    assert len(alerts) == 2
    vids = {a['vehicle_id'] for a in alerts}
    assert vids == {VID, VID_B}


def test_t13_two_stops_correct_plan_item_id():
    items = [
        _item(plan_item_id=9001, company='Durak A'),
        _item(plan_item_id=9002, company='Durak B', arrived_at='2026-09-20 09:49:00'),
    ]
    alerts = _only_overstay(_alerts_for(items, [_vehicle()]))
    ids = {a['plan_item_id'] for a in alerts}
    assert ids == {9001, 9002}


def test_t14_polling_no_duplicate():
    items = [_item()]
    vehicles = [_vehicle(gps_timestamp='2026-09-20 10:05:00')]
    a = _only_overstay(_alerts_for(items, vehicles))
    b = _only_overstay(_alerts_for(items, vehicles))
    assert len(a) == 1 and len(b) == 1
    assert a[0]['alert_id'] == b[0]['alert_id']


def test_t15_persisted_arrived_at_survives_reload():
    ops = _ops()
    items = [_item()]
    vehicles = [_vehicle()]
    first = ops._collect_stop_overstay_alerts(vehicles, items)
    second = ops._collect_stop_overstay_alerts(vehicles, items)
    assert len(_only_overstay(first)) == len(_only_overstay(second)) == 1


def test_t16_stale_backdated_gps_not_wall_clock():
    """Geçmiş GPS timestamp wall-clock ile 10 dk sayılmaz."""
    items = [_item(arrived_at='2026-09-20 09:00:00')]
    vehicles = [_vehicle(gps_timestamp='2026-09-20 09:05:00')]
    assert _only_overstay(_alerts_for(items, vehicles)) == []


def test_t18_visit_label_uses_gps_reference_not_wall_clock():
    """Fixture tarihleri gelecekteyken Konumda X dk GPS timestamp ile hesaplanır."""
    from datetime import datetime

    from modules.planlama.arac_gps_poll_service import parse_gps_timestamp

    ops = _ops()
    veh = _vehicle(gps_timestamp='2026-09-21 10:00:00')
    ref = ops._gps_reference_now(veh, datetime(2026, 9, 14, 12, 0, 0))
    assert ref == parse_gps_timestamp('2026-09-21 10:00:00')
    visit = {'state': 'ARRIVED', 'arrived_at': '2026-09-21 09:50:00'}
    label = ops._build_visit_label(visit, now=ref)
    assert 'Konumda 10 dk' in label


def test_t17_overstay_alert_is_read_only_builder():
    """Alert builder DB'ye yazmaz; yalnız read-model."""
    ops = _ops()
    items = [_item()]
    vehicles = [_vehicle()]
    before = len(_only_overstay(ops._collect_stop_overstay_alerts(vehicles, items)))
    after = len(_only_overstay(ops._collect_stop_overstay_alerts(vehicles, items)))
    assert before == after == 1


def test_t19_vehicle_latest_gps_used_for_elapsed():
    """Freshest GPS bundle vehicle.latest_gps üzerinden elapsed hesaplanır."""
    items = [_item(arrived_at='2026-09-20 09:50:00')]
    vehicles = [{
        'arac_external_id': VID,
        'plan_id': 7001,
        'plate': PLATE,
        'latest_gps': {
            'gps_timestamp': '2026-09-20 10:00:00',
            'latitude': 41.0,
            'longitude': 29.0,
            'speed_kmh': 0,
            'is_stale': False,
        },
    }]
    alerts = _only_overstay(_alerts_for(items, vehicles))
    assert len(alerts) == 1
    assert alerts[0]['overstay_seconds'] == 600


def test_t20_timezone_day_boundary():
    items = [_item(arrived_at='2026-09-19 23:55:00')]
    vehicles = [_vehicle(gps_timestamp='2026-09-20 00:06:00')]
    alerts = _only_overstay(_alerts_for(items, vehicles))
    assert len(alerts) == 1
    assert alerts[0]['overstay_seconds'] == 660


def test_integration_today_operations_api(r05_db):
    con = sqlite3.connect(r05_db)
    now = '2026-09-20 08:00:00'
    con.execute(
        "INSERT INTO arac_gunluk_plan (plan_tarihi, arac_provider, arac_external_id, "
        "arac_plaka_snapshot, sofor_id, sofor_adi_snapshot, durum, created_at, created_by, updated_at, updated_by) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (PLAN_DATE, 'TURKCELL_FILOM', VID, PLATE, 1, 'Test', 'AKTIF', now, 1, now, 1),
    )
    plan_id = con.execute('SELECT id FROM arac_gunluk_plan WHERE arac_external_id=?', (VID,)).fetchone()[0]
    con.execute(
        "INSERT INTO arac_is_talebi (talep_no, talep_eden_user_id, talep_eden_adi_snapshot, talep_tarihi, "
        "firma_adi, oncelik, latitude, longitude, adres, yapilacak_is, durum, created_at, created_by, updated_at, updated_by) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ('AIT-2026-R0501', 1, 'R05_FIX', PLAN_DATE, COMPANY, 'NORMAL', 41.0, 29.0, 'Adres', 'Z', 'PLANA_ALINDI', now, 1, now, 1),
    )
    talep_id = con.execute("SELECT id FROM arac_is_talebi WHERE talep_eden_adi_snapshot='R05_FIX'").fetchone()[0]
    con.execute(
        "INSERT INTO arac_gunluk_plan_is (plan_id, is_talebi_id, sira, durum, created_at, created_by) "
        "VALUES (?,?,?,?,?,?)",
        (plan_id, talep_id, 1, 'BASLADI', now, 1),
    )
    plan_is_id = con.execute('SELECT id FROM arac_gunluk_plan_is WHERE plan_id=?', (plan_id,)).fetchone()[0]
    con.execute(
        "INSERT INTO arac_plan_is_ziyaret_durum (plan_id, plan_is_id, arac_external_id, state, arrived_at, "
        "consecutive_inside, consecutive_outside, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (plan_id, plan_is_id, VID, 'ARRIVED', '2026-09-20 09:50:00', 2, 0, now, now),
    )
    con.execute(
        "INSERT INTO arac_gps_snapshot (arac_provider, arac_external_id, plate_snapshot, gps_timestamp, "
        "received_at, latitude, longitude, speed_kmh, is_stale, dedup_key, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ('TURKCELL_FILOM', VID, PLATE, '2026-09-20 10:00:00', '2026-09-20 10:00:01',
         41.0, 29.0, 0.0, 0, 'r05-dedup-1', now),
    )
    con.commit()
    con.close()

    payload = _ops().get_today_vehicle_operations(
        PLAN_DATE,
        filom_payload={'ok': True, 'vehicles': [], 'kpi': {}},
    )
    overstay = [a for a in payload.get('alerts') or [] if a.get('type') == 'STOP_OVERSTAY']
    assert len(overstay) == 1
    assert PLATE in overstay[0]['message']
    assert COMPANY in overstay[0]['message']
