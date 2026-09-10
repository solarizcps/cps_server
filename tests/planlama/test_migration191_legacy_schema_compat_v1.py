# -*- coding: utf-8 -*-
"""Migration 191 öncesi legacy şema — Kalıp Master ve seri read uyumluluk testleri."""
from __future__ import annotations

import importlib
import json
import sqlite3
import sys
from pathlib import Path

import pytest
from flask import Flask

_REPO = Path(__file__).resolve().parents[2]
_APP = _REPO / 'app'
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

LEGACY_SCHEMA_SQL = """
CREATE TABLE enj_kalip (
    id INTEGER PRIMARY KEY,
    kalip_kod TEXT,
    kalip_tipi TEXT,
    model_kod TEXT,
    model_ad TEXT,
    asorti TEXT,
    kalip_basi_cift INTEGER,
    varsayilan_bagli_kalip INTEGER,
    renk TEXT,
    gorsel_dosya TEXT,
    aktif INTEGER DEFAULT 1,
    kapasite_cift INTEGER,
    kalip_durumu TEXT DEFAULT 'AKTIF',
    aciklama TEXT,
    cift_agirlik_gr REAL,
    pisme_suresi_sn INTEGER,
    guncelleme_tarihi TEXT
);
INSERT INTO enj_kalip (
    id, kalip_kod, kalip_tipi, model_kod, model_ad, asorti,
    kalip_basi_cift, varsayilan_bagli_kalip, aktif, kapasite_cift, kalip_durumu
) VALUES
 (1, 'TR-21M2', 'GOVDE', 'BRM-9000', 'Test A', NULL, 1, 8, 1, 600, 'AKTIF'),
 (2, '23M21', 'GOVDE', 'YZZ-9800', 'Test B', NULL, 1, 8, 1, 400, 'AKTIF'),
 (3, '21M5', 'GOVDE', 'CRX-71026', 'Test C', '22-28', 2, 8, 1, 3000, 'AKTIF');
"""


def _patch_mock_db(monkeypatch, db_path: str) -> None:
    """Temp DB yolu — importlib.reload kullanmadan, paylaşılan Config nesnesini patch'le."""
    import config

    monkeypatch.setenv('CPS_MOCK_DB_PATH', db_path)
    monkeypatch.setattr(config.Config, 'MOCK_DB_PATH', db_path, raising=False)


def _sqlite_conn(db_path: str) -> sqlite3.Connection:
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    return con


def _noop_yetki(*_a, **_k):
    def deco(fn):
        return fn
    return deco


@pytest.fixture
def legacy_db(tmp_path, monkeypatch):
    db = tmp_path / 'legacy_no191.db'
    con = sqlite3.connect(db)
    con.executescript(LEGACY_SCHEMA_SQL)
    con.close()
    _patch_mock_db(monkeypatch, str(db))
    yield db


@pytest.fixture
def yonetim_app(legacy_db, monkeypatch):
    import modules.auth as auth_mod
    import modules.yonetim.routes as yroutes_mod

    monkeypatch.setattr(auth_mod, 'yetki_gerekli', _noop_yetki)
    yroutes = importlib.reload(yroutes_mod)
    monkeypatch.setattr(yroutes, '_ky_db_path', lambda: str(legacy_db))

    app = Flask('legacy_schema_test')
    app.secret_key = 'test-only'
    app.register_blueprint(yroutes.yonetim_bp)
    return app, yroutes


@pytest.fixture
def plan_app(legacy_db, monkeypatch):
    import modules.auth as auth_mod
    import modules.planlama.uretim_plan_routes as upr_mod

    monkeypatch.setattr(auth_mod, 'yetki_gerekli', _noop_yetki)
    upr = importlib.reload(upr_mod)
    monkeypatch.setattr(upr, 'get_conn', lambda: _sqlite_conn(str(legacy_db)))

    app = Flask('legacy_schema_plan_test')
    app.secret_key = 'test-only'
    app.register_blueprint(upr.uretim_plan_bp, url_prefix='/planlama/uretim-plan')
    return app, upr


