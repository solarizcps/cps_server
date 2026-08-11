# -*- coding: utf-8 -*-
"""SEVKIYAT-SNAPSHOT-WRITER-GUARD-01 — fiyat snapshot zorunluluğu lock testleri."""
from __future__ import annotations

import hashlib
import os
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'app'))

from modules.nexgen.mo_sevkiyat_service import (
    MoSevkiyatError,
    sevkiyat_olustur,
)
from modules.nexgen.mo_tahsilat_sevk_service import tahsilat_sevk_adaylari

YK = {'*'}
UID = 1
CANONICAL_DB = Path(__file__).resolve().parents[2] / 'app' / 'mock_data.db'
PRE_CANONICAL_SHA = hashlib.sha256(CANONICAL_DB.read_bytes()).hexdigest()


def _mem_schema(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE nexgen_cari (
            id INTEGER PRIMARY KEY, unvan TEXT, cari_kod TEXT, aktif INTEGER DEFAULT 1
        );
        CREATE TABLE nexgen_planlama_siparis (
            id INTEGER PRIMARY KEY, siparis_no TEXT, cari_id INTEGER, cari_unvan TEXT,
            durum TEXT, anlasma_para_birimi TEXT, anlasma_birim_fiyat REAL,
            vade_gun INTEGER, tahsilat_kurali TEXT, kaynak_modul TEXT,
            tahsilat_durumu TEXT, tahsilat_gun_sayisi INTEGER,
            planlanan_tahsilat_tarihi TEXT, talep_referansi TEXT,
            guncelleme_tarihi TEXT, olusturma_tarihi TEXT,
            musteri_termin TEXT, onerilen_termin TEXT, termin_tarihi TEXT
        );
        CREATE TABLE nexgen_planlama_siparis_kalem (
            id INTEGER PRIMARY KEY, planlama_siparis_id INTEGER,
            sira_no INTEGER DEFAULT 1,
            birim_fiyat REAL, net_birim_fiyat REAL, iskonto_orani REAL,
            iskonto_tutari REAL, satir_tutari REAL,
            miktar_l REAL, miktar_s REAL, miktar_m REAL, durum TEXT DEFAULT 'AKTIF',
            urun_ailesi TEXT, renk_ad TEXT, formul_ad TEXT, formul_id INTEGER,
            renk_varyant_id INTEGER, rf_renk_id INTEGER,
            termin_tarihi TEXT, notlar TEXT, uretim_plan_id INTEGER,
            legacy_kaynak TEXT, olusturma_tarihi TEXT, guncelleme_tarihi TEXT
        );
        CREATE TABLE mo_musteri_sevkiyat (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sevkiyat_no TEXT NOT NULL UNIQUE,
            siparis_id INTEGER NOT NULL, cari_id INTEGER NOT NULL,
            durum TEXT NOT NULL DEFAULT 'HAZIRLANIYOR',
            hazirlik_tarihi TEXT, sevk_tarihi TEXT, teslim_tarihi TEXT,
            tamamlanma_tarihi TEXT, arac_plaka TEXT, sofor TEXT,
            irsaliye_no TEXT, kargo_firmasi TEXT, kargo_takip_no TEXT,
            teslim_alan TEXT, teslim_durumu TEXT, notlar TEXT,
            idempotency_key TEXT NOT NULL UNIQUE,
            olusturan_id INTEGER NOT NULL, aktif INTEGER NOT NULL DEFAULT 1,
            olusturma_tarihi TEXT, guncelleme_tarihi TEXT, audit_json TEXT
        );
        CREATE TABLE mo_musteri_sevkiyat_kalem (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sevkiyat_id INTEGER NOT NULL, siparis_kalem_id INTEGER,
            urun_adi TEXT, renk_ad TEXT, formul_ad TEXT,
            miktar_kg REAL NOT NULL DEFAULT 0, miktar_adet REAL, notlar TEXT,
            birim_fiyat_snapshot REAL, para_birimi_snapshot TEXT, fiyat_kaynagi TEXT
        );
        CREATE TABLE sistem_kullanici (
            Id INTEGER PRIMARY KEY, AdSoyad TEXT, KullaniciAdi TEXT
        );
        INSERT INTO sistem_kullanici (Id, AdSoyad, KullaniciAdi) VALUES (1, 'Test', 'test');
        INSERT INTO nexgen_cari (id, unvan) VALUES (1, 'Test Cari');
        """
    )


def _mem_con() -> sqlite3.Connection:
    con = sqlite3.connect(':memory:')
    con.row_factory = sqlite3.Row
    _mem_schema(con)
    return con


def _siparis(
    con: sqlite3.Connection,
    sid: int,
    *,
    pb: str = 'USD',
    header_fiyat: float | None = None,
    durum: str = 'ONAYLANDI',
) -> None:
    con.execute(
        """
        INSERT INTO nexgen_planlama_siparis
            (id, siparis_no, cari_id, cari_unvan, durum,
             anlasma_para_birimi, anlasma_birim_fiyat, kaynak_modul, talep_referansi)
        VALUES (?, ?, 1, 'Test Cari', ?, ?, ?, 'MUSTERI_OPERASYONU', NULL)
        """,
        (sid, f'PZM-2026-{sid:04d}', durum, pb, header_fiyat),
    )


def _kalem(
    con: sqlite3.Connection,
    kid: int,
    sid: int,
    *,
    net: float | None = None,
    brut: float | None = None,
    iskonto: float | None = None,
    kg: float = 1000,
    durum: str = 'AKTIF',
) -> None:
    con.execute(
        """
        INSERT INTO nexgen_planlama_siparis_kalem
            (id, planlama_siparis_id, sira_no, birim_fiyat, net_birim_fiyat, iskonto_orani,
             miktar_l, miktar_s, miktar_m, durum, urun_ailesi)
        VALUES (?, ?, 1, ?, ?, ?, ?, 0, 0, ?, 'BOYA')
        """,
        (kid, sid, brut, net, iskonto, kg, durum),
    )


def _payload(sid: int, kalemler: list[dict], idem: str = 'test-idem-1') -> dict:
    return {
        'siparis_id': sid,
        'idempotency_key': idem,
        'kalemler': kalemler,
    }


def _sevk_count(con: sqlite3.Connection) -> int:
    return int(con.execute('SELECT COUNT(*) FROM mo_musteri_sevkiyat').fetchone()[0])


def _kalem_count(con: sqlite3.Connection) -> int:
    return int(con.execute('SELECT COUNT(*) FROM mo_musteri_sevkiyat_kalem').fetchone()[0])


class TestSevkiyatSnapshotWriterGuard(unittest.TestCase):
    """A–G: snapshot writer guard — :memory: only."""

    def test_a_kalem_net_pass(self) -> None:
        con = _mem_con()
        _siparis(con, 1, pb='USD')
        _kalem(con, 101, 1, net=4.0)
        con.commit()
        kayit = sevkiyat_olustur(
            con, _payload(1, [{'siparis_kalem_id': 101, 'miktar_kg': 100}]), UID, YK,
        )
        k = kayit['kalemler'][0]
        self.assertEqual(k['birim_fiyat_snapshot'], 4.0)
        self.assertEqual(k['para_birimi_snapshot'], 'USD')
        self.assertEqual(k['fiyat_kaynagi'], 'KALEM_NET')

    def test_b_kalem_brut_pass(self) -> None:
        con = _mem_con()
        _siparis(con, 2, pb='EUR')
        _kalem(con, 201, 2, brut=10.0, iskonto=10.0)
        con.commit()
        kayit = sevkiyat_olustur(
            con, _payload(2, [{'siparis_kalem_id': 201, 'miktar_kg': 50}], 'test-b'), UID, YK,
        )
        k = kayit['kalemler'][0]
        self.assertEqual(k['birim_fiyat_snapshot'], 9.0)
        self.assertEqual(k['para_birimi_snapshot'], 'EUR')
        self.assertEqual(k['fiyat_kaynagi'], 'KALEM_BRUT')

    def test_c_siparis_baslik_pass(self) -> None:
        con = _mem_con()
        _siparis(con, 3, pb='USD', header_fiyat=2.5)
        _kalem(con, 301, 3)
        con.commit()
        kayit = sevkiyat_olustur(
            con, _payload(3, [{'siparis_kalem_id': 301, 'miktar_kg': 25}], 'test-c'), UID, YK,
        )
        k = kayit['kalemler'][0]
        self.assertEqual(k['birim_fiyat_snapshot'], 2.5)
        self.assertEqual(k['fiyat_kaynagi'], 'SIPARIS_BASLIK')

    def test_d_no_price_block(self) -> None:
        con = _mem_con()
        _siparis(con, 4, pb='USD', header_fiyat=None)
        _kalem(con, 401, 4)
        _kalem(con, 402, 4)
        con.commit()
        with self.assertRaises(MoSevkiyatError) as ctx:
            sevkiyat_olustur(
                con,
                _payload(4, [{'siparis_kalem_id': 401, 'miktar_kg': 10}], 'test-d'),
                UID,
                YK,
            )
        self.assertEqual(ctx.exception.kod, 409)
        self.assertIn('birim fiyat bulunamadı', ctx.exception.mesaj)
        self.assertEqual(_sevk_count(con), 0)
        self.assertEqual(_kalem_count(con), 0)

    def test_e_multi_item_atomicity(self) -> None:
        con = _mem_con()
        _siparis(con, 5, pb='USD')
        _kalem(con, 501, 5, net=3.0)
        _kalem(con, 502, 5)
        con.commit()
        with self.assertRaises(MoSevkiyatError):
            sevkiyat_olustur(
                con,
                _payload(
                    5,
                    [
                        {'siparis_kalem_id': 501, 'miktar_kg': 10},
                        {'siparis_kalem_id': 502, 'miktar_kg': 10},
                    ],
                    'test-e',
                ),
                UID,
                YK,
            )
        self.assertEqual(_sevk_count(con), 0)
        self.assertEqual(_kalem_count(con), 0)

    def test_f_pb_missing_block(self) -> None:
        con = _mem_con()
        _siparis(con, 6, pb=None, header_fiyat=None)
        _kalem(con, 601, 6, net=5.0)
        con.commit()
        with self.assertRaises(MoSevkiyatError) as ctx:
            sevkiyat_olustur(
                con, _payload(6, [{'siparis_kalem_id': 601, 'miktar_kg': 10}], 'test-f'), UID, YK,
            )
        self.assertEqual(ctx.exception.kod, 409)
        self.assertIn('para birimi snapshot', ctx.exception.mesaj)
        self.assertEqual(_sevk_count(con), 0)

    def test_g_tahsilat_contract(self) -> None:
        con = _mem_con()
        _siparis(con, 7, pb='USD', header_fiyat=4.0)
        _kalem(con, 701, 7, net=4.0)
        con.commit()
        kayit = sevkiyat_olustur(
            con, _payload(7, [{'siparis_kalem_id': 701, 'miktar_kg': 100}], 'test-g'), UID, YK,
        )
        con.execute(
            "UPDATE mo_musteri_sevkiyat SET durum='SEVK_EDILDI', sevk_tarihi='2026-08-10' WHERE id=?",
            (kayit['id'],),
        )
        con.commit()
        aday = tahsilat_sevk_adaylari(con, 7)
        eksik = [a for a in aday if a.get('durum') == 'EKSIK_FIYAT']
        self.assertEqual(eksik, [])
        uygun = [a for a in aday if a.get('tahsilata_uygun')]
        self.assertTrue(uygun)

    def test_zero_net_price_allowed(self) -> None:
        """net_birim_fiyat=0 — mevcut PZM semantics: ücretsiz kalem geçerli."""
        con = _mem_con()
        _siparis(con, 8, pb='TRY')
        _kalem(con, 801, 8, net=0.0)
        con.commit()
        kayit = sevkiyat_olustur(
            con, _payload(8, [{'siparis_kalem_id': 801, 'miktar_kg': 5}], 'test-zero'), UID, YK,
        )
        self.assertEqual(kayit['kalemler'][0]['birim_fiyat_snapshot'], 0.0)
        self.assertEqual(kayit['kalemler'][0]['fiyat_kaynagi'], 'KALEM_NET')


class TestSevkiyatSnapshotHistoricalLock(unittest.TestCase):
    """H — canonical DB read-only: post-153 fiyatlı sevkiyatlar dolu."""

    def test_h_post153_snapshots_present(self) -> None:
        if not CANONICAL_DB.exists():
            self.skipTest('canonical DB yok')
        con = sqlite3.connect(str(CANONICAL_DB))
        con.row_factory = sqlite3.Row
        try:
            rows = con.execute(
                """
                SELECT k.id, k.birim_fiyat_snapshot, k.para_birimi_snapshot, k.fiyat_kaynagi
                FROM mo_musteri_sevkiyat_kalem k
                JOIN mo_musteri_sevkiyat s ON s.id = k.sevkiyat_id
                WHERE COALESCE(s.aktif, 1) = 1
                  AND COALESCE(k.miktar_kg, 0) > 0
                  AND k.birim_fiyat_snapshot IS NOT NULL
                """
            ).fetchall()
            self.assertGreaterEqual(len(rows), 3)
            for r in rows:
                self.assertNotIn(r['birim_fiyat_snapshot'], (None, ''))
                self.assertNotIn(r['para_birimi_snapshot'], (None, ''))
                self.assertNotIn(r['fiyat_kaynagi'], (None, ''))
        finally:
            con.close()

    def test_canonical_db_sha_unchanged(self) -> None:
        if not CANONICAL_DB.exists():
            self.skipTest('canonical DB yok')
        sha = hashlib.sha256(CANONICAL_DB.read_bytes()).hexdigest()
        self.assertEqual(sha, PRE_CANONICAL_SHA)


if __name__ == '__main__':
    unittest.main()
