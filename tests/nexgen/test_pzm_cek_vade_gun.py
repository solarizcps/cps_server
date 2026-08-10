# -*- coding: utf-8 -*-
"""
tests/nexgen/test_pzm_cek_vade_gun.py
======================================
CEK vade_gun canonical fix — regression testleri.

Çalıştır:
  python -m unittest tests/nexgen/test_pzm_cek_vade_gun.py -v

Kapsam:
  1. CEK + 220 gün → vade_gun = 220
  2. NAKIT → vade_gun = 0
  3. VADELI → vade_gun = geçirilen değer
  4. CEK vade günü boş/geçersiz → validation reddeder
  5. Vade motoru: sevk + vade_gun hesabı değişmez
"""
from __future__ import annotations

import os
import sqlite3
import sys
import unittest
from datetime import date, timedelta
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "app"))

from modules.nexgen.pzm_siparis_write import (
    PzmWriteError,
    pzm_cek_vade_gun_dogrula,
    pzm_ticari_sartlar_dogrula,
    pzm_vade_gun_dogrula,
)
from modules.nexgen.mo_vade_kontrol_service import CekSatiriInput, hesapla


# ---------------------------------------------------------------------------
# Test 1 — CEK + 220 gün
# ---------------------------------------------------------------------------
class TestCekVadeGunYazilir(unittest.TestCase):
    """CEK ödeme tipinde vade_gun canonical kolona 220 olarak kaydedilmeli."""

    def _data(self):
        return {
            "odeme_tipi": "CEK",
            "anlasma_para_birimi": "USD",
            "cek_vade_gun": 220,
            "cek_vadesi": "2026-08-14",
        }

    def test_vade_gun_220(self):
        result = pzm_ticari_sartlar_dogrula(self._data(), zorunlu=True)
        self.assertEqual(result["vade_gun"], 220, "CEK: vade_gun 220 olmalı")

    def test_cek_vade_gun_ayri_korunur(self):
        result = pzm_ticari_sartlar_dogrula(self._data(), zorunlu=True)
        self.assertEqual(result["cek_vade_gun"], 220, "cek_vade_gun ayrı key olarak korunmalı")

    def test_string_cek_vade_gun(self):
        data = self._data()
        data["cek_vade_gun"] = "220"
        result = pzm_ticari_sartlar_dogrula(data, zorunlu=True)
        self.assertEqual(result["vade_gun"], 220)

    def test_vade_gun_dogrula_cek_branch(self):
        self.assertEqual(pzm_vade_gun_dogrula(220, odeme_tipi="CEK"), 220)
        self.assertEqual(pzm_vade_gun_dogrula("220", odeme_tipi="CEK"), 220)
        self.assertIsNone(pzm_vade_gun_dogrula(None, odeme_tipi="CEK"))
        self.assertIsNone(pzm_vade_gun_dogrula("", odeme_tipi="CEK"))


# ---------------------------------------------------------------------------
# Test 2 — NAKIT
# ---------------------------------------------------------------------------
class TestNakitVadeGun(unittest.TestCase):
    """NAKIT: vade_gun = 0, mevcut davranış korunmalı."""

    def _data(self):
        return {
            "odeme_tipi": "NAKIT",
            "anlasma_para_birimi": "TRY",
        }

    def test_nakit_vade_gun_sifir(self):
        result = pzm_ticari_sartlar_dogrula(self._data(), zorunlu=True)
        self.assertEqual(result["vade_gun"], 0)

    def test_nakit_pozitif_vade_sifira_indirilir(self):
        data = self._data()
        data["vade_gun"] = 30
        result = pzm_ticari_sartlar_dogrula(data, zorunlu=True)
        self.assertEqual(result["vade_gun"], 0)

    def test_nakit_pzm_vade_gun_dogrula(self):
        self.assertEqual(pzm_vade_gun_dogrula(None, odeme_tipi="NAKIT"), 0)
        self.assertEqual(pzm_vade_gun_dogrula(0, odeme_tipi="NAKIT"), 0)
        self.assertEqual(pzm_vade_gun_dogrula(99, odeme_tipi="NAKIT"), 0)


# ---------------------------------------------------------------------------
# Test 3 — VADELI
# ---------------------------------------------------------------------------
class TestVadeliVadeGun(unittest.TestCase):
    """VADELI: kullanıcı girdiği vade_gun korunmalı."""

    def _data(self, gun):
        return {
            "odeme_tipi": "VADELI",
            "anlasma_para_birimi": "TRY",
            "vade_gun": gun,
        }

    def test_vadeli_60_gun(self):
        result = pzm_ticari_sartlar_dogrula(self._data(60), zorunlu=True)
        self.assertEqual(result["vade_gun"], 60)

    def test_vadeli_1_gun(self):
        result = pzm_ticari_sartlar_dogrula(self._data(1), zorunlu=True)
        self.assertEqual(result["vade_gun"], 1)

    def test_vadeli_string_gun(self):
        result = pzm_ticari_sartlar_dogrula(self._data("90"), zorunlu=True)
        self.assertEqual(result["vade_gun"], 90)

    def test_vadeli_bos_gun_hata(self):
        with self.assertRaises(PzmWriteError):
            pzm_ticari_sartlar_dogrula(self._data(None), zorunlu=True)

    def test_vadeli_sifir_hata(self):
        with self.assertRaises(PzmWriteError):
            pzm_ticari_sartlar_dogrula(self._data(0), zorunlu=True)


