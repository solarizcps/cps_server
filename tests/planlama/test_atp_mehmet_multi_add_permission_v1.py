# -*- coding: utf-8 -*-
"""ATP Mehmet narrow planlama.arac_takip permission — T1–T15 (temp DB only)."""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

APP = Path(__file__).resolve().parents[2] / 'app'
MIGS = APP / 'migrations'
sys.path.insert(0, str(APP))
os.chdir(APP)
os.environ['CPS_TEST_DB_GUARD'] = '1'

from tools.nexgen_tmp_db import assert_resolved_db_is_tmp, canonical_db_path, sha256_file

PHASE = 'ATP_MEHMET_MULTI_ADD_PERMISSION_IMPLEMENT_V1'
MIG189 = MIGS / '189_planlama_arac_takip_rol32_yetki.py'
VEHICLE = '45077045'
PLAN_DATE = '2026-08-29'
CANONICAL_SOURCE = Path(os.environ.get(
    'CPS_CANONICAL_DB_SOURCE',
    r'C:\Solariz_CPS_SERVER\app\mock_data.db',
))


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
        'Id': r[0],
        'KullaniciAdi': r[1],
        'AdSoyad': r[2],
        'RolId': r[3],
        'Aktif': r[4],
        'Tip': r[5],
        'ZorunluSifreDegistir': int(r[6] or 0),
        'AuthVersion': int(r[7] or 1),
    }


def _forbidden(body: dict) -> bool:
    err = (body.get('error') or body.get('hata') or '').lower()
    return body.get('code') == 'FORBIDDEN' or err == 'forbidden' or 'yetkiniz yok' in err


def _strip_mehmet_overrides(db: str) -> None:
    con = sqlite3.connect(db)
    con.execute('DELETE FROM user_permission_override WHERE KullaniciId=31')
    con.commit()
    con.close()


def _apply_mig189(db: str) -> None:
    mod = _load_migration(MIG189)
    mod.run(db)


def _loc(con: sqlite3.Connection) -> dict:
    con.row_factory = sqlite3.Row
    r = con.execute(
        """
        SELECT id,firma_adi,latitude,longitude,adres
        FROM arac_kayitli_yer WHERE aktif=1 AND latitude IS NOT NULL LIMIT 1
        """
    ).fetchone()
    return dict(r)


@pytest.fixture(scope='module')
def env():
    live = str(CANONICAL_SOURCE.resolve())
    if not os.path.isfile(live):
        live = canonical_db_path()
    sha_before = sha256_file(live)
    tmp_dir = tempfile.mkdtemp(prefix='atp_mehmet_perm_')
    db = os.path.join(tmp_dir, 'mock_data_test.db')
    shutil.copy2(live, db)
    assert_resolved_db_is_tmp(db, live)
    _strip_mehmet_overrides(db)
    _apply_mig189(db)
    os.environ['CPS_MOCK_DB_PATH'] = db
    import config as cfg
    cfg.Config.MOCK_DB_PATH = db
    yield {'db': db, 'live': live, 'sha_before': sha_before, 'tmp_dir': tmp_dir}
    assert sha256_file(live) == sha_before, 'Canonical source DB must not be modified'
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


def _login(client, user: dict):
    with client.session_transaction() as sess:
        sess['kullanici'] = user
        sess['auth_version'] = user.get('AuthVersion', 1)


def _batch_payload(loc, key: str | None = None):
    key = key or f'test_{uuid.uuid4().hex[:10]}'
    row = {
        'plan_tarihi': PLAN_DATE, 'tarih': PLAN_DATE, 'arac_external_id': VEHICLE,
        'sofor_adi': 'ibrahim', 'firma': loc['firma_adi'], 'yapilacak_is': 'Perm test',
        'is': 'Perm test', 'oncelik': 'NORMAL', 'location_master_id': loc['id'],
        'latitude': loc['latitude'], 'longitude': loc['longitude'],
        'lat': loc['latitude'], 'lng': loc['longitude'],
        'adres': loc['adres'] or 'Test', 'client_submit_id': key,
    }
    return {'rows': [row], 'plan_tarihi': PLAN_DATE, 'arac_external_id': VEHICLE}


