# -*- coding: utf-8 -*-
"""MACHINE_SIDE_BASE_DATE_FIX_V1 — Base ilk uygun / seçilen tarih ayrımı."""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SERVICE = _REPO / 'app/modules/planlama/enj_plan_availability_service.py'
_JS = _REPO / 'app/static/js/uretim_plan.js'
_CSS = _REPO / 'app/static/css/uretim_plan.css'
_HTML = _REPO / 'app/templates/planlama/uretim_plan.html'


@pytest.fixture(scope='module')
def service_src():
    return _SERVICE.read_text(encoding='utf-8')


@pytest.fixture(scope='module')
def js():
    return _JS.read_text(encoding='utf-8')


@pytest.fixture(scope='module')
def css():
    return _CSS.read_text(encoding='utf-8')


@pytest.fixture(scope='module')
def html():
    return _HTML.read_text(encoding='utf-8')


# ── SERVICE / API ─────────────────────────────────────────────────────────────

def test_service_base_fields_defined(service_src):
    assert 'base_first_available' in service_src
    assert 'base_first_available_gosterim' in service_src
    assert 'base_first_available_tam' in service_src


def test_service_base_uses_now_not_anchor(service_src):
    """Base hesap from_dt=None ile yapılır — anchor'dan bağımsız."""
    idx = service_src.index('# A) Base first available')
    block = service_src[idx:idx+900]
    assert 'from_dt=None' in block
    assert 'base_first_avail' in block
    assert 'base_first_disp' in block


def test_service_legacy_first_available_preserved(service_src):
    """Geriye uyumluluk: first_available alanı korunuyor."""
    assert "'first_available': first_avail" in service_src
    assert "'first_available_gosterim': first_disp" in service_src


def test_build_makine_detay_base_independent_of_anchor():
    """Mock: base tarih anchor'dan farklı kalmalı."""
    sys_path = str(_REPO / 'app')
    import sys
    sys.path.insert(0, sys_path)
    try:
        from modules.planlama.enj_plan_availability_service import build_makine_detay

        con = sqlite3.connect(':memory:')
        con.row_factory = sqlite3.Row
        con.executescript("""
            CREATE TABLE enj_makine (id INTEGER PRIMARY KEY, kod TEXT, istasyon_sayisi INT, aktif INT, sira INT);
            INSERT INTO enj_makine VALUES (1, 'M1', 8, 1, 1);
        """)
        con.commit()

        base_dt = datetime(2026, 9, 9, 17, 0)
        anchor_dt = datetime(2026, 9, 16, 15, 48)

        def fake_find(con, mid, slot, ist, *, calisma_modu='GUNDUZ_GECE',
                      hafta_sonu='HAYIR', hs_vardiya=None, from_dt=None, haric_plan_id=None):
            if from_dt is None:
                return base_dt
            return anchor_dt

        with patch('modules.planlama.enj_plan_availability_service.find_first_available_start', side_effect=fake_find), \
             patch('modules.planlama.enj_kapasite_read_service.build_side_physical_block', return_value={
                 'occupied_count': 0, 'empty_count': 8, 'total_count': 8, 'stations': [],
             }), \
             patch('modules.planlama.enj_plan_availability_service.build_side_planned_block', return_value={
                 'planned_count': 1, 'available_count': 7, 'total_count': 8,
                 'stations': [], 'plan_tarih_secilmedi': False,
             }):
            det = build_makine_detay(
                con, 1,
                plan_baslangic='2026-09-16 15:48:00',
                secim_baslangic='2026-09-16 15:48:00',
                include_stations=False,
            )

        side_a = det['sides']['A']
        assert side_a['base_first_available_gosterim'] == '09.09 17:00'
        assert '16.09' in (side_a['first_available_gosterim'] or '')
    finally:
        if sys_path in sys.path:
            sys.path.remove(sys_path)


# ── FRONTEND CONTRACT ─────────────────────────────────────────────────────────

def test_js_base_map_state(js):
    assert 'baseFirstAvailableMap' in js
    assert 'slotOzetSeq' in js


def test_js_merge_base_function(js):
    assert 'function enjMergeBaseFromSlotOzet' in js
    assert 'base_first_available_gosterim' in js


def test_js_side_card_uses_base_not_anchor(js):
    idx = js.index('function enjSideCardBlock')
    block = js[idx:idx+1200]
    assert 'enjSideBaseDate' in block
    assert 'first_available_gosterim' not in block, \
        'Kart hâlâ first_available_gosterim (anchor) kullanıyor'


def test_js_plan_row_selected_side_only(js):
    idx = js.index('function enjSideCardBlock')
    block = js[idx:idx+1200]
    assert 'up-enj-card-plan-row' in block
    assert 'e.makineId === machineId' in block
    assert 'e.slot === slotKey' in block


def test_js_async_race_guard(js):
    idx = js.index('function enjYukleSlotOzet')
    block = js[idx:idx+800]
    assert 'slotOzetSeq' in block
    assert 'seq !== e.slotOzetSeq' in block


def test_js_prune_stations_on_date_change(js):
    assert 'function enjPruneInvalidStations' in js
    assert 'upEnjIstasyonDateWarn' in js


def test_js_en_erken_uses_base_map(js):
    idx = js.index('function enjUseIlkUygunDate')
    block = js[idx:idx+400]
    assert 'ilkUygunMap' in block


def test_css_no_ellipsis_on_card_date(css):
    idx = css.index('.up-enj-card-ilk-val')
    block = css[idx:idx+200]
    assert 'text-overflow: ellipsis' not in block


def test_css_plan_row_styles(css):
    assert '.up-enj-card-plan-lbl' in css
    assert '.up-enj-card-plan-val' in css


def test_cache_v23(html):
    """CSS ve JS versiyonları eşit ve >=23 olmalı"""
    import re
    css_v = re.search(r"uretim_plan\.css['\"]?\s*\)\s*\}\}\?v=(\d+)", html)
    js_v = re.search(r"uretim_plan\.js['\"]?\s*\)\s*\}\}\?v=(\d+)", html)
    assert css_v and int(css_v.group(1)) >= 23
    assert js_v and int(js_v.group(1)) >= 23
    assert css_v.group(1) == js_v.group(1)
