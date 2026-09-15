# -*- coding: utf-8 -*-
"""Narrow UI regression — sıra dışı ziyaret günlük + geçmiş gösterimi."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / 'app' / 'static' / 'js' / 'planlama_arac_takip.js').read_text(encoding='utf-8')


def test_daily_make_alert_row_shows_oos_fields():
    assert "a.type === 'OUT_OF_SEQUENCE_VISIT'" in MAIN
    assert 'expected_stop' in MAIN
    assert 'actual_stop' in MAIN
    assert 'olay_zamani' in MAIN


def test_history_detail_renders_oos_block():
    assert '_hdmOosAlertsBlock' in MAIN
    assert 'out_of_sequence_alerts' in MAIN
    assert 'Sıra dışı ziyaret uyarıları' in MAIN
    assert 'Beklenen:' in MAIN and 'Gidilen:' in MAIN
