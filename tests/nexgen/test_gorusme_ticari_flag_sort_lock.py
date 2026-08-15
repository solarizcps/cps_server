# -*- coding: utf-8 -*-
"""Görüşme ticari flag koruması + tarih sıralama regression LOCK."""
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
from modules.nexgen.mo_gorusme_service import (
    MoGorusmeError,
    _TICARI_FLAG_REQUIRED_MSG,
    _payload_has_ticari_input,
    _validate_fiyat_snapshot,
    acik_takip_sayisi,
    fiyat_ozet_metin,
    format_tr_tonaj,
    list_gorusmeler,
    list_gorusmeler_paginated,
)

FIXED_NOW = datetime(2026, 8, 15, 18, 0, 0)
CARI_ID = 9009
UID = 1
YK = {'cari360.view': {'can_view': True}, 'cari360.crm_write': {'can_write': True}}
MO_TPL = Path(__file__).resolve().parents[2] / 'app' / 'templates' / 'nexgen' / 'musteri_pazarlama.html'
SVC_TPL = Path(__file__).resolve().parents[2] / 'app' / 'modules' / 'nexgen' / 'mo_gorusme_service.py'


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
    con.execute('INSERT INTO nexgen_cari VALUES (?,?,?,1)', (CARI_ID, 'SEHA Test', 'SEHA'))
    con.execute(
        'INSERT INTO cari_sorumlu (cari_id, kullanici_id, sorumluluk_rolu, aktif) VALUES (?,?,?,1)',
        (CARI_ID, UID, 'ANA'),
    )
    con.execute('INSERT INTO sistem_kullanici VALUES (?,?,?)', (UID, 'admin', 'Admin'))
    con.commit()


def _insert(con, **kw) -> int:
    defaults = {
        'cari_id': CARI_ID,
        'kullanici_id': UID,
        'olusturan_kullanici_id': UID,
        'gorusme_tipi': GORUSME_TIPLERI_ALL[0],
        'sonuc_tipi': 'Tamamlandı',
        'kisa_not': 'not',
        'gorusme_tarihi': '2026-08-10 12:00:00',
        'idempotency_key': 'K-DFLT',
        'fiyat_verildi': 0,
        'takip_durumu': None,
        'sonraki_takip_tarihi': None,
    }
    defaults.update(kw)
    cols = ', '.join(defaults.keys())
    ph = ', '.join('?' * len(defaults))
    con.execute(f'INSERT INTO musteri_operasyon_gorusme ({cols}) VALUES ({ph})', tuple(defaults.values()))
    con.commit()
    return con.execute('SELECT last_insert_rowid()').fetchone()[0]


def _full_snap(**kw):
    base = {
        'fiyat_verildi': 1,
        'verilen_fiyat': 5,
        'fiyat_para_birimi': 'USD',
        'fiyat_birimi': 'KG',
        'odeme_tipi': 'NAKIT',
        'konusulan_tonaj': 10000,
    }
    base.update(kw)
    return base


class TicariPayloadDetectTests(unittest.TestCase):
    def test_detect_fields(self) -> None:
        self.assertTrue(_payload_has_ticari_input({'verilen_fiyat': '5'}))
        self.assertTrue(_payload_has_ticari_input({'fiyat_para_birimi': 'USD'}))
        self.assertTrue(_payload_has_ticari_input({'konusulan_tonaj': '10000'}))
        self.assertTrue(_payload_has_ticari_input({'konusulan_tonaj': '10.000'}))
        self.assertTrue(_payload_has_ticari_input({'odeme_tipi': 'NAKIT'}))
        self.assertTrue(_payload_has_ticari_input({'ticari_not': 'eva'}))
        self.assertFalse(_payload_has_ticari_input({'fiyat_verildi': 0}))


class TicariFlagBackendTests(unittest.TestCase):
    def test_flag_false_empty_snapshot(self) -> None:
        snap = _validate_fiyat_snapshot({'fiyat_verildi': 0})
        self.assertEqual(snap['fiyat_verildi'], 0)
        self.assertIsNone(snap['verilen_fiyat'])
        self.assertIsNone(snap['konusulan_tonaj'])

    def test_flag_false_dolu_fiyat_400(self) -> None:
        with self.assertRaises(MoGorusmeError) as ctx:
            _validate_fiyat_snapshot({'fiyat_verildi': 0, 'verilen_fiyat': 5})
        self.assertIn('Fiyat verildi', ctx.exception.mesaj)

    def test_flag_false_dolu_para_400(self) -> None:
        with self.assertRaises(MoGorusmeError):
            _validate_fiyat_snapshot({'fiyat_verildi': 0, 'fiyat_para_birimi': 'USD'})

    def test_flag_false_dolu_tonaj_400(self) -> None:
        with self.assertRaises(MoGorusmeError):
            _validate_fiyat_snapshot({'fiyat_verildi': 0, 'konusulan_tonaj': 10000})

    def test_flag_false_dolu_odeme_400(self) -> None:
        with self.assertRaises(MoGorusmeError):
            _validate_fiyat_snapshot({'fiyat_verildi': 0, 'odeme_tipi': 'NAKIT'})

    def test_flag_true_full_snapshot(self) -> None:
        snap = _validate_fiyat_snapshot(_full_snap())
        self.assertEqual(snap['fiyat_verildi'], 1)
        self.assertEqual(snap['verilen_fiyat'], 5.0)
        self.assertEqual(snap['konusulan_tonaj'], 10000.0)
        self.assertEqual(snap['fiyat_para_birimi'], 'USD')

    def test_flag_true_tonaj_tr_strings(self) -> None:
        snap = _validate_fiyat_snapshot(_full_snap(konusulan_tonaj='10.000'))
        self.assertEqual(snap['konusulan_tonaj'], 10000.0)

    def test_flag_true_missing_fiyat_400(self) -> None:
        with self.assertRaises(MoGorusmeError):
            _validate_fiyat_snapshot(_full_snap(verilen_fiyat=None))

    def test_message_constant(self) -> None:
        self.assertIn('Fiyat verildi', _TICARI_FLAG_REQUIRED_MSG)


