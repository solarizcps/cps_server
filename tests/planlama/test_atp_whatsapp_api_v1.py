# -*- coding: utf-8 -*-
"""ATP WhatsApp API — validation, auth, multi-vehicle isolation, DB fingerprint."""
from __future__ import annotations

import importlib.util
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
import urllib.parse

import pytest

APP = Path(__file__).resolve().parents[2] / 'app'
MIGS = APP / 'migrations'
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP.parent / 'tests' / 'planlama'))

from atp_canonical_forensic import assert_canonical_atp_unchanged, canonical_logical_snapshot
from atp_plan2_fixture import PLAN_DATE, PLAN_ID, VEHICLE, insert_factory_base, seed_plan2_fixture
from tools.nexgen_tmp_db import assert_resolved_db_is_tmp

CANONICAL_SOURCE = Path(os.environ.get(
    'CPS_CANONICAL_DB_SOURCE',
    r'C:\Solariz_CPS_SERVER\app\mock_data.db',
))
MIG189 = MIGS / '189_planlama_arac_takip_rol32_yetki.py'
URL = '/planlama/arac-takip/api/whatsapp'
OTHER_VEHICLE = '990DEMO001'


def _load_migration(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _user(con: sqlite3.Connection, uid: int) -> dict:
    con.row_factory = sqlite3.Row
    r = con.execute(
        """
        SELECT Id,KullaniciAdi,AdSoyad,RolId,Aktif,Tip,ZorunluSifreDegistir,AuthVersion
        FROM sistem_kullanici WHERE Id=?
        """,
        (uid,),
    ).fetchone()
    return {
        'Id': r[0], 'KullaniciAdi': r[1], 'AdSoyad': r[2], 'RolId': r[3],
        'Aktif': r[4], 'Tip': r[5],
        'ZorunluSifreDegistir': int(r[6] or 0), 'AuthVersion': int(r[7] or 1),
    }


def _login(client, user: dict):
    with client.session_transaction() as sess:
        sess['kullanici'] = user
        sess['auth_version'] = user.get('AuthVersion', 1)


@pytest.fixture
def env():
    live = str(CANONICAL_SOURCE.resolve())
    if not os.path.isfile(live):
        pytest.skip(f'canonical missing: {live}')
    logical_before = canonical_logical_snapshot(live)
    tmp_dir = tempfile.mkdtemp(prefix='atp_whatsapp_api_')
    db = os.path.join(tmp_dir, 'mock_data_test.db')
    shutil.copy2(live, db)
    assert_resolved_db_is_tmp(db, live)
    con = sqlite3.connect(db)
    con.execute('DELETE FROM user_permission_override WHERE KullaniciId=31')
    con.commit()
    con.close()
    _load_migration(MIG189).run(db)
    os.environ['CPS_MOCK_DB_PATH'] = db
    os.environ['CPS_TEST_DB_GUARD'] = '1'
    import config as cfg
    cfg.Config.MOCK_DB_PATH = db
    yield {'db': db, 'live': live, 'logical_before': logical_before, 'tmp_dir': tmp_dir}
    assert_canonical_atp_unchanged(live, logical_before)
    shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest.fixture
def client(env):
    import importlib
    import config as cfg
    cfg.Config.MOCK_DB_PATH = env['db']
    os.environ['CPS_MOCK_DB_PATH'] = env['db']
    import modules.auth as auth_mod
    importlib.reload(auth_mod)
    from modules.planlama import arac_takip_routes as routes_mod
    importlib.reload(routes_mod)
    import app as flask_app
    flask_app.app.config['TESTING'] = True
    return flask_app.app.test_client()


def _prepare_plan(env, *, vehicle: str = VEHICLE, plan_date: str = PLAN_DATE) -> None:
    con = sqlite3.connect(env['db'])
    if vehicle == VEHICLE:
        seed_plan2_fixture(con, with_coords=True)
    else:
        from datetime import datetime
        now = datetime.now().replace(microsecond=0).isoformat(sep=' ')
        con.execute(
            'DELETE FROM arac_gunluk_plan_is WHERE plan_id IN '
            '(SELECT id FROM arac_gunluk_plan WHERE plan_tarihi=? AND arac_external_id=?)',
            (plan_date, vehicle),
        )
        con.execute(
            'DELETE FROM arac_gunluk_plan WHERE plan_tarihi=? AND arac_external_id=?',
            (plan_date, vehicle),
        )
        cur = con.execute(
            """
            INSERT INTO arac_gunluk_plan (
                plan_tarihi, arac_provider, arac_external_id, arac_plaka_snapshot,
                sofor_adi_snapshot, durum, cikis_saati, created_at, created_by, updated_at, updated_by
            ) VALUES (?,'TURKCELL_FILOM',?,?,?,'AKTIF','08:00',?,?,?,?)
            """,
            (plan_date, vehicle, '34 DEMO 001', 'Other Driver', now, 1, now, 1),
        )
        plan_id = int(cur.lastrowid)
        tcur = con.execute(
            """
            INSERT INTO arac_is_talebi (
                talep_no, talep_eden_user_id, talep_eden_adi_snapshot, talep_tarihi,
                firma_adi, adres, yapilacak_is, oncelik, durum, save_to_master,
                created_at, created_by, updated_at, updated_by
            ) VALUES (?,?,?,?,?,?,?,?,'PLANA_ALINDI',0,?,?,?,?)
            """,
            (f'OTH-{vehicle}', 1, 'Test', plan_date, 'Other Firma', 'Other adres', 'Other is', 'NORMAL', now, 1, now, 1),
        )
        con.execute(
            """
            INSERT INTO arac_gunluk_plan_is (plan_id, is_talebi_id, sira, durum, created_at, created_by)
            VALUES (?,?,1,'PLANLANDI',?,?)
            """,
            (plan_id, int(tcur.lastrowid), now, 1),
        )
    insert_factory_base(
        con, base_name='Solariz Fabrika', latitude=40.99285, longitude=28.69441,
        maps_url='https://maps.example/factory',
    )
    con.commit()
    con.close()


def _decode_message(url: str) -> str:
    return urllib.parse.unquote(url.split('text=', 1)[1])


class TestWhatsAppApiV1:
    def test_missing_vehicle_id_400(self, client):
        con = sqlite3.connect(client.application.config.get('TESTING') and os.environ['CPS_MOCK_DB_PATH'])
        _login(client, _user(con, 1))
        con.close()
        r = client.get(f'{URL}?date={PLAN_DATE}')
        assert r.status_code == 400
        assert r.get_json()['code'] == 'INVALID_REQUEST'

    def test_missing_date_400(self, client):
        con = sqlite3.connect(os.environ['CPS_MOCK_DB_PATH'])
        _login(client, _user(con, 1))
        con.close()
        r = client.get(f'{URL}?vehicle_id={VEHICLE}')
        assert r.status_code == 400
        assert r.get_json()['code'] == 'INVALID_REQUEST'

    def test_plan_not_found_404(self, client, env):
        con = sqlite3.connect(env['db'])
        _login(client, _user(con, 1))
        con.close()
        r = client.get(f'{URL}?date=2099-01-01&vehicle_id={VEHICLE}')
        assert r.status_code == 404
        assert r.get_json()['code'] == 'PLAN_NOT_FOUND'

    def test_success_200(self, client, env):
        _prepare_plan(env)
        con = sqlite3.connect(env['db'])
        _login(client, _user(con, 1))
        con.close()
        with patch('modules.planlama.arac_timeline_service.build_timeline_for_plan', return_value={'estimated_return_time': '21:00', 'timeline_complete': True, 'status': 'HESAPLANDI', 'plan_departure_time': '19:00', 'estimated_total_seconds': 3600.0}):
            r = client.get(f'{URL}?date={PLAN_DATE}&vehicle_id={VEHICLE}')
        assert r.status_code == 200
        body = r.get_json()
        assert body['ok'] is True
        assert body['whatsapp_url'].startswith('https://wa.me/?text=')
        assert 'message' not in body
        assert body['vehicle_external_id'] == VEHICLE
        assert body['plan_id'] == PLAN_ID
        assert '34 MOR 049' in _decode_message(body['whatsapp_url'])

    def test_multi_vehicle_isolation(self, client, env):
        _prepare_plan(env, vehicle=VEHICLE)
        _prepare_plan(env, vehicle=OTHER_VEHICLE)
        con = sqlite3.connect(env['db'])
        _login(client, _user(con, 1))
        con.close()
        with patch('modules.planlama.arac_timeline_service.build_timeline_for_plan', return_value={'estimated_return_time': '21:00', 'timeline_complete': True, 'status': 'HESAPLANDI', 'plan_departure_time': '19:00', 'estimated_total_seconds': 3600.0}):
            r1 = client.get(f'{URL}?date={PLAN_DATE}&vehicle_id={VEHICLE}')
            r2 = client.get(f'{URL}?date={PLAN_DATE}&vehicle_id={OTHER_VEHICLE}')
        m1 = _decode_message(r1.get_json()['whatsapp_url'])
        m2 = _decode_message(r2.get_json()['whatsapp_url'])
        assert '34 MOR 049' in m1
        assert 'Other Firma' not in m1
        assert 'Other Firma' in m2
        assert '34 MOR 049' not in m2

    def test_mehmet_admin_same_payload(self, client, env):
        _prepare_plan(env)
        con = sqlite3.connect(env['db'])
        admin = _user(con, 1)
        mehmet = _user(con, 31)
        con.close()
        with patch('modules.planlama.arac_timeline_service.build_timeline_for_plan', return_value={'estimated_return_time': '21:00', 'timeline_complete': True, 'status': 'HESAPLANDI', 'plan_departure_time': '19:00', 'estimated_total_seconds': 3600.0}):
            _login(client, admin)
            r_admin = client.get(f'{URL}?date={PLAN_DATE}&vehicle_id={VEHICLE}')
            _login(client, mehmet)
            r_mehmet = client.get(f'{URL}?date={PLAN_DATE}&vehicle_id={VEHICLE}')
        assert r_admin.get_json()['whatsapp_url'] == r_mehmet.get_json()['whatsapp_url']

    def test_erhan_403(self, client, env):
        _prepare_plan(env)
        con = sqlite3.connect(env['db'])
        _login(client, _user(con, 49))
        con.close()
        r = client.get(f'{URL}?date={PLAN_DATE}&vehicle_id={VEHICLE}')
        assert r.status_code == 403

    def test_db_logical_unchanged(self, client, env):
        _prepare_plan(env)
        logical_before = canonical_logical_snapshot(env['db'])
        con = sqlite3.connect(env['db'])
        _login(client, _user(con, 1))
        con.close()
        with patch('modules.planlama.arac_timeline_service.build_timeline_for_plan', return_value={'estimated_return_time': '21:00'}):
            r = client.get(f'{URL}?date={PLAN_DATE}&vehicle_id={VEHICLE}')
        assert r.status_code == 200
        logical_after = canonical_logical_snapshot(env['db'])
        assert logical_before == logical_after
