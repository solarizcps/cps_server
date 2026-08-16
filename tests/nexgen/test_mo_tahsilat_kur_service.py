# -*- coding: utf-8 -*-
"""
tests/nexgen/test_mo_tahsilat_kur_service.py
=============================================
TCMB Döviz Satış → TRY hedef canonical servis testleri.

Live DB write YOK. Isolated in-memory SQLite.
Çalıştır: python -m unittest tests.nexgen.test_mo_tahsilat_kur_service
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'app'))

from modules.nexgen.mo_tahsilat_kur_service import (
    KUR_KAYNAGI,
    KUR_KAYNAGI_ONCEKI_GECERLI_GUN,
    MoTahsilatKurError,
    fx_try_hedef_hesapla,
    fx_try_hedef_json,
    tcmb_satis_kur_cozumle,
    tcmb_satis_kur_oku,
)


def _mem_con() -> sqlite3.Connection:
    con = sqlite3.connect(':memory:')
    con.row_factory = sqlite3.Row
    con.execute(
        """
        CREATE TABLE sistem_kur (
            Id INTEGER PRIMARY KEY AUTOINCREMENT,
            Tarih TEXT NOT NULL,
            ParaBirimi TEXT NOT NULL,
            Alis REAL,
            Satis REAL,
            MerkezKur REAL,
            Kaynak TEXT
        )
        """
    )
    return con


def _kur_ekle(con: sqlite3.Connection, tarih: str, pb: str, satis: float, merkez: float) -> None:
    con.execute(
        'INSERT INTO sistem_kur (Tarih, ParaBirimi, Alis, Satis, MerkezKur, Kaynak) VALUES (?,?,?,?,?,?)',
        (tarih, pb, satis * 0.99, satis, merkez, 'TEST'),
    )
    con.commit()


class TestMoTahsilatKurService(unittest.TestCase):
    def test_a_usd_400_x_4725(self) -> None:
        con = _mem_con()
        _kur_ekle(con, '2026-08-09', 'USD', 47.25, 99.99)
        r = fx_try_hedef_hesapla(con, para_birimi='USD', kur_tarihi='2026-08-09', fx_tutar=400)
        self.assertEqual(r['try_hedef_tutar'], 18900.0)
        self.assertEqual(r['tcmb_satis_kur'], 47.25)
        self.assertEqual(r['kaynak_pb'], 'USD')
        self.assertEqual(r['kur_kaynagi'], 'TCMB_SATIS')

    def test_b_eur_1000(self) -> None:
        con = _mem_con()
        _kur_ekle(con, '2026-08-09', 'EUR', 51.5, 88.0)
        r = fx_try_hedef_hesapla(con, para_birimi='EUR', kur_tarihi='2026-08-09', fx_tutar=1000)
        self.assertEqual(r['try_hedef_tutar'], 51500.0)
        self.assertEqual(r['tcmb_satis_kur'], 51.5)

    def test_c_try_5000(self) -> None:
        con = _mem_con()
        r = fx_try_hedef_hesapla(con, para_birimi='TRY', kur_tarihi='2026-08-09', fx_tutar=5000)
        self.assertEqual(r['tcmb_satis_kur'], 1.0)
        self.assertEqual(r['try_hedef_tutar'], 5000.0)
        self.assertEqual(r['kaynak_pb'], 'TRY')

    def test_d_kur_tarihi_yok(self) -> None:
        con = _mem_con()
        _kur_ekle(con, '2026-08-10', 'USD', 47.25, 47.0)
        with self.assertRaises(MoTahsilatKurError) as ctx:
            fx_try_hedef_hesapla(con, para_birimi='USD', kur_tarihi='2026-08-09', fx_tutar=400)
        self.assertEqual(ctx.exception.kod, 404)

    def test_e_satis_not_merkez_kur(self) -> None:
        con = _mem_con()
        _kur_ekle(con, '2026-08-09', 'USD', 47.25, 99.99)
        kur = tcmb_satis_kur_oku(con, 'USD', '2026-08-09')
        self.assertEqual(float(kur), 47.25)
        r = fx_try_hedef_hesapla(con, para_birimi='USD', kur_tarihi='2026-08-09', fx_tutar=400)
        self.assertNotEqual(r['try_hedef_tutar'], 400 * 99.99)
        self.assertEqual(r['try_hedef_tutar'], 18900.0)

    def test_f_previous_business_day_fallback(self) -> None:
        con = _mem_con()
        _kur_ekle(con, '2026-08-21', 'USD', 47.20, 47.0)
        r = fx_try_hedef_hesapla(con, para_birimi='USD', kur_tarihi='2026-08-22', fx_tutar=400)
        self.assertEqual(r['istenen_sevk_tarihi'], '2026-08-22')
        self.assertEqual(r['kur_tarihi'], '2026-08-21')
        self.assertEqual(r['kur_kaynagi'], KUR_KAYNAGI_ONCEKI_GECERLI_GUN)
        self.assertEqual(r['try_hedef_tutar'], 18880.0)

    def test_f2_cumartesi_cuma(self) -> None:
        con = _mem_con()
        _kur_ekle(con, '2026-08-21', 'USD', 47.20, 47.0)
        c = tcmb_satis_kur_cozumle(con, 'USD', '2026-08-22')
        self.assertEqual(c['kur_tarihi'], '2026-08-21')
        self.assertEqual(c['kur_kaynagi'], KUR_KAYNAGI_ONCEKI_GECERLI_GUN)

    def test_f3_pazar_cuma(self) -> None:
        con = _mem_con()
        _kur_ekle(con, '2026-08-21', 'USD', 47.20, 47.0)
        c = tcmb_satis_kur_cozumle(con, 'USD', '2026-08-23')
        self.assertEqual(c['kur_tarihi'], '2026-08-21')

    def test_f4_is_gunu_exact(self) -> None:
        con = _mem_con()
        _kur_ekle(con, '2026-08-20', 'USD', 47.25, 47.0)
        c = tcmb_satis_kur_cozumle(con, 'USD', '2026-08-20')
        self.assertEqual(c['kur_tarihi'], '2026-08-20')
        self.assertEqual(c['kur_kaynagi'], KUR_KAYNAGI)

    def test_f5_no_future_fallback(self) -> None:
        con = _mem_con()
        _kur_ekle(con, '2026-08-10', 'USD', 50.0, 50.0)
        with self.assertRaises(MoTahsilatKurError):
            fx_try_hedef_hesapla(con, para_birimi='USD', kur_tarihi='2026-08-09', fx_tutar=100)

    def test_g_json_serializable(self) -> None:
        con = _mem_con()
        _kur_ekle(con, '2026-08-09', 'USD', 47.25, 47.0)
        raw = fx_try_hedef_json(con, para_birimi='USD', kur_tarihi='2026-08-09', fx_tutar=400)
        parsed = json.loads(raw)
        self.assertEqual(parsed['try_hedef_tutar'], 18900.0)

    def test_validation_negative_fx(self) -> None:
        con = _mem_con()
        with self.assertRaises(MoTahsilatKurError):
            fx_try_hedef_hesapla(con, para_birimi='USD', kur_tarihi='2026-08-09', fx_tutar=-1)

    def test_validation_unsupported_pb(self) -> None:
        con = _mem_con()
        with self.assertRaises(MoTahsilatKurError):
            fx_try_hedef_hesapla(con, para_birimi='GBP', kur_tarihi='2026-08-09', fx_tutar=100)

    def test_validation_invalid_date(self) -> None:
        con = _mem_con()
        with self.assertRaises(MoTahsilatKurError):
            fx_try_hedef_hesapla(con, para_birimi='USD', kur_tarihi='09-08-2026', fx_tutar=100)

    def test_validation_satis_null(self) -> None:
        con = _mem_con()
        con.execute(
            'INSERT INTO sistem_kur (Tarih, ParaBirimi, Satis, MerkezKur) VALUES (?,?,?,?)',
            ('2026-08-09', 'USD', None, 47.0),
        )
        con.commit()
        with self.assertRaises(MoTahsilatKurError) as ctx:
            fx_try_hedef_hesapla(con, para_birimi='USD', kur_tarihi='2026-08-09', fx_tutar=100)
        self.assertEqual(ctx.exception.kod, 404)

    def test_validation_satis_zero(self) -> None:
        con = _mem_con()
        _kur_ekle(con, '2026-08-09', 'USD', 0, 47.0)
        with self.assertRaises(MoTahsilatKurError):
            fx_try_hedef_hesapla(con, para_birimi='USD', kur_tarihi='2026-08-09', fx_tutar=100)


if __name__ == '__main__':
    unittest.main()
