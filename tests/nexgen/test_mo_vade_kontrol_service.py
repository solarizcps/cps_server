# -*- coding: utf-8 -*-
"""
tests/nexgen/test_mo_vade_kontrol_service.py
============================================
Unit tests — mo_vade_kontrol_service K1–K7 + validation.

Live DB write YOK. Isolated/temp SQLite veya pure-function level.
Çalıştır: python -m unittest tests/nexgen/test_mo_vade_kontrol_service.py
"""
from __future__ import annotations

import sys
import os
import sqlite3
import time
import unittest
from decimal import Decimal

# Repo app klasörünü path'e ekle
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "app"))

from modules.nexgen.mo_vade_kontrol_service import (
    CekSatiriInput,
    VadeKontrolError,
    hesapla,
)
from modules.nexgen.mo_vade_kontrol_config import (
    DURUM_AVANTAJ,
    DURUM_CEK_YOK,
    DURUM_FAZLA_VADE,
    DURUM_NAKIT_PAKET,
    DURUM_SEVK_BEKLIYOR,
    DURUM_VADE_UYGUN,
)


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------

SEVK = "2026-08-10"  # tüm test senaryolarında sabit sevk tarihi
ONAYLANAN = 180  # gün


def _gun_sonra(base: str, gun: int) -> str:
    """base (YYYY-MM-DD) tarihinden gun gün sonra."""
    from datetime import date, timedelta
    d = date.fromisoformat(base)
    return (d + timedelta(days=gun)).isoformat()


def _cek(tutar: float, vade_gun: int, pb: str = "TRY") -> CekSatiriInput:
    return CekSatiriInput(
        tutar=Decimal(str(tutar)),
        gercek_cek_vade_tarihi=_gun_sonra(SEVK, vade_gun),
        para_birimi=pb,
    )


def _hesapla_pure(cekler, onaylanan=ONAYLANAN, sevk=SEVK, hedef=None, pb="TRY",
                  odeme_tipi="CEK", oran=None):
    """hesapla() wrapper, no DB."""
    kwargs = dict(
        odeme_tipi=odeme_tipi,
        cek_satirlari=cekler,
        para_birimi=pb,
        onaylanan_vade_gun=onaylanan,
        sevk_tarihi=sevk,
    )
    if hedef is not None:
        kwargs["paket_hedef_tutar"] = Decimal(str(hedef))
    if oran is not None:
        kwargs["aylik_finansman_orani"] = Decimal(str(oran))
    return hesapla(**kwargs)


# ---------------------------------------------------------------------------
# K1 — Ağırlıklı ortalama (4 çek, mixed tutar)
# ---------------------------------------------------------------------------

class TestK1AgirlikliOrtalama(unittest.TestCase):

    def setUp(self):
        """
        K1: 4 çek
          100k @150 gün → katkı 15.000.000
          200k @180 gün → katkı 36.000.000
          400k @210 gün → katkı 84.000.000
          300k @240 gün → katkı 72.000.000
          Toplam tutar: 1.000.000
          Ağırlıklı toplam: 207.000.000
          Ortalama: 207.0 gün
        """
        self.cekler = [
            _cek(100_000, 150),
            _cek(200_000, 180),
            _cek(400_000, 210),
            _cek(300_000, 240),
        ]
        self.sonuc = _hesapla_pure(self.cekler, onaylanan=180, hedef=1_000_000)

    def test_agirlikli_ortalama_207(self):
        self.assertEqual(self.sonuc.agirlikli_ortalama_vade_gun_gosterim, 207)

    def test_toplam_tutar(self):
        self.assertAlmostEqual(self.sonuc.toplam_cek_tutari, 1_000_000, places=1)

    def test_cek_adedi(self):
        self.assertEqual(self.sonuc.cek_adedi, 4)

    def test_sapma_27(self):
        self.assertEqual(self.sonuc.vade_sapma_gun_gosterim, 27)

    def test_paket_tamamlandi(self):
        self.assertTrue(self.sonuc.paket_tamamlandi)

    def test_karsilama_100(self):
        self.assertAlmostEqual(self.sonuc.karsilama_orani, 100.0, places=1)


