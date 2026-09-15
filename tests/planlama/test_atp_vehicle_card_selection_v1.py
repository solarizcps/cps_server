# -*- coding: utf-8 -*-
"""Vehicle card direct selection — click, keyboard, selected state, cursor."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / 'app' / 'static' / 'js' / 'planlama_arac_takip.js').read_text(encoding='utf-8')
CSS = (ROOT / 'app' / 'static' / 'css' / 'planlama_arac_takip.css').read_text(encoding='utf-8')


def test_vehicle_card_delegated_click_handler():
    assert 'initVehicleCardSelection' in MAIN
    assert 'initVehicleCardSelection._bound' in MAIN
    assert "e.target.closest('.vcard')" in MAIN
    assert "openPlanRouteForVehicle(vid)" in MAIN


def test_vehicle_card_vid_before_selected_class():
    idx_vid = MAIN.find('var vid = v.arac_external_id || v.id ||')
    idx_sel = MAIN.find("cardCls += ' selected'")
    assert idx_vid != -1 and idx_sel != -1
    assert idx_vid < idx_sel


def test_vehicle_card_action_buttons_stop_propagation():
    assert "e.target.closest('.atp-v2-open-plan, .atp-v2-timeline-btn, button, a" in MAIN


def test_vehicle_card_cursor_pointer_css():
    assert '#atpV2Root .vcard' in CSS
    vcard_block = CSS[CSS.find('#atpV2Root .vcard {'):CSS.find('#atpV2Root .vcard.ok')]
    assert 'cursor:pointer' in vcard_block.replace(' ', '')


def test_vehicle_card_keyboard_access():
    assert "e.key !== 'Enter' && e.key !== ' '" in MAIN
    assert 'role="button" tabindex="0"' in MAIN
