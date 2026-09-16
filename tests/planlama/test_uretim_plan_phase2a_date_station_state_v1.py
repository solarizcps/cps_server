# -*- coding: utf-8 -*-
"""Phase 2A — date/station state order and preservation (D03, D04, D10)."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_JS = _REPO / 'app/static/js/uretim_plan.js'
_HTML = _REPO / 'app/templates/planlama/uretim_plan.html'
_CSS = _REPO / 'app/static/css/uretim_plan.css'
_NODE_SIM = Path(__file__).resolve().parent / 'phase2a_enj_state_sim.node.js'


@pytest.fixture(scope='module')
def js():
    return _JS.read_text(encoding='utf-8')


@pytest.fixture(scope='module')
def html():
    return _HTML.read_text(encoding='utf-8')


def _section_block(js_src: str) -> str:
    idx = js_src.index('function enjUpdateStep2SectionStates')
    return js_src[idx:idx + 900]


def _station_handler_block(js_src: str) -> str:
    idx = js_src.index('function enjRenderIstasyonGrid')
    return js_src[idx:idx + 3500]


def test_section_order_station_before_mold_unlock(js):
    """TEST1 contract — istasyon bölümü kalıp seçimi olmadan açılır."""
    block = _section_block(js)
    assert 'upStep2SecIstasyon: !!(e.makineId && e.slot && hasBas)' in block
    assert 'upStep2SecKalip: !!(e.makineId && e.slot && hasBas)' in block
    assert 'enjKalipSecili()' not in block.split('upStep2SecIstasyon')[1].split('upStep2SecKalip')[0]


def test_station_handler_preserves_date(js):
    """TEST2/3 contract — istasyon change baslangicManuel sıfırlamaz."""
    block = _station_handler_block(js)
    assert 'baslangicManuel = false' not in block
    assert 'enjFetchIlkUygun(false)' not in block
    assert 'enjValidateSelectedStationsAtDate' in block


def test_fetch_ilk_uygun_does_not_clear_date_input(js):
    """D04 — enjFetchIlkUygun seçili tarihi temizlemez."""
    idx = js.index('function enjFetchIlkUygun')
    block = js[idx:idx + 1200]
    assert "upEnjBas').value = ''" not in block
    assert '!e.baslangicManuel' not in block


def test_async_sequence_guard_present(js):
    """D10 — istasyonAvailabilitySeq guard."""
    assert 'istasyonAvailabilitySeq' in js
    assert 'function enjAvailabilityStillValid' in js
    assert 'function enjValidateSelectedStationsAtDate' in js
    assert 'enjAvailabilityStillValid(capture)' in js


def test_kalip_adedi_coupling_comment_preserved(js):
    """Geçici kalipAdedi=istasyon coupling korunur; Faz 2B notu var."""
    idx = js.index('function enjSyncKalipAdediFromStations')
    block = js[idx - 120:idx + 200]
    assert "Faz 2B'de fiziksel kalıp envanteri" in block
    assert 'istasyonlar || []).length' in block


def test_calculate_requires_kalip(js):
    """TEST9 — Hesapla kalıp seçimi olmadan hazır değil."""
    idx = js.index('function enjHesaplaRequirements')
    block = js[idx:idx + 1200]
    assert "key: 'kalip'" in block
    assert 'enjKalipSecili()' in block


def test_design_lock_css_unchanged():
    """V31 CSS içeriği değişmedi (cache bump hariç)."""
    css = (_REPO / 'app/static/css/uretim_plan.css').read_text(encoding='utf-8')
    assert '.up-step2-layout' in css
    assert 'grid-template-columns' in css


def test_cache_v32(html):
    css_v = re.search(r"uretim_plan\.css['\"]?\s*\)\s*\}\}\?v=(\d+)", html)
    js_v = re.search(r"uretim_plan\.js['\"]?\s*\)\s*\}\}\?v=(\d+)", html)
    assert css_v and js_v
    assert css_v.group(1) == js_v.group(1) == '32'


def test_node_behavior_simulation():
    """TEST1–10 davranış simülasyonu (node:test)."""
    if sys.platform == 'win32':
        cmd = ['node', str(_NODE_SIM)]
    else:
        cmd = ['node', str(_NODE_SIM)]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(_REPO))
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_regression_quantity_and_validation_tests_exist():
    """TEST11 — ilgili regression test dosyaları mevcut."""
    planlama = _REPO / 'tests/planlama'
    assert (planlama / 'test_uretim_plan_update_enj_validation_v1.py').is_file()
    assert (planlama / 'test_uretim_plan_remaining_quantity_v1.py').is_file()
