# -*- coding: utf-8 -*-
"""Ajanda görüşme detayı — ticari snapshot read/display LOCK."""
from __future__ import annotations

import os
import sqlite3
import sys
import unittest
from datetime import datetime
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'app'))

from modules.nexgen.mo_ajanda_service import ajanda_enrich_gorusme_ozet, gorusme_ozet_map
from modules.nexgen.mo_gorusme_config import GORUSME_TIPLERI_ALL

FIXED_NOW = datetime(2026, 8, 10, 12, 0, 0)
CARI_ID = 2001
UID = 49


def _schema(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE nexgen_cari (
            id INTEGER PRIMARY KEY, unvan TEXT, cari_kod TEXT, aktif INTEGER DEFAULT 1
        );
        CREATE TABLE sistem_kullanici (
            Id INTEGER PRIMARY KEY, KullaniciAdi TEXT, AdSoyad TEXT
        );
        CREATE TABLE musteri_operasyon_gorusme (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cari_id INTEGER, kullanici_id INTEGER,
            gorusme_tipi TEXT, sonuc_tipi TEXT, kisa_not TEXT,
            gorusme_tarihi TEXT, sonraki_aksiyon TEXT, sonraki_takip_tarihi TEXT,
            idempotency_key TEXT NOT NULL UNIQUE, aktif INTEGER DEFAULT 1,
            olusturan_kullanici_id INTEGER,
            fiyat_verildi INTEGER DEFAULT 0,
            verilen_fiyat REAL, fiyat_para_birimi TEXT, fiyat_birimi TEXT,
            konusulan_tonaj REAL, odeme_tipi TEXT,
            vade_gun INTEGER, cek_vade_gun INTEGER, cek_adedi INTEGER,
            ticari_not TEXT, cek_notu TEXT
        );
        CREATE TABLE musteri_operasyon_ajanda (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cari_id INTEGER NOT NULL, kullanici_id INTEGER NOT NULL,
            plan_tarihi TEXT NOT NULL, gorusme_tipi TEXT NOT NULL,
            durum TEXT NOT NULL DEFAULT 'PLANLANDI', gorusme_id INTEGER,
            idempotency_key TEXT NOT NULL UNIQUE, aktif INTEGER NOT NULL DEFAULT 1,
            olusturan_kullanici_id INTEGER NOT NULL
        );
        """
    )
    con.execute('INSERT INTO nexgen_cari VALUES (?,?,?,1)', (CARI_ID, 'Ticari Test', 'TT01'))
    con.execute('INSERT INTO sistem_kullanici VALUES (?,?,?)', (UID, 'erhan', 'Erhan Test'))
    con.commit()


def _insert_gorusme(con, **kw) -> int:
    defaults = {
        'cari_id': CARI_ID,
        'kullanici_id': UID,
        'gorusme_tipi': GORUSME_TIPLERI_ALL[0],
        'sonuc_tipi': 'Beklemede',
        'kisa_not': 'test not',
        'gorusme_tarihi': '2026-08-10 12:58:00',
        'sonraki_aksiyon': None,
        'sonraki_takip_tarihi': None,
        'idempotency_key': 'TIC-KEY',
        'olusturan_kullanici_id': UID,
        'fiyat_verildi': 0,
        'verilen_fiyat': None,
        'fiyat_para_birimi': None,
        'fiyat_birimi': None,
        'konusulan_tonaj': None,
        'odeme_tipi': None,
        'vade_gun': None,
        'cek_vade_gun': None,
        'cek_adedi': None,
        'ticari_not': None,
        'cek_notu': None,
    }
    defaults.update(kw)
    cols = ', '.join(defaults.keys())
    ph = ', '.join('?' * len(defaults))
    con.execute(
        f'INSERT INTO musteri_operasyon_gorusme ({cols}) VALUES ({ph})',
        tuple(defaults.values()),
    )
    con.commit()
    return con.execute('SELECT last_insert_rowid()').fetchone()[0]


class TicariDisplayLockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.con = sqlite3.connect(':memory:')
        self.con.row_factory = sqlite3.Row
        _schema(self.con)

    def tearDown(self) -> None:
        self.con.close()

    def test_a_ticari_gorusme_ozet_map(self) -> None:
        gid = _insert_gorusme(
            self.con,
            idempotency_key='TIC-A',
            fiyat_verildi=1,
            verilen_fiyat=5.0,
            fiyat_para_birimi='USD',
            fiyat_birimi='KG',
            konusulan_tonaj=100000.0,
            odeme_tipi='NAKIT',
        )
        m = gorusme_ozet_map(self.con, [gid])
        oz = m[gid]
        self.assertEqual(int(oz['fiyat_verildi']), 1)
        self.assertEqual(float(oz['verilen_fiyat']), 5.0)
        self.assertEqual(oz['fiyat_para_birimi'], 'USD')
        self.assertEqual(oz['fiyat_birimi'], 'KG')
        self.assertEqual(float(oz['konusulan_tonaj']), 100000.0)
        self.assertEqual(oz['odeme_tipi'], 'NAKIT')
        self.assertTrue(oz.get('fiyat_ozet'))
        self.assertIn('5', oz['fiyat_ozet'])
        self.assertIn('USD', oz['fiyat_ozet'])
        self.assertIn('NAKİT', oz['fiyat_ozet'])

    def test_b_ticari_veri_yok(self) -> None:
        gid = _insert_gorusme(self.con, idempotency_key='TIC-B', fiyat_verildi=0)
        m = gorusme_ozet_map(self.con, [gid])
        oz = m[gid]
        self.assertEqual(int(oz['fiyat_verildi']), 0)
        self.assertIsNone(oz.get('fiyat_ozet'))
        self.assertIsNone(oz.get('verilen_fiyat'))

    def test_c_vadeli_fiyat_ozet(self) -> None:
        gid = _insert_gorusme(
            self.con,
            idempotency_key='TIC-C',
            fiyat_verildi=1,
            verilen_fiyat=12.5,
            fiyat_para_birimi='EUR',
            fiyat_birimi='KG',
            odeme_tipi='VADELI',
            vade_gun=60,
        )
        oz = gorusme_ozet_map(self.con, [gid])[gid]
        self.assertEqual(oz['vade_gun'], 60)
        self.assertIn('VADELİ', oz['fiyat_ozet'])
        self.assertIn('60', oz['fiyat_ozet'])

    def test_d_cek_alanlari(self) -> None:
        gid = _insert_gorusme(
            self.con,
            idempotency_key='TIC-D',
            fiyat_verildi=1,
            verilen_fiyat=3.0,
            fiyat_para_birimi='USD',
            fiyat_birimi='KG',
            odeme_tipi='CEK',
            cek_vade_gun=90,
            cek_adedi=2,
            cek_notu='2 cek paket',
        )
        oz = gorusme_ozet_map(self.con, [gid])[gid]
        self.assertEqual(oz['cek_vade_gun'], 90)
        self.assertEqual(oz['cek_adedi'], 2)
        self.assertEqual(oz['cek_notu'], '2 cek paket')
        self.assertIn('ÇEK', oz['fiyat_ozet'])
        self.assertIn('90', oz['fiyat_ozet'])

    def test_e_ajanda_enrich_sync_contract(self) -> None:
        gid = _insert_gorusme(
            self.con,
            idempotency_key='TIC-E',
            fiyat_verildi=1,
            verilen_fiyat=5.0,
            fiyat_para_birimi='USD',
            fiyat_birimi='KG',
            konusulan_tonaj=100000.0,
            odeme_tipi='NAKIT',
        )
        self.con.execute(
            """
            INSERT INTO musteri_operasyon_ajanda
              (cari_id, kullanici_id, plan_tarihi, gorusme_tipi, durum, gorusme_id,
               idempotency_key, aktif, olusturan_kullanici_id)
            VALUES (?,?,?,?,?,?,?,1,?)
            """,
            (CARI_ID, UID, '2026-08-10 12:58:00', GORUSME_TIPLERI_ALL[0],
             'GERCEKLESTI', gid, 'TIC-E-AJ', UID),
        )
        self.con.commit()
        planlar = [{'id': 1, 'gorusme_id': gid, 'musteri': 'Ticari Test'}]
        out = ajanda_enrich_gorusme_ozet(self.con, planlar)
        self.assertIsNotNone(out[0].get('gorusme_ozet'))
        oz = out[0]['gorusme_ozet']
        self.assertEqual(int(oz['gorusme_id']), gid)
        self.assertTrue(oz.get('fiyat_ozet'))


if __name__ == '__main__':
    unittest.main()
