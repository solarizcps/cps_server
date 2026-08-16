# -*- coding: utf-8 -*-
"""
test_tahsilat_close_reopen_reset_lock.py
=========================================
Close/Reopen reset bug lock testleri

Reset contract:
- window.mpResetCekPanel export var
- cekTbody innerHTML temizleme kodu var
- cekOzet hidden yapılıyor
- cekBaglamCache sıfırlanıyor
- finansman detay gizleniyor
- fazla vade mesajı gizleniyor
- istisna açıklama wrap display:none
- buton text 'ONAYA GÖNDER' + style.background reset
- cekPanel hidden
- resetTahsilatModal içinde mpResetCekPanel çağrılıyor
- resetTahsilatModal içinde cekPanel gizleniyor
- resetTahsilatModal içinde istisnaWrap.style.display = 'none'
- buton style.background ve style.border sıfırlanıyor
"""
from __future__ import annotations

import re
import os
import sqlite3
import unittest

HTML_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'app', 'templates', 'nexgen', 'musteri_pazarlama.html')
CANONICAL_DB = os.path.join(os.path.dirname(__file__), '..', '..', 'app', 'mock_data.db')


def _html() -> str:
    with open(HTML_PATH, encoding='utf-8', errors='replace') as f:
        return f.read()


class Test01MpResetCekPanelExport(unittest.TestCase):
    def test_mpResetCekPanel_exported(self):
        html = _html()
        self.assertIn('window.mpResetCekPanel', html, 'window.mpResetCekPanel export yok')

    def test_cekTbody_innerHTML_cleared(self):
        html = _html()
        self.assertIn("cekTbody.innerHTML = ''", html, 'cekTbody temizleme kodu yok')

    def test_cekBaglamCache_reset(self):
        html = _html()
        # mpResetCekPanel içinde cekBaglamCache = null
        self.assertIn('cekBaglamCache = null', html, 'cekBaglamCache null reset yok')

    def test_cekOzet_hidden_in_reset(self):
        html = _html()
        self.assertIn('cekOzet.hidden = true', html, 'cekOzet.hidden = true reset yok')

    def test_finansman_detay_hidden_in_reset(self):
        html = _html()
        self.assertIn("mp-cek-oz-finansman-detay", html, 'mp-cek-oz-finansman-detay element yok')
        # finDetay.style.display = 'none' olmalı
        self.assertIn("finDetay.style.display = 'none'", html, 'finansman detay display:none reset yok')

    def test_fazla_vade_mesaj_hidden_in_reset(self):
        html = _html()
        self.assertIn('mp-cek-oz-fazla-vade-mesaj', html)
        # fazlaEl.style.display = 'none' + textContent = ''
        self.assertIn("fazlaEl.style.display = 'none'", html, 'fazla vade mesaj display:none reset yok')
        self.assertIn("fazlaEl.textContent = ''", html, 'fazla vade mesaj textContent reset yok')


class Test02ResetTahsilatModal(unittest.TestCase):
    def test_mpResetCekPanel_called_in_reset(self):
        html = _html()
        self.assertIn("window.mpResetCekPanel()", html, 'resetTahsilatModal mpResetCekPanel() çağırmıyor')

    def test_cekPanel_hidden_in_reset(self):
        html = _html()
        self.assertIn("cekPanelEl.hidden = true", html, 'resetTahsilatModal cekPanel gizlemiyor')

    def test_istisna_wrap_display_none_in_reset(self):
        html = _html()
        self.assertIn("istisnaWrap.style.display = 'none'", html, 'istisna wrap display:none reset yok')

    def test_istisna_input_cleared_in_reset(self):
        html = _html()
        self.assertIn("istisnaInput.value = ''", html, 'istisna input temizleme yok')

    def test_gonder_btn_text_reset(self):
        html = _html()
        self.assertIn("gonderBtn.textContent = 'ONAYA GÖNDER'", html, 'buton text reset yok')

    def test_gonder_btn_style_reset(self):
        html = _html()
        self.assertIn("gonderBtn.style.background = ''", html, 'buton style.background reset yok')
        self.assertIn("gonderBtn.style.border = ''", html, 'buton style.border reset yok')


class Test03HydratePreserved(unittest.TestCase):
    def test_hydrateTahsilatDraft_reads_cek_satirlari(self):
        """Mevcut taslak hydrate'i çek satırlarını geri getirmeli"""
        html = _html()
        self.assertIn('cek_satirlari', html, 'cek_satirlari hydrate kodu yok')
        # hydrate sırasında addCekRow çağrılmalı
        self.assertIn('addCekRow', html, 'addCekRow çağrısı yok')

    def test_tahsilatKayitId_set_in_hydrate(self):
        """Mevcut taslak hydrate'i tahsilatKayitId'yi set etmeli"""
        html = _html()
        self.assertIn('tahsilatKayitId = k.id', html, 'tahsilatKayitId hydrate edilmiyor')

    def test_tahsilatKayitId_null_in_reset(self):
        """Yeni kayıt açılışında tahsilatKayitId null olmalı"""
        html = _html()
        self.assertIn('tahsilatKayitId = null', html, 'tahsilatKayitId null reset yok')

    def test_tahsilatTcmbFrozen_false_in_reset(self):
        """Yeni kayıt açılışında tahsilatTcmbFrozen false olmalı"""
        html = _html()
        self.assertIn('tahsilatTcmbFrozen = false', html, 'tahsilatTcmbFrozen false reset yok')


class Test04CanonicalDb(unittest.TestCase):
    def test_canonical_db_content_stable(self):
        """Canonical DB içerik kontrolü"""
        con = sqlite3.connect(CANONICAL_DB)
        count = con.execute("SELECT COUNT(*) FROM mo_tahsilat_kayit").fetchone()[0]
        onaylandi = con.execute("SELECT COUNT(*) FROM mo_tahsilat_kayit WHERE durum='ONAYLANDI'").fetchone()[0]
        con.close()
        self.assertGreaterEqual(count, 47, "Kayıt sayısı azaldı!")
        self.assertGreaterEqual(onaylandi, 47, "ONAYLANDI kaydı kayboldu!")


if __name__ == '__main__':
    unittest.main(verbosity=2)
