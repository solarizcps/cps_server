# -*- coding: utf-8 -*-
"""C360-CANONICAL-REFRESH-01 LOCK — Freshness / cache-invalidation regression.

Her sekme aktivasyonunda stale guard sıfırlanmalı, API fresh çağrılmalı.

Kilitlenen davranışlar:
A.  ckartTab: her tab geçişinde ckartOzetYukle() çağrılıyor
B.  ckartTab/siparisler: _opsLoaded.siparisler = false + _opsLoaded.ticariOzet = false
C.  ckartTab/uretim:     _opsLoaded.uretim = false
D.  ckartTab/sevkiyatlar: _opsLoaded.sevkiyatlar = false
E.  ckartTab/numuneler:  _opsLoaded.numuneler = false
F.  ckartTab/finans:     _ckartFinansYuklendi = false
G.  ckartTab/hafiza:     _ckartHafizaTabYuklendi = false
H.  ckartTab: init block'ta ckartOzetYukle() init-çağrısı korunuyor
I.  Pagination (ckartSipGitPage) filter-state bozmuyor, ticariOzet reset YOK
J.  Filtre apply (_ckartSipApplyFilter): siparisler = false, ticariOzet reset YOK burada
K.  gorusmeSonrasiYenile: ckartGorusmeYukle + ckartOzetYukle birlikte çağrılıyor
L.  Görüşmeler sekmesinde _opsLoaded guard YOK (her geçiş fetch)
M.  Onaylar sekmesinde _opsLoaded guard YOK (her geçiş fetch)
N.  Son Alış Fiyatı: ticariOzet tab activation'da invalidate ediliyor
O.  Duplicate ozet guard: filtre apply içinde ckartOzetYukle DOĞRUDAN çağrılmıyor
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

TMPL = Path(__file__).resolve().parents[2] / 'app' / 'templates' / 'nexgen' / 'cari360_kart.html'


def _src() -> str:
    return TMPL.read_text(encoding='utf-8')


class TabRefreshContractTests(unittest.TestCase):
    """C360-CANONICAL-REFRESH-01 — ckartTab merkezi freshness contract."""

    def setUp(self):
        self.src = _src()

    def _tab_block(self) -> str:
        """ckartTab function body (ilk 2500 karakter)."""
        idx = self.src.find('window.ckartTab = function(tab)')
        self.assertGreater(idx, 0, 'ckartTab bulunamadı')
        return self.src[idx: idx + 2500]

    def _filter_apply_block(self) -> str:
        idx = self.src.find('_ckartSipApplyFilter')
        self.assertGreater(idx, 0, '_ckartSipApplyFilter bulunamadı')
        return self.src[idx: idx + 600]

    def _pagination_block(self) -> str:
        idx = self.src.find('window.ckartSipGitPage = function(page)')
        self.assertGreater(idx, 0, 'ckartSipGitPage bulunamadı')
        return self.src[idx: idx + 300]

    # A — ckartTab her aktivasyonda ckartOzetYukle çağırıyor
    def test_A_tab_calls_ckartOzetYukle(self):
        blk = self._tab_block()
        self.assertIn('ckartOzetYukle()', blk,
                      'ckartTab içinde ckartOzetYukle() çağrısı yok')

    # B — siparisler: opsLoaded.siparisler + ticariOzet reset
    def test_B_siparisler_invalidates_siparisler_flag(self):
        blk = self._tab_block()
        self.assertIn("_opsLoaded.siparisler = false", blk)

    def test_B_siparisler_invalidates_ticariOzet_flag(self):
        blk = self._tab_block()
        self.assertIn("_opsLoaded.ticariOzet = false", blk)

    # C — uretim reset
    def test_C_uretim_invalidates_flag(self):
        blk = self._tab_block()
        self.assertIn("_opsLoaded.uretim = false", blk)

    # D — sevkiyatlar reset
    def test_D_sevkiyatlar_invalidates_flag(self):
        blk = self._tab_block()
        self.assertIn("_opsLoaded.sevkiyatlar = false", blk)

    # E — numuneler reset
    def test_E_numuneler_invalidates_flag(self):
        blk = self._tab_block()
        self.assertIn("_opsLoaded.numuneler = false", blk)

    # F — finans reset
    def test_F_finans_invalidates_flag(self):
        blk = self._tab_block()
        self.assertIn("_ckartFinansYuklendi = false", blk)

    # G — hafiza reset
    def test_G_hafiza_invalidates_flag(self):
        blk = self._tab_block()
        self.assertIn("_ckartHafizaTabYuklendi = false", blk)

    # H — init block ckartOzetYukle korunuyor
    def test_H_init_ckartOzetYukle_preserved(self):
        # İnit bölgesi: ckartTab tanımından sonra gelen standalone çağrı
        idx = self.src.find('window.ckartTab = function(tab)')
        after_tab = self.src[idx + 50:]
        # ckartOzetYukle() standalone satırı olmalı
        self.assertIn('ckartOzetYukle();', after_tab,
                      'init ckartOzetYukle() çağrısı bulunamadı')

    # I — Pagination içinde ticariOzet reset YOK (gereksiz ağır endpoint)
    def test_I_pagination_no_ticariOzet_reset(self):
        blk = self._pagination_block()
        self.assertNotIn('_opsLoaded.ticariOzet = false', blk,
                         'Pagination ticariOzet sıfırlamamalı')

    # J — Filtre apply içinde ticariOzet reset YOK (tab activation yapıyor)
    def test_J_filter_apply_no_ticariOzet_reset(self):
        blk = self._filter_apply_block()
        self.assertNotIn('_opsLoaded.ticariOzet = false', blk,
                         'Filtre apply ticariOzet sıfırlamamalı (tab activation yeterli)')

    # K — gorusmeSonrasiYenile: hem gorusme hem ozet çağrıyor
    def test_K_gorusmeSonrasiYenile_calls_ozet(self):
        idx = self.src.find('function gorusmeSonrasiYenile')
        blk = self.src[idx: idx + 250]
        self.assertIn('ckartGorusmeYukle()', blk)
        self.assertIn('ckartOzetYukle()', blk)

    # L — Görüşmeler: _opsLoaded.gorusmeler guard YOK
    def test_L_gorusmeler_no_opsLoaded_guard(self):
        idx = self.src.find('ckartGorusmeYukle = function')
        blk = self.src[idx: idx + 200]
        self.assertNotIn('_opsLoaded.gorusmeler', blk,
                         'Görüşmeler guard olmamalı — her geçiş fresh fetch')

    # M — Onaylar: guard yok
    def test_M_onaylar_no_opsLoaded_guard(self):
        idx = self.src.find('function ckartOnaylarYukle')
        blk = self.src[idx: idx + 200]
        self.assertNotIn('_opsLoaded.onaylar', blk,
                         'Onaylar guard olmamalı')

    # N — Son Alış Fiyatı: ticariOzet ckartTab/siparisler bölgesinde invalidate ediliyor
    def test_N_son_alis_fiyati_ticariOzet_invalidated_on_siparisler_tab(self):
        blk = self._tab_block()
        # siparisler bölgesi içinde hem ticariOzet hem ticariOzetYukle var mı?
        siparisler_idx = blk.find("'siparisler'")
        self.assertGreater(siparisler_idx, 0)
        after = blk[siparisler_idx: siparisler_idx + 200]
        self.assertIn('_opsLoaded.ticariOzet = false', after)

    # O — Duplicate ozet: filtre apply içinde ckartOzetYukle DOĞRUDAN çağrılmıyor
    def test_O_filter_apply_no_direct_ckartOzetYukle(self):
        blk = self._filter_apply_block()
        self.assertNotIn('ckartOzetYukle()', blk,
                         'Filtre apply ckartOzetYukle doğrudan çağırmamalı (loop riski)')


class FreshnessFlagDeclarationTests(unittest.TestCase):
    """_opsLoaded başlangıç değerleri ve flag var mı kontrol."""

    def setUp(self):
        self.src = _src()

    def test_opsLoaded_declaration_exists(self):
        self.assertIn('var _opsLoaded = {', self.src)

    def test_opsLoaded_all_tabs_declared(self):
        m = re.search(r'var _opsLoaded\s*=\s*\{([^}]+)\}', self.src)
        self.assertIsNotNone(m, '_opsLoaded deklarasyonu bulunamadı')
        decl = m.group(1)
        for tab in ('siparisler', 'ticariOzet', 'uretim', 'sevkiyatlar', 'urunler', 'numuneler'):
            self.assertIn(tab, decl, f'_opsLoaded.{tab} eksik')

    def test_finans_flag_declared(self):
        self.assertIn('var _ckartFinansYuklendi = false', self.src)

    def test_hafiza_flag_declared(self):
        self.assertIn('var _ckartHafizaTabYuklendi = false', self.src)


class NoRefreshLoopTests(unittest.TestCase):
    """Loader success callback'leri ckartOzetYukle çağırmıyor (loop yok)."""

    def setUp(self):
        self.src = _src()

    def _loader_body(self, marker: str, size: int = 2000) -> str:
        idx = self.src.find(marker)
        self.assertGreater(idx, 0, f'{marker} bulunamadı')
        return self.src[idx: idx + size]

    def test_siparisler_loader_no_ckartOzetYukle_in_success(self):
        blk = self._loader_body('window.ckartSiparisYukle = function(force)')
        # ckartOzetYukle ckartSiparisYukle içinde çağrılmamalı (tab orchestration yeterli)
        self.assertNotIn('ckartOzetYukle()', blk,
                         'ckartSiparisYukle success içinde ckartOzetYukle olmamalı')

    def test_sevk_loader_no_ckartOzetYukle_in_success(self):
        blk = self._loader_body('window.ckartSevkYukle = function(force)')
        self.assertNotIn('ckartOzetYukle()', blk,
                         'ckartSevkYukle success içinde ckartOzetYukle olmamalı')

    def test_uretim_loader_no_ckartOzetYukle_in_success(self):
        blk = self._loader_body('window.ckartUretimYukle = function(force)')
        self.assertNotIn('ckartOzetYukle()', blk)

    def test_numune_loader_no_ckartOzetYukle_in_success(self):
        blk = self._loader_body('window.ckartNumuneYukle = function(force)')
        self.assertNotIn('ckartOzetYukle()', blk)


if __name__ == '__main__':
    unittest.main(verbosity=2)