# ---------------------------------------------------------------------------
# K2 — VADE_UYGUN
# ---------------------------------------------------------------------------

class TestK2VadeUygun(unittest.TestCase):

    def test_exact_match(self):
        """Tüm çekler tam onaylanan vade günündeyse VADE_UYGUN."""
        cekler = [_cek(500_000, 180), _cek(500_000, 180)]
        s = _hesapla_pure(cekler, onaylanan=180)
        self.assertEqual(s.durum_kodu, DURUM_VADE_UYGUN)
        self.assertEqual(s.vade_sapma_gun_gosterim, 0)

    def test_weighted_equals_target(self):
        """Ağırlıklı ortalama = onaylanan vade → VADE_UYGUN."""
        # 100k@160 + 100k@200 → avg 180
        cekler = [_cek(100_000, 160), _cek(100_000, 200)]
        s = _hesapla_pure(cekler, onaylanan=180)
        self.assertEqual(s.durum_kodu, DURUM_VADE_UYGUN)
        self.assertEqual(s.vade_sapma_gun_gosterim, 0)


# ---------------------------------------------------------------------------
# K3 — FAZLA_VADE (+27 gün)
# ---------------------------------------------------------------------------

class TestK3FazlaVade(unittest.TestCase):

    def test_fazla_vade_27(self):
        cekler = [
            _cek(100_000, 150),
            _cek(200_000, 180),
            _cek(400_000, 210),
            _cek(300_000, 240),
        ]
        s = _hesapla_pure(cekler, onaylanan=180)
        self.assertEqual(s.durum_kodu, DURUM_FAZLA_VADE)
        self.assertEqual(s.vade_sapma_gun_gosterim, 27)

    def test_durum_etiket_contains_plus(self):
        cekler = [_cek(1_000_000, 210)]
        s = _hesapla_pure(cekler, onaylanan=180)
        self.assertIn("+", s.durum_etiket)


# ---------------------------------------------------------------------------
# K4 — AVANTAJ (-10 gün)
# ---------------------------------------------------------------------------

class TestK4Avantaj(unittest.TestCase):

    def test_avantaj_minus10(self):
        cekler = [_cek(1_000_000, 170)]
        s = _hesapla_pure(cekler, onaylanan=180)
        self.assertEqual(s.durum_kodu, DURUM_AVANTAJ)
        self.assertEqual(s.vade_sapma_gun_gosterim, -10)

    def test_finansman_negatif(self):
        """Avantajda finansman etkisi negatif."""
        cekler = [_cek(1_000_000, 170)]
        s = _hesapla_pure(cekler, onaylanan=180, oran="0.04")
        # sapma=-10, finansman = 1M * 0.04 * (-10/30) ≈ -13333
        self.assertLess(s.finansman_net, 0)


# ---------------------------------------------------------------------------
# K5 — Finansman etkisi (4%/ay, örnek: ~36.000 TL net)
# ---------------------------------------------------------------------------

