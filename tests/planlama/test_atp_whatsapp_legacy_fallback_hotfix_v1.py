# -*- coding: utf-8 -*-
"""ATP WhatsApp legacy fallback removal + popup-safe flow (T1–T15)."""
from __future__ import annotations

import importlib.util
import os
import shutil
import sqlite3
import sys
import tempfile
import urllib.parse
from pathlib import Path
from unittest.mock import patch

import pytest

APP = Path(__file__).resolve().parents[2] / 'app'
MIGS = APP / 'migrations'
ROOT = APP.parent
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP.parent / 'tests' / 'planlama'))

from atp_plan2_fixture import CIKIS, PLAN_DATE, PLAN_ID, PLAN_IS_ID, PLAKA, SOFOR, VEHICLE, insert_factory_base, seed_plan2_fixture

CANONICAL_SOURCE = Path(os.environ.get(
    'CPS_CANONICAL_DB_SOURCE',
    r'C:\Solariz_CPS_SERVER\app\mock_data.db',
))
MIG189 = MIGS / '189_planlama_arac_takip_rol32_yetki.py'
URL = '/planlama/arac-takip/api/whatsapp'
MAIN_JS = APP / 'static' / 'js' / 'planlama_arac_takip.js'
TEMPLATE = APP / 'templates' / 'planlama' / 'arac_takip_plan.html'


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


def _decode_wa_message(whatsapp_url: str) -> str:
    text = whatsapp_url.split('text=', 1)[1]
    return urllib.parse.unquote(text)


def _timeline_ok(return_time: str = '21:00') -> dict:
    return {
        'status': 'HESAPLANDI',
        'timeline_complete': True,
        'plan_departure_time': CIKIS,
        'estimated_return_time': return_time,
        'estimated_total_seconds': 3600.0,
    }


@pytest.fixture
def env():
    live = str(CANONICAL_SOURCE.resolve())
    if not os.path.isfile(live):
        pytest.skip(f'canonical missing: {live}')
    tmp_dir = tempfile.mkdtemp(prefix='atp_wa_hotfix_')
    db = os.path.join(tmp_dir, 'mock_data_test.db')
    shutil.copy2(live, db)
    _load_migration(MIG189).run(db)
    os.environ['CPS_MOCK_DB_PATH'] = db
    os.environ['CPS_TEST_DB_GUARD'] = '1'
    import config as cfg
    cfg.Config.MOCK_DB_PATH = db
    con = sqlite3.connect(db)
    seed_plan2_fixture(con, with_coords=True)
    insert_factory_base(
        con, base_name='Solariz Fabrika', latitude=40.9928503, longitude=28.6944178,
        maps_url='https://maps.example/factory',
    )
    con.commit()
    con.close()
    yield {'db': db, 'tmp_dir': tmp_dir}
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


@pytest.fixture(scope='module')
def js_src():
    return MAIN_JS.read_text(encoding='utf-8')


@pytest.fixture(scope='module')
def tpl_src():
    return TEMPLATE.read_text(encoding='utf-8')


