# -*- coding: utf-8 -*-
"""Cari360 V2 layout — template contract LOCK (C360-0)."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[2] / 'app' / 'templates' / 'nexgen' / 'cari360_kart.html'

TAB_LABELS = (
    'Genel Bilgiler',
    'Sipariş Geçmişi',
    'Üretim',
    'Sevkiyatlar',
    # 'Son Aldığı Ürünler' — C360-UX-REV kaldırıldı
    'Numuneler',
    'Görüşmeler',
    'Finans',
    'Onaylar',
    'Hafıza / Timeline',
    'Dosyalar',
    'Notlar',
)

TAB_DATA = (
    'genel',
    'siparisler',
    'uretim',
    'sevkiyatlar',
    # 'urunler' — sekme kaldırıldı; panel hâlâ DOM'da (display:none)
    'numuneler',
    'gorusmeler',
    'finans',
    'onaylar',
    'hafiza',
    'dosyalar',
    'notlar',
)

LOADER_MARKERS = (
    'function ckartFinansYukle',
    'function ckartOnaylarYukle',
    'function ckartHafizaTabYukle',
    'window.ckartGorusmeYukle',
)


class Cari360V2LayoutLockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.src = TEMPLATE.read_text(encoding='utf-8')

    def test_a_v2_header_and_container_css(self) -> None:
        self.assertIn('ckart-ust-v2', self.src)
        self.assertIn('ckart-sekme-bar-v2', self.src)
        # C360-UX-REV: max-width 100% (tam ekran kullanımı)
        self.assertRegex(self.src, r'\.ckart\s*\{[^}]*max-width:\s*100%')
        self.assertNotRegex(self.src, r'\.ckart\s*\{[^}]*max-width:\s*1100px')

    def test_b_eleven_tabs_exact_labels(self) -> None:
        """Son Aldığı Ürünler sekmesi kaldırıldı — C360-UX-REV (11 sekme)."""
        for label in TAB_LABELS:
            self.assertIn(label, self.src, msg=f'missing tab label: {label}')
        for tab in TAB_DATA:
            self.assertIn(f'data-tab="{tab}"', self.src, msg=f'missing data-tab: {tab}')
        self.assertEqual(len(TAB_LABELS), 11)
        self.assertEqual(len(TAB_DATA), 11)
        self.assertNotIn('data-tab="yetkililer"', self.src)
        self.assertNotIn('id="ckart-panel-yetkililer"', self.src)
        # Sekme butonu kaldırıldı; panel hâlâ DOM'da
        self.assertNotIn('>Son Aldığı Ürünler</button>', self.src)
        self.assertIn('id="ckart-panel-urunler"', self.src)

    def test_b2_son_alis_fiyat_karti(self) -> None:
        """Son Alış Fiyatı kartı üst kartta mevcut."""
        self.assertIn('ckart-son-alis-kart', self.src)
        self.assertIn('ckart-son-alis-fiyat', self.src)
        self.assertIn('urun_fiyatlari', self.src)
        self.assertIn('son_net_birim_fiyat', self.src)
        self.assertNotIn('Kayıtlı Toplam', self.src)
        self.assertNotIn('Para Birimleri</span>', self.src)

    def test_c_panel_sections_and_tab_map(self) -> None:
        panels = list(TAB_DATA) + ['urunler']
        for tab in panels:
            self.assertIn(f'id="ckart-panel-{tab}"', self.src, msg=f'missing panel: {tab}')
        for marker in ('finans', 'onaylar', 'hafiza', 'dosyalar', 'notlar'):
            self.assertIn(f"{marker}: 'ckart-panel-{marker}'", self.src)

    def test_d_tab_loaders_present(self) -> None:
        for fn in LOADER_MARKERS:
            self.assertIn(fn, self.src, msg=f'missing loader: {fn}')
        # C360-CANONICAL-REFRESH-01: finans/hafiza artık invalidate + call formatında
        self.assertIn("ckartFinansYukle()", self.src)
        self.assertIn("if (tab === 'onaylar') ckartOnaylarYukle()", self.src)
        self.assertIn("ckartHafizaTabYukle()", self.src)
        self.assertIn("if (tab === 'gorusmeler') ckartGorusmeYukle()", self.src)

    def test_e_gorusme_ticari_ozet_lock_preserved(self) -> None:
        # Görüşme ticari özet (fiyat_ozet) korunuyor — sipariş paneli değil
        self.assertIn('g.fiyat_ozet', self.src)
        self.assertIn('ckart-gorusme-tablo', self.src)
        # C360-UX-REV2: Sipariş paneli Ticari Özet HTML'i kaldırıldı
        self.assertNotIn('id="ckart-ticari-ozet"', self.src)
        self.assertNotIn('ckart-ticari-baslik', self.src)


if __name__ == '__main__':
    unittest.main()
