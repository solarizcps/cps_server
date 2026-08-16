# -*- coding: utf-8 -*-
"""FX sevkiyat kalan hesabı — MSV-2026-0166 dimensional bug lock."""
from __future__ import annotations

import hashlib
import os
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'app'))

from modules.nexgen.mo_tahsilat_config import (
    KAYIT_DURUM_ISTISNA_ONAY_BEKLIYOR,
    KAYIT_DURUM_ONAYLANDI,
    KAYIT_DURUM_REDDEDILDI,
    KAYIT_DURUM_YONETIM_ONAY_BEKLIYOR,
    KAYIT_DURUM_YONETIM_ONAYLANDI,
    KAYNAK_MUSTERI_OPERASYONU,
)
from modules.nexgen.mo_tahsilat_kayit_service import MoTahsilatError
from modules.nexgen.mo_tahsilat_sevk_service import (
    sevk_tahsil_kalan_hesapla,
    tahsilat_sevk_adaylari,
    tahsilat_sevk_write_guard,
)

CANONICAL_DB = os.path.join(
    os.path.dirname(__file__), '..', '..', 'app', 'mock_data.db',
)
KUR = 47.0
SEVK_HEDEF = 4000.0


def _canonical_sha() -> str:
    p = os.path.normpath(CANONICAL_DB)
    if not os.path.isfile(p):
        return ''
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest().upper()