def test_ky_kaliplar_legacy_schema_200(yonetim_app):
    app, yroutes = yonetim_app
    with app.test_request_context('/yonetim/api/kaliplar'):
        resp = yroutes.ky_api_kaliplar()
    status = resp[1] if isinstance(resp, tuple) else 200
    data = resp[0].get_json() if isinstance(resp, tuple) else resp.get_json()
    assert status == 200
    assert data['ok'] is True
    assert data['sayi'] == 3
    first = data['kayitlar'][0]
    assert first['aktif_goz_sayisi'] is None
    assert first['kapasite_onayli'] is False


def test_ky_kaliplars_no_sqlite_error_leak(yonetim_app):
    app, yroutes = yonetim_app
    with app.test_request_context('/yonetim/api/kaliplar'):
        resp = yroutes.ky_api_kaliplar()
    body = resp[0].get_data(as_text=True) if isinstance(resp, tuple) else resp.get_data(as_text=True)
    assert 'no such column' not in body.lower()
    assert 'no such table' not in body.lower()


def test_ky_patch_legacy_field_ok(yonetim_app, legacy_db):
    app, yroutes = yonetim_app
    with app.test_request_context(
        '/yonetim/api/kalip/1',
        method='PATCH',
        json={'kalip_basi_cift': 2},
    ):
        resp = yroutes.ky_api_kalip_patch(1)
    status = resp[1] if isinstance(resp, tuple) else 200
    assert status == 200
    con = sqlite3.connect(str(legacy_db))
    val = con.execute('SELECT kalip_basi_cift FROM enj_kalip WHERE id=1').fetchone()[0]
    con.close()
    assert val == 2


def test_ky_patch_mig191_field_rejected_before_write(yonetim_app, legacy_db):
    app, yroutes = yonetim_app
    with app.test_request_context(
        '/yonetim/api/kalip/1',
        method='PATCH',
        json={'aktif_goz_sayisi': 5},
    ):
        resp = yroutes.ky_api_kalip_patch(1)
    assert resp[1] == 409
    data = resp[0].get_json()
    assert data['kod'] == 'SCHEMA_FIELD_UNAVAILABLE'
    assert 'henüz etkin değil' in data['hata']
    con = sqlite3.connect(str(legacy_db))
    assert con.execute('SELECT COUNT(*) FROM enj_kalip').fetchone()[0] == 3
    con.close()


def test_ky_patch_kapasite_onayli_rejected(yonetim_app):
    app, yroutes = yonetim_app
    with app.test_request_context(
        '/yonetim/api/kalip/2',
        method='PATCH',
        json={'kapasite_onayli': 1},
    ):
        resp = yroutes.ky_api_kalip_patch(2)
    assert resp[1] == 409
    assert resp[0].get_json()['kod'] == 'SCHEMA_FIELD_UNAVAILABLE'


def test_seri_list_legacy_empty(plan_app):
    app, upr = plan_app
    with app.test_request_context(
        '/planlama/uretim-plan/api/enj/kalip-serileri?model_kod=BRM-9000',
    ):
        resp = upr.api_enj_kalip_serileri_read()
    status = resp[1] if isinstance(resp, tuple) else 200
    data = resp[0].get_json() if isinstance(resp, tuple) else resp.get_json()
    assert status == 200
    assert data['ok'] is True
    assert data['seriler'] == []
    assert data['schema_available'] is False


def test_seri_detail_legacy_404(plan_app):
    app, upr = plan_app
    with app.test_request_context('/planlama/uretim-plan/api/enj/kalip-seri/1'):
        resp = upr.api_enj_kalip_seri_read(1)
    assert resp[1] == 404
    data = resp[0].get_json()
    assert data['kod'] == 'SERIES_SCHEMA_UNAVAILABLE'
    assert 'no such table' not in json.dumps(data).lower()


