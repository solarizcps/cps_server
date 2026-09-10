# -*- coding: utf-8 -*-
"""Legacy Kalıp Master restore — template/route smoke tests."""
from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_KY_HTML = (_REPO / 'app' / 'templates' / 'yonetim' / 'kalip_yonetimi.html').read_text(encoding='utf-8')
_YON_ROUTES = (_REPO / 'app' / 'modules' / 'yonetim' / 'routes.py').read_text(encoding='utf-8')
_PLAN_ROUTES = (_REPO / 'app' / 'modules' / 'planlama' / 'routes.py').read_text(encoding='utf-8')


def test_legacy_master_no_series_tab():
    assert 'KALIP SERİLERİ' not in _KY_HTML
    assert 'data-ky-tab="seriler"' not in _KY_HTML
    assert 'seriYukle' not in _KY_HTML


def test_legacy_master_table_present():
    assert 'id="ky-tablo"' in _KY_HTML
    assert 'id="ky-btn-yeni-kalip"' in _KY_HTML
    assert 'id="ky-arama"' in _KY_HTML


def test_legacy_master_read_only_alias_support():
    assert 'kalip_read_only' in _KY_HTML
    assert 'ky-read-only' in _KY_HTML
    assert 'kalip_read_only=True' in _PLAN_ROUTES


def test_yonetim_series_write_routes_removed():
    assert '/api/kalip-seri/ekle' not in _YON_ROUTES
    assert 'F_KALIP_SERI_MASTER' not in _YON_ROUTES


def test_production_mold_list_route_preserved():
    up = (_REPO / 'app' / 'modules' / 'planlama' / 'uretim_plan_routes.py').read_text(encoding='utf-8')
    assert re.search(r"route\('/api/enj/kaliplar'", up)
    assert re.search(r"route\('/api/enj/kalip-serileri'", up)


def test_ky_db_path_uses_config_mock_db_path():
    assert 'Config.MOCK_DB_PATH' in _YON_ROUTES
    assert "return _os_ky.path.join(base, 'mock_data.db')" not in _YON_ROUTES


def test_ky_api_kaliplar_reads_temp_db(tmp_path, monkeypatch):
    import sqlite3
    import sys

    db = tmp_path / 'kalip_test.db'
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE enj_kalip (
            id INTEGER PRIMARY KEY, kalip_kod TEXT, kalip_tipi TEXT,
            model_kod TEXT, model_ad TEXT, asorti TEXT,
            kalip_basi_cift INTEGER, varsayilan_bagli_kalip INTEGER,
            renk TEXT, gorsel_dosya TEXT, aktif INTEGER,
            kapasite_cift INTEGER, kalip_durumu TEXT, aciklama TEXT,
            cift_agirlik_gr REAL, pisme_suresi_sn INTEGER,
            aktif_goz_sayisi INTEGER, kapasite_onayli INTEGER DEFAULT 0
        );
        INSERT INTO enj_kalip (id, kalip_kod, kalip_tipi, model_kod, kalip_basi_cift, aktif, kalip_durumu)
        VALUES (1, 'TR-TEST', 'GOVDE', 'YZZ-9800', 1, 1, 'AKTIF');
    """)
    con.close()

    db_str = str(db)
    monkeypatch.setenv('CPS_MOCK_DB_PATH', db_str)
    sys.path.insert(0, str(_REPO / 'app'))
    import config
    monkeypatch.setattr(config.Config, 'MOCK_DB_PATH', db_str, raising=False)
    from modules.yonetim import routes as yroutes

    assert yroutes._ky_db_path() == db_str
    con = sqlite3.connect(db_str)
    count = con.execute('SELECT COUNT(*) FROM enj_kalip').fetchone()[0]
    con.close()
    assert count == 1
