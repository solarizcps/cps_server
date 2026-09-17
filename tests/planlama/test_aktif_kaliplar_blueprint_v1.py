# -*- coding: utf-8 -*-
"""Aktif Kalıplar blueprint — registry + GET page (temp DB + mold_library schema)."""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import flask
import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_APP_DIR = _REPO_ROOT / 'app'
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

MOLD_LIBRARY_DDL = """
CREATE TABLE IF NOT EXISTS mold_library_mold (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    library_uuid TEXT NOT NULL UNIQUE,
    material_group TEXT NOT NULL,
    model_code TEXT NOT NULL,
    visible_mold_code TEXT NOT NULL,
    business_key TEXT NOT NULL UNIQUE,
    review_status TEXT NOT NULL,
    source_file_sha256 TEXT NOT NULL,
    source_main_row INTEGER NOT NULL,
    image_present INTEGER NOT NULL DEFAULT 0,
    is_archived INTEGER NOT NULL DEFAULT 0,
    row_version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS mold_library_series (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mold_library_uuid TEXT NOT NULL,
    display_order INTEGER NOT NULL,
    numara_asorti TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE (mold_library_uuid, display_order)
);
CREATE TABLE IF NOT EXISTS mold_library_image (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mold_library_uuid TEXT NOT NULL,
    storage_key TEXT NOT NULL,
    display_order INTEGER NOT NULL DEFAULT 1,
    is_primary INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS mold_library_legacy_map (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mold_library_uuid TEXT NOT NULL,
    legacy_enj_kalip_id INTEGER NOT NULL,
    match_status TEXT NOT NULL,
    UNIQUE (mold_library_uuid, legacy_enj_kalip_id)
);
CREATE TABLE IF NOT EXISTS mold_library_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mold_library_uuid TEXT NOT NULL,
    action TEXT NOT NULL,
    changed_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
"""


@pytest.fixture()
def aktif_kaliplar_db(monkeypatch):
    fd, path = tempfile.mkstemp(suffix='_aktif_kaliplar.db')
    os.close(fd)
    con0 = sqlite3.connect(path)
    con0.execute(
        'CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, aciklama TEXT)'
    )
    con0.commit()
    con0.close()
    import importlib
    mig = importlib.import_module('migrations.198_mold_library_preview')
    mig.run(path)
    con = sqlite3.connect(path)
    con.execute(
        """INSERT INTO mold_library_mold (
            library_uuid, material_group, model_code, visible_mold_code,
            business_key, review_status, source_file_sha256, source_main_row
        ) VALUES ('uuid-test-1','EVA','M-TEST','VK-1','bk-test-1','active','sha',1)"""
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


def test_aktif_kaliplar_bp_registered_on_full_app():
    import app as cps_app

    assert 'aktif_kaliplar_bp.aktif_kaliplar' in cps_app.app.view_functions


def test_aktif_kaliplar_fixture_json_200(aktif_kaliplar_db):
    from functools import wraps
    import importlib
    import modules.auth as auth_mod

    def _login(f):
        @wraps(f)
        def w(*a, **k):
            flask.session['kullanici'] = {'Id': 1, 'KullaniciAdi': 'tester'}
            return f(*a, **k)
        return w

    auth_mod.login_gerekli = _login
    import modules.planlama.aktif_kaliplar_routes as ak
    importlib.reload(ak)

    app = flask.Flask(__name__)
    app.secret_key = 'aktif-kaliplar-test'
    app.register_blueprint(ak.aktif_kaliplar_bp)
    client = app.test_client()
    with client.session_transaction() as sess:
        sess['kullanici'] = {'Id': 1, 'KullaniciAdi': 'tester'}
    rv = client.get('/planlama/aktif-kaliplar/fixture.json')
    assert rv.status_code == 200
    data = rv.get_json()
    assert data is not None
    assert 'records' in data
    assert len(data['records']) >= 1