class TestLegacyFallbackRemovalSource:
    def test_t1_no_legacy_preview_dom_in_template(self, tpl_src):
        assert 'atpWhatsappLegacyPreview' not in tpl_src
        assert 'data-atp-whatsapp-legacy-preview' not in tpl_src
        assert 'GÜNLÜK ARAÇ PROGRAMI' not in tpl_src

    def test_t2_no_legacy_builder_in_frontend(self, js_src):
        assert 'build_whatsapp_plan_message' not in js_src
        assert 'selected_driver_name' not in js_src
        assert 'removeLegacyWhatsappPreview' in js_src

    def test_t3_no_url_fallback_only_whatsapp_url(self, js_src):
        block = js_src[js_src.find('/* ─── WhatsApp'):js_src.find('/* ─── Base location button')]
        assert 'j.whatsapp_url' in block
        assert 'j.url' not in block
        assert 'build_whatsapp_plan_message' not in block

    def test_t4_no_vehicle_message_and_no_fetch_before_popup(self, js_src):
        assert "toast('WhatsApp için önce bir araç planı seçin.')" in js_src
        idx = js_src.find("toast('WhatsApp için önce bir araç planı seçin.')")
        popup_idx = js_src.find("window.open('about:blank'", idx)
        fetch_idx = js_src.find('fetch(waUrl', idx)
        assert popup_idx == -1 or fetch_idx == -1 or popup_idx < fetch_idx

    def test_t5_popup_null_message(self, js_src):
        assert 'Tarayıcı WhatsApp penceresini engelledi' in js_src

    def test_t6_api_error_closes_popup(self, js_src):
        assert 'closeWhatsappPopup(popup)' in js_src
        assert 'WhatsApp planı hazırlanamadı.' in js_src

    def test_t7_invalid_whatsapp_url_closes_popup(self, js_src):
        assert 'isValidWhatsappUrl' in js_src
        assert 'closeWhatsappPopup(popup)' in js_src

    def test_t8_success_uses_location_replace(self, js_src):
        assert 'popup.location.replace(j.whatsapp_url)' in js_src

    def test_t15_single_encode_in_api_url(self, client, env):
        con = sqlite3.connect(env['db'])
        _login(client, _user(con, 1))
        con.close()
        with patch(
            'modules.planlama.arac_timeline_service.build_timeline_for_plan',
            return_value=_timeline_ok(),
        ):
            r = client.get(f'{URL}?date={PLAN_DATE}&vehicle_id={VEHICLE}')
        url = r.get_json()['whatsapp_url']
        assert url.count('%25') == 0
        decoded = _decode_wa_message(url)
        assert 'GÜNLÜK ARAÇ PROGRAMI' in decoded
        assert 'şahin taban' in decoded.lower()


