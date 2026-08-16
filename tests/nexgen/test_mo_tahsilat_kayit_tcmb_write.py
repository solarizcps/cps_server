# -*- coding: utf-8 -*-
"""
tests/nexgen/test_mo_tahsilat_kayit_tcmb_write.py
==================================================
Tahsilat TCMB snapshot write integration — isolated DB.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'app'))

from modules.nexgen.mo_tahsilat_config import KAYNAK_MUSTERI_OPERASYONU
from modules.nexgen.mo_tahsilat_kayit_service import (
    MoTahsilatError,
    onaya_gonder,
    sync_cek_parent_tutarlar,
    taslak_kaydet,
)

YK = {'*'}
UID = 1
KUR_TARIH = '2026-08-09'
SEVK_KUR_TARIH = '2026-08-01'


def _schema(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE nexgen_cari (id INTEGER PRIMARY KEY, unvan TEXT, aktif INTEGER DEFAULT 1);
        CREATE TABLE nexgen_planlama_siparis (
            id INTEGER PRIMARY KEY, siparis_no TEXT, cari_id INTEGER, durum TEXT,
            anlasma_para_birimi TEXT, anlasma_birim_fiyat REAL, vade_gun INTEGER,
            tahsilat_kurali TEXT, kaynak_modul TEXT, tahsilat_durumu TEXT,
            guncelleme_tarihi TEXT, talep_referansi TEXT
        );
        CREATE TABLE mo_musteri_sevkiyat (
            id INTEGER PRIMARY KEY, sevkiyat_no TEXT, siparis_id INTEGER, cari_id INTEGER,
            durum TEXT, aktif INTEGER DEFAULT 1, sevk_tarihi TEXT,
            idempotency_key TEXT, olusturan_id INTEGER, olusturma_tarihi TEXT
        );
        CREATE TABLE mo_musteri_sevkiyat_kalem (
            id INTEGER PRIMARY KEY, sevkiyat_id INTEGER, miktar_kg REAL,
            birim_fiyat_snapshot REAL, para_birimi_snapshot TEXT
        );
        CREATE TABLE sistem_kur (
            Id INTEGER PRIMARY KEY AUTOINCREMENT, Tarih TEXT, ParaBirimi TEXT,
            Alis REAL, Satis REAL, MerkezKur REAL
        );
        CREATE TABLE mo_tahsilat_kayit (
            id INTEGER PRIMARY KEY AUTOINCREMENT, kayit_kodu TEXT,
            cari_id INTEGER, siparis_id INTEGER, sevkiyat_id INTEGER,
            kaynak_modul TEXT, beklenen_tutar REAL, beklenen_tahmini INTEGER,
            paket_hedef_tutar REAL, alinan_tutar REAL, kalan_tutar REAL,
            planlanan_tahsilat_tarihi TEXT, alinan_tarih TEXT,
            odeme_tipi TEXT, odeme_referansi TEXT, kismi_mi INTEGER,
            aciklama TEXT, dosya_ref TEXT, onay_notu TEXT, durum TEXT,
            cari_entegrasyon_durumu TEXT, idempotency_key TEXT UNIQUE,
            olusturan_id INTEGER, onaylayan_id INTEGER, aktif INTEGER DEFAULT 1,
            olusturma_tarihi TEXT, guncelleme_tarihi TEXT,
            para_birimi TEXT,
            onaylanan_vade_gun_snapshot INTEGER,
            gercek_sevk_tarihi_snapshot TEXT, hedef_vade_tarihi TEXT,
            sevk_hedef_tutar_snapshot REAL, sevk_para_birimi_snapshot TEXT,
            sevk_kalan_fx_snapshot REAL, tcmb_satis_kur_snapshot REAL,
            kur_tarihi_snapshot TEXT
        );
        CREATE TABLE mo_tahsilat_cek (
            id INTEGER PRIMARY KEY AUTOINCREMENT, tahsilat_kayit_id INTEGER,
            tutar REAL, cek_alim_tarihi TEXT, gercek_cek_vade_tarihi TEXT,
            para_birimi TEXT, aktif INTEGER DEFAULT 1, idempotency_key TEXT UNIQUE,
            sira_no INTEGER
        );
        """
    )