KY_KAYIT_KEYS = {
    'id', 'kalip_kod', 'kalip_tipi', 'model_kod', 'model_ad', 'asorti',
    'kalip_basi_cift', 'varsayilan_bagli_kalip', 'renk', 'gorsel_dosya', 'aktif',
    'kapasite_cift', 'kalip_durumu', 'aciklama', 'cift_agirlik_gr', 'pisme_suresi_sn',
    'aktif_goz_sayisi', 'kapasite_onayli',
}


def _sqlite_master_snapshot(con: sqlite3.Connection) -> list[tuple]:
    return con.execute(
        "SELECT type, name, sql FROM sqlite_master WHERE type IN ('table','index') ORDER BY type, name"
    ).fetchall()


@pytest.fixture
def legacy_db_69(tmp_path, monkeypatch):
    db = tmp_path / 'legacy_69.db'
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE enj_kalip (
            id INTEGER PRIMARY KEY, kalip_kod TEXT, kalip_tipi TEXT,
            model_kod TEXT, model_ad TEXT, asorti TEXT,
            kalip_basi_cift INTEGER, varsayilan_bagli_kalip INTEGER,
            renk TEXT, gorsel_dosya TEXT, aktif INTEGER DEFAULT 1,
            kapasite_cift INTEGER, kalip_durumu TEXT DEFAULT 'AKTIF',
            aciklama TEXT, cift_agirlik_gr REAL, pisme_suresi_sn INTEGER,
            guncelleme_tarihi TEXT
        );
    """)
    rows = [
        (i, f'K-{i:03d}', 'GOVDE', f'M-{i % 7}', None, None, 1, 8, None, None, 1, 100, 'AKTIF', None, None, None, None)
        for i in range(1, 70)
    ]
    con.executemany(
        """INSERT INTO enj_kalip (
            id, kalip_kod, kalip_tipi, model_kod, model_ad, asorti,
            kalip_basi_cift, varsayilan_bagli_kalip, renk, gorsel_dosya, aktif,
            kapasite_cift, kalip_durumu, aciklama, cift_agirlik_gr, pisme_suresi_sn,
            guncelleme_tarihi
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        rows,
    )
    con.commit()
    con.close()
    _patch_mock_db(monkeypatch, str(db))
    yield db


@pytest.fixture
def incomplete_seri_db(tmp_path):
    db = tmp_path / 'incomplete_seri.db'
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE enj_kalip (
            id INTEGER PRIMARY KEY, kalip_kod TEXT, kalip_tipi TEXT,
            model_kod TEXT, aktif INTEGER DEFAULT 1, kalip_basi_cift INTEGER DEFAULT 1
        );
        INSERT INTO enj_kalip VALUES (1, 'TR-1', 'GOVDE', 'BRM-9000', 1, 1);
        CREATE TABLE enj_kalip_seri (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            seri_kod TEXT NOT NULL, model_kod TEXT NOT NULL, aktif INTEGER DEFAULT 1
        );
        INSERT INTO enj_kalip_seri (seri_kod, model_kod, aktif) VALUES ('S1', 'BRM-9000', 1);
    """)
    con.close()
    return db


@pytest.fixture
def migrated_schema_db(tmp_path):
    db = tmp_path / 'migrated191.db'
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE enj_kalip (
            id INTEGER PRIMARY KEY, kalip_kod TEXT, kalip_tipi TEXT,
            model_kod TEXT, model_ad TEXT, asorti TEXT,
            kalip_basi_cift INTEGER, varsayilan_bagli_kalip INTEGER,
            renk TEXT, gorsel_dosya TEXT, aktif INTEGER DEFAULT 1,
            kapasite_cift INTEGER, kalip_durumu TEXT DEFAULT 'AKTIF',
            aciklama TEXT, cift_agirlik_gr REAL, pisme_suresi_sn INTEGER,
            aktif_goz_sayisi INTEGER, kapasite_onayli INTEGER DEFAULT 0
        );
        CREATE TABLE enj_kalip_seri (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            seri_kod TEXT NOT NULL COLLATE NOCASE,
            seri_ad TEXT, model_kod TEXT NOT NULL, model_ad TEXT,
            aciklama TEXT, aktif INTEGER NOT NULL DEFAULT 1,
            created_at TEXT, updated_at TEXT, created_by INTEGER, updated_by INTEGER,
            UNIQUE (seri_kod)
        );
        CREATE TABLE enj_kalip_seri_uye (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            seri_id INTEGER NOT NULL, kalip_id INTEGER NOT NULL,
            uye_rolu TEXT NOT NULL CHECK (uye_rolu IN ('GOVDE','ATKI','DIGER')),
            beden_numara TEXT, sira_no INTEGER,
            varsayilan_fiziksel_adet INTEGER, aktif INTEGER NOT NULL DEFAULT 1,
            created_at TEXT, updated_at TEXT, created_by INTEGER, updated_by INTEGER,
            UNIQUE (seri_id, kalip_id)
        );
        INSERT INTO enj_kalip (
            id, kalip_kod, kalip_tipi, model_kod, kalip_basi_cift, aktif,
            aktif_goz_sayisi, kapasite_onayli
        ) VALUES (1, 'TR-21M2', 'GOVDE', 'BRM-9000', 1, 1, 4, 1);
        INSERT INTO enj_kalip_seri (id, seri_kod, model_kod, aktif)
        VALUES (1, 'BRM-S1', 'BRM-9000', 1);
        INSERT INTO enj_kalip_seri_uye (seri_id, kalip_id, uye_rolu, aktif)
        VALUES (1, 1, 'GOVDE', 1);
    """)
    con.close()
    return db


