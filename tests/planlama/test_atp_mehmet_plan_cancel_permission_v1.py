# -*- coding: utf-8 -*-
"""ATP Mehmet narrow cancel — PLANLANDI only, can_update path, 409 guards."""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

APP = Path(__file__).resolve().parents[2] / 'app'
MIGS = APP / 'migrations'
sys.path.insert(0, str(APP))

from atp_canonical_forensic import assert_canonical_atp_unchanged, canonical_logical_snapshot
from tools.nexgen_tmp_db import assert_resolved_db_is_tmp, sha256_file

MIG189 = MIGS / '189_planlama_arac_takip_rol32_yetki.py'
VEHICLE = '45077045'
PLAN_DATE = '2026-08-29'
CANONICAL_SOURCE = Path(os.environ.get(
    'CPS_CANONICAL_DB_SOURCE',
    r'C:\Solariz_CPS_SERVER\app\mock_data.db',
))
CANCEL_MSG = 'Başlamış veya ziyaret sürecine girmiş iş plan dışına alınamaz.'


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


def _loc(con: sqlite3.Connection) -> dict:
    con.row_factory = sqlite3.Row
    r = con.execute(
        """
        SELECT id,firma_adi,latitude,longitude,adres
        FROM arac_kayitli_yer WHERE aktif=1 AND latitude IS NOT NULL LIMIT 1
        """,
    ).fetchone()
    return dict(r)


def _batch_payload(loc, key: str | None = None):
    key = key or f'cancel_{uuid.uuid4().hex[:10]}'
    row = {
        'plan_tarihi': PLAN_DATE, 'tarih': PLAN_DATE, 'arac_external_id': VEHICLE,
        'sofor_adi': 'ibrahim', 'firma': loc['firma_adi'], 'yapilacak_is': 'Cancel test',
        'is': 'Cancel test', 'oncelik': 'NORMAL', 'location_master_id': loc['id'],
        'latitude': loc['latitude'], 'longitude': loc['longitude'],
        'lat': loc['latitude'], 'lng': loc['longitude'],
        'adres': loc['adres'] or 'Test', 'client_submit_id': key,
    }
    return {'rows': [row], 'plan_tarihi': PLAN_DATE, 'arac_external_id': VEHICLE}


@pytest.fixture(scope='module')
def env():
    live = str(CANONICAL_SOURCE.resolve())
    if not os.path.isfile(live):
        pytest.skip(f'canonical missing: {live}')
    sha_before = sha256_file(live)
    logical_before = canonical_logical_snapshot(live)
    tmp_dir = tempfile.mkdtemp(prefix='atp_mehmet_cancel_')
    db = os.path.join(tmp_dir, 'mock_data_test.db')
    shutil.copy2(live, db)
    assert_resolved_db_is_tmp(db, live)
    con = sqlite3.connect(db)
    con.execute('DELETE FROM user_permission_override WHERE KullaniciId=31')
    con.commit()
    con.close()
    _load_migration(MIG189).run(db)
    os.environ['CPS_MOCK_DB_PATH'] = db
    import config as cfg
    cfg.Config.MOCK_DB_PATH = db
    yield {'db': db, 'live': live, 'sha_before': sha_before, 'logical_before': logical_before, 'tmp_dir': tmp_dir}
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


def _login(client, user: dict):
    with client.session_transaction() as sess:
        sess['kullanici'] = user
        sess['auth_version'] = user.get('AuthVersion', 1)


def _seed_plan(client, loc) -> int:
    r = client.post(
        '/planlama/arac-takip/api/plana-is-ekle-batch',
        json=_batch_payload(loc, key=uuid.uuid4().hex),
    )
    assert r.status_code == 200
    return int(r.get_json()['results'][0]['plan_is_id'])


def _cancel(client, plan_is_id: int, *, reason: str = 'test iptal nedeni', uid: int = 31):
    _login(client, _user(sqlite3.connect(client.application.config.get('TESTING') and env_db()), uid))
    return client.post(
        f'/planlama/arac-takip/api/plan-job/{plan_is_id}/change',
        json={
            'action': 'cancel',
            'reason': reason,
            'plan_tarihi': PLAN_DATE,
            'client_submit_id': uuid.uuid4().hex,
        },
    )


