# -*- coding: utf-8 -*-
"""Operasyon raporu F9.5.1 — DB path resolver + GET /api/operasyon/genel (temp DB)."""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import flask
import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_APP_DIR = _REPO_ROOT / 'app'
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))


@pytest.fixture()
def operasyon_temp_db(monkeypatch):
    fd, path = tempfile.mkstemp(suffix='_operasyon_f951.db')
    os.close(fd)
    con = sqlite3.connect(path)
    con.execute(
        """CREATE TABLE enj_makine (
            id INTEGER PRIMARY KEY, kod TEXT, ad TEXT, istasyon_sayisi INTEGER
        )"""
    )
    con.execute(
        """CREATE TABLE enj_gunluk_rapor (
            id INTEGER PRIMARY KEY, makine_id INTEGER, tarih TEXT, vardiya TEXT
        )"""
    )
    con.execute(
        "INSERT INTO enj_makine (id, kod, ad, istasyon_sayisi) VALUES (1,'M1','Test',2)"
    )
    con.commit()
    con.close()
    monkeypatch.setenv('CPS_MOCK_DB_PATH', path)
    import config
    config.Config.MOCK_DB_PATH = path
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


def test_f951_db_path_uses_config_mock_db_path(operasyon_temp_db):
    from modules.planlama.routes import _f951_db_path

    assert os.path.normpath(_f951_db_path()) == os.path.normpath(operasyon_temp_db)
    assert not _f951_db_path().endswith(
        os.path.join('repo', 'app', 'mock_data.db')
    ) or os.path.getsize(_f951_db_path()) > 0


def test_f951_db_path_not_zero_byte_app_stub(monkeypatch):
    stub = _APP_DIR / 'mock_data.db'
    if stub.is_file() and stub.stat().st_size == 0:
        monkeypatch.setenv('CPS_MOCK_DB_PATH', str(_APP_DIR / 'nonexistent_for_test_only.db'))
        import config
        config.Config.MOCK_DB_PATH = monkeypatch.getenv('CPS_MOCK_DB_PATH')
        from modules.planlama.routes import _f951_db_path

        resolved = os.path.normpath(_f951_db_path())
        assert resolved != os.path.normpath(str(stub))


def _build_planlama_app():
    from functools import wraps
    import importlib

    def _fake_yetki_gerekli(kod, action='can_view'):
        def deco(f):
            @wraps(f)
            def wrapper(*args, **kwargs):
                flask.session['kullanici'] = {'Id': 1, 'AdSoyad': 'Test User'}
                return f(*args, **kwargs)
            return wrapper
        return deco

    import modules.auth as auth_mod
    auth_mod.yetki_gerekli = _fake_yetki_gerekli
    auth_mod.yetki_var = lambda *a, **k: True

    import modules.planlama.routes as routes_mod
    importlib.reload(routes_mod)
    from modules.planlama.routes import planlama_bp

    app = flask.Flask(
        __name__,
        template_folder=str(_APP_DIR / 'templates'),
        static_folder=str(_APP_DIR / 'static'),
    )
    app.secret_key = 'test-operasyon-f951'
    app.config['TESTING'] = True

    @app.context_processor
    def _minimal_globals():
        return {
            'DB_MODE': 'mock',
            'APP_NAME': 'CPS Dev',
            'now': datetime.now().strftime('%Y-%m-%d'),
            'g_user': flask.session.get('kullanici'),
            'g_yetkiler': set(),
            'yetki': lambda *a, **k: True,
            'depo_sade_mod': False,
            'arge_tablet_mod': False,
            'can_musteri_operasyonu_menu': False,
            'pazarlamaci_home_user': False,
            'enjeksiyon_home_user': False,
            'home_landing_url': '/',
        }

    app.register_blueprint(routes_mod.planlama_bp)
    return app


def test_api_operasyon_genel_returns_200_json(operasyon_temp_db):
    app = _build_planlama_app()
    client = app.test_client()
    with client.session_transaction() as sess:
        sess['kullanici'] = {'Id': 1, 'AdSoyad': 'Test User'}
    today = datetime.now().strftime('%Y-%m-%d')
    rv = client.get(f'/planlama/api/operasyon/genel?tarih={today}&vardiya=gunduz')
    assert rv.status_code == 200, rv.get_data(as_text=True)
    data = rv.get_json()
    assert data is not None
    assert data.get('ok') is True or 'makineler' in data


def test_operasyon_raporu_routes_registered_on_full_app():
    import app as cps_app

    vf = cps_app.app.view_functions
    assert 'planlama_bp.f951_operasyon_raporu_sayfa' in vf
    assert 'planlama_bp.f951_api_operasyon_genel' in vf
