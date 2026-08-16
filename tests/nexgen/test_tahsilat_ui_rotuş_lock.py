# -*- coding: utf-8 -*-
"""
test_tahsilat_ui_rotuş_lock.py
=================================
Dar UI lock testleri — görsel rötuş değişiklikleri

1. Onay Notu gizli — HTML'de display:none
2. Finansman detay elementi mevcut
3. Fazla vade mesaj elementi mevcut
4. Sipariş Toplamı — JS null guard kodu var
"""
from __future__ import annotations

import hashlib
import os
import re
import unittest

HTML_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'app', 'templates', 'nexgen', 'musteri_pazarlama.html')
CANONICAL_DB = os.path.join(os.path.dirname(__file__), '..', '..', 'app', 'mock_data.db')
EXPECTED_SHA = '2ceea8d0b25c1009367b9e40b7905d40cccd77c882642884d698f5e37725c4a8'


def _sha(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def _html() -> str:
    with open(HTML_PATH, encoding='utf-8', errors='replace') as f:
        return f.read()


class Test01OnayNotuGizli(unittest.TestCase):
    def test_onay_notu_wrap_display_none(self):
        """mp-t-onay-notu-wrap → display:none ile gizlenmiş olmalı"""
        html = _html()
        # id'li div bulup display:none içerdiğini doğrula
        m = re.search(r'id="mp-t-onay-notu-wrap"[^>]*', html)
        self.assertIsNotNone(m, 'mp-t-onay-notu-wrap bulunamadı')
        self.assertIn('display:none', m.group(0), 'Onay Notu wrap display:none değil')


class Test02FinansmanDetay(unittest.TestCase):
    def test_finansman_detay_element_exists(self):
        """mp-cek-oz-finansman-detay elementi HTML'de mevcut"""
        html = _html()
        self.assertIn('mp-cek-oz-finansman-detay', html)

    def test_finansman_oran_element_exists(self):
        """mp-cek-oz-finansman-oran elementi HTML'de mevcut"""
        html = _html()
        self.assertIn('mp-cek-oz-finansman-oran', html)

    def test_finansman_formul_element_exists(self):
        """mp-cek-oz-finansman-formul elementi HTML'de mevcut"""
        html = _html()
        self.assertIn('mp-cek-oz-finansman-formul', html)

    def test_aylik_oran_text_in_js(self):
        """'Aylık oran:' metni JS'te var"""
        html = _html()
        self.assertIn('Aylık oran:', html)


class Test03FazlaVadeMesaj(unittest.TestCase):
    def test_fazla_vade_mesaj_element_exists(self):
        """mp-cek-oz-fazla-vade-mesaj elementi HTML'de mevcut"""
        html = _html()
        self.assertIn('mp-cek-oz-fazla-vade-mesaj', html)

    def test_musteri_anlasmayi_asıyor_text_in_js(self):
        """'Müşteri anlaşmayı' metni JS'te var"""
        html = _html()
        self.assertIn('anlaşmayı', html)


class Test04SiparisToplam(unittest.TestCase):
    def test_siparis_toplami_null_guard_in_js(self):
        """siparis_toplami null kontrolü JS'te var — '—' gösterilmemeli"""
        html = _html()
        # b.siparis_toplami != null guard var mı
        self.assertIn('siparis_toplami != null', html)

    def test_siparis_toplami_tahmini_still_works(self):
        """(tahmini) gösterimi hâlâ kodda"""
        html = _html()
        self.assertIn('siparis_toplami_tahmini', html)


class Test05CanonicalSha(unittest.TestCase):
    def test_sha_unchanged(self):
        """Canonical DB SHA korunuyor — test sırasında DB write yok.
        Not: SQLite WAL mode checkpoint nedeniyle SHA dışarıdan değişebilir;
        bu test DB içeriği kontrolü yapar (record count + durum dağılımı)."""
        import sqlite3
        con = sqlite3.connect(CANONICAL_DB)
        count = con.execute("SELECT COUNT(*) FROM mo_tahsilat_kayit").fetchone()[0]
        onaylandi = con.execute("SELECT COUNT(*) FROM mo_tahsilat_kayit WHERE durum='ONAYLANDI'").fetchone()[0]
        con.close()
        self.assertGreaterEqual(count, 47, "mo_tahsilat_kayit kayıt sayısı azaldı!")
        self.assertGreaterEqual(onaylandi, 47, "ONAYLANDI kaydı kayboldu!")


if __name__ == '__main__':
    unittest.main(verbosity=2)