def _mem_con() -> sqlite3.Connection:
    con = sqlite3.connect(':memory:')
    con.row_factory = sqlite3.Row
    _schema(con)
    con.execute('INSERT INTO nexgen_cari (id, unvan) VALUES (1, ?)', ('Test Cari',))
    con.execute(
        """
        INSERT INTO nexgen_planlama_siparis
            (id, siparis_no, cari_id, durum, anlasma_para_birimi, vade_gun,
             tahsilat_kurali, kaynak_modul)
        VALUES (1, 'S-1', 1, 'ONAYLANDI', 'USD', 180, 'VADE_GUN', ?)
        """,
        (KAYNAK_MUSTERI_OPERASYONU,),
    )
    con.execute(
        """
        INSERT INTO mo_musteri_sevkiyat
            (id, sevkiyat_no, siparis_id, cari_id, durum, aktif, sevk_tarihi, idempotency_key, olusturan_id, olusturma_tarihi)
        VALUES (10, 'MSV-10', 1, 1, 'SEVK_EDILDI', 1, '2026-08-01', 'sevk-10', 1, '2026-08-01')
        """
    )
    con.execute(
        """
        INSERT INTO mo_musteri_sevkiyat_kalem
            (sevkiyat_id, miktar_kg, birim_fiyat_snapshot, para_birimi_snapshot)
        VALUES (10, 200, 2, 'USD')
        """
    )
    con.execute(
        'INSERT INTO sistem_kur (Tarih, ParaBirimi, Alis, Satis, MerkezKur) VALUES (?,?,?,?,?)',
        (SEVK_KUR_TARIH, 'USD', 47.0, 47.25, 99.99),
    )
    con.execute(
        'INSERT INTO sistem_kur (Tarih, ParaBirimi, Alis, Satis, MerkezKur) VALUES (?,?,?,?,?)',
        (KUR_TARIH, 'USD', 47.0, 47.25, 99.99),
    )
    con.commit()
    return con


def _payload(**kw) -> dict:
    base = {
        'idempotency_key': kw.pop('idempotency_key', 'idem-1'),
        'cari_id': 1,
        'siparis_id': 1,
        'sevkiyat_id': 10,
        'odeme_tipi': 'NAKIT',
        'alinan_tarih': KUR_TARIH,
        'manuel_fx_kur': 47.25,
    }
    base.update(kw)
    return base


