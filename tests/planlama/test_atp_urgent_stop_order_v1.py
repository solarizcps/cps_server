# -*- coding: utf-8 -*-
"""ATP_URGENT_STOP_ORDER_NARROW_FIX_V1 — T01-T20 matrix + consumer parity (temp DB only)."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

_APP_DIR = Path(__file__).resolve().parents[2] / 'app'
_MIGRATIONS = _APP_DIR / 'migrations'
CANONICAL_DB = Path(r'C:\Solariz_CPS_SERVER\app\mock_data.db')
PLAN_DATE = '2026-09-14'
VEHICLE = '45077045'
OTHER_VEHICLE = '45077046'
PLAKA = '34 MOR 049'
NOW = '2026-09-14 10:00:00'
USER_ID = 1

FILOM_FIXTURE = {
    'ok': True,
    'vehicles': [{'id': VEHICLE, 'plate': '34MOR049', 'plate_display': PLAKA, 'driver_name': 'test'}],
}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def _run_migration(db_path: str, filename: str) -> None:
    spec = importlib.util.spec_from_file_location(filename, _MIGRATIONS / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.run(db_path)


@contextmanager
def _temp_atp_db(*, with_rota: bool = False):
    tmpdir = tempfile.mkdtemp(prefix='urgent_order_v1_')
    db_path = str(Path(tmpdir) / 'test.db')
    migs = [
        '176_arac_takip_v13.py',
        '177_arac_operasyon_ayar.py',
        '178_arac_is_talebi_ux_v2_fields.py',
        '180_arac_plan_ziyaret_durum.py',
        '182_arac_plan_change_v1.py',
    ]
    if with_rota:
        migs.append('179_arac_gps_snapshot_p1.py')
    for mig in migs:
        _run_migration(db_path, mig)
    import config
    with patch.object(config.Config, 'MOCK_DB_PATH', db_path):
        yield db_path


def _conn(db_path: str) -> sqlite3.Connection:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    return con


def _seed_location(con: sqlite3.Connection) -> int:
    cur = con.execute(
        """
        INSERT INTO arac_kayitli_yer (
            firma_adi, adres, latitude, longitude, aktif, kullanim_sayisi, created_at, created_by
        ) VALUES (?,?,?,?,1,0,?,?)
        """,
        ('Test Firma', 'Test Adres Istanbul', 41.01, 29.01, NOW, USER_ID),
    )
    return int(cur.lastrowid)


def _seed_talep(con, *, oncelik='NORMAL', durum='BEKLIYOR', yapilacak_is='Is', suffix='', created_at=None):
    loc_id = _seed_location(con)
    talep_no = f'UO-{oncelik}-{suffix}-{con.total_changes}'
    ts = created_at or NOW
    cur = con.execute(
        """
        INSERT INTO arac_is_talebi (
            talep_no, talep_eden_user_id, talep_eden_adi_snapshot, talep_tarihi,
            kayitli_yer_id, firma_adi, adres, latitude, longitude, yapilacak_is,
            oncelik, durum, save_to_master, created_at, created_by, updated_at, updated_by
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0,?,?,?,?)
        """,
        (talep_no, USER_ID, 'User', PLAN_DATE, loc_id, yapilacak_is, 'Adres',
         41.01, 29.01, yapilacak_is, oncelik, durum, ts, USER_ID, ts, USER_ID),
    )
    return int(cur.lastrowid)


def _seed_plan(con, vehicle=VEHICLE, plan_date=PLAN_DATE):
    cur = con.execute(
        """
        INSERT INTO arac_gunluk_plan (
            plan_tarihi, arac_provider, arac_external_id, arac_plaka_snapshot,
            durum, created_at, created_by, updated_at, updated_by
        ) VALUES (?,?,?,?,'AKTIF',?,?,?,?)
        """,
        (plan_date, 'TURKCELL_FILOM', vehicle, PLAKA, NOW, USER_ID, NOW, USER_ID),
    )
    return int(cur.lastrowid)


def _seed_plan_item(con, plan_id, talep_id, sira, durum='PLANLANDI', created_at=None):
    ts = created_at or NOW
    cur = con.execute(
        """
        INSERT INTO arac_gunluk_plan_is (
            plan_id, is_talebi_id, sira, durum, created_at, created_by
        ) VALUES (?,?,?,?,?,?)
        """,
        (plan_id, talep_id, sira, durum, ts, USER_ID),
    )
    return int(cur.lastrowid)


def _seed_visit(con, plan_id, plan_is_id, state, arrived_at=None):
    con.execute(
        """
        INSERT INTO arac_plan_is_ziyaret_durum (
            plan_id, plan_is_id, arac_external_id, state,
            geofence_radius_m, exit_radius_m, consecutive_inside, consecutive_outside,
            arrived_at, updated_at, created_at
        ) VALUES (?,?,?,?,200,250,0,0,?,?,?)
        """,
        (plan_id, plan_is_id, VEHICLE, state, arrived_at, NOW, NOW),
    )


def _acil_payload(**kw):
    p = {
        'plan_tarihi': PLAN_DATE, 'arac_external_id': VEHICLE,
        'firma': 'Acil Firma', 'adres': 'Acil Adres Istanbul',
        'yapilacak_is': 'Acil Is', 'latitude': 41.02, 'longitude': 29.02,
        'oncelik': 'ACIL',
    }
    p.update(kw)
    return p


def _ordered_firmas(db_path, plan_id):
    con = _conn(db_path)
    try:
        rows = con.execute(
            """
            SELECT t.firma_adi, pi.sira FROM arac_gunluk_plan_is pi
            JOIN arac_is_talebi t ON t.id=pi.is_talebi_id
            WHERE pi.plan_id=? ORDER BY pi.sira
            """,
            (plan_id,),
        ).fetchall()
        return [(r['firma_adi'], int(r['sira'])) for r in rows]
    finally:
        con.close()


@pytest.fixture(autouse=True)
def _filom_catalog():
    from modules.planlama.arac_vehicle_identity_service import update_filom_vehicle_catalog
    update_filom_vehicle_catalog(FILOM_FIXTURE['vehicles'])
    yield
    update_filom_vehicle_catalog([])


@patch('modules.planlama.arac_operasyonu.services.turkcell_filom_adapter.get_live_vehicles', return_value=FILOM_FIXTURE)
class TestUrgentStopOrderMatrix:
    def test_t01_empty_plan_acil_sira_1(self, _m):
        with _temp_atp_db() as db:
            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
            r = add_job_to_plan_atomic(USER_ID, _acil_payload(client_submit_id='t01'))
            con = _conn(db)
            sira = con.execute('SELECT sira FROM arac_gunluk_plan_is WHERE id=?', (r['plan_is_id'],)).fetchone()['sira']
            assert int(sira) == 1

    def test_t02_normal_varken_acil_ilk_acik(self, _m):
        with _temp_atp_db() as db:
            con = _conn(db)
            pid = _seed_plan(con)
            for i in range(1, 4):
                tid = _seed_talep(con, yapilacak_is=f'N{i}', suffix=str(i))
                _seed_plan_item(con, pid, tid, i)
            con.commit()
            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
            r = add_job_to_plan_atomic(USER_ID, _acil_payload(client_submit_id='t02'))
            assert _ordered_firmas(db, pid)[0][1] == 1  # ACIL first

    def test_t03_yuksek_varken_acil_once(self, _m):
        with _temp_atp_db() as db:
            con = _conn(db)
            pid = _seed_plan(con)
            y = _seed_talep(con, oncelik='YUKSEK', yapilacak_is='Yuksek1', suffix='y')
            _seed_plan_item(con, pid, y, 1)
            con.commit()
            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
            add_job_to_plan_atomic(USER_ID, _acil_payload(client_submit_id='t03'))
            order = _ordered_firmas(db, pid)
            assert order[0][0] == 'Acil Firma'
            assert order[1][0] == 'Yuksek1'

    def test_t04_basladi_sonrasi_acil(self, _m):
        with _temp_atp_db() as db:
            con = _conn(db)
            pid = _seed_plan(con)
            t1 = _seed_talep(con, yapilacak_is='Started', suffix='s')
            _seed_plan_item(con, pid, t1, 1, durum='BASLADI')
            t2 = _seed_talep(con, yapilacak_is='Normal', suffix='n')
            _seed_plan_item(con, pid, t2, 2)
            con.commit()
            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
            r = add_job_to_plan_atomic(USER_ID, _acil_payload(client_submit_id='t04'))
            con = _conn(db)
            sira = int(con.execute('SELECT sira FROM arac_gunluk_plan_is WHERE id=?', (r['plan_is_id'],)).fetchone()['sira'])
            assert sira == 2

    def test_t07_second_acil_fifo(self, _m):
        with _temp_atp_db() as db:
            con = _conn(db)
            pid = _seed_plan(con)
            d = _seed_talep(con, yapilacak_is='Done', suffix='d')
            _seed_plan_item(con, pid, d, 1, durum='TAMAMLANDI')
            n = _seed_talep(con, yapilacak_is='Norm', suffix='n')
            _seed_plan_item(con, pid, n, 2)
            con.commit()
            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
            r1 = add_job_to_plan_atomic(USER_ID, _acil_payload(firma='Acil1', client_submit_id='t07a'))
            r2 = add_job_to_plan_atomic(USER_ID, _acil_payload(firma='Acil2', client_submit_id='t07b'))
            con = _conn(db)
            s1 = int(con.execute('SELECT sira FROM arac_gunluk_plan_is WHERE id=?', (r1['plan_is_id'],)).fetchone()['sira'])
            s2 = int(con.execute('SELECT sira FROM arac_gunluk_plan_is WHERE id=?', (r2['plan_is_id'],)).fetchone()['sira'])
            assert s1 == 2 and s2 == 3

    def test_t09_yuksek_append(self, _m):
        with _temp_atp_db() as db:
            con = _conn(db)
            pid = _seed_plan(con)
            n = _seed_talep(con, yapilacak_is='N1', suffix='n')
            _seed_plan_item(con, pid, n, 1)
            con.commit()
            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
            r = add_job_to_plan_atomic(USER_ID, _acil_payload(
                oncelik='YUKSEK', firma='YuksekNew', yapilacak_is='Yuksek Is', client_submit_id='t09'))
            con = _conn(db)
            sira = int(con.execute('SELECT sira FROM arac_gunluk_plan_is WHERE id=?', (r['plan_is_id'],)).fetchone()['sira'])
            assert sira == 2

    def test_t10_snapshot_invalidate_rebuild_required(self, _m):
        with _temp_atp_db(with_rota=True) as db:
            con = _conn(db)
            pid = _seed_plan(con)
            n = _seed_talep(con, yapilacak_is='N', suffix='n')
            _seed_plan_item(con, pid, n, 1)
            con.execute(
                """
                INSERT INTO arac_plan_rota_snapshot (
                    plan_id, route_version, is_active, stop_order_json, geometry_json, created_at
                ) VALUES (?,1,1,'[]','{"type":"LineString","coordinates":[]}',?)
                """,
                (pid, NOW),
            )
            con.commit()
            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
            r = add_job_to_plan_atomic(USER_ID, _acil_payload(client_submit_id='t10'))
            assert r.get('route_rebuild_required') is True
            con = _conn(db)
            active = con.execute(
                'SELECT COUNT(*) c FROM arac_plan_rota_snapshot WHERE plan_id=? AND is_active=1', (pid,),
            ).fetchone()['c']
            assert int(active) == 0

    def test_t11_whatsapp_order_matches_db(self, _m):
        with _temp_atp_db() as db:
            con = _conn(db)
            pid = _seed_plan(con)
            for i, name in enumerate(['Tam', 'Bas', 'AcilEski', 'N1', 'N2'], 1):
                on = 'ACIL' if name == 'AcilEski' else 'NORMAL'
                st = 'TAMAMLANDI' if name == 'Tam' else ('BASLADI' if name == 'Bas' else 'PLANLANDI')
                tid = _seed_talep(con, oncelik=on, yapilacak_is=name, suffix=name)
                _seed_plan_item(con, pid, tid, i, durum=st)
            con.commit()
            from modules.planlama.arac_whatsapp_message_service import load_whatsapp_plan_context
            ctx = load_whatsapp_plan_context(PLAN_DATE, VEHICLE)
            wa_ids = [s.get('order_no') for s in ctx['stops']]
            from modules.planlama.arac_takip_repo import list_plan_tasks
            db_ids = [t['order_no'] for t in list_plan_tasks(PLAN_DATE, VEHICLE)]
            assert wa_ids == db_ids

    def test_t13_next_stop_first_open_sira(self, _m):
        with _temp_atp_db() as db:
            con = _conn(db)
            pid = _seed_plan(con)
            t1 = _seed_talep(con, yapilacak_is='Done', suffix='d')
            _seed_plan_item(con, pid, t1, 1, durum='TAMAMLANDI')
            t2 = _seed_talep(con, yapilacak_is='Active', suffix='a')
            _seed_plan_item(con, pid, t2, 2, durum='BASLADI')
            t3 = _seed_talep(con, oncelik='ACIL', yapilacak_is='AcilQ', suffix='q')
            _seed_plan_item(con, pid, t3, 3)
            con.commit()
            from modules.planlama.arac_takip_repo import list_plans_for_date
            plans = list_plans_for_date(PLAN_DATE)
            nxt = plans[0]['next_item']
            assert nxt['order_no'] == 2  # BASLADI first open by sira

    def test_t14_plan_isolation(self, _m):
        with _temp_atp_db() as db:
            con = _conn(db)
            p1 = _seed_plan(con, vehicle=VEHICLE)
            p2 = _seed_plan(con, vehicle=OTHER_VEHICLE)
            t1 = _seed_talep(con, yapilacak_is='A', suffix='a')
            _seed_plan_item(con, p1, t1, 1)
            t2 = _seed_talep(con, yapilacak_is='B', suffix='b')
            _seed_plan_item(con, p2, t2, 1)
            con.commit()
            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
            add_job_to_plan_atomic(USER_ID, _acil_payload(client_submit_id='t14'))
            assert len(_ordered_firmas(db, p2)) == 1
            assert _ordered_firmas(db, p1)[0][1] == 1

    def test_t15_no_duplicate_sira(self, _m):
        with _temp_atp_db() as db:
            con = _conn(db)
            pid = _seed_plan(con)
            for i in range(1, 3):
                tid = _seed_talep(con, yapilacak_is=f'X{i}', suffix=str(i))
                _seed_plan_item(con, pid, tid, i)
            con.commit()
            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
            add_job_to_plan_atomic(USER_ID, _acil_payload(client_submit_id='t15'))
            con = _conn(db)
            siras = [int(r[0]) for r in con.execute(
                'SELECT sira FROM arac_gunluk_plan_is WHERE plan_id=? ORDER BY sira', (pid,),
            ).fetchall()]
            assert len(siras) == len(set(siras))

    def test_screen_scenario_consumer_parity(self, _m):
        """Real screen: TAM, BASLADI, existing ACIL, 2 NORMAL, then new ACIL."""
        with _temp_atp_db() as db:
            con = _conn(db)
            pid = _seed_plan(con)
            t_done = _seed_talep(con, yapilacak_is='Tamam', suffix='done')
            _seed_plan_item(con, pid, t_done, 1, durum='TAMAMLANDI')
            t_bas = _seed_talep(con, yapilacak_is='Basladi', suffix='bas')
            _seed_plan_item(con, pid, t_bas, 2, durum='BASLADI')
            t_acil_old = _seed_talep(con, oncelik='ACIL', yapilacak_is='EskiAcil', suffix='ao',
                                     created_at='2026-09-14 09:00:00')
            _seed_plan_item(con, pid, t_acil_old, 3, created_at='2026-09-14 09:00:00')
            t_n1 = _seed_talep(con, yapilacak_is='Normal1', suffix='n1')
            _seed_plan_item(con, pid, t_n1, 4)
            t_n2 = _seed_talep(con, yapilacak_is='Normal2', suffix='n2')
            _seed_plan_item(con, pid, t_n2, 5)
            con.commit()
            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
            add_job_to_plan_atomic(USER_ID, _acil_payload(
                firma='YeniAcil', yapilacak_is='YeniAcil', client_submit_id='screen'))
            expected = ['Tamam', 'Basladi', 'EskiAcil', 'YeniAcil', 'Normal1', 'Normal2']
            names = [x[0] for x in _ordered_firmas(db, pid)]
            assert names == expected

            from modules.planlama.arac_takip_repo import list_plan_tasks, list_plans_for_date, _pick_next_task
            from modules.planlama.arac_dashboard_service import _build_plan_map_dto
            from modules.planlama.arac_whatsapp_message_service import load_whatsapp_plan_context, sort_stops_for_whatsapp

            tasks = list_plan_tasks(PLAN_DATE, VEHICLE)
            list_names = [t['company_name'] for t in tasks]
            assert list_names == expected

            plans = list_plans_for_date(PLAN_DATE)
            plan_names = [t['company_name'] for t in plans[0]['items']]
            assert plan_names == expected

            nxt = _pick_next_task(tasks)
            assert nxt['company_name'] == 'Basladi'
            assert nxt['order_no'] == 2

            wa = load_whatsapp_plan_context(PLAN_DATE, VEHICLE)
            wa_names = [s['company_name'] for s in sort_stops_for_whatsapp(tasks)]
            assert wa_names == expected

            map_dto = _build_plan_map_dto(tasks, None)
            map_names = [s['company_name'] for s in map_dto['stops']]
            assert map_names == expected


def test_t20_canonical_db_write_guard():
    assert CANONICAL_DB.is_file()
    before = _sha256(CANONICAL_DB)
    with _temp_atp_db() as db:
        con = _conn(db)
        _seed_plan(con)
        con.commit()
    after = _sha256(CANONICAL_DB)
    assert before == after