# ---------------------------------------------------------------------------
# Test 4 — CEK vade günü boş/geçersiz → validation reddeder
# ---------------------------------------------------------------------------
class TestCekVadeGunValidation(unittest.TestCase):
    """CEK vade günü boş veya geçersizse PzmWriteError fırlatılmalı."""

    def _base(self):
        return {
            "odeme_tipi": "CEK",
            "anlasma_para_birimi": "USD",
            "cek_vadesi": "2026-08-14",
        }

    def test_bos_cek_vade_gun_zorunlu_hata(self):
        data = self._base()
        data["cek_vade_gun"] = None
        with self.assertRaises(PzmWriteError):
            pzm_ticari_sartlar_dogrula(data, zorunlu=True)

    def test_bos_string_cek_vade_gun_zorunlu_hata(self):
        data = self._base()
        data["cek_vade_gun"] = ""
        with self.assertRaises(PzmWriteError):
            pzm_ticari_sartlar_dogrula(data, zorunlu=True)

    def test_negatif_cek_vade_gun_hata(self):
        with self.assertRaises(PzmWriteError):
            pzm_cek_vade_gun_dogrula(-5, odeme_tipi="CEK", zorunlu=True)

    def test_sifir_cek_vade_gun_hata(self):
        with self.assertRaises(PzmWriteError):
            pzm_cek_vade_gun_dogrula(0, odeme_tipi="CEK", zorunlu=True)

    def test_metin_cek_vade_gun_hata(self):
        with self.assertRaises(PzmWriteError):
            pzm_cek_vade_gun_dogrula("abc", odeme_tipi="CEK", zorunlu=True)

    def test_bool_cek_vade_gun_hata(self):
        with self.assertRaises(PzmWriteError):
            pzm_cek_vade_gun_dogrula(True, odeme_tipi="CEK", zorunlu=True)

    def test_cek_vade_gun_zorunlu_degil_none_gecmez(self):
        result = pzm_cek_vade_gun_dogrula(None, odeme_tipi="CEK", zorunlu=False)
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# Test 5 — Vade motoru: sevk + vade_gun hesabı değişmez
# ---------------------------------------------------------------------------
class TestVadeMotoru(unittest.TestCase):
    """
    hesapla() — gerçek sevk + vade_gun hedef vade tarihini doğru hesaplar.
    CEK fix sonrası motor davranışı değişmemeli.
    """

    def _minimal_con(self):
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        con.execute("""
            CREATE TABLE nexgen_planlama_siparis (
                id INTEGER PRIMARY KEY,
                siparis_no TEXT,
                vade_gun INTEGER,
                anlasma_para_birimi TEXT,
                odeme_tipi TEXT
            )
        """)
        con.execute("""
            CREATE TABLE mo_musteri_sevkiyat (
                id INTEGER PRIMARY KEY,
                siparis_id INTEGER,
                durum TEXT,
                sevk_tarihi TEXT,
                aktif INTEGER DEFAULT 1
            )
        """)
        return con

    def test_cek_220_gun_hedef_vade(self):
        """gerçek sevk 2026-08-10 + 220 gün = 2027-03-19"""
        con = self._minimal_con()
        con.execute(
            "INSERT INTO nexgen_planlama_siparis VALUES (759,'PZM-2026-0221',220,'USD','CEK')"
        )
        con.execute(
            "INSERT INTO mo_musteri_sevkiyat VALUES (227,759,'SEVK_EDILDI','2026-08-10',1)"
        )
        con.commit()

        beklenen = (date(2026, 8, 10) + timedelta(days=220)).isoformat()

        sonuc = hesapla(
            con=con,
            siparis_id=759,
            cek_satirlari=[],
        )
        self.assertEqual(sonuc.hedef_vade_tarihi, beklenen,
                         f"Hedef vade {beklenen} olmalı, geldi: {sonuc.hedef_vade_tarihi}")
        self.assertEqual(sonuc.onaylanan_vade_gun, 220)

    def test_sevk_yok_hedef_vade_none(self):
        """sevk_tarihi NULL ise hedef_vade_tarihi None olmalı."""
        con = self._minimal_con()
        con.execute(
            "INSERT INTO nexgen_planlama_siparis VALUES (759,'PZM-2026-0221',220,'USD','CEK')"
        )
        con.commit()

        sonuc = hesapla(
            con=con,
            siparis_id=759,
            cek_satirlari=[],
        )
        self.assertIsNone(sonuc.hedef_vade_tarihi)
        self.assertIsNone(sonuc.gercek_sevk_tarihi)

    def test_nakit_hedef_vade_motor(self):
        """NAKIT için motor DURUM_NAKIT_PAKET döner, hedef_vade_tarihi yoktur."""
        from modules.nexgen.mo_vade_kontrol_config import DURUM_NAKIT_PAKET
        con = self._minimal_con()
        con.execute(
            "INSERT INTO nexgen_planlama_siparis VALUES (800,'PZM-2026-9999',0,'TRY','NAKIT')"
        )
        con.execute(
            "INSERT INTO mo_musteri_sevkiyat VALUES (300,800,'SEVK_EDILDI','2026-08-10',1)"
        )
        con.commit()

        sonuc = hesapla(
            con=con,
            siparis_id=800,
            odeme_tipi="NAKIT",
            cek_satirlari=[],
        )
        self.assertEqual(sonuc.durum_kodu, DURUM_NAKIT_PAKET)


if __name__ == "__main__":
    unittest.main(verbosity=2)