class TestLegacyFallbackApiParity:
    def test_t9_selected_vehicle_plate_driver_in_decoded_message(self, client, env):
        con = sqlite3.connect(env['db'])
        _login(client, _user(con, 1))
        con.close()
        with patch(
            'modules.planlama.arac_timeline_service.build_timeline_for_plan',
            return_value=_timeline_ok(),
        ):
            body = client.get(f'{URL}?date={PLAN_DATE}&vehicle_id={VEHICLE}').get_json()
        msg = _decode_wa_message(body['whatsapp_url'])
        assert body['vehicle_external_id'] == VEHICLE
        assert PLAKA in msg
        assert SOFOR in msg
        assert 'Ali (Üretim Operatörü)' not in msg

    def test_t10_order_ids_match_message_sequence(self, client, env):
        con = sqlite3.connect(env['db'])
        _login(client, _user(con, 1))
        con.close()
        with patch(
            'modules.planlama.arac_timeline_service.build_timeline_for_plan',
            return_value=_timeline_ok(),
        ):
            body = client.get(f'{URL}?date={PLAN_DATE}&vehicle_id={VEHICLE}').get_json()
        assert body['plan_id'] == PLAN_ID
        assert body['stop_count'] == 1
        assert body['order_ids'] == [str(PLAN_IS_ID)]
        msg = _decode_wa_message(body['whatsapp_url'])
        assert msg.index('1.') < msg.lower().index('şahin')

    def test_t11_location_links_in_decoded_message(self, client, env):
        con = sqlite3.connect(env['db'])
        _login(client, _user(con, 1))
        con.close()
        with patch(
            'modules.planlama.arac_timeline_service.build_timeline_for_plan',
            return_value=_timeline_ok(),
        ):
            body = client.get(f'{URL}?date={PLAN_DATE}&vehicle_id={VEHICLE}').get_json()
        msg = _decode_wa_message(body['whatsapp_url'])
        assert 'google.com/maps?q=' in msg

    def test_t12_inactive_stops_excluded(self, client, env):
        con = sqlite3.connect(env['db'])
        con.execute(
            "UPDATE arac_gunluk_plan_is SET durum='IPTAL' WHERE id=?",
            (PLAN_IS_ID,),
        )
        con.commit()
        _login(client, _user(con, 1))
        con.close()
        with patch(
            'modules.planlama.arac_timeline_service.build_timeline_for_plan',
            return_value=_timeline_ok(),
        ):
            body = client.get(f'{URL}?date={PLAN_DATE}&vehicle_id={VEHICLE}').get_json()
        assert body['stop_count'] == 0
        assert body['order_ids'] == []
        msg = _decode_wa_message(body['whatsapp_url'])
        assert 'şahin taban' not in msg.lower()

    def test_t13_other_vehicle_no_leak(self, client, env):
        other = '990DEMO001'
        con = sqlite3.connect(env['db'])
        from datetime import datetime
        now = datetime.now().replace(microsecond=0).isoformat(sep=' ')
        con.execute(
            """
            INSERT INTO arac_gunluk_plan (
                plan_tarihi, arac_provider, arac_external_id, arac_plaka_snapshot,
                sofor_adi_snapshot, durum, cikis_saati, created_at, created_by, updated_at, updated_by
            ) VALUES (?,'TURKCELL_FILOM',?,?,?,'AKTIF','08:00',?,?,?,?)
            """,
            (PLAN_DATE, other, '34 LEAK 001', 'Leak Driver', now, 1, now, 1),
        )
        pid = int(con.execute('SELECT last_insert_rowid()').fetchone()[0])
        tcur = con.execute(
            """
            INSERT INTO arac_is_talebi (
                talep_no, talep_eden_user_id, talep_eden_adi_snapshot, talep_tarihi,
                firma_adi, adres, yapilacak_is, oncelik, durum, save_to_master,
                created_at, created_by, updated_at, updated_by
            ) VALUES (?,?,?,?,?,?,?,?,'PLANA_ALINDI',0,?,?,?,?)
            """,
            (f'LEAK-{other}', 1, 'Test', PLAN_DATE, 'Leak Firma', 'Adres', 'Leak is', 'NORMAL', now, 1, now, 1),
        )
        con.execute(
            """
            INSERT INTO arac_gunluk_plan_is (plan_id, is_talebi_id, sira, durum, created_at, created_by)
            VALUES (?, ?, 1, 'PLANLANDI', ?, ?)
            """,
            (pid, int(tcur.lastrowid), now, 1),
        )
        con.commit()
        _login(client, _user(con, 1))
        con.close()
        with patch(
            'modules.planlama.arac_timeline_service.build_timeline_for_plan',
            return_value=_timeline_ok('09:00'),
        ):
            body = client.get(f'{URL}?date={PLAN_DATE}&vehicle_id={VEHICLE}').get_json()
        msg = _decode_wa_message(body['whatsapp_url'])
        assert 'Leak Firma' not in msg
        assert '34 LEAK' not in msg

    def test_t14_backend_response_metadata_only(self, client, env):
        con = sqlite3.connect(env['db'])
        _login(client, _user(con, 1))
        con.close()
        with patch(
            'modules.planlama.arac_timeline_service.build_timeline_for_plan',
            return_value=_timeline_ok(),
        ):
            body = client.get(f'{URL}?date={PLAN_DATE}&vehicle_id={VEHICLE}').get_json()
        assert set(body.keys()) == {
            'ok', 'whatsapp_url', 'vehicle_external_id', 'plan_id', 'stop_count', 'order_ids',
        }
        assert 'message' not in body
        assert 'url' not in body

    def test_api_404_shape(self, client, env):
        con = sqlite3.connect(env['db'])
        _login(client, _user(con, 1))
        con.close()
        r = client.get(f'{URL}?date=2099-01-01&vehicle_id={VEHICLE}')
        assert r.status_code == 404
        body = r.get_json()
        assert body['ok'] is False
        assert body['code'] == 'PLAN_NOT_FOUND'
        assert 'error' in body