class TestK5Finansman(unittest.TestCase):

    def setUp(self):
        """
        K5 referans senaryosu (plan dokümanından):
        4 çek, 700k toplam hedef, sevk sabit, onaylanan=180
        Çek bazlı sapma toplamı → net ~36.000 TL
        """
        self.cekler = [
            _cek(100_000, 150),   # sapma = -30 → etki = 100k*0.04*(-30/30) = -4.000
            _cek(200_000, 180),   # sapma =   0 → etki = 0
            _cek(200_000, 210),   # sapma = +30 → etki = 200k*0.04*(30/30) = +8.000
            _cek(200_000, 240),   # sapma = +60 → etki = 200k*0.04*(60/30) = +16.000
        ]
        # Toplam hedef 700k, toplam çek 700k
        self.sonuc = _hesapla_pure(self.cekler, onaylanan=180, hedef=700_000, oran="0.04")

    def test_net_finansman(self):
        # -4.000 + 0 + 8.000 + 16.000 = 20.000 TL
        self.assertAlmostEqual(self.sonuc.finansman_net, 20_000.0, places=1)

    def test_cek_detay_count(self):
        self.assertEqual(len(self.sonuc.cek_detaylari), 4)

    def test_cek_detay_finansman_sum(self):
        total = sum(c["finansman_etkisi"] for c in self.sonuc.cek_detaylari)
        self.assertAlmostEqual(total, self.sonuc.finansman_net, places=1)

    def test_k1_net_36000(self):
        """
        K1 senaryosundaki 4 çek üzerinden ~36.000 TL.
        sapma hesabı:
          100k @ 150 → sapma=-30 → -4.000
          200k @ 180 → sapma=0   →      0
          400k @ 210 → sapma=+30 → +16.000
          300k @ 240 → sapma=+60 → +24.000
          TOPLAM = 36.000
        """
        cekler = [
            _cek(100_000, 150),
            _cek(200_000, 180),
            _cek(400_000, 210),
            _cek(300_000, 240),
        ]
        s = _hesapla_pure(cekler, onaylanan=180, hedef=1_000_000, oran="0.04")
        self.assertAlmostEqual(s.finansman_net, 36_000.0, places=1)


# ---------------------------------------------------------------------------
# K6 — Sevk Bekleniyor
# ---------------------------------------------------------------------------

class TestK6SevkBekliyor(unittest.TestCase):

    def test_no_sevk(self):
        cekler = [_cek(500_000, 180)]
        s = hesapla(
            odeme_tipi="CEK",
            cek_satirlari=cekler,
            para_birimi="TRY",
            onaylanan_vade_gun=180,
            sevk_tarihi=None,
        )
        self.assertEqual(s.durum_kodu, DURUM_SEVK_BEKLIYOR)
        self.assertIsNone(s.gercek_sevk_tarihi)
        self.assertIsNone(s.vade_sapma_gun_raw)
        self.assertIsNone(s.finansman_net)
        self.assertIsNone(s.hedef_vade_tarihi)

    def test_empty_sevk(self):
        s = hesapla(
            odeme_tipi="CEK",
            cek_satirlari=[_cek(100_000, 180)],
            para_birimi="TRY",
            onaylanan_vade_gun=180,
            sevk_tarihi="",
        )
        self.assertEqual(s.durum_kodu, DURUM_SEVK_BEKLIYOR)


# ---------------------------------------------------------------------------
# K7 — Nakit Paket
# ---------------------------------------------------------------------------

class TestK7NakitPaket(unittest.TestCase):

    def test_nakit(self):
        s = hesapla(
            odeme_tipi="NAKIT",
            cek_satirlari=[],
            para_birimi="TRY",
            onaylanan_vade_gun=180,
            sevk_tarihi=SEVK,
        )
        self.assertEqual(s.durum_kodu, DURUM_NAKIT_PAKET)
        self.assertIsNone(s.vade_sapma_gun_raw)
        self.assertIsNone(s.finansman_net)
        self.assertEqual(s.cek_adedi, 0)

    def test_havale(self):
        s = hesapla(
            odeme_tipi="HAVALE",
            cek_satirlari=[],
            para_birimi="TRY",
            onaylanan_vade_gun=180,
            sevk_tarihi=SEVK,
        )
        self.assertEqual(s.durum_kodu, DURUM_NAKIT_PAKET)

    def test_lowercase_nakit(self):
        """lowercase odeme_tipi da çalışmalı."""
        s = hesapla(
            odeme_tipi="nakit",
            cek_satirlari=[],
            para_birimi="TRY",
            onaylanan_vade_gun=180,
            sevk_tarihi=SEVK,
        )
        self.assertEqual(s.durum_kodu, DURUM_NAKIT_PAKET)


# ---------------------------------------------------------------------------
# Ek validation testleri
# ---------------------------------------------------------------------------