def env_db():
    return os.environ['CPS_MOCK_DB_PATH']


def _cancel_as(client, env, uid: int, plan_is_id: int, reason: str = 'test iptal nedeni'):
    con = sqlite3.connect(env['db'])
    _login(client, _user(con, uid))
    con.close()
    return client.post(
        f'/planlama/arac-takip/api/plan-job/{plan_is_id}/change',
        json={
            'action': 'cancel',
            'reason': reason,
            'plan_tarihi': PLAN_DATE,
            'client_submit_id': uuid.uuid4().hex,
        },
    )


def _plan_row(db: str, plan_is_id: int) -> sqlite3.Row:
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    row = con.execute(
        """
        SELECT pi.*, p.plan_tarihi, p.arac_external_id, p.id AS plan_id
        FROM arac_gunluk_plan_is pi
        JOIN arac_gunluk_plan p ON p.id = pi.plan_id
        WHERE pi.id=?
        """,
        (plan_is_id,),
    ).fetchone()
    con.close()
    return row


def _upsert_visit(db: str, row: sqlite3.Row, state: str, **extra) -> None:
    con = sqlite3.connect(db)
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    existing = con.execute(
        'SELECT id FROM arac_plan_is_ziyaret_durum WHERE plan_is_id=?', (row['id'],),
    ).fetchone()
    if existing:
        sets = ['state=?', 'updated_at=?']
        vals: list = [state, now]
        for k, v in extra.items():
            sets.append(f'{k}=?')
            vals.append(v)
        vals.append(row['id'])
        con.execute(
            f"UPDATE arac_plan_is_ziyaret_durum SET {', '.join(sets)} WHERE plan_is_id=?",
            vals,
        )
    else:
        con.execute(
            """
            INSERT INTO arac_plan_is_ziyaret_durum (
                plan_id, plan_is_id, arac_external_id, state, geofence_radius_m,
                exit_radius_m, consecutive_inside, consecutive_outside,
                arrived_at, departed_at, updated_at, created_at
            ) VALUES (?,?,?,?,200,250,0,0,?,?,?,?)
            """,
            (
                row['plan_id'], row['id'], row['arac_external_id'], state,
                extra.get('arrived_at'), extra.get('departed_at'), now, now,
            ),
        )
    con.commit()
    con.close()


def _insert_event(db: str, row: sqlite3.Row, olay_turu: str) -> None:
    con = sqlite3.connect(db)
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    try:
        con.execute(
            """
            INSERT INTO arac_plan_olay (
                plan_id, plan_is_id, arac_external_id, olay_turu, mesaj, olay_zamani, created_at
            ) VALUES (?,?,?,?,?,?,?)
            """,
            (row['plan_id'], row['id'], row['arac_external_id'], olay_turu, 'test', now, now),
        )
        con.commit()
    except sqlite3.IntegrityError as exc:
        con.rollback()
        con.close()
        pytest.skip(f'olay_turu {olay_turu} not in schema CHECK: {exc}')
    con.close()


