# -*- coding: utf-8 -*-
"""Gerçek Görüşme → Ajanda Canonical Sync — Regression Lock Tests (A-I)."""
from __future__ import annotations

import os
import sqlite3
import sys
import unittest
from datetime import datetime
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'app'))

from modules.nexgen.mo_ajanda_service import (
    MoAjandaError,
    ajanda_tamamla,
    gercek_gorusmeyi_ajandaya_bagla,
)
from modules.nexgen.mo_gorusme_config import GORUSME_TIPLERI_ALL

FIXED_NOW = datetime(2026, 8, 10, 12, 0, 0)
CARI_A = 1001
CARI_B = 1002
UID_ERHAN = 49
UID_OTHER = 50
YK = {'cari360.view': {'can_view': True}, 'cari360.crm_write': {'can_write': True}}

GORUSME_TARIHI_TODAY = '2026-08-10 10:45:00'
GORUSME_TARIHI_FUTURE = '2026-08-15 09:00:00'


def _build_schema(con: sqlite3.Connection) -> None:
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
    con.execute('INSERT INTO nexgen_cari VALUES (?,?,?,1)', (CARI_A, 'Test A', 'A001'))
    con.execute('INSERT INTO nexgen_cari VALUES (?,?,?,1)', (CARI_B, 'Test B', 'B001'))
    con.execute(
        'INSERT INTO cari_sorumlu (cari_id, kullanici_id, sorumluluk_rolu, aktif) VALUES (?,?,?,1)',
        (CARI_A, UID_ERHAN, 'ANA'),
    )
    con.execute(
        'INSERT INTO sistem_kullanici VALUES (?,?,?)', (UID_ERHAN, 'erhan', 'Erhan Test')
    )
    con.commit()


def _insert_ajanda(
    con: sqlite3.Connection,
    cari_id: int,
    kullanici_id: int,
    plan_tarihi: str,
    durum: str = 'PLANLANDI',
    gorusme_id: int | None = None,
    idem: str | None = None,
) -> int:
    _idem = idem or f'TEST-AJ-{cari_id}-{kullanici_id}-{plan_tarihi}'
    con.execute(
        """
        INSERT INTO musteri_operasyon_ajanda
          (cari_id, kullanici_id, plan_tarihi, gorusme_tipi, durum, gorusme_id,
           idempotency_key, aktif, olusturan_kullanici_id, olusturma_tarihi)
        VALUES (?,?,?,?,?,?,?,1,?,?)
        """,
        (cari_id, kullanici_id, plan_tarihi, GORUSME_TIPLERI_ALL[0],
         durum, gorusme_id, _idem, kullanici_id, '2026-08-10 08:00:00'),
    )
    con.commit()
    return con.execute('SELECT last_insert_rowid()').fetchone()[0]


def _insert_gorusme(
    con: sqlite3.Connection,
    cari_id: int,
    kullanici_id: int,
    gorusme_tarihi: str,
    idem: str,
) -> int:
    con.execute(
        """
        INSERT INTO musteri_operasyon_gorusme
          (cari_id, kullanici_id, gorusme_tipi, sonuc_tipi, kisa_not,
           gorusme_tarihi, idempotency_key, olusturan_kullanici_id, aktif)
        VALUES (?,?,?,?,?,?,?,?,1)
        """,
        (cari_id, kullanici_id, GORUSME_TIPLERI_ALL[0], 'Genel Görüşme', 'sync test',
         gorusme_tarihi, idem, kullanici_id),
    )
    con.commit()
    return con.execute('SELECT last_insert_rowid()').fetchone()[0]


class AjandaCanonicalSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.con = sqlite3.connect(':memory:')
        self.con.row_factory = sqlite3.Row
        _build_schema(self.con)

    def tearDown(self) -> None:
        self.con.close()

    # -----------------------------------------------------------------------
    # A) PLAN VAR — mevcut PLANLANDI tamamlanmalı, yeni satır oluşmamalı
    # -----------------------------------------------------------------------
    def test_a_plan_var_tamamlandi(self) -> None:
        aj_id = _insert_ajanda(self.con, CARI_A, UID_ERHAN, '2026-08-10 09:00:00')
        gor_id = _insert_gorusme(self.con, CARI_A, UID_ERHAN, GORUSME_TARIHI_TODAY, 'A-GOR-1')

        result = gercek_gorusmeyi_ajandaya_bagla(
            self.con, gor_id, UID_ERHAN, GORUSME_TARIHI_TODAY, cari_id=CARI_A
        )
        self.assertEqual(result['durum'], 'plan_tamamlandi')
        self.assertEqual(result['ajanda_id'], aj_id)

        row = self.con.execute(
            'SELECT durum, gorusme_id FROM musteri_operasyon_ajanda WHERE id=?', (aj_id,)
        ).fetchone()
        self.assertEqual(row['durum'], 'GERCEKLESTI')
        self.assertEqual(int(row['gorusme_id']), gor_id)

        count = self.con.execute(
            'SELECT COUNT(*) FROM musteri_operasyon_ajanda WHERE cari_id=? AND kullanici_id=?',
            (CARI_A, UID_ERHAN),
        ).fetchone()[0]
        self.assertEqual(count, 1)

    # -----------------------------------------------------------------------
    # B) PLAN YOK — tek GERCEKLESTI adhoc kayıt oluşmalı
    # -----------------------------------------------------------------------
    def test_b_plan_yok_adhoc_olusturuldu(self) -> None:
        gor_id = _insert_gorusme(self.con, CARI_A, UID_ERHAN, GORUSME_TARIHI_TODAY, 'B-GOR-1')

        result = gercek_gorusmeyi_ajandaya_bagla(
            self.con, gor_id, UID_ERHAN, GORUSME_TARIHI_TODAY, cari_id=CARI_A
        )
        self.assertEqual(result['durum'], 'adhoc_olusturuldu')
        new_id = result['ajanda_id']

        row = self.con.execute(
            'SELECT durum, gorusme_id FROM musteri_operasyon_ajanda WHERE id=?', (new_id,)
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row['durum'], 'GERCEKLESTI')
        self.assertEqual(int(row['gorusme_id']), gor_id)

    # -----------------------------------------------------------------------
    # C) DUPLICATE LOCK — aynı gorusme_id ikinci kez sync → idempotent
    # -----------------------------------------------------------------------
    def test_c_duplicate_lock_idempotent(self) -> None:
        gor_id = _insert_gorusme(self.con, CARI_A, UID_ERHAN, GORUSME_TARIHI_TODAY, 'C-GOR-1')

        r1 = gercek_gorusmeyi_ajandaya_bagla(
            self.con, gor_id, UID_ERHAN, GORUSME_TARIHI_TODAY, cari_id=CARI_A
        )
        count_before = self.con.execute(
            'SELECT COUNT(*) FROM musteri_operasyon_ajanda'
        ).fetchone()[0]

        r2 = gercek_gorusmeyi_ajandaya_bagla(
            self.con, gor_id, UID_ERHAN, GORUSME_TARIHI_TODAY, cari_id=CARI_A
        )
        count_after = self.con.execute(
            'SELECT COUNT(*) FROM musteri_operasyon_ajanda'
        ).fetchone()[0]

        self.assertEqual(r2['durum'], 'idempotent')
        self.assertEqual(r2['ajanda_id'], r1['ajanda_id'])
        self.assertEqual(count_before, count_after)

    # -----------------------------------------------------------------------
    # D) BAŞKA CARİ — başka cari planı eşleşmez
    # -----------------------------------------------------------------------
    def test_d_baska_cari_eslesmez(self) -> None:
        _insert_ajanda(self.con, CARI_B, UID_ERHAN, '2026-08-10 09:00:00', idem='D-AJ-CARIB')
        gor_id = _insert_gorusme(self.con, CARI_A, UID_ERHAN, GORUSME_TARIHI_TODAY, 'D-GOR-CARIA')

        result = gercek_gorusmeyi_ajandaya_bagla(
            self.con, gor_id, UID_ERHAN, GORUSME_TARIHI_TODAY, cari_id=CARI_A
        )
        # CARI_B planı eşleşmez → adhoc
        self.assertEqual(result['durum'], 'adhoc_olusturuldu')

        cari_b_row = self.con.execute(
            'SELECT durum, gorusme_id FROM musteri_operasyon_ajanda WHERE cari_id=?', (CARI_B,)
        ).fetchone()
        self.assertEqual(cari_b_row['durum'], 'PLANLANDI')
        self.assertIsNone(cari_b_row['gorusme_id'])

    # -----------------------------------------------------------------------
    # E) BAŞKA KULLANICI — başka kullanıcının planı eşleşmez
    # -----------------------------------------------------------------------
    def test_e_baska_kullanici_eslesmez(self) -> None:
        _insert_ajanda(self.con, CARI_A, UID_OTHER, '2026-08-10 09:00:00', idem='E-AJ-OTHER')
        gor_id = _insert_gorusme(self.con, CARI_A, UID_ERHAN, GORUSME_TARIHI_TODAY, 'E-GOR-ERHAN')

        result = gercek_gorusmeyi_ajandaya_bagla(
            self.con, gor_id, UID_ERHAN, GORUSME_TARIHI_TODAY, cari_id=CARI_A
        )
        self.assertEqual(result['durum'], 'adhoc_olusturuldu')

        other_row = self.con.execute(
            'SELECT durum, gorusme_id FROM musteri_operasyon_ajanda WHERE kullanici_id=?',
            (UID_OTHER,),
        ).fetchone()
        self.assertEqual(other_row['durum'], 'PLANLANDI')
        self.assertIsNone(other_row['gorusme_id'])

    # -----------------------------------------------------------------------
    # F) İPTAL — iptal plan gerçek görüşmeyle tamamlanmaz → adhoc oluşur
    # -----------------------------------------------------------------------
    def test_f_iptal_plan_eslesmez(self) -> None:
        _insert_ajanda(
            self.con, CARI_A, UID_ERHAN, '2026-08-10 09:00:00',
            durum='IPTAL', idem='F-AJ-IPTAL',
        )
        gor_id = _insert_gorusme(self.con, CARI_A, UID_ERHAN, GORUSME_TARIHI_TODAY, 'F-GOR-1')

        result = gercek_gorusmeyi_ajandaya_bagla(
            self.con, gor_id, UID_ERHAN, GORUSME_TARIHI_TODAY, cari_id=CARI_A
        )
        self.assertEqual(result['durum'], 'adhoc_olusturuldu')

        iptal_row = self.con.execute(
            "SELECT durum FROM musteri_operasyon_ajanda WHERE durum='IPTAL'"
        ).fetchone()
        self.assertIsNotNone(iptal_row)
        self.assertEqual(iptal_row['durum'], 'IPTAL')

    # -----------------------------------------------------------------------
    # G) GELECEK PLAN — gelecek günün planı bugünkü görüşmeye eşleşmez
    # -----------------------------------------------------------------------
    def test_g_gelecek_plan_eslesmez(self) -> None:
        _insert_ajanda(
            self.con, CARI_A, UID_ERHAN, '2026-08-15 09:00:00', idem='G-AJ-FUTURE'
        )
        gor_id = _insert_gorusme(self.con, CARI_A, UID_ERHAN, GORUSME_TARIHI_TODAY, 'G-GOR-TODAY')

        result = gercek_gorusmeyi_ajandaya_bagla(
            self.con, gor_id, UID_ERHAN, GORUSME_TARIHI_TODAY, cari_id=CARI_A
        )
        self.assertEqual(result['durum'], 'adhoc_olusturuldu')

        future_row = self.con.execute(
            "SELECT durum FROM musteri_operasyon_ajanda WHERE idempotency_key='G-AJ-FUTURE'"
        ).fetchone()
        self.assertEqual(future_row['durum'], 'PLANLANDI')

    # -----------------------------------------------------------------------
    # H) Mevcut explicit ajanda_id akışı bozulmaz — ajanda_tamamla doğrudan
    # -----------------------------------------------------------------------
    @patch('modules.nexgen.mo_ajanda_service.can_mo_view_cari', return_value=True)
    @patch('modules.nexgen.mo_ajanda_service.can_mo_gorusme_yaz', return_value=True)
    def test_h_explicit_ajanda_id_flow_unchanged(self, _yaz, _view) -> None:
        aj_id = _insert_ajanda(self.con, CARI_A, UID_ERHAN, '2026-08-10 09:00:00', idem='H-AJ')
        gor_id = _insert_gorusme(self.con, CARI_A, UID_ERHAN, GORUSME_TARIHI_TODAY, 'H-GOR')

        # Explicit flow: ajanda_tamamla doğrudan çağrılır (musteri_pazarlama_ajanda akışı)
        ajanda_tamamla(
            self.con, aj_id, gor_id, UID_ERHAN, CARI_A, YK, commit=True
        )

        row = self.con.execute(
            'SELECT durum, gorusme_id FROM musteri_operasyon_ajanda WHERE id=?', (aj_id,)
        ).fetchone()
        self.assertEqual(row['durum'], 'GERCEKLESTI')
        self.assertEqual(int(row['gorusme_id']), gor_id)

        # İkinci kez ajanda_tamamla → 404 hatası (PLANLANDI kayıt artık yok)
        with self.assertRaises(MoAjandaError) as ctx:
            ajanda_tamamla(self.con, aj_id, gor_id + 1, UID_ERHAN, CARI_A, YK, commit=True)
        self.assertEqual(ctx.exception.kod, 404)

    # -----------------------------------------------------------------------
    # I) Cari360 regression — gorusme_id zaten bağlıysa helper idempotent
    # -----------------------------------------------------------------------
    def test_i_cari360_gorusme_idempotent_sync(self) -> None:
        gor_id = _insert_gorusme(self.con, CARI_A, UID_ERHAN, GORUSME_TARIHI_TODAY, 'I-GOR')

        r1 = gercek_gorusmeyi_ajandaya_bagla(
            self.con, gor_id, UID_ERHAN, GORUSME_TARIHI_TODAY, cari_id=CARI_A
        )
        r2 = gercek_gorusmeyi_ajandaya_bagla(
            self.con, gor_id, UID_ERHAN, GORUSME_TARIHI_TODAY, cari_id=CARI_A
        )

        self.assertEqual(r2['durum'], 'idempotent')
        self.assertEqual(r1['ajanda_id'], r2['ajanda_id'])

        count = self.con.execute('SELECT COUNT(*) FROM musteri_operasyon_ajanda').fetchone()[0]
        self.assertEqual(count, 1)


if __name__ == '__main__':
    unittest.main()
