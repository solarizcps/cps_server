# -*- coding: utf-8 -*-
"""Gelecek tarihli görüşme — write reject + read defensive lock."""
from __future__ import annotations

import os
import sqlite3
import sys
import unittest
from datetime import datetime
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'app'))

from modules.nexgen.mo_ajanda_service import MoAjandaError, ajanda_olustur
from modules.nexgen.mo_gorusme_service import (
    MoGorusmeError,
    _validate_payload,
    gorusme_kaydet,
    list_gorusmeler,
    son_gorusme_ozet_map,
)
from modules.nexgen.musteri_pazarlama_service import ajanda_gorusulmeyen_firmalar

FIXED_NOW = datetime(2026, 8, 10, 12, 0, 0)
CARI_ID = 9001
UID = 49
YK = {'cari360.view': {'can_view': True}, 'cari360.crm_write': {'can_write': True}}


def _gorusme_schema(con: sqlite3.Connection) -> None:
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
            cari_id INTEGER, musteri_aday_id INTEGER, kullanici_id INTEGER,
            kaynak TEXT DEFAULT 'MUSTERI_OPERASYONU',
            gorusme_tipi TEXT, sonuc_tipi TEXT, sonuc_etiketler TEXT,
            kisa_not TEXT, konu TEXT, sonraki_aksiyon TEXT,
            yetkili_id INTEGER, yetkili_metin TEXT,
            gorusme_tarihi TEXT, sonraki_takip_tarihi TEXT, takip_durumu TEXT,
            oncelik TEXT DEFAULT 'NORMAL',
            tahmini_siparis_tutari REAL, tahmini_siparis_tarihi TEXT,
            istenen_vade_gun INTEGER, cek_alim_tarihi TEXT, rakip_firma TEXT,
            makina_notu TEXT, detay_not TEXT, dosya_ref TEXT,
            idempotency_key TEXT NOT NULL UNIQUE, aktif INTEGER DEFAULT 1,
            olusturma_tarihi TEXT, guncelleme_tarihi TEXT,
            olusturan_kullanici_id INTEGER, guncelleyen_kullanici_id INTEGER,
            audit_json TEXT, numune_talep_id INTEGER
        );
        CREATE TABLE musteri_operasyon_ajanda (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cari_id INTEGER NOT NULL, kullanici_id INTEGER NOT NULL,
            plan_tarihi TEXT NOT NULL, gorusme_tipi TEXT NOT NULL, plan_notu TEXT,
            durum TEXT NOT NULL DEFAULT 'PLANLANDI', gorusme_id INTEGER,
            idempotency_key TEXT NOT NULL UNIQUE, aktif INTEGER NOT NULL DEFAULT 1,
            olusturma_tarihi TEXT, guncelleme_tarihi TEXT,
            olusturan_kullanici_id INTEGER NOT NULL
        );
        """
    )
    con.execute('INSERT INTO nexgen_cari (id, unvan, cari_kod) VALUES (?, ?, ?)', (CARI_ID, 'Lock Test', 'LT01'))
    con.execute(
        'INSERT INTO cari_sorumlu (cari_id, kullanici_id, sorumluluk_rolu, aktif) VALUES (?,?,?,1)',
        (CARI_ID, UID, 'ANA'),
    )
    con.execute(
        'INSERT INTO sistem_kullanici (Id, KullaniciAdi, AdSoyad) VALUES (?, ?, ?)',
        (UID, 'erhan', 'Erhan'),
    )
    con.commit()


def _base_payload(**overrides) -> dict:
    p = {
        'cari_id': CARI_ID,
        'gorusme_tipi': 'Telefon',
        'sonuc_tipi': 'Genel Görüşme',
        'kisa_not': 'Test görüşme notu',
        'gorusme_tarihi': '2020-08-09 10:00:00',
        'idempotency_key': 'LOCK-TEST-KEY',
    }
    p.update(overrides)
    return p


class FutureGorusmeTarihLockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.con = sqlite3.connect(':memory:')
        self.con.row_factory = sqlite3.Row
        _gorusme_schema(self.con)

    def tearDown(self) -> None:
        self.con.close()

    @patch('modules.nexgen.mo_gorusme_service.datetime')
    def test_a_future_write_reject(self, mock_dt) -> None:
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.strptime = datetime.strptime
        with self.assertRaises(MoGorusmeError) as ctx:
            _validate_payload(_base_payload(gorusme_tarihi='2026-08-11 09:00:00'))
        self.assertIn('gelecekte', ctx.exception.mesaj.lower())
        before = self.con.execute('SELECT COUNT(*) FROM musteri_operasyon_gorusme').fetchone()[0]
        with self.assertRaises(MoGorusmeError):
            gorusme_kaydet(
                self.con,
                _base_payload(
                    gorusme_tarihi='2026-08-11 09:00:00',
                    idempotency_key='LOCK-FUTURE-1',
                ),
                UID,
                YK,
                commit=True,
            )
        after = self.con.execute('SELECT COUNT(*) FROM musteri_operasyon_gorusme').fetchone()[0]
        self.assertEqual(before, after)

    @patch('modules.nexgen.mo_gorusme_service.can_mo_gorusme_yaz', return_value=True)
    @patch('modules.nexgen.mo_gorusme_service.datetime')
    def test_b_today_past_allowed(self, mock_dt, _yaz) -> None:
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.strptime = datetime.strptime
        norm = _validate_payload(_base_payload(gorusme_tarihi='2026-08-10 11:00:00'))
        self.assertEqual(norm['gorusme_tarihi'], '2026-08-10 11:00:00')
        out = gorusme_kaydet(
            self.con,
            _base_payload(
                gorusme_tarihi='2026-08-09 15:00:00',
                idempotency_key='LOCK-PAST-1',
            ),
            UID,
            YK,
            commit=True,
        )
        self.assertTrue(out.get('id'))

    @patch('modules.nexgen.mo_gorusme_service.datetime')
    def test_c_son_gorusme_ignores_future_legacy(self, mock_dt) -> None:
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.strptime = datetime.strptime
        self.con.execute(
            """
            INSERT INTO musteri_operasyon_gorusme (
                cari_id, kullanici_id, gorusme_tipi, sonuc_tipi, kisa_not,
                gorusme_tarihi, idempotency_key, olusturan_kullanici_id, aktif
            ) VALUES (?,?,?,?,?,?,?,?,1)
            """,
            (CARI_ID, UID, 'Telefon', 'Genel Görüşme', 'gecmis',
             '2020-08-01 10:00:00', 'LEG-PAST', UID),
        )
        self.con.execute(
            """
            INSERT INTO musteri_operasyon_gorusme (
                cari_id, kullanici_id, gorusme_tipi, sonuc_tipi, kisa_not,
                gorusme_tarihi, idempotency_key, olusturan_kullanici_id, aktif
            ) VALUES (?,?,?,?,?,?,?,?,1)
            """,
            (CARI_ID, UID, 'Telefon', 'Genel Görüşme', 'gelecek',
             '2030-08-20 10:00:00', 'LEG-FUTURE', UID),
        )
        self.con.commit()
        m = son_gorusme_ozet_map(self.con, [CARI_ID])
        self.assertIn(CARI_ID, m)
        self.assertEqual((m[CARI_ID].get('gorusme_tarihi') or '')[:10], '2020-08-01')

    @patch('modules.nexgen.mo_gorusme_service.datetime')
    def test_d_cari360_timeline_skips_future(self, mock_dt) -> None:
        """cari360_timeline_service.build_ops_timeline aynı is_gerceklesmis filtresini kullanır."""
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.strptime = datetime.strptime
        from modules.nexgen.mo_gorusme_service import is_gerceklesmis_gorusme_tarihi

        future = {
            'id': 99,
            'gorusme_tarihi': '2030-09-01 10:00:00',
            'kisa_not': 'fut',
        }
        past = {
            'id': 98,
            'gorusme_tarihi': '2020-09-01 10:00:00',
            'kisa_not': 'past',
        }
        gorusme_rows: list[dict] = []
        for d in (future, past):
            if is_gerceklesmis_gorusme_tarihi(d.get('gorusme_tarihi')):
                gorusme_rows.append(d)
        self.assertEqual([x['id'] for x in gorusme_rows], [98])

        self.con.execute(
            """
            INSERT INTO musteri_operasyon_gorusme (
                cari_id, kullanici_id, olusturan_kullanici_id, gorusme_tipi, sonuc_tipi,
                kisa_not, gorusme_tarihi, olusturma_tarihi, aktif, idempotency_key
            ) VALUES (?,?,?,?,?,?,?,?,1,?)
            """,
            (CARI_ID, UID, UID, 'Telefon', 'Genel Görüşme', 'fut',
             '2030-09-01 10:00:00', '2020-01-01 10:00:00', 'TL-FUT'),
        )
        self.con.commit()
        loaded: list[dict] = []
        for r in self.con.execute(
            'SELECT id, gorusme_tarihi FROM musteri_operasyon_gorusme WHERE cari_id=?',
            (CARI_ID,),
        ):
            d = dict(r)
            if is_gerceklesmis_gorusme_tarihi(d.get('gorusme_tarihi')):
                loaded.append(d)
        self.assertEqual(loaded, [])

    @patch('modules.nexgen.mo_gorusme_service.datetime')
    @patch('modules.nexgen.musteri_pazarlama_service.get_musteri_operasyonu_kapsami')
    @patch('modules.nexgen.musteri_pazarlama_service.load_kullanici_yetkileri')
    def test_e_gorusulmeyen_only_future_stays_listed(self, mock_yk, mock_kapsam, mock_dt) -> None:
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.strptime = datetime.strptime
        mock_yk.return_value = YK
        mock_kapsam.return_value = {'cari_id_listesi': [CARI_ID]}
        self.con.execute(
            """
            INSERT INTO musteri_operasyon_gorusme (
                cari_id, kullanici_id, gorusme_tipi, sonuc_tipi, kisa_not,
                gorusme_tarihi, idempotency_key, olusturan_kullanici_id, aktif
            ) VALUES (?,?,?,?,?,?,?,?,1)
            """,
            (CARI_ID, UID, 'Telefon', 'Genel Görüşme', 'sadece gelecek',
             '2030-09-15 10:00:00', 'ONLY-FUTURE', UID),
        )
        self.con.commit()
        listed = ajanda_gorusulmeyen_firmalar(self.con, UID, YK, limit=50)
        ids = [x['cari_id'] for x in listed]
        self.assertIn(CARI_ID, ids)

    @patch('modules.nexgen.mo_ajanda_service.datetime')
    @patch('modules.nexgen.mo_ajanda_service.can_mo_gorusme_yaz', return_value=True)
    @patch('modules.nexgen.mo_ajanda_service.can_mo_view_cari', return_value=True)
    def test_f_ajanda_future_plan_allowed(self, _view, _yaz, mock_dt) -> None:
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.strptime = datetime.strptime
        out = ajanda_olustur(
            self.con,
            {
                'cari_id': CARI_ID,
                'plan_tarihi': '2026-08-15T09:00',
                'gorusme_tipi': 'Telefon',
                'plan_notu': 'gelecek plan',
                'idempotency_key': 'AJANDA-FUTURE-PLAN',
            },
            UID,
            YK,
            commit=True,
        )
        self.assertTrue(out.get('ok'))
        row = self.con.execute(
            'SELECT durum, plan_tarihi FROM musteri_operasyon_ajanda WHERE id=?',
            (out['kayit']['id'],),
        ).fetchone()
        self.assertEqual(row['durum'], 'PLANLANDI')
        self.assertTrue(str(row['plan_tarihi']).startswith('2026-08-15'))

    @patch('modules.nexgen.mo_gorusme_service.datetime')
    def test_list_gorusmeler_skips_future(self, mock_dt) -> None:
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.strptime = datetime.strptime
        self.con.execute(
            """
            INSERT INTO musteri_operasyon_gorusme (
                cari_id, kullanici_id, gorusme_tipi, sonuc_tipi, kisa_not,
                gorusme_tarihi, idempotency_key, olusturan_kullanici_id, aktif
            ) VALUES (?,?,?,?,?,?,?,?,1)
            """,
            (CARI_ID, UID, 'Telefon', 'Genel Görüşme', 'ok',
             '2020-08-05 10:00:00', 'LIST-PAST', UID),
        )
        self.con.execute(
            """
            INSERT INTO musteri_operasyon_gorusme (
                cari_id, kullanici_id, gorusme_tipi, sonuc_tipi, kisa_not,
                gorusme_tarihi, idempotency_key, olusturan_kullanici_id, aktif
            ) VALUES (?,?,?,?,?,?,?,?,1)
            """,
            (CARI_ID, UID, 'Telefon', 'Genel Görüşme', 'skip',
             '2030-12-01 10:00:00', 'LIST-FUTURE', UID),
        )
        self.con.commit()
        with patch('modules.nexgen.mo_gorusme_service.can_mo_view_cari', return_value=True):
            rows = list_gorusmeler(self.con, cari_id=CARI_ID, kullanici_id=UID, yk=YK)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['kisa_not'], 'ok')


if __name__ == '__main__':
    unittest.main()
