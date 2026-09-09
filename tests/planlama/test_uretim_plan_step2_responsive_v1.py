# -*- coding: utf-8 -*-
"""Üretim Planı Adım 2 UX — statik DOM/JS/CSS sözleşme testleri."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_HTML = _REPO / 'app/templates/planlama/uretim_plan.html'
_JS = _REPO / 'app/static/js/uretim_plan.js'
_CSS = _REPO / 'app/static/css/uretim_plan.css'


@pytest.fixture(scope='module')
def html():
    return _HTML.read_text(encoding='utf-8')


@pytest.fixture(scope='module')
def js():
    return _JS.read_text(encoding='utf-8')


@pytest.fixture(scope='module')
def css():
    return _CSS.read_text(encoding='utf-8')


def _section_ids(html: str) -> list[str]:
    return re.findall(r'id="(upStep2Sec[^"]+)"', html)


def test_selection_dom_order(html):
    """SELECTION_DOM_ORDER=PASS"""
    ids = _section_ids(html)
    expected = [
        'upStep2SecMakine', 'upStep2SecSlot', 'upStep2SecTarih', 'upStep2SecKalip',
        'upStep2SecIstasyon', 'upStep2SecMiktar', 'upStep2SecVardiya', 'upStep2SecHs',
        'upStep2SecTur', 'upStep2SecHesap',
    ]
    assert ids == expected


def test_mold_count_readonly(html):
    """MOLD_COUNT_READONLY=PASS"""
    m = re.search(r'id="upEnjKalipAdedi"[^>]*>', html)
    assert m, 'upEnjKalipAdedi input missing'
    assert 'readonly' in m.group(0)


def test_sticky_summary_and_footer(html, css):
    """SUMMARY_VISIBLE / STICKY_FOOTER markup=PASS"""
    assert 'upStep2KurulumOzet' in html
    assert 'up-create-foot' in html
    assert '.up-step2-summary' in css
    assert 'up-create-foot' in css


def test_backdrop_does_not_close(html):
    """BACKDROP_DOES_NOT_CLOSE=PASS"""
    create_block = html.split('upCreateModal')[1].split('upEnjConflictModal')[0]
    assert 'upCreateBackdrop' in create_block
    assert 'data-close="1"' not in create_block.split('upCreateBackdrop')[0]


def test_dirty_close_confirm_js(js):
    """DIRTY_FORM_X_REQUIRES_CONFIRM / ESC=PASS (source)"""
    assert 'requestCloseCreateModal' in js
    assert 'createModalIsDirty' in js
    assert 'Kaydedilmemiş seçimler silinecek' in js


def test_machine_change_confirm_js(js):
    """MACHINE_CHANGE_CONFIRM / CANCEL_PRESERVES=PASS (source)"""
    assert 'enjRequestMakineChange' in js
    assert 'Makine değiştirildiğinde slot' in js


def test_calculate_requirements_single_source(js):
    """CALCULATE_REQUIREMENTS_SINGLE_SOURCE=PASS"""
    assert 'function enjHesaplaRequirements' in js
    assert 'function enjCanHesapla' in js
    assert 'enjHesaplaRequirements().every' in js
    assert 'upEnjHesapReqList' in js


def test_quantity_summary_api_js(js):
    """QUANTITY_SUMMARY wiring=PASS"""
    assert 'kalem-miktar-ozet' in js
    assert 'enjUpdateMiktarOzet' in js
    assert 'TOPLAM SİPARİŞ' in js


def test_mold_duplicate_display_js(js):
    """MOLD_DUPLICATE_DISPLAY=PASS (source)"""
    assert 'Sipariş asortisi' in js
    assert 'Kayıt ' in js


def test_machine_detail_preserved(html, js):
    """MACHINE_DETAIL_STATE_PRESERVED / CONTRACT=PASS (source)"""
    assert 'upEnjMakineDetayModal' in html
    assert 'stopPropagation' in js
    assert 'makine-detay' in js


def test_responsive_css(css):
    """CSS responsive hooks present — browser NOT_MEASURED"""
    assert '100dvh' in css or '96vh' in css
    assert 'overflow-x: hidden' in css
    assert 'min-height: 0' in css
    assert '@media (max-width: 1099px)' in css


def test_no_font_below_12px(css):
    """NO_FONT_BELOW_12PX=PASS (step2 scoped block)"""
    step2_block = css.split('.up-step2-layout')[1].split('@media (max-width: 720px)')[0]
    bad = re.findall(r'font-size:\s*(\d+)px', step2_block)
    tiny = [int(x) for x in bad if int(x) < 12]
    assert not tiny, f'step2 font-size below 12px: {tiny}'


def test_quantity_passthrough_route():
    """QUANTITY endpoint passthrough exists"""
    routes = (_REPO / 'app/modules/planlama/uretim_plan_routes.py').read_text(encoding='utf-8')
    service = (_REPO / 'app/modules/planlama/uretim_plan_service.py').read_text(encoding='utf-8')
    assert 'kalem-miktar-ozet' in routes
    assert 'resolve_line_quantity_summary' in service
    assert 'already_planned_quantity' in service