def test_ky_kaliplar_response_shape(yonetim_app):
    app, yroutes = yonetim_app
    with app.test_request_context('/yonetim/api/kaliplar'):
        resp = yroutes.ky_api_kaliplar()
    data = resp[0].get_json() if isinstance(resp, tuple) else resp.get_json()
    assert set(data.keys()) >= {'ok', 'sayi', 'kayitlar'}
    for kayit in data['kayitlar']:
        assert set(kayit.keys()) == KY_KAYIT_KEYS


def test_ky_kaliplar_69_rows(legacy_db_69, monkeypatch):
    import modules.auth as auth_mod
    import modules.yonetim.routes as yroutes_mod

    monkeypatch.setattr(auth_mod, 'yetki_gerekli', _noop_yetki)
    yroutes = importlib.reload(yroutes_mod)
    monkeypatch.setattr(yroutes, '_ky_db_path', lambda: str(legacy_db_69))
    app = Flask('legacy69')
    app.register_blueprint(yroutes.yonetim_bp)
    with app.test_request_context('/yonetim/api/kaliplar'):
        resp = yroutes.ky_api_kaliplar()
    data = resp[0].get_json() if isinstance(resp, tuple) else resp.get_json()
    assert data['sayi'] == 69
    assert len(data['kayitlar']) == 69
    assert all(k['aktif_goz_sayisi'] is None for k in data['kayitlar'])
    assert all(k['kapasite_onayli'] is False for k in data['kayitlar'])


def test_ky_patch_mixed_legacy_new_atomic(yonetim_app, legacy_db):
    app, yroutes = yonetim_app
    con = sqlite3.connect(str(legacy_db))
    before = con.execute(
        'SELECT kalip_basi_cift, kapasite_cift FROM enj_kalip WHERE id=1'
    ).fetchone()
    con.close()
    with app.test_request_context(
        '/yonetim/api/kalip/1',
        method='PATCH',
        json={'kalip_basi_cift': 9, 'aktif_goz_sayisi': 3},
    ):
        resp = yroutes.ky_api_kalip_patch(1)
    assert resp[1] == 409
    assert resp[0].get_json()['kod'] == 'SCHEMA_FIELD_UNAVAILABLE'
    con = sqlite3.connect(str(legacy_db))
    after = con.execute(
        'SELECT kalip_basi_cift, kapasite_cift FROM enj_kalip WHERE id=1'
    ).fetchone()
    con.close()
    assert after == before