class TestMehmetPlanCancelPermissionV1:
    def test_mehmet_planlandi_cancel_200_audit(self, env, client, vehicle_patch):
        con = sqlite3.connect(env['db'])
        _login(client, _user(con, 31))
        loc = _loc(con)
        con.close()
        pid = _seed_plan(client, loc)
        r = _cancel_as(client, env, 31, pid)
        assert r.status_code == 200
        body = r.get_json()
        assert body.get('ok') and body.get('message') == 'İş plan dışına alındı.'
        con = sqlite3.connect(env['db'])
        con.row_factory = sqlite3.Row
        durum = con.execute('SELECT durum FROM arac_gunluk_plan_is WHERE id=?', (pid,)).fetchone()['durum']
        audit = con.execute(
            'SELECT * FROM arac_plan_is_degisim WHERE plan_is_id=? ORDER BY id DESC LIMIT 1', (pid,),
        ).fetchone()
        cnt = con.execute('SELECT COUNT(*) c FROM arac_gunluk_plan_is WHERE id=?', (pid,)).fetchone()['c']
        con.close()
        assert durum == 'IPTAL'
        assert cnt == 1
        assert audit and audit['created_by'] == 31 and audit['reason'] == 'test iptal nedeni'

    def test_mehmet_cancel_short_reason_400(self, env, client, vehicle_patch):
        con = sqlite3.connect(env['db'])
        _login(client, _user(con, 31))
        loc = _loc(con)
        con.close()
        pid = _seed_plan(client, loc)
        r = _cancel_as(client, env, 31, pid, reason='x')
        assert r.status_code == 400

    def test_mehmet_baslandi_409(self, env, client, vehicle_patch):
        con = sqlite3.connect(env['db'])
        _login(client, _user(con, 31))
        loc = _loc(con)
        con.close()
        pid = _seed_plan(client, loc)
        con = sqlite3.connect(env['db'])
        con.execute("UPDATE arac_gunluk_plan_is SET durum='BASLADI' WHERE id=?", (pid,))
        con.commit()
        con.close()
        r = _cancel_as(client, env, 31, pid)
        assert r.status_code == 409
        assert CANCEL_MSG in (r.get_json().get('error') or '')

    def test_mehmet_approaching_409(self, env, client, vehicle_patch):
        con = sqlite3.connect(env['db'])
        _login(client, _user(con, 31))
        loc = _loc(con)
        con.close()
        pid = _seed_plan(client, loc)
        row = _plan_row(env['db'], pid)
        _upsert_visit(env['db'], row, 'APPROACHING')
        r = _cancel_as(client, env, 31, pid)
        assert r.status_code == 409

    def test_mehmet_arrived_409(self, env, client, vehicle_patch):
        con = sqlite3.connect(env['db'])
        _login(client, _user(con, 31))
        loc = _loc(con)
        con.close()
        pid = _seed_plan(client, loc)
        row = _plan_row(env['db'], pid)
        _upsert_visit(env['db'], row, 'ARRIVED', arrived_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        r = _cancel_as(client, env, 31, pid)
        assert r.status_code == 409

    def test_mehmet_sonuc_bekliyor_409(self, env, client, vehicle_patch):
        con = sqlite3.connect(env['db'])
        _login(client, _user(con, 31))
        loc = _loc(con)
        con.close()
        pid = _seed_plan(client, loc)
        row = _plan_row(env['db'], pid)
        _upsert_visit(env['db'], row, 'DEPARTED_PENDING')
        r = _cancel_as(client, env, 31, pid)
        assert r.status_code == 409

    def test_mehmet_tamamlandi_409(self, env, client, vehicle_patch):
        con = sqlite3.connect(env['db'])
        _login(client, _user(con, 31))
        loc = _loc(con)
        con.close()
        pid = _seed_plan(client, loc)
        con = sqlite3.connect(env['db'])
        con.execute("UPDATE arac_gunluk_plan_is SET durum='TAMAMLANDI' WHERE id=?", (pid,))
        con.commit()
        con.close()
        r = _cancel_as(client, env, 31, pid)
        assert r.status_code == 409

    def test_mehmet_fabrikadan_ayrildi_409(self, env, client, vehicle_patch):
        con = sqlite3.connect(env['db'])
        _login(client, _user(con, 31))
        loc = _loc(con)
        con.close()
        pid = _seed_plan(client, loc)
        row = _plan_row(env['db'], pid)
        _insert_event(env['db'], row, 'FABRIKADAN_AYRILDI')
        r = _cancel_as(client, env, 31, pid)
        assert r.status_code == 409

    def test_mehmet_duraga_yaklasiyor_409(self, env, client, vehicle_patch):
        con = sqlite3.connect(env['db'])
        _login(client, _user(con, 31))
        loc = _loc(con)
        con.close()
        pid = _seed_plan(client, loc)
        row = _plan_row(env['db'], pid)
        _insert_event(env['db'], row, 'DURAGA_YAKLASIYOR')
        r = _cancel_as(client, env, 31, pid)
        assert r.status_code == 409

    def test_mehmet_konuma_varildi_event_409(self, env, client, vehicle_patch):
        con = sqlite3.connect(env['db'])
        _login(client, _user(con, 31))
        loc = _loc(con)
        con.close()
        pid = _seed_plan(client, loc)
        row = _plan_row(env['db'], pid)
        _insert_event(env['db'], row, 'KONUMA_VARILDI')
        r = _cancel_as(client, env, 31, pid)
        assert r.status_code == 409

    def test_admin_planlandi_cancel_200(self, env, client, vehicle_patch):
        con = sqlite3.connect(env['db'])
        _login(client, _user(con, 31))
        loc = _loc(con)
        con.close()
        pid = _seed_plan(client, loc)
        r = _cancel_as(client, env, 1, pid)
        assert r.status_code == 200

    def test_erhan_cancel_403(self, env, client, vehicle_patch):
        con = sqlite3.connect(env['db'])
        _login(client, _user(con, 31))
        loc = _loc(con)
        con.close()
        pid = _seed_plan(client, loc)
        r = _cancel_as(client, env, 49, pid)
        assert r.status_code == 403

    def test_mehmet_defer_next_day_403(self, env, client, vehicle_patch):
        con = sqlite3.connect(env['db'])
        _login(client, _user(con, 31))
        loc = _loc(con)
        con.close()
        pid = _seed_plan(client, loc)
        con = sqlite3.connect(env['db'])
        _login(client, _user(con, 31))
        con.close()
        r = client.post(
            f'/planlama/arac-takip/api/plan-job/{pid}/change',
            json={
                'action': 'defer_next_day',
                'reason': 'erteleme test',
                'plan_tarihi': PLAN_DATE,
                'target_date': '2026-08-30',
                'client_submit_id': uuid.uuid4().hex,
            },
        )
        assert r.status_code == 403
        assert r.get_json().get('code') == 'FORBIDDEN'

    def test_cancel_shared_visibility(self, env, client, vehicle_patch):
        from modules.planlama.arac_plan_service import get_tasks_for_session
        from modules.planlama.arac_plan_changes_service import list_plan_changes_for_date
        con = sqlite3.connect(env['db'])
        _login(client, _user(con, 31))
        loc = _loc(con)
        other = con.execute(
            "SELECT Id FROM sistem_kullanici WHERE RolId=32 AND Id NOT IN (31) AND Aktif=1 LIMIT 1",
        ).fetchone()
        con.close()
        assert other
        pid = _seed_plan(client, loc)
        r = _cancel_as(client, env, 31, pid, reason='paylasim testi')
        assert r.status_code == 200
        admin_tasks = get_tasks_for_session(1, PLAN_DATE, VEHICLE)
        other_tasks = get_tasks_for_session(int(other[0]), PLAN_DATE, VEHICLE)
        changes = list_plan_changes_for_date(PLAN_DATE)
        iptal_items = [c for c in changes.get('items', []) if c.get('plan_is_id') == pid]
        assert iptal_items
        assert iptal_items[0].get('actor_user_id') == 31 or iptal_items[0].get('created_by') == 31

    def test_detail_cancel_disabled_started(self, env, client, vehicle_patch):
        con = sqlite3.connect(env['db'])
        _login(client, _user(con, 31))
        loc = _loc(con)
        con.close()
        pid = _seed_plan(client, loc)
        con = sqlite3.connect(env['db'])
        con.execute("UPDATE arac_gunluk_plan_is SET durum='BASLADI' WHERE id=?", (pid,))
        con.commit()
        con.close()
        r = client.get(f'/planlama/arac-takip/api/plan-job/{pid}/detail')
        assert r.status_code == 200
        allowed = r.get_json()['detail']['allowed_actions']
        assert allowed.get('cancel') is False
        assert CANCEL_MSG in (allowed.get('cancel_disabled_reason') or '')

    def test_detail_cancel_enabled_planlandi(self, env, client, vehicle_patch):
        con = sqlite3.connect(env['db'])
        _login(client, _user(con, 31))
        loc = _loc(con)
        con.close()
        pid = _seed_plan(client, loc)
        r = client.get(f'/planlama/arac-takip/api/plan-job/{pid}/detail')
        allowed = r.get_json()['detail']['allowed_actions']
        assert allowed.get('cancel') is True
        assert not allowed.get('cancel_disabled_reason')
