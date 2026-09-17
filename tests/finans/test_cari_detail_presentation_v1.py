# -*- coding: utf-8 -*-
"""CPS_FINANCE_CARI_DETAIL_VISUAL_REDESIGN_V1 — presentation-only gates."""
from __future__ import annotations

import os
import re
import sys
import unittest

_APP = os.path.join(os.path.dirname(__file__), '..', '..', 'app')
sys.path.insert(0, _APP)

TMPL = os.path.join(_APP, 'templates', 'finans', 'odeme_plani.html')
POPUP = os.path.join(_APP, 'templates', 'finans', '_cari_detay_popup_v1.inc.html')
STYLES = os.path.join(_APP, 'templates', 'finans', '_odeme_plani_styles.inc.html')


def _read(path: str) -> str:
    with open(path, encoding='utf-8') as f:
        return f.read()


class TestCariDetailPresentationV1(unittest.TestCase):
    def setUp(self):
        self.tmpl = _read(TMPL)
        self.popup = _read(POPUP)
        self.styles = _read(STYLES)

    def test_01_template_includes_v1_popup(self):
        self.assertIn("_cari_detay_popup_v1.inc.html", self.tmpl)
        self.assertIn("MUSTERI/TEDARIKCI UNIFIED DETAY MODAL V1", self.tmpl)
        self.assertNotIn("op-modal-har op-modal-cari-detay", self.tmpl)

    def test_02_no_duplicate_modal_definitions(self):
        self.assertEqual(self.tmpl.count("id=\"opCariDetayModal\""), 0)
        self.assertEqual(self.popup.count("id=\"opCariDetayModal\""), 1)
        self.assertEqual(self.popup.count("function _openModal"), 1)

    def test_03_v1_css_present(self):
        for cls in (
            'op-cd-v1', 'op-cd-sticky-top', 'op-cd-sticky-bottom', 'op-cd-kpi-grid',
            'op-cd-mutabakat', 'op-cd-parity', 'op-cd-table-wrap',
        ):
            self.assertIn(cls, self.styles, cls)

    def test_04_customer_supplier_separation(self):
        self.assertIn("RECEIVABLE", self.popup)
        self.assertIn("PAYABLE", self.popup)
        self.assertIn("Planlanan Tahsilat", self.popup)
        self.assertIn("Planlanan Ödeme", self.popup)
        self.assertIn("Müşteri", self.popup)
        self.assertIn("Tedarikçi", self.popup)

    def test_05_sticky_and_scroll_structure(self):
        self.assertIn("op-cd-sticky-top", self.popup)
        self.assertIn("op-cd-sticky-bottom", self.popup)
        self.assertIn("op-cd-table-wrap", self.popup)
        self.assertIn("position: sticky", self.styles)

    def test_06_tabs_and_filters(self):
        for tab in ('hareketler', 'anlasmalar', 'planlama', 'notlar'):
            self.assertIn('data-cdtab="{}"'.format(tab), self.popup)
        for fid in ('opCdMetin', 'opCdTarihBas', 'opCdTarihBit', 'opCdHarTuru', 'opCdTemizle'):
            self.assertIn(fid, self.popup)

    def test_07_esc_close_and_open_exports(self):
        self.assertIn("Escape", self.popup)
        self.assertIn("window.opOpenMusteriDetay", self.popup)
        self.assertIn("window.opOpenTedarikciDetay", self.popup)
        self.assertIn("window.opCloseMusteriDetay", self.popup)

    def test_08_amt_or_note_zero_guard(self):
        self.assertIn("Tutar kaynağı bulunamadı", self.popup)
        self.assertIn("_amtOrNote", self.popup)

    def test_09_parity_warning_not_error_red(self):
        self.assertIn("parity_ok===false", self.popup)
        self.assertIn("op-cd-parity warn", self.popup)
        self.assertNotIn("op-cd-parity err", self.popup)
        self.assertNotIn("op-cd-parity error", self.styles)

    def test_10_canonical_mirror_badges(self):
        self.assertIn("Canonical:", self.popup)
        self.assertIn("Mirror hariç:", self.popup)
        self.assertNotIn("canonical_location}", self.popup)

    def test_11_compact_table_columns(self):
        cols = ('Tarih', 'İşlem', 'Belge No', 'Açıklama', 'Vade', 'Borç', 'Alacak', 'PB', 'Kaynak')
        for c in cols:
            self.assertIn(c, self.popup)

    def test_12_official_vs_movement_footer(self):
        self.assertIn("Resmî Bakiye", self.popup)
        self.assertIn("Net Hareket", self.popup)
        self.assertIn("fn_net", self.popup)
        self.assertIn("har_net", self.popup)

    def test_13_list_page_wires_opener(self):
        self.assertIn("opOpenMusteriDetay(this)", self.tmpl)

    def test_14_responsive_breakpoints(self):
        self.assertIn("@media (max-width: 1366px)", self.styles)


class TestCariDetailDataGatesV1(unittest.TestCase):
    """Uses verified DTO fields — no ledger/resolver changes."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("CPS_DB_MODE", "mock")
        from modules.finans.business_truth_verify import verify_business_truth
        cls.truth = verify_business_truth()

    def test_20_runnix_canonical_balance(self):
        self.assertTrue(self.truth.get("RUNNIX_PASS"))
        self.assertAlmostEqual(self.truth["RUNNIX_CANONICAL_BALANCE"], 3096039.29, places=2)

    def test_21_list_detail_zero_mismatch(self):
        self.assertEqual(self.truth.get("LIST_DETAIL_BALANCE_MISMATCH_COUNT"), 0)

    def test_22_last_transaction_gates(self):
        self.assertEqual(self.truth.get("LAST_TRANSACTION_REFERENCE_GATES"), "PASS")


if __name__ == "__main__":
    unittest.main()
