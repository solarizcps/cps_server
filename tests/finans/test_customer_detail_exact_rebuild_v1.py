# -*- coding: utf-8 -*-
"""Müşteri cari detay A-referans rebuild — statik kilit."""
from __future__ import annotations

import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TPL = os.path.join(ROOT, "app", "templates", "finans")
MODAL = os.path.join(TPL, "_musteri_cari_detay_modal.inc.html")
PAGE = os.path.join(TPL, "odeme_plani.html")
STYLES = os.path.join(TPL, "_odeme_plani_styles.inc.html")
SVC = os.path.join(ROOT, "app", "modules", "finans", "services", "musteri_hareket_service.py")


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


class CustomerDetailExactRebuildV1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.modal = _read(MODAL)
        cls.page = _read(PAGE)
        cls.styles = _read(STYLES)
        cls.svc = _read(SVC)

    def test_page_includes_rebuild_not_old_body(self):
        self.assertIn('{% include "finans/_musteri_cari_detay_modal.inc.html" %}', self.page)
        self.assertNotIn("opCdCsSekli", self.page)
        self.assertNotIn("opCdKaynakFiltre", self.page)
        self.assertNotIn("MUSTERI/TEDARIKCI UNIFIED DETAY MODAL", self.page)

    def test_raw_form_removed(self):
        blob = self.modal + self.page
        for token in (
            "opCdCsSekli",
            "opCdVade",
            "opCdOyMode",
            "opCdKaydetBtn",
            "opCdKaynakFiltre",
            "opCdHarTuru",
            "opCdTemizle",
            "_cdKaydet",
            "Faturalar (Alış)",
            "Tüm İşlemler",
        ):
            self.assertNotIn(token, blob, token)

    def test_card_and_tab_counts(self):
        # Birinci satır: bilgi bandı
        self.assertTrue(
            "op-cd-info-band" in self.modal or "op-cd-row-info" in self.modal,
            "info band missing",
        )
        self.assertEqual(self.modal.count("op-cd-row-kpi"), 1)
        self.assertEqual(len(re.findall(r'data-cd-card="', self.modal)), 9)
        self.assertEqual(self.modal.count('data-cdtab='), 4)
        self.assertIn("Cari Hareketleri", self.modal)
        self.assertIn("Anlaşmalar", self.modal)
        self.assertIn("Planlanan Tahsilat", self.modal)
        self.assertNotIn("Planlanan Tahsilat / Ödeme", self.modal)
        self.assertIn("Takip Notları", self.modal)
        self.assertIn("Anlaşma kayıtları — yakında", self.modal)
        self.assertIn("Planlanan tahsilat — yakında", self.modal)
        self.assertIn("Takip notları — yakında", self.modal)

    def test_eight_movement_columns(self):
        th = re.findall(r"<th[^>]*>([^<]+)</th>", self.modal)
        self.assertEqual(
            [t.strip() for t in th],
            ["Tarih", "İşlem", "Belge No", "Açıklama", "Vade", "Borç", "Alacak", "PB"],
        )
        self.assertNotIn("Kaynak", self.modal)

    def test_five_bottom_cards(self):
        self.assertEqual(self.modal.count("op-cd-alt-card"), 5)
        for label in ("Toplam Borç", "Toplam Alacak", "Net Hareket", "Güncel Açık Alacak", "Hareket"):
            self.assertIn(label, self.modal)

    def test_no_reference_sample_numbers(self):
        blob = self.modal + self.page
        for fake in ("4.862.320", "104 gün", "1.248.750", "1.250.000", "732.500"):
            self.assertNotIn(fake, blob)

    def test_customer_isolation_and_supplier_guard(self):
        self.assertIn("match(/^120\\./)", self.modal)
        self.assertIn("Tedarikçi detayı sonraki aşamada hazırlanacak", self.modal)
        self.assertNotIn("/finans/cariler/tedarikci/", self.modal)
        self.assertIn("NOT_FOUND yok", self.page)
        self.assertIn("opOpenTedarikciDetay(btn)", self.page)

    def test_summary_does_not_call_live_korgun(self):
        start = self.svc.find("def get_customer_summary(")
        nxt = self.svc.find("\ndef ", start + 10)
        body = self.svc[start:nxt]
        self.assertIn("read_receivable_customer", body)
        self.assertNotIn("fetch_authoritative_balance", body)
        self.assertNotIn("fetch_customer_layer2", body)

    def test_finance_list_filters_still_present(self):
        self.assertIn("Müşteri Carileri", self.page)
        self.assertIn("op-fh-btn", self.page)
        self.assertIn("op-view-toggle", self.page)


if __name__ == "__main__":
    unittest.main()
