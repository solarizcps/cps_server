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
    popup_idx = MAIN.find("window.open('about:blank'", idx)
    assert idx != -1
    assert fetch_idx == -1 or popup_idx == -1 or popup_idx < fetch_idx


def test_popup_opens_before_fetch():
    assert "window.open('about:blank', '_blank')" in BLOCK
    assert 'popup.location.replace(j.whatsapp_url)' in BLOCK


def test_backend_error_closes_popup():
    assert 'closeWhatsappPopup(popup)' in BLOCK
    assert 'j.error' in BLOCK
    assert 'j.message' not in BLOCK


def test_legacy_preview_removal_hook():
    assert 'removeLegacyWhatsappPreview' in MAIN