def test_seri_incomplete_list_409(incomplete_seri_db, monkeypatch):
    import modules.auth as auth_mod
    import modules.planlama.uretim_plan_routes as upr_mod

    monkeypatch.setattr(auth_mod, 'yetki_gerekli', _noop_yetki)
    upr = importlib.reload(upr_mod)
    monkeypatch.setattr(upr, 'get_conn', lambda: _sqlite_conn(str(incomplete_seri_db)))
    app = Flask('inc')
    app.register_blueprint(upr.uretim_plan_bp, url_prefix='/planlama/uretim-plan')
    with app.test_request_context('/planlama/uretim-plan/api/enj/kalip-serileri?model_kod=BRM-9000'):
        resp = upr.api_enj_kalip_serileri_read()
    assert resp[1] == 409
    assert resp[0].get_json()['kod'] == 'SERIES_SCHEMA_INCOMPLETE'


def test_seri_incomplete_detail_409(incomplete_seri_db, monkeypatch):
    import modules.auth as auth_mod
    import modules.planlama.uretim_plan_routes as upr_mod

    monkeypatch.setattr(auth_mod, 'yetki_gerekli', _noop_yetki)
    upr = importlib.reload(upr_mod)
    monkeypatch.setattr(upr, 'get_conn', lambda: _sqlite_conn(str(incomplete_seri_db)))
    app = Flask('inc2')
    app.register_blueprint(upr.uretim_plan_bp, url_prefix='/planlama/uretim-plan')
    with app.test_request_context('/planlama/uretim-plan/api/enj/kalip-seri/1'):
        resp = upr.api_enj_kalip_seri_read(1)
    assert resp[1] == 409
    assert resp[0].get_json()['kod'] == 'SERIES_SCHEMA_INCOMPLETE'


def test_migrated_schema_reads_real_fields(migrated_schema_db):
    from modules.planlama.enj_kalip_seri_service import get_seri_detail, read_series_for_model

    con = sqlite3.connect(str(migrated_schema_db))
    con.row_factory = sqlite3.Row
    master = _sqlite_master_snapshot(con)
    rows = read_series_for_model(con, 'BRM-9000')
    assert len(rows) == 1
    assert rows[0]['uyeler'][0]['aktif_goz_sayisi'] == 4
    assert rows[0]['uyeler'][0]['kapasite_onayli'] is True
    detail = get_seri_detail(con, 1, aktif_uyeler_only=True)
    assert detail['uyeler'][0]['kalip_kod'] == 'TR-21M2'
    after = _sqlite_master_snapshot(con)
    assert master == after
    con.close()


def test_ky_kaliplar_sqlite_master_unchanged(yonetim_app, legacy_db):
    con = sqlite3.connect(str(legacy_db))
    before = _sqlite_master_snapshot(con)
    con.close()
    app, yroutes = yonetim_app
    with app.test_request_context('/yonetim/api/kaliplar'):
        yroutes.ky_api_kaliplar()
    con = sqlite3.connect(str(legacy_db))
    after = _sqlite_master_snapshot(con)
    con.close()
    assert before == after


def test_schema_helpers_read_only(legacy_db):
    from modules.planlama.enj_schema_compat import (
        column_names,
        has_column,
        ky_kaliplar_select_sql,
        series_schema_state,
        table_exists,
    )

    con = sqlite3.connect(str(legacy_db))
    assert table_exists(con, 'enj_kalip') is True
    assert table_exists(con, 'enj_kalip_seri') is False
    cols = column_names(con, 'enj_kalip')
    assert 'kalip_basi_cift' in cols
    assert 'aktif_goz_sayisi' not in cols
    assert has_column(con, 'enj_kalip', 'kapasite_onayli') is False
    assert series_schema_state(con) == 'absent'
    sql = ky_kaliplar_select_sql(con)
    assert 'NULL AS aktif_goz_sayisi' in sql
    assert '0 AS kapasite_onayli' in sql
    rows = con.execute(sql).fetchall()
    assert len(rows) == 3
    con.close()
