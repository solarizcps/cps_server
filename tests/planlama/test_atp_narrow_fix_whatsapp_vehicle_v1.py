# -*- coding: utf-8 -*-
"""Narrow fix regression — WhatsApp direct open + vehicle card direct click."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / 'app' / 'static' / 'js' / 'planlama_arac_takip.js').read_text(encoding='utf-8')
CSS = (ROOT / 'app' / 'static' / 'css' / 'planlama_arac_takip.css').read_text(encoding='utf-8')
WA_BLOCK = MAIN[MAIN.find('/* ─── WhatsApp'):MAIN.find('/* ─── Base location button')]


def test_whatsapp_web_send_url_from_api():
    assert 'https://web.whatsapp.com/send?text=' in WA_BLOCK
    assert 'buildWhatsappWebSendUrl' in WA_BLOCK
    assert 'whatsapp://' not in WA_BLOCK
    assert 'window.confirm' not in WA_BLOCK
    assert '1600' not in WA_BLOCK
    assert "window.open('about:blank'" not in WA_BLOCK


def test_whatsapp_single_bind_and_inflight_guard():
    assert 'data-atp-wa-bound' in WA_BLOCK
    assert '_waInFlight' in WA_BLOCK
    assert 'bindWhatsappButton' in WA_BLOCK
    assert WA_BLOCK.count("addEventListener('click'") == 1


def test_whatsapp_fetch_before_web_open():
    handler = WA_BLOCK[WA_BLOCK.find("btnWa.addEventListener('click'"):]
    idx_fetch = handler.find('fetch(waUrl')
    idx_open = handler.find('window.open(webSendUrl')
    assert idx_fetch != -1 and idx_open != -1
    assert idx_fetch < idx_open


def test_whatsapp_error_toasts_no_popup_staging():
    assert 'isValidWhatsappUrl' in WA_BLOCK
    assert 'j.error' in WA_BLOCK or 'WhatsApp planı hazırlanamadı.' in WA_BLOCK
    assert '.finally(function ()' in WA_BLOCK
    assert 'closeWhatsappPopup' not in WA_BLOCK


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