class TestValidation(unittest.TestCase):

    def test_zero_tutar_reject(self):
        cek = CekSatiriInput(
            tutar=Decimal("0"),
            gercek_cek_vade_tarihi=_gun_sonra(SEVK, 180),
            para_birimi="TRY",
        )
        with self.assertRaises(VadeKontrolError):
            _hesapla_pure([cek])

    def test_negative_tutar_reject(self):
        cek = CekSatiriInput(
            tutar=Decimal("-1000"),
            gercek_cek_vade_tarihi=_gun_sonra(SEVK, 180),
            para_birimi="TRY",
        )
        with self.assertRaises(VadeKontrolError):
            _hesapla_pure([cek])

    def test_pb_mismatch_reject(self):
        cekler = [
            _cek(100_000, 180, "TRY"),
            _cek(100_000, 180, "USD"),
        ]
        with self.assertRaises(VadeKontrolError):
            hesapla(
                odeme_tipi="CEK",
                cek_satirlari=cekler,
                para_birimi="TRY",
                onaylanan_vade_gun=180,
                sevk_tarihi=SEVK,
            )

    def test_invalid_date_reject(self):
        cek = CekSatiriInput(
            tutar=Decimal("100000"),
            gercek_cek_vade_tarihi="NOT-A-DATE",
            para_birimi="TRY",
        )
        with self.assertRaises(VadeKontrolError):
            _hesapla_pure([cek])

    def test_hedef_none_rollup_nullable(self):
        """paket_hedef_tutar verilmezse rollup alanları None."""
        cekler = [_cek(500_000, 180)]
        s = _hesapla_pure(cekler, hedef=None)
        self.assertIsNone(s.paket_hedef_tutar)
        self.assertIsNone(s.kalan_tutar)
        self.assertIsNone(s.karsilama_orani)
        self.assertIsNone(s.paket_tamamlandi)

    def test_cek_yok(self):
        """Çek listesi boşsa CEK_YOK."""
        s = _hesapla_pure([], onaylanan=180, sevk=SEVK)
        self.assertEqual(s.durum_kodu, DURUM_CEK_YOK)
        self.assertIsNone(s.agirlikli_ortalama_vade_gun_raw)

    def test_30_cek_performance_smoke(self):
        """30 çek satırı makul sürede tamamlanmalı."""
        cekler = [_cek(10_000, 150 + i * 2) for i in range(30)]
        t0 = time.perf_counter()
        s = _hesapla_pure(cekler, hedef=300_000)
        elapsed = time.perf_counter() - t0
        self.assertEqual(s.cek_adedi, 30)
        self.assertLess(elapsed, 1.0, f"30 çek hesabı {elapsed:.3f}s sürdü (limit 1s)")

    def test_json_serializable(self):
        """Sonuç dict olarak JSON serialize edilebilmeli."""
        import json
        cekler = [_cek(500_000, 207)]
        s = _hesapla_pure(cekler, onaylanan=180, hedef=500_000)
        d = s.to_dict()
        raw = json.dumps(d)  # exception atmamalı
        self.assertIn("durum_kodu", raw)

    def test_hedef_tutar_exact_match_tamamlandi(self):
        cekler = [_cek(700_000, 180)]
        s = _hesapla_pure(cekler, hedef=700_000)
        self.assertTrue(s.paket_tamamlandi)

    def test_eksik_paket_uyari(self):
        cekler = [_cek(650_000, 180)]
        s = _hesapla_pure(cekler, hedef=700_000)
        self.assertFalse(s.paket_tamamlandi)
        self.assertAlmostEqual(s.kalan_tutar, 50_000.0, places=0)
        self.assertTrue(any("Eksik" in u for u in s.uyarilar))

    def test_karsilama_orani(self):
        cekler = [_cek(650_000, 180)]
        s = _hesapla_pure(cekler, hedef=700_000)
        self.assertAlmostEqual(s.karsilama_orani, 92.86, places=1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
