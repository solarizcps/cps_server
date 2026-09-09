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