class GorusmeSortTests(unittest.TestCase):
    def setUp(self) -> None:
        self.con = sqlite3.connect(':memory:')
        self.con.row_factory = sqlite3.Row
        _schema(self.con)
        self.old_acik = _insert(
            self.con,
            idempotency_key='SEHA-652',
            gorusme_tarihi='2026-08-10 12:58:00',
            takip_durumu='ACIK',
            sonraki_takip_tarihi='2026-08-27',
            fiyat_verildi=1,
            verilen_fiyat=5,
            fiyat_para_birimi='USD',
            fiyat_birimi='KG',
            konusulan_tonaj=100000,
            odeme_tipi='NAKIT',
        )
        self.new_norm = _insert(
            self.con,
            idempotency_key='SEHA-659',
            gorusme_tarihi='2026-08-15 18:52:00',
            takip_durumu=None,
            fiyat_verildi=0,
        )

    def tearDown(self) -> None:
        self.con.close()

    @patch('modules.nexgen.mo_gorusme_service.datetime')
    @patch('modules.nexgen.mo_gorusme_service.can_mo_view_cari', return_value=True)
    def test_list_newer_above_old_acik(self, _view, mock_dt) -> None:
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.strptime = datetime.strptime
        rows = list_gorusmeler(self.con, CARI_ID, UID, YK)
        ids = [r['id'] for r in rows]
        self.assertEqual(ids[0], self.new_norm)
        self.assertEqual(ids[1], self.old_acik)

    @patch('modules.nexgen.mo_gorusme_service.datetime')
    @patch('modules.nexgen.mo_gorusme_service.can_mo_view_cari', return_value=True)
    def test_paginated_same_order(self, _view, mock_dt) -> None:
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.strptime = datetime.strptime
        paged = list_gorusmeler_paginated(self.con, CARI_ID, UID, YK, page=1, page_size=10)
        ids = [r['id'] for r in paged['items']]
        self.assertEqual(ids[0], self.new_norm)
        self.assertEqual(ids[1], self.old_acik)

    @patch('modules.nexgen.mo_gorusme_service.datetime')
    @patch('modules.nexgen.mo_gorusme_service.can_mo_view_cari', return_value=True)
    def test_acik_badge_data_preserved(self, _view, mock_dt) -> None:
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.strptime = datetime.strptime
        rows = list_gorusmeler(self.con, CARI_ID, UID, YK)
        old = next(r for r in rows if r['id'] == self.old_acik)
        self.assertEqual(old['takip_durumu'], 'ACIK')
        self.assertEqual(old['sonraki_takip_tarihi'], '2026-08-27')
        self.assertEqual(acik_takip_sayisi(self.con, CARI_ID), 1)

    def test_same_date_higher_id_first(self) -> None:
        a = _insert(self.con, idempotency_key='D-A', gorusme_tarihi='2026-08-15 10:00:00')
        b = _insert(self.con, idempotency_key='D-B', gorusme_tarihi='2026-08-15 10:00:00')
        rows = self.con.execute(
            'SELECT id FROM musteri_operasyon_gorusme WHERE cari_id=? ORDER BY gorusme_tarihi DESC, id DESC',
            (CARI_ID,),
        ).fetchall()
        ids = [r[0] for r in rows]
        self.assertLess(ids.index(b), ids.index(a))


class TicariFlagTemplateLockTests(unittest.TestCase):
    def test_frontend_auto_flag_helpers(self) -> None:
        src = MO_TPL.read_text(encoding='utf-8')
        self.assertIn('function hasMeaningfulTicariFormInput', src)
        self.assertIn('function syncFiyatVerildiFromTicariFields', src)
        self.assertIn('syncFiyatVerildiFromTicariFields();', src)
        self.assertIn("'odeme_tipi','vade_gun'", src)

    def test_order_by_no_acik_priority(self) -> None:
        src = SVC_TPL.read_text(encoding='utf-8')
        self.assertNotIn("CASE WHEN g.takip_durumu='ACIK' THEN 0", src)

    def test_tonaj_display_unchanged(self) -> None:
        self.assertEqual(format_tr_tonaj(10000), '10.000')
        oz = fiyat_ozet_metin(_full_snap())
        self.assertIn('10.000 ton', oz or '')
        self.assertIn('5 USD/KG', oz or '')


if __name__ == '__main__':
    unittest.main()
