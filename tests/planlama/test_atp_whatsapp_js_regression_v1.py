# -*- coding: utf-8 -*-
"""JS regression — WhatsApp button wiring (static source inspection)."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / 'app' / 'static' / 'js' / 'planlama_arac_takip.js').read_text(encoding='utf-8')
BLOCK = MAIN[MAIN.find('/* ─── WhatsApp'):MAIN.find('/* ─── Base location button')]


def test_whatsapp_fetch_includes_vehicle_id():
    assert "vehicle_id=' + encodeURIComponent(vid)" in MAIN or '&vehicle_id=' in MAIN
    assert 'vehicleId()' in MAIN


def test_whatsapp_url_key_only_no_legacy_url():
    assert 'j.whatsapp_url' in BLOCK
    assert 'j.url' not in BLOCK


def test_no_vehicle_toast_without_fetch():
    idx = MAIN.find("toast('WhatsApp için önce bir araç planı seçin.'")
    fetch_idx = MAIN.find("fetch(waUrl", idx)
    open_idx = MAIN.find('window.open(webSendUrl', idx)
    assert idx != -1
    assert fetch_idx != -1
    assert open_idx == -1 or fetch_idx < open_idx


def test_success_opens_whatsapp_web_send():
    assert 'https://web.whatsapp.com/send?text=' in BLOCK
    assert 'buildWhatsappWebSendUrl' in BLOCK
    assert 'whatsapp://' not in BLOCK
    assert "window.open('about:blank'" not in BLOCK


def test_backend_error_shows_toast():
    assert 'j.error' in BLOCK
    assert 'WhatsApp planı hazırlanamadı.' in BLOCK
    assert 'j.message' not in BLOCK
    assert 'closeWhatsappPopup' not in BLOCK


def test_legacy_preview_removal_hook():
    assert 'removeLegacyWhatsappPreview' in MAIN
