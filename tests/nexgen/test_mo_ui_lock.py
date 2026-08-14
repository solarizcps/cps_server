# -*- coding: utf-8 -*-
"""Müşteri Operasyonu UI/navigation contract lock — template-only, no HTTP."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MO_HTML = ROOT / 'app' / 'templates' / 'nexgen' / 'musteri_pazarlama.html'
AJANDA_HTML = ROOT / 'app' / 'templates' / 'nexgen' / 'musteri_pazarlama_ajanda.html'


class MoUiLockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = MO_HTML.read_text(encoding='utf-8')
        cls.ajanda = AJANDA_HTML.read_text(encoding='utf-8')

    def test_cariler_sekme(self) -> None:
        self.assertIn('id="mp-sekme-cari"', self.html)
        self.assertIn('>Cariler<', self.html)

    def test_yeni_musteriler_sekme(self) -> None:
        self.assertIn('id="mp-sekme-aday"', self.html)
        self.assertIn('Yeni Müşteriler', self.html)
        self.assertIn('mp-sekme-aktif', self.html)

    def test_musteri_arama(self) -> None:
        self.assertIn('id="mp-v2-musteri-ara"', self.html)
        self.assertIn('mp-v2-ara-input', self.html)

    def test_pagination_container(self) -> None:
        for token in (
            'id="mp-v2-sayfalama"',
            'id="mp-v2-sayfa-bilgi"',
            'id="mp-v2-sayfa-ilk"',
            'id="mp-v2-sayfa-geri"',
            'id="mp-v2-sayfa-ileri"',
            'id="mp-v2-sayfa-son"',
            'id="mp-v2-sayfa-no-container"',
        ):
            self.assertIn(token, self.html)

    def test_sayfa_boyutu_12(self) -> None:
        self.assertIn('id="mp-v2-sayfa-boyutu"', self.html)
        self.assertIn('12 / sayfa', self.html)
        self.assertRegex(self.html, r'value="12"\s+selected')

    def test_ticari_kolon_basliklari(self) -> None:
        for label in (
            'Muhasebe Bakiye',
            'Beklenen Tahsilat',
            'Kalan Tahsilat',
            'Planlanan Çek',
            'En Yakın Vade',
            'Son İşlem',
        ):
            self.assertIn(label, self.html)

    def test_ajanda_href(self) -> None:
        self.assertIn('href="/nexgen/musteri-pazarlama/ajanda"', self.html)

    def test_layout_contract_no_max_width_1400(self) -> None:
        self.assertNotIn('max-width: 1400px', self.html)
        self.assertIn('main:has(#mp-sayfa)', self.html)

    def test_open_ajanda_detay_canonical(self) -> None:
        self.assertIn('function openAjandaDetay(k)', self.ajanda)
        self.assertIn('mpa-gun-ev-click', self.ajanda)

    def test_pagination_js_contract(self) -> None:
        self.assertIn('window._mpPagination', self.html)
        self.assertIn('mp-v2-sayfa-aktif', self.html)


if __name__ == '__main__':
    unittest.main()
