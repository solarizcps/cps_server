# -*- coding: utf-8 -*-
"""Dar test — WhatsApp Web doğrudan send URL açılışı."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / 'app' / 'static' / 'js' / 'planlama_arac_takip.js').read_text(encoding='utf-8')
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
    assert 'WhatsApp planı hazırlanamadı.' in WA_BLOCK
    assert '.finally(function ()' in WA_BLOCK
    assert 'closeWhatsappPopup' not in WA_BLOCK
