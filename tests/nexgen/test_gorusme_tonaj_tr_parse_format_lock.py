# -*- coding: utf-8 -*-
"""Görüşme konuşulan tonaj — TR parse/format regression LOCK."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'app'))

from modules.nexgen.mo_gorusme_service import (
    MoGorusmeError,
    _parse_konusulan_tonaj,
    _validate_fiyat_snapshot,
    format_tr_tonaj,
    fiyat_ozet_metin,
)

MO_TPL = Path(__file__).resolve().parents[2] / 'app' / 'templates' / 'nexgen' / 'musteri_pazarlama.html'
C360_TPL = Path(__file__).resolve().parents[2] / 'app' / 'templates' / 'nexgen' / 'cari360_kart.html'


def _fiyat_payload(**kw):
    base = {
        'fiyat_verildi': 1,
        'verilen_fiyat': 5,
        'fiyat_para_birimi': 'USD',
        'fiyat_birimi': 'KG',
        'odeme_tipi': 'NAKIT',
    }
    base.update(kw)
    return base


class TonajTrParseTests(unittest.TestCase):
    def test_numeric_and_string_plain(self) -> None:
        self.assertEqual(_parse_konusulan_tonaj(10000), 10000.0)
        self.assertEqual(_parse_konusulan_tonaj('10000'), 10000.0)

    def test_tr_thousand_dot(self) -> None:
        self.assertEqual(_parse_konusulan_tonaj('10.000'), 10000.0)
        self.assertEqual(_parse_konusulan_tonaj('100.000'), 100000.0)
        self.assertEqual(_parse_konusulan_tonaj('1.234.567'), 1234567.0)

    def test_tr_decimal_comma(self) -> None:
        self.assertEqual(_parse_konusulan_tonaj('10,5'), 10.5)
        self.assertEqual(_parse_konusulan_tonaj('10.000,5'), 10000.5)
        self.assertEqual(_parse_konusulan_tonaj('0,5'), 0.5)

    def test_ascii_decimal_dot(self) -> None:
        self.assertEqual(_parse_konusulan_tonaj('10.5'), 10.5)
        self.assertEqual(_parse_konusulan_tonaj('10.50'), 10.5)

    def test_empty_none(self) -> None:
        self.assertIsNone(_parse_konusulan_tonaj(None))
        self.assertIsNone(_parse_konusulan_tonaj(''))
        self.assertIsNone(_parse_konusulan_tonaj('   '))

    def test_invalid_returns_none(self) -> None:
        self.assertIsNone(_parse_konusulan_tonaj('abc'))
        self.assertIsNone(_parse_konusulan_tonaj('10a'))

    def test_validate_zero_negative_invalid(self) -> None:
        with self.assertRaises(MoGorusmeError):
            _validate_fiyat_snapshot(_fiyat_payload(konusulan_tonaj=0))
        with self.assertRaises(MoGorusmeError):
            _validate_fiyat_snapshot(_fiyat_payload(konusulan_tonaj=-1))
        with self.assertRaises(MoGorusmeError):
            _validate_fiyat_snapshot(_fiyat_payload(konusulan_tonaj='abc'))
        with self.assertRaises(MoGorusmeError):
            _validate_fiyat_snapshot(_fiyat_payload(konusulan_tonaj='0'))

    def test_validate_tr_string_roundtrip(self) -> None:
        snap = _validate_fiyat_snapshot(_fiyat_payload(konusulan_tonaj='10.000'))
        self.assertEqual(snap['konusulan_tonaj'], 10000.0)


class TonajTrDisplayTests(unittest.TestCase):
    def test_format_tr_tonaj(self) -> None:
        self.assertEqual(format_tr_tonaj(10000), '10.000')
        self.assertEqual(format_tr_tonaj(10000.5), '10.000,5')
        self.assertEqual(format_tr_tonaj(10.5), '10,5')
        self.assertEqual(format_tr_tonaj(100000), '100.000')

    def test_fiyat_ozet_tonaj_format(self) -> None:
        oz = fiyat_ozet_metin(_fiyat_payload(konusulan_tonaj=10000))
        self.assertIn('10.000 ton', oz or '')
        self.assertIn('5 USD/KG', oz or '')
        self.assertIn('NAKİT', oz or '')

    def test_fiyat_ozet_decimal_tonaj(self) -> None:
        oz = fiyat_ozet_metin(_fiyat_payload(konusulan_tonaj=10000.5))
        self.assertIn('10.000,5 ton', oz or '')

    def test_fiyat_ozet_large_tonaj_display_only(self) -> None:
        """652 benzeri canonical 100000 → 100.000 ton (DB değişmez)."""
        oz = fiyat_ozet_metin(_fiyat_payload(konusulan_tonaj=100000))
        self.assertIn('100.000 ton', oz or '')
        self.assertNotIn('100000 ton', oz or '')


class TonajFormTemplateLockTests(unittest.TestCase):
    def test_mo_form_label_and_placeholder(self) -> None:
        src = MO_TPL.read_text(encoding='utf-8')
        self.assertIn('Konuşulan Tonaj (ton)', src)
        self.assertIn('placeholder="10.000"', src)
        self.assertIn('function parseTrTonaj', src)
        self.assertIn('parseTrTonaj(payload.konusulan_tonaj)', src)

    def test_mo_fiyat_birimi_kg_unchanged(self) -> None:
        src = MO_TPL.read_text(encoding='utf-8')
        self.assertIn('name="fiyat_birimi"', src)
        self.assertIn('<option value="KG">KG</option>', src)
        self.assertNotIn('parseTrTonaj(el.value)', src.replace('parseTrTonaj(payload.konusulan_tonaj)', ''))

    def test_parse_tr_money_unchanged(self) -> None:
        src = MO_TPL.read_text(encoding='utf-8')
        self.assertIn('function parseTrMoney', src)
        self.assertIn('bindMoneyInput', src)

    def test_cari360_expand_format(self) -> None:
        src = C360_TPL.read_text(encoding='utf-8')
        self.assertIn('function formatTrSayi', src)
        self.assertIn('function formatTonajTr', src)
        self.assertIn('formatTonajTr(g.konusulan_tonaj)', src)
        self.assertNotIn("esc(String(g.konusulan_tonaj)) + ' ton'", src)


if __name__ == '__main__':
    unittest.main()