@pytest.fixture
def vehicle_patch():
    with patch(
        'modules.planlama.arac_vehicle_identity_service.resolve_vehicle_identity',
        return_value={
            'arac_provider': 'TURKCELL_FILOM',
            'arac_external_id': VEHICLE,
            'arac_plaka_snapshot': '34 MOR 049',
        },
    ):
        yield


class TestAtpMehmetPermissionV1:
    def test_t1_admin_batch_200_after_mig(self, env, client, vehicle_patch):
        con = sqlite3.connect(env['db'])
        _login(client, _user(con, 1))
        loc = _loc(con)
        con.close()
        r = client.post('/planlama/arac-takip/api/plana-is-ekle-batch', json=_batch_payload(loc))
        assert r.status_code == 200
        assert r.get_json()['ok'] is True

    def test_t2_mehmet_before_mig_403(self, env, client, vehicle_patch):
        live = env['live']
        tmp = tempfile.mkdtemp(prefix='atp_pre_mig_')
        db2 = os.path.join(tmp, 'pre.db')
        shutil.copy2(live, db2)
        assert_resolved_db_is_tmp(db2, live)
        _strip_mehmet_overrides(db2)
        con2 = sqlite3.connect(db2)
        con2.execute(
            """
            DELETE FROM sistem_rol_yetki
            WHERE RolId=32 AND YetkiId IN (SELECT Id FROM sistem_yetki WHERE Kod='planlama.arac_takip')
            """
        )
        con2.commit()
        con2.close()
        import config as cfg
        prev = cfg.Config.MOCK_DB_PATH
        cfg.Config.MOCK_DB_PATH = db2
        os.environ['CPS_MOCK_DB_PATH'] = db2
        try:
            con = sqlite3.connect(db2)
            _login(client, _user(con, 31))
            loc = _loc(con)
            con.close()
            r = client.post('/planlama/arac-takip/api/plana-is-ekle-batch', json=_batch_payload(loc))
            assert r.status_code == 403
            assert _forbidden(r.get_json())
        finally:
            cfg.Config.MOCK_DB_PATH = prev
            os.environ['CPS_MOCK_DB_PATH'] = prev
            shutil.rmtree(tmp, ignore_errors=True)

    def test_t3_mehmet_after_mig_200(self, env, client, vehicle_patch):
        con = sqlite3.connect(env['db'])
        _login(client, _user(con, 31))
        loc = _loc(con)
        con.close()
        r = client.post('/planlama/arac-takip/api/plana-is-ekle-batch', json=_batch_payload(loc))
        assert r.status_code == 200
        assert r.get_json()['ok'] is True

    def test_t4_t6_visibility_shared(self, env, client, vehicle_patch):
        from modules.planlama.arac_plan_service import get_tasks_for_session, list_plans_for_date
        con = sqlite3.connect(env['db'])
        _login(client, _user(con, 31))
        loc = _loc(con)
        con.close()
        client.post('/planlama/arac-takip/api/plana-is-ekle-batch', json=_batch_payload(loc))
        m_tasks = get_tasks_for_session(31, PLAN_DATE, VEHICLE)
        a_tasks = get_tasks_for_session(1, PLAN_DATE, VEHICLE)
        other = con = sqlite3.connect(env['db'])
        row = con.execute(
            "SELECT Id FROM sistem_kullanici WHERE RolId=32 AND Id NOT IN (31) AND Aktif=1 LIMIT 1"
        ).fetchone()
        con.close()
        assert row
        o_tasks = get_tasks_for_session(int(row[0]), PLAN_DATE, VEHICLE)
        assert len(m_tasks) >= 1
        assert {t['id'] for t in m_tasks} == {t['id'] for t in a_tasks}
        assert {t['id'] for t in m_tasks} == {t['id'] for t in o_tasks}
        assert len(list_plans_for_date(PLAN_DATE)) >= 1

    def test_t7_erhan_403(self, env, client, vehicle_patch):
        con = sqlite3.connect(env['db'])
        _login(client, _user(con, 49))
        loc = _loc(con)
        con.close()
        r = client.post('/planlama/arac-takip/api/plana-is-ekle-batch', json=_batch_payload(loc))
        assert r.status_code == 403

    def test_t8_other_planlama_not_broadened(self, env):
        import importlib
        import modules.auth as auth_mod
        importlib.reload(auth_mod)
        con = sqlite3.connect(env['db'])
        yks = auth_mod.kullanici_yetkileri(_user(con, 31))
        con.close()
        assert 'planlama:can_create' not in yks
        assert 'planlama.arac_takip:can_create' in yks
        assert 'planlama.enjeksiyon.kalip:can_create' in yks

    def test_t9_create_vs_t10_update(self, env, client, vehicle_patch):
        con = sqlite3.connect(env['db'])
        _login(client, _user(con, 31))
        loc = _loc(con)
        con.close()
        r = client.post('/planlama/arac-takip/api/plana-is-ekle-batch', json=_batch_payload(loc))
        assert r.status_code == 200
        tasks = r.get_json().get('daily_tasks') or []
        assert tasks
        tid = tasks[0]['id']
        r2 = client.post(
            '/planlama/arac-takip/api/reorder',
            json={'date': PLAN_DATE, 'vehicle_id': VEHICLE, 'task_id': tid, 'direction': 'down'},
        )
        assert r2.status_code == 200

    def test_t11_manage_cancel_forbidden(self, env, client, vehicle_patch):
        con = sqlite3.connect(env['db'])
        _login(client, _user(con, 31))
        loc = _loc(con)
        con.close()
        r = client.post('/planlama/arac-takip/api/plana-is-ekle-batch', json=_batch_payload(loc))
        plan_is_id = r.get_json()['results'][0]['plan_is_id']
        r2 = client.post(
            f'/planlama/arac-takip/api/plan-job/{plan_is_id}/change',
            json={'action': 'cancel', 'reason': 'test iptal', 'plan_tarihi': PLAN_DATE},
        )
        assert r2.status_code == 403
        assert r2.get_json()['code'] == 'FORBIDDEN'

    def test_t12_ui_permissions_in_page(self, env, client):
        con = sqlite3.connect(env['db'])
        _login(client, _user(con, 31))
        con.close()
        r = client.get('/planlama/arac-takip/?tab=gunluk')
        assert r.status_code == 200
        html = r.get_data(as_text=True)
        m = re.search(r'id="atpDashboardJson"[^>]*>(\{.*?\})</script>', html, re.S)
        assert m
        dash = json.loads(m.group(1))
        assert dash['atp_permissions']['can_create'] is True

    def test_t13_forbidden_message(self, env, client, vehicle_patch):
        con = sqlite3.connect(env['db'])
        _login(client, _user(con, 49))
        loc = _loc(con)
        con.close()
        r = client.post('/planlama/arac-takip/api/plana-is-ekle-batch', json=_batch_payload(loc))
        assert _forbidden(r.get_json())

    def test_t14_admin_regression(self, env, client):
        con = sqlite3.connect(env['db'])
        _login(client, _user(con, 1))
        con.close()
        r = client.get('/planlama/arac-takip/api/dashboard?tab=gunluk')
        assert r.status_code == 200
        perms = r.get_json()['dashboard']['atp_permissions']
        assert perms['can_create'] is True
        assert perms['can_manage'] is True

    def test_t15_no_created_by_filter(self, env):
        from modules.planlama.arac_takip_repo import list_plan_tasks
        src = Path(APP / 'modules/planlama/arac_takip_repo.py').read_text(encoding='utf-8')
        fn = src.split('def list_plan_tasks', 1)[1].split('\ndef ', 1)[0]
        assert 'created_by' not in fn
        assert list_plan_tasks  # callable

    def test_mig189_idempotent(self, env):
        _apply_mig189(env['db'])
        _apply_mig189(env['db'])
        con = sqlite3.connect(env['db'])
        cnt = con.execute(
            """
            SELECT COUNT(*) FROM sistem_rol_yetki ry
            JOIN sistem_yetki y ON y.Id=ry.YetkiId
            WHERE ry.RolId=32 AND y.Kod='planlama.arac_takip'
            """
        ).fetchone()[0]
        con.close()
        assert cnt == 1

    def test_mig189_blocks_canonical(self):
        mod = _load_migration(MIG189)
        from migrations._migration_db_guard import resolve_db_path, canonical_db_path
        wt_canonical = canonical_db_path()
        with pytest.raises(PermissionError):
            resolve_db_path(wt_canonical, allow_canonical=False)
