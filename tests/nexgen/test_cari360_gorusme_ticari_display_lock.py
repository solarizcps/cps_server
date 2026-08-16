# -*- coding: utf-8 -*-
"""Cari360 Görüşmeler — API fiyat_ozet + template field-level ticari render LOCK."""
from __future__ import annotations

import os
import sqlite3
import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'app'))

from modules.nexgen.mo_gorusme_config import GORUSME_TIPLERI_ALL
from modules.nexgen.mo_gorusme_service import list_gorusmeler

FIXED_NOW = datetime(2026, 8, 10, 12, 0, 0)
CARI_ID = 3001
UID = 49
YK = {'cari360.view': {'can_view': True}, 'cari360.crm_write': {'can_write': True}}
TEMPLATE = Path(__file__).resolve().parents[2] / 'app' / 'templates' / 'nexgen' / 'cari360_kart.html'


def _schema(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE nexgen_cari (
            id INTEGER PRIMARY KEY, unvan TEXT, cari_kod TEXT, aktif INTEGER DEFAULT 1
        );
        CREATE TABLE cari_sorumlu (
            id INTEGER PRIMARY KEY, cari_id INTEGER, kullanici_id INTEGER,
            sorumluluk_rolu TEXT, aktif INTEGER DEFAULT 1, bitis_tarihi TEXT,
            baslangic_tarihi TEXT, atayan_kullanici_id INTEGER
        );
        CREATE TABLE sistem_kullanici (Id INTEGER PRIMARY KEY, KullaniciAdi TEXT, AdSoyad TEXT);
        CREATE TABLE musteri_operasyon_gorusme (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cari_id INTEGER, kullanici_id INTEGER,
            gorusme_tipi TEXT, sonuc_tipi TEXT, kisa_not TEXT, konu TEXT,
            gorusme_tarihi TEXT, sonraki_aksiyon TEXT, sonraki_takip_tarihi TEXT,
            takip_durumu TEXT, idempotency_key TEXT NOT NULL UNIQUE, aktif INTEGER DEFAULT 1,
            olusturan_kullanici_id INTEGER,
            fiyat_verildi INTEGER DEFAULT 0,
            verilen_fiyat REAL, fiyat_para_birimi TEXT, fiyat_birimi TEXT,
            konusulan_tonaj REAL, odeme_tipi TEXT,
            vade_gun INTEGER, cek_vade_gun INTEGER, cek_adedi INTEGER,
            ticari_not TEXT, cek_notu TEXT
        );
        """
    )
    con.execute('INSERT INTO nexgen_cari VALUES (?,?,?,1)', (CARI_ID, 'Cari360 Ticari', 'C360'))
    con.execute(
        'INSERT INTO cari_sorumlu (cari_id, kullanici_id, sorumluluk_rolu, aktif) VALUES (?,?,?,1)',
        (CARI_ID, UID, 'ANA'),
    )
    con.execute(
        'INSERT INTO sistem_kullanici VALUES (?,?,?)', (UID, 'erhan', 'Erhan Test'),
    )
    con.commit()


def _insert_gorusme(con, **kw) -> int:
    defaults = {
        'cari_id': CARI_ID,
        'kullanici_id': UID,
        'olusturan_kullanici_id': UID,
        'gorusme_tipi': GORUSME_TIPLERI_ALL[0],
        'sonuc_tipi': 'Beklemede',
        'kisa_not': 'test not',
        'konu': None,
        'gorusme_tarihi': '2026-08-10 12:58:00',
        'idempotency_key': 'C360-KEY',
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


class Cari360GorusmeTicariDisplayLockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.con = sqlite3.connect(':memory:')
        self.con.row_factory = sqlite3.Row
        _schema(self.con)

    def tearDown(self) -> None:
        self.con.close()

    @patch('modules.nexgen.mo_gorusme_service.datetime')
    @patch('modules.nexgen.mo_gorusme_service.can_mo_view_cari', return_value=True)
    def test_a_ticari_gorusme_fiyat_ozet_dolu(self, _view, mock_dt) -> None:
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.strptime = datetime.strptime
        _insert_gorusme(
            self.con,
            idempotency_key='C360-A',
            fiyat_verildi=1,
            verilen_fiyat=5.0,
            fiyat_para_birimi='USD',
            fiyat_birimi='KG',
            konusulan_tonaj=100000.0,
            odeme_tipi='NAKIT',
        )
        rows = list_gorusmeler(self.con, CARI_ID, UID, YK)
        self.assertEqual(len(rows), 1)
        oz = rows[0].get('fiyat_ozet')
        self.assertTrue(oz)
        self.assertIn('5', oz)
        self.assertIn('USD', oz)
        self.assertIn('NAKİT', oz)

    @patch('modules.nexgen.mo_gorusme_service.datetime')
    @patch('modules.nexgen.mo_gorusme_service.can_mo_view_cari', return_value=True)
    def test_b_ticari_veri_yok_fiyat_ozet_bos(self, _view, mock_dt) -> None:
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.strptime = datetime.strptime
        _insert_gorusme(self.con, idempotency_key='C360-B', fiyat_verildi=0)
        rows = list_gorusmeler(self.con, CARI_ID, UID, YK)
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0].get('fiyat_ozet'))

    @patch('modules.nexgen.mo_gorusme_service.datetime')
    @patch('modules.nexgen.mo_gorusme_service.can_mo_view_cari', return_value=True)
    def test_c_gorusme_liste_zinciri_korunur(self, _view, mock_dt) -> None:
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.strptime = datetime.strptime
        _insert_gorusme(
            self.con,
            idempotency_key='C360-C',
            kisa_not='adadasda',
            konu='Konu test',
            sonuc_tipi='Beklemede',
            sonraki_aksiyon='adad',
        )
        row = list_gorusmeler(self.con, CARI_ID, UID, YK)[0]
        self.assertTrue(row.get('id'))
        self.assertEqual(row.get('kisa_not'), 'adadasda')
        self.assertEqual(row.get('konu'), 'Konu test')
        self.assertEqual(row.get('sonuc_tipi'), 'Beklemede')
        self.assertEqual(row.get('sonraki_aksiyon'), 'adad')
        self.assertIn('pazarlamaci_adi', row)

    def test_template_fiyat_ozet_render_smoke(self) -> None:
        src = TEMPLATE.read_text(encoding='utf-8')
        idx = src.find('function _gorDetayHtml(g)')
        self.assertGreater(idx, 0, '_gorDetayHtml bulunamadı')
        end = src.find('\n  function _gorPaginationRender', idx)
        self.assertGreater(end, idx, '_gorDetayHtml sonu bulunamadı')
        det = src[idx: end]
        self.assertNotIn('g.fiyat_ozet', det, 'UI eski tek parça fiyat_ozet kullanmamalı')
        for field in (
            'g.verilen_fiyat',
            'g.fiyat_para_birimi',
            'g.fiyat_birimi',
            'g.konusulan_tonaj',
            'g.odeme_tipi',
            'g.vade_gun',
            'g.cek_vade_gun',
            'g.cek_adedi',
            'g.ticari_not',
        ):
            self.assertIn(field, det, msg=f'missing {field} in _gorDetayHtml')
        self.assertIn('formatTonajTr(g.konusulan_tonaj)', det)
        self.assertIn('Ticari bilgi girilmemiş.', det)
        self.assertIn('ckartGorusmeYukle', src)
        self.assertIn('ckart-gorusme-tablo', src)


if __name__ == '__main__':
    unittest.main()
