# -*- coding: utf-8 -*-
"""
TAHSILAT-CEK-VADE-LOCK — CEK cek_vade_gun → nexgen_planlama_siparis.vade_gun DB integration.

Isolated in-memory SQLite only. mock_data.db write YASAK.
Çalıştır: python -m unittest tests.nexgen.test_pzm_cek_vade_db_lock -v
"""
from __future__ import annotations

import os
import sqlite3
import sys
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'app'))

from modules.nexgen.pzm_siparis_write import (
    PZM_V2_JSON_PREFIX,
    pzm_v2_header_pack,
    pzm_v2_taslak_kaydet,
)


def _pzm_write_schema(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE nexgen_cari (
            id INTEGER PRIMARY KEY, unvan TEXT, aktif INTEGER DEFAULT 1
        );
        CREATE TABLE nexgen_formul (
            id INTEGER PRIMARY KEY, kod TEXT, ad TEXT, urun_ailesi TEXT,
            durum TEXT, aktif INTEGER DEFAULT 1
        );
        CREATE TABLE nexgen_renk_varyant (
            id INTEGER PRIMARY KEY, formul_id INTEGER, ad TEXT, aktif INTEGER DEFAULT 1
        );
        CREATE TABLE nexgen_uretim_varyant (
            id INTEGER PRIMARY KEY, renk_varyant_id INTEGER, boyut TEXT,
            aktif INTEGER DEFAULT 1, recete_durum TEXT
        );
        CREATE TABLE nexgen_recete_kalem (
            id INTEGER PRIMARY KEY, uretim_varyant_id INTEGER, aktif INTEGER DEFAULT 1
        );
        CREATE TABLE nexgen_rf_renk (
            id INTEGER PRIMARY KEY, rf_kod TEXT, ad TEXT, durum TEXT,
            aktif INTEGER DEFAULT 1, cari_id INTEGER, ilk_talep_cari_id INTEGER,
            kaynak_arge_test_id INTEGER
        );
        CREATE TABLE nexgen_rf_formul_uygunluk (
            id INTEGER PRIMARY KEY, rf_renk_id INTEGER, formul_id INTEGER, aktif INTEGER DEFAULT 1
        );
        CREATE TABLE nexgen_planlama_siparis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            siparis_no TEXT, cari_id INTEGER, cari_unvan TEXT,
            termin_tarihi TEXT, talep_referansi TEXT, durum TEXT, notlar TEXT,
            olusturan_id INTEGER, guncelleme_tarihi TEXT,
            anlasma_para_birimi TEXT, vade_gun INTEGER, anlasma_birim_fiyat REAL,
            odeme_tipi TEXT, odeme_notu TEXT, cek_vadesi TEXT
        );
        CREATE TABLE nexgen_planlama_siparis_kalem (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            planlama_siparis_id INTEGER, sira_no INTEGER, urun_ailesi TEXT,
            formul_id INTEGER, formul_ad TEXT, renk_varyant_id INTEGER, renk_ad TEXT,
            rf_renk_id INTEGER, miktar_l REAL, miktar_s REAL, miktar_m REAL,
            termin_tarihi TEXT, notlar TEXT, birim_fiyat REAL, iskonto_orani REAL,
            iskonto_tutari REAL, net_birim_fiyat REAL, satir_tutari REAL,
            durum TEXT, legacy_kaynak INTEGER DEFAULT 0
        );
        """
    )


def _seed_fixtures(con: sqlite3.Connection) -> dict[str, int]:
    con.execute("INSERT INTO nexgen_cari (id, unvan, aktif) VALUES (1, 'LOCK TEST CARI', 1)")
    con.execute(
        """
        INSERT INTO nexgen_formul (id, kod, ad, urun_ailesi, durum, aktif)
        VALUES (1, '2BA-FL-1828', 'TABAN TEST', 'TABAN', 'AKTIF', 1)
        """
    )
    con.execute(
        "INSERT INTO nexgen_renk_varyant (id, formul_id, ad, aktif) VALUES (1, 1, 'RV1', 1)"
    )
    con.execute(
        """
        INSERT INTO nexgen_uretim_varyant (id, renk_varyant_id, boyut, aktif, recete_durum)
        VALUES (1, 1, 'LARGE', 1, 'URETIME_ACIK')
        """
    )
    con.execute(
        "INSERT INTO nexgen_recete_kalem (id, uretim_varyant_id, aktif) VALUES (1, 1, 1)"
    )
    con.execute(
        """
        INSERT INTO nexgen_rf_renk
            (id, rf_kod, ad, durum, aktif, cari_id, ilk_talep_cari_id, kaynak_arge_test_id)
        VALUES (1, '0677 KIRMIZI', 'Kirmizi', 'ONAYLI', 1, NULL, NULL, NULL)
        """
    )
    con.execute(
        'INSERT INTO nexgen_rf_formul_uygunluk (rf_renk_id, formul_id, aktif) VALUES (1, 1, 1)'
    )
    con.commit()
    return {'cari_id': 1, 'formul_id': 1, 'rf_renk_id': 1}


def _mem_con() -> sqlite3.Connection:
    con = sqlite3.connect(':memory:')
    con.row_factory = sqlite3.Row
    _pzm_write_schema(con)
    return con


def _cek_payload(*, cek_vade_gun: int = 185, talep_id: int | None = None) -> dict:
    termin = (date.today() + timedelta(days=30)).isoformat()
    cek_vadesi = (date.today() + timedelta(days=cek_vade_gun)).isoformat()
    payload = {
        'cari_id': 1,
        'siparis_tarihi': date.today().isoformat(),
        'odeme_tipi': 'CEK',
        'cek_vade_gun': cek_vade_gun,
        'cek_vadesi': cek_vadesi,
        'anlasma_para_birimi': 'USD',
        'kalemler': [{
            'urun_ailesi': 'TABAN',
            'formul_id': 1,
            'rf_renk_id': 1,
            'renk_varyant_id': 1,
            'miktar_l': 50,
            'miktar_s': 0,
            'miktar_m': 0,
            'termin_tarihi': termin,
        }],
    }
    if talep_id is not None:
        payload['talep_id'] = talep_id
    return payload


def _vade_gun_db(con: sqlite3.Connection, ps_id: int) -> int | None:
    row = con.execute(
        'SELECT vade_gun, odeme_tipi FROM nexgen_planlama_siparis WHERE id=?',
        (ps_id,),
    ).fetchone()
    return None if not row else row['vade_gun']


class TestCekVadeDbWriteLock(unittest.TestCase):
    """TAHSILAT-CEK-VADE-LOCK — gerçek pzm_v2_taslak_kaydet write path."""

    def setUp(self) -> None:
        self.con = _mem_con()
        _seed_fixtures(self.con)

    def test_insert_cek_185_vade_gun_canonical(self) -> None:
        """INSERT: CEK cek_vade_gun=185 → nexgen_planlama_siparis.vade_gun=185"""
        result = pzm_v2_taslak_kaydet(self.con, _cek_payload(cek_vade_gun=185), uid=None)
        ps_id = int(result['talep_id'])
        self.assertEqual(_vade_gun_db(self.con, ps_id), 185)
        row = self.con.execute(
            'SELECT odeme_tipi, vade_gun FROM nexgen_planlama_siparis WHERE id=?',
            (ps_id,),
        ).fetchone()
        self.assertEqual(row['odeme_tipi'], 'CEK')
        self.assertEqual(row['vade_gun'], 185)

    def test_update_cek_vade_gun_canonical(self) -> None:
        """UPDATE: mevcut TASLAK CEK kaydında cek_vade_gun değişimi vade_gun'a yansır."""
        ins = pzm_v2_taslak_kaydet(self.con, _cek_payload(cek_vade_gun=185), uid=None)
        ps_id = int(ins['talep_id'])
        self.assertEqual(_vade_gun_db(self.con, ps_id), 185)

        upd = pzm_v2_taslak_kaydet(self.con, _cek_payload(cek_vade_gun=220, talep_id=ps_id), uid=None)
        self.assertEqual(int(upd['talep_id']), ps_id)
        self.assertEqual(_vade_gun_db(self.con, ps_id), 220)

    def test_insert_nakit_vade_gun_zero(self) -> None:
        """NAKIT koruma: vade_gun canonical 0."""
        payload = _cek_payload()
        payload['odeme_tipi'] = 'NAKIT'
        payload.pop('cek_vade_gun', None)
        payload.pop('cek_vadesi', None)
        payload['anlasma_para_birimi'] = 'TRY'
        result = pzm_v2_taslak_kaydet(self.con, payload, uid=None)
        ps_id = int(result['talep_id'])
        self.assertEqual(_vade_gun_db(self.con, ps_id), 0)

    def test_insert_vadeli_vade_gun_preserved(self) -> None:
        """VADELI koruma: girilen vade_gun canonical korunur."""
        payload = _cek_payload()
        payload['odeme_tipi'] = 'VADELI'
        payload['vade_gun'] = 60
        payload.pop('cek_vade_gun', None)
        payload.pop('cek_vadesi', None)
        payload['anlasma_para_birimi'] = 'TRY'
        result = pzm_v2_taslak_kaydet(self.con, payload, uid=None)
        ps_id = int(result['talep_id'])
        self.assertEqual(_vade_gun_db(self.con, ps_id), 60)


if __name__ == '__main__':
    unittest.main(verbosity=2)
