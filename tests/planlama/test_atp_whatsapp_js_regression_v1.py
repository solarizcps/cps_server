# -*- coding: utf-8 -*-
"""JS regression — WhatsApp button wiring (static source inspection)."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / 'app' / 'static' / 'js' / 'planlama_arac_takip.js').read_text(encoding='utf-8')


def test_whatsapp_fetch_includes_vehicle_id():
    assert "vehicle_id=' + encodeURIComponent(vid)" in MAIN or '&vehicle_id=' in MAIN
    assert 'vehicleId()' in MAIN


def test_whatsapp_url_key_primary():
    assert 'j.whatsapp_url' in MAIN
    assert 'j.url' in MAIN


def test_no_vehicle_toast_without_fetch():
    idx = MAIN.find("toast('WhatsApp planı için önce bir araç seçin.'")
    fetch_idx = MAIN.find("fetch(waUrl", idx)
    assert idx != -1 and fetch_idx > idx


def test_backend_error_not_replaced_by_message_body():
    block = MAIN[MAIN.find('/* ─── WhatsApp ─── */'):MAIN.find('/* ─── Base location button')]
    assert 'j.error' in block or 'j.message' in block
    assert "if (!r.ok)" in block


def test_window_open_noopener():
    assert "window.open(openUrl, '_blank', 'noopener')" in MAIN