class TestMoTahsilatKayitTcmbWrite(unittest.TestCase):
    def test_a_usd_freeze_snapshots(self) -> None:
        con = _mem_con()
        kayit = taslak_kaydet(con, _payload(alinan_tutar=10000), UID, YK)
        self.assertEqual(kayit['beklenen_tutar'], 18900.0)
        self.assertEqual(kayit['para_birimi'], 'TRY')
        self.assertEqual(kayit['sevk_kalan_fx_snapshot'], 400.0)
        self.assertEqual(kayit['tcmb_satis_kur_snapshot'], 47.25)
        self.assertEqual(kayit['kur_tarihi_snapshot'], SEVK_KUR_TARIH)
        self.assertEqual(kayit['sevk_para_birimi_snapshot'], 'USD')

    def test_b_nakit_kalan_try(self) -> None:
        con = _mem_con()
        kayit = taslak_kaydet(con, _payload(alinan_tutar=10000), UID, YK)
        self.assertEqual(kayit['kalan_tutar'], 8900.0)
        self.assertEqual(kayit['kismi_mi'], 1)

    def test_c_cek_paket_100(self) -> None:
        con = _mem_con()
        p = {
            'idempotency_key': 'cek-1',
            'cari_id': 1,
            'siparis_id': 1,
            'odeme_tipi': 'CEK',
            'manuel_fx_kur': 47.25,
        }
        kayit = taslak_kaydet(con, p, UID, YK)
        kid = kayit['id']
        con.execute(
            """
            INSERT INTO mo_tahsilat_cek
                (tahsilat_kayit_id, tutar, cek_alim_tarihi, gercek_cek_vade_tarihi,
                 para_birimi, aktif, idempotency_key, sira_no)
            VALUES (?, 10000, ?, '2027-02-09', 'TRY', 1, 'cek-a', 1)
            """,
            (kid, KUR_TARIH),
        )
        con.execute(
            """
            INSERT INTO mo_tahsilat_cek
                (tahsilat_kayit_id, tutar, cek_alim_tarihi, gercek_cek_vade_tarihi,
                 para_birimi, aktif, idempotency_key, sira_no)
            VALUES (?, 8900, ?, '2027-03-09', 'TRY', 1, 'cek-b', 2)
            """,
            (kid, KUR_TARIH),
        )
        con.commit()
        kayit2 = taslak_kaydet(
            con,
            {**p, 'sevkiyat_id': 10},
            UID,
            YK,
            kayit_id=kid,
        )
        self.assertEqual(kayit2['paket_hedef_tutar'], 18900.0)
        sync_cek_parent_tutarlar(con, kid)
        con.commit()
        row = con.execute(
            'SELECT alinan_tutar, kalan_tutar FROM mo_tahsilat_kayit WHERE id=?',
            (kid,),
        ).fetchone()
        self.assertEqual(float(row['alinan_tutar']), 18900.0)
        self.assertEqual(float(row['kalan_tutar'] or 0), 0.0)

    def test_d_kur_yok_fail(self) -> None:
        con = _mem_con()
        con.execute(
            "UPDATE mo_musteri_sevkiyat SET sevk_tarihi='2025-07-01' WHERE id=10"
        )
        con.commit()
        with self.assertRaises(MoTahsilatError):
            taslak_kaydet(
                con,
                _payload(idempotency_key='no-kur', alinan_tarih=KUR_TARIH, manuel_fx_kur=None),
                UID,
                YK,
            )

    def test_e_satis_not_merkez(self) -> None:
        con = _mem_con()
        kayit = taslak_kaydet(con, _payload(idempotency_key='satis'), UID, YK)
        self.assertEqual(kayit['tcmb_satis_kur_snapshot'], 47.25)
        self.assertEqual(kayit['beklenen_tutar'], 18900.0)

    def test_f_snapshot_immutable_after_kur_change(self) -> None:
        con = _mem_con()
        kayit = taslak_kaydet(con, _payload(idempotency_key='imm'), UID, YK)
        kid = kayit['id']
        con.execute(
            "UPDATE sistem_kur SET Satis=50.0, MerkezKur=50.0 WHERE Tarih=? AND ParaBirimi='USD'",
            (SEVK_KUR_TARIH,),
        )
        con.commit()
        kayit2 = taslak_kaydet(
            con,
            _payload(idempotency_key='imm', alinan_tutar=12000),
            UID,
            YK,
            kayit_id=kid,
        )
        self.assertEqual(kayit2['tcmb_satis_kur_snapshot'], 47.25)
        self.assertEqual(kayit2['beklenen_tutar'], 18900.0)

    @patch('modules.nexgen.onay_tahsilat_adapter.tahsilat_onaya_gonder')
    def test_g_onaya_gonder_preserves_snapshot(self, mock_onay) -> None:
        mock_onay.return_value = {'ok': True, 'talep_id': 1}
        con = _mem_con()
        kayit = taslak_kaydet(
            con,
            _payload(idempotency_key='onay', alinan_tutar=18900),
            UID,
            YK,
        )
        kid = kayit['id']
        con.execute(
            "UPDATE sistem_kur SET Satis=55.0 WHERE Tarih=? AND ParaBirimi='USD'",
            (SEVK_KUR_TARIH,),
        )
        con.commit()
        onaya_gonder(con, kid, UID, set())
        row = con.execute(
            'SELECT tcmb_satis_kur_snapshot, beklenen_tutar, durum FROM mo_tahsilat_kayit WHERE id=?',
            (kid,),
        ).fetchone()
        self.assertEqual(float(row['tcmb_satis_kur_snapshot']), 47.25)
        self.assertEqual(float(row['beklenen_tutar']), 18900.0)

    def test_legacy_no_sevk(self) -> None:
        con = _mem_con()
        p = {
            'idempotency_key': 'legacy-1',
            'cari_id': 1,
            'siparis_id': 1,
            'odeme_tipi': 'NAKIT',
            'alinan_tarih': KUR_TARIH,
            'beklenen_tutar': 5000,
            'alinan_tutar': 5000,
        }
        kayit = taslak_kaydet(con, p, UID, YK)
        self.assertIsNone(kayit.get('sevkiyat_id'))
        self.assertIsNone(kayit.get('tcmb_satis_kur_snapshot'))


if __name__ == '__main__':
    unittest.main()
