# -*- coding: utf-8 -*-
"""C360-NUMUNE-ARGE-LINK-LOCK — AR-GE bağlantı render kontratı.

Kilitlenen davranış (_numDetayHtml):
- Modern NX-AR (arge_kodu NX-AR-*): detay linki /nexgen/arge/nx-ar/{id}
- Legacy AR-GE: etiket düz metin, link yok
- AR-GE kaydı yok: —
- Etiket fallback: arge_kodu → test_no → AR-GE #{id}

Pilot legacy: AT-M-2026-0056 / arge id=115 / arge_kodu=null / test_no=AT-M-2026-0056
"""
from __future__ import annotations

import unittest
from pathlib import Path

TMPL = Path(__file__).resolve().parents[2] / 'app' / 'templates' / 'nexgen' / 'cari360_kart.html'


class NumuneArgeLinkLockTests(unittest.TestCase):
    """Statik template kontratı — DB kullanmaz."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.src = TMPL.read_text(encoding='utf-8')
        start = cls.src.index('function _numDetayHtml(n)')
        end = cls.src.index('function _numunePaginationRender', start)
        cls.block = cls.src[start:end]

    def test_01_numDetayHtml_tanimli(self) -> None:
        self.assertIn('function _numDetayHtml(n)', self.src)

    def test_02_arge_satir_id_kosulu(self) -> None:
        """AR-GE satırı arge && arge.id ile; yoksa —."""
        self.assertIn('if (arge && arge.id)', self.block)
        self.assertIn("esc('—')", self.block)

    def test_03_etiket_fallback_sirasi(self) -> None:
        """Etiket: arge_kodu → test_no → AR-GE #id."""
        self.assertIn('var _argeKod = (arge.arge_kodu || \'\').trim();', self.block)
        self.assertIn('var _argeTestNo = (arge.test_no || \'\').trim();', self.block)
        self.assertIn("var _argeLabel = _argeKod || _argeTestNo || ('AR-GE #' + String(arge.id));", self.block)

    def test_04_modern_nx_ar_link_legacy_duz_metin(self) -> None:
        """NX-AR-* link; legacy düz metin (_argeHtml)."""
        self.assertIn("_argeKod.indexOf('NX-AR-') === 0", self.block)
        self.assertIn("href=\"/nexgen/arge/nx-ar/' + esc(String(arge.id))", self.block)
        self.assertIn(': esc(_argeLabel);', self.block)

    def test_05_arge_durumu_ayri_kalir(self) -> None:
        """AR-GE Durumu hâlâ arge.durum üzerinden (linkten bağımsız)."""
        self.assertIn("esc(dash(arge.durum))", self.block)

    def test_06_legacy_icin_zorunlu_link_yok(self) -> None:
        """Regression: id varken her zaman link üretme deseni yok."""
        self.assertNotIn(
            "+ '<a class=\"ckart-link\" href=\"/nexgen/arge/nx-ar/' + esc(String(arge.id)) + '\">' + esc(_argeLabel) + ' ↗</a>'\n        + '</span></div>';",
            self.block,
        )