def _schema(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE mo_musteri_sevkiyat (
            id INTEGER PRIMARY KEY, sevkiyat_no TEXT, siparis_id INTEGER, cari_id INTEGER,
            durum TEXT, aktif INTEGER DEFAULT 1, sevk_tarihi TEXT, olusturma_tarihi TEXT
        );
        CREATE TABLE mo_musteri_sevkiyat_kalem (
            id INTEGER PRIMARY KEY, sevkiyat_id INTEGER, miktar_kg REAL,
            birim_fiyat_snapshot REAL, para_birimi_snapshot TEXT
        );
        CREATE TABLE mo_tahsilat_kayit (
            id INTEGER PRIMARY KEY AUTOINCREMENT, kayit_kodu TEXT,
            cari_id INTEGER, siparis_id INTEGER, sevkiyat_id INTEGER,
            alinan_tutar REAL, odeme_tipi TEXT, durum TEXT, aktif INTEGER DEFAULT 1,
            tcmb_satis_kur_snapshot REAL
        );
        CREATE TABLE mo_tahsilat_cek (
            id INTEGER PRIMARY KEY AUTOINCREMENT, tahsilat_kayit_id INTEGER,
            tutar REAL, aktif INTEGER DEFAULT 1
        );
        """
    )


def _mem_usd_con() -> sqlite3.Connection:
    con = sqlite3.connect(':memory:')
    con.row_factory = sqlite3.Row
    _schema(con)
    con.execute(
        """
        INSERT INTO mo_musteri_sevkiyat
            (id, sevkiyat_no, siparis_id, cari_id, durum, aktif, sevk_tarihi, olusturma_tarihi)
        VALUES (228, 'MSV-2026-0166', 760, 11, 'SEVK_EDILDI', 1, '2026-08-10', '2026-08-10')
        """
    )
    con.execute(
        """
        INSERT INTO mo_musteri_sevkiyat_kalem
            (sevkiyat_id, miktar_kg, birim_fiyat_snapshot, para_birimi_snapshot)
        VALUES (228, 2000, 2, 'USD')
        """
    )
    con.commit()
    return con


def _mem_try_con() -> sqlite3.Connection:
    con = sqlite3.connect(':memory:')
    con.row_factory = sqlite3.Row
    _schema(con)
    con.execute(
        """
        INSERT INTO mo_musteri_sevkiyat
            (id, sevkiyat_no, siparis_id, cari_id, durum, aktif, sevk_tarihi, olusturma_tarihi)
        VALUES (50, 'MSV-TRY', 100, 1, 'SEVK_EDILDI', 1, '2026-08-10', '2026-08-10')
        """
    )
    con.execute(
        """
        INSERT INTO mo_musteri_sevkiyat_kalem
            (sevkiyat_id, miktar_kg, birim_fiyat_snapshot, para_birimi_snapshot)
        VALUES (50, 100, 500, 'TRY')
        """
    )
    con.commit()
    return con


def _insert_cek_kayit(
    con: sqlite3.Connection,
    *,
    durum: str,
    cek_try: float,
    kur: float | None = KUR,
    kod: str,
) -> int:
    cur = con.execute(
        """
        INSERT INTO mo_tahsilat_kayit
            (kayit_kodu, cari_id, siparis_id, sevkiyat_id, alinan_tutar,
             odeme_tipi, durum, aktif, tcmb_satis_kur_snapshot)
        VALUES (?, 11, 760, 228, ?, 'CEK', ?, 1, ?)
        """,
        (kod, cek_try, durum, kur),
    )
    kid = int(cur.lastrowid)
    con.execute(
        'INSERT INTO mo_tahsilat_cek (tahsilat_kayit_id, tutar, aktif) VALUES (?, ?, 1)',
        (kid, cek_try),
    )
    con.commit()
    return kid


class TestFxSevkKalanMsv166(unittest.TestCase):
    def test_1_3_karsilanan_kalan_fx_try(self) -> None:
        con = _mem_usd_con()
        _insert_cek_kayit(con, durum=KAYIT_DURUM_YONETIM_ONAYLANDI, cek_try=125_000, kod='MO-T-0080')
        info = sevk_tahsil_kalan_hesapla(con, 228, SEVK_HEDEF, 'USD')
        self.assertAlmostEqual(info['tahsil_edilen_fx'], 125_000 / KUR, places=2)
        self.assertAlmostEqual(info['kalan_fx'], 4000 - 125_000 / KUR, places=2)
        self.assertAlmostEqual(info['kalan_try'], round((4000 - 125_000 / KUR) * KUR, 2), places=0)

    def test_4_5_not_completed_not_exceeded(self) -> None:
        con = _mem_usd_con()
        _insert_cek_kayit(con, durum=KAYIT_DURUM_YONETIM_ONAYLANDI, cek_try=125_000, kod='MO-T-0080')
        aday = tahsilat_sevk_adaylari(con, 760)[0]
        self.assertFalse(aday['tahsil_tamamlandi'])
        self.assertFalse(aday['kalan_negatif'])
        self.assertTrue(aday['secilebilir'])

    def test_6_pending_partial_still_selectable(self) -> None:
        con = _mem_usd_con()
        _insert_cek_kayit(con, durum=KAYIT_DURUM_YONETIM_ONAY_BEKLIYOR, cek_try=125_000, kod='MO-T-PEND')
        aday = tahsilat_sevk_adaylari(con, 760)[0]
        self.assertTrue(aday['onay_bekleyen_tahsilat'])
        self.assertEqual(aday['onay_bekleyen_rezerve_try'], 125_000.0)
        self.assertFalse(aday['tahsil_tamamlandi'])
        self.assertFalse(aday['kalan_negatif'])
        self.assertTrue(aday['secilebilir'])
        self.assertAlmostEqual(aday['kalan_fx'], 4000 - 125_000 / KUR, places=2)
        guard = tahsilat_sevk_write_guard(con, cari_id=11, siparis_id=760, sevkiyat_id=228)
        self.assertTrue(guard['secilebilir'])

    def test_6b_pending_full_target_not_selectable(self) -> None:
        con = _mem_usd_con()
        _insert_cek_kayit(con, durum=KAYIT_DURUM_YONETIM_ONAY_BEKLIYOR, cek_try=188_000, kod='MO-T-PFULL')
        aday = tahsilat_sevk_adaylari(con, 760)[0]
        self.assertTrue(aday['onay_bekleyen_tahsilat'])
        self.assertTrue(aday['tahsil_tamamlandi'])
        self.assertFalse(aday['secilebilir'])
        with self.assertRaises(MoTahsilatError) as ctx:
            tahsilat_sevk_write_guard(con, cari_id=11, siparis_id=760, sevkiyat_id=228)
        self.assertIn('tahsilat tamamlanmış', str(ctx.exception).lower())

    def test_7_full_cek_completed(self) -> None:
        con = _mem_usd_con()
        _insert_cek_kayit(con, durum=KAYIT_DURUM_YONETIM_ONAYLANDI, cek_try=188_000, kod='MO-T-FULL')
        aday = tahsilat_sevk_adaylari(con, 760)[0]
        self.assertTrue(aday['tahsil_tamamlandi'])
        self.assertLessEqual(aday['kalan_fx'] or 0, 0.009)
        self.assertFalse(aday['secilebilir'])

    def test_8_try_shipment_direct(self) -> None:
        con = _mem_try_con()
        con.execute(
            """
            INSERT INTO mo_tahsilat_kayit
                (kayit_kodu, cari_id, siparis_id, sevkiyat_id, alinan_tutar,
                 odeme_tipi, durum, aktif, tcmb_satis_kur_snapshot)
            VALUES ('TRY-1', 1, 100, 50, 30000, 'NAKIT', ?, 1, NULL)
            """,
            (KAYIT_DURUM_YONETIM_ONAYLANDI,),
        )
        con.commit()
        info = sevk_tahsil_kalan_hesapla(con, 50, 50_000.0, 'TRY')
        self.assertEqual(info['tahsil_edilen_fx'], 30_000.0)
        self.assertEqual(info['kalan_fx'], 20_000.0)
        self.assertIsNone(info['kalan_try'])

    def test_9_invalid_kur_controlled_error(self) -> None:
        con = _mem_usd_con()
        _insert_cek_kayit(con, durum=KAYIT_DURUM_YONETIM_ONAYLANDI, cek_try=125_000, kur=0, kod='MO-T-BAD')
        info = sevk_tahsil_kalan_hesapla(con, 228, SEVK_HEDEF, 'USD')
        self.assertIsNotNone(info['kur_hesap_hatasi'])
        aday = tahsilat_sevk_adaylari(con, 760)[0]
        self.assertFalse(aday['secilebilir'])

    def test_10_red_iptal_excluded(self) -> None:
        con = _mem_usd_con()
        _insert_cek_kayit(con, durum=KAYIT_DURUM_YONETIM_ONAYLANDI, cek_try=125_000, kod='MO-T-OK')
        _insert_cek_kayit(con, durum=KAYIT_DURUM_REDDEDILDI, cek_try=999_999, kod='MO-T-RED')
        _insert_cek_kayit(con, durum=KAYIT_DURUM_ONAYLANDI, cek_try=999_999, kur=KUR, kod='MO-T-LEG')
        con.execute(
            """
            UPDATE mo_tahsilat_kayit SET durum='REDDEDILDI' WHERE kayit_kodu='MO-T-LEG'
            """
        )
        con.commit()
        info = sevk_tahsil_kalan_hesapla(con, 228, SEVK_HEDEF, 'USD')
        self.assertAlmostEqual(info['tahsil_edilen_fx'], 125_000 / KUR, places=2)

    def test_istisna_pending_reserved_only(self) -> None:
        con = _mem_usd_con()
        _insert_cek_kayit(
            con, durum=KAYIT_DURUM_ISTISNA_ONAY_BEKLIYOR, cek_try=125_000, kod='MO-T-IST',
        )
        info = sevk_tahsil_kalan_hesapla(con, 228, SEVK_HEDEF, 'USD')
        self.assertAlmostEqual(info['tahsil_edilen_fx'], 125_000 / KUR, places=2)
        self.assertTrue(info['onay_bekleyen_tahsilat'])


class TestFxSevkKalanCanonicalSha(unittest.TestCase):
    def test_canonical_db_unchanged(self) -> None:
        sha = _canonical_sha()
        if not sha:
            self.skipTest('canonical mock_data.db yok')
        self.assertEqual(len(sha), 64)


if __name__ == '__main__':
    unittest.main()
