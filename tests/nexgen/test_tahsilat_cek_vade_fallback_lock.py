# -*- coding: utf-8 -*-
"""
Faz — CEK vade canonical fallback LOCK.
Temporary DB only — canonical DB'ye hiçbir write yapılmaz.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'app'))

from modules.nexgen.mo_vade_kontrol_service import _cek_vade_fallback, siparis_vade_baglam
from modules.nexgen.mo_tahsilat_kayit_service import acik_planlar

_CANONICAL = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..', 'app', 'mock_data.db')
)
_SHA_BEFORE = hashlib.sha256(open(_CANONICAL, 'rb').read()).hexdigest()

_PZM_V2_220 = '__PZM_V2__' + json.dumps({
    "v": 2, "anlasma_para_birimi": "USD", "vade_gun": None,
    "odeme_tipi": "CEK", "cek_vade_gun": 220,
    "cek_vadesi": "2026-08-14",
})
_PZM_V2_BAD = '__PZM_V2__{not valid json'
_PZM_V2_ZERO = '__PZM_V2__' + json.dumps({"cek_vade_gun": 0})
_PZM_V2_NEG = '__PZM_V2__' + json.dumps({"cek_vade_gun": -5})
_PZM_V2_STR = '__PZM_V2__' + json.dumps({"cek_vade_gun": "220"})


def _mem_con() -> sqlite3.Connection:
    con = sqlite3.connect(':memory:')
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE nexgen_cari (
            id INTEGER PRIMARY KEY, unvan TEXT, aktif INTEGER DEFAULT 1
        );
        CREATE TABLE nexgen_planlama_siparis (
            id INTEGER PRIMARY KEY,
            siparis_no TEXT,
            cari_id INTEGER,
            cari_unvan TEXT,
            durum TEXT DEFAULT 'TAMAMLANDI',
            anlasma_para_birimi TEXT,
            anlasma_birim_fiyat REAL,
            vade_gun INTEGER,
            odeme_tipi TEXT,
            talep_referansi TEXT,
            tahsilat_kurali TEXT,
            tahsilat_gun_sayisi INTEGER,
            tahsilat_durumu TEXT,
            planlanan_tahsilat_tarihi TEXT,
            kur REAL,
            kur_tarihi TEXT
        );
        CREATE TABLE mo_musteri_sevkiyat (
            id INTEGER PRIMARY KEY,
            siparis_id INTEGER,
            cari_id INTEGER,
            sevkiyat_no TEXT,
            durum TEXT DEFAULT 'SEVK_EDILDI',
            aktif INTEGER DEFAULT 1,
            sevk_tarihi TEXT
        );
        CREATE TABLE mo_musteri_sevkiyat_kalem (
            id INTEGER PRIMARY KEY,
            sevkiyat_id INTEGER,
            miktar_kg REAL,
            birim_fiyat_snapshot REAL,
            para_birimi_snapshot TEXT
        );
    """)
    return con


def _siparis(con, sip_id, *, cari_id=5, odeme='CEK', vade_gun=None,
             talep_ref=None, pb='USD', birim=4.0):
    con.execute(
        """INSERT INTO nexgen_planlama_siparis
           (id, siparis_no, cari_id, cari_unvan, durum, anlasma_para_birimi,
            anlasma_birim_fiyat, vade_gun, odeme_tipi, talep_referansi)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (sip_id, f'PZM-TEST-{sip_id}', cari_id, 'Test Cari', 'TAMAMLANDI',
         pb, birim, vade_gun, odeme, talep_ref),
    )


def _sevk(con, sevk_id, sip_id, cari_id=5, tarih='2026-08-10'):
    con.execute(
        """INSERT INTO mo_musteri_sevkiyat
           (id, siparis_id, cari_id, sevkiyat_no, durum, aktif, sevk_tarihi)
           VALUES (?,?,?,?,?,?,?)""",
        (sevk_id, sip_id, cari_id, f'MSV-TEST-{sevk_id}', 'SEVK_EDILDI', 1, tarih),
    )
    con.execute(
        """INSERT INTO mo_musteri_sevkiyat_kalem
           (sevkiyat_id, miktar_kg, birim_fiyat_snapshot, para_birimi_snapshot)
           VALUES (?,?,?,?)""",
        (sevk_id, 3000.0, 4.0, 'USD'),
    )


# ── Unit: _cek_vade_fallback ──────────────────────────────────────────────

class TestCekVadeFallbackUnit(unittest.TestCase):
    """Kontrat 1–9: _cek_vade_fallback helper."""

    def test_01_cek_kolon_wins_over_json(self):
        # Kolon 185; JSON 220 → kolon kazanır
        ref = '__PZM_V2__' + json.dumps({"cek_vade_gun": 220})
        self.assertEqual(_cek_vade_fallback(185, 'CEK', ref), 185)

    def test_02_cek_kolon_null_json_220(self):
        self.assertEqual(_cek_vade_fallback(None, 'CEK', _PZM_V2_220), 220)

    def test_03_cek_json_string_220(self):
        self.assertEqual(_cek_vade_fallback(None, 'CEK', _PZM_V2_STR), 220)

    def test_04_cek_json_eksik_field(self):
        ref = '__PZM_V2__' + json.dumps({"vade_gun": None})
        self.assertIsNone(_cek_vade_fallback(None, 'CEK', ref))

    def test_05_cek_bozuk_json(self):
        self.assertIsNone(_cek_vade_fallback(None, 'CEK', _PZM_V2_BAD))

    def test_06_cek_json_zero(self):
        self.assertIsNone(_cek_vade_fallback(None, 'CEK', _PZM_V2_ZERO))

    def test_07_cek_json_negatif(self):
        self.assertIsNone(_cek_vade_fallback(None, 'CEK', _PZM_V2_NEG))

    def test_08_nakit_json_ignored(self):
        self.assertIsNone(_cek_vade_fallback(None, 'NAKIT', _PZM_V2_220))

    def test_09_vadeli_json_ignored(self):
        self.assertIsNone(_cek_vade_fallback(None, 'VADELI', _PZM_V2_220))


# ── siparis_vade_baglam ───────────────────────────────────────────────────

class TestSiparisVadeBaglam(unittest.TestCase):
    """Kontrat 11–13."""

    def test_11_onaylanan_vade_220_fallback(self):
        con = _mem_con()
        _siparis(con, 759, vade_gun=None, talep_ref=_PZM_V2_220)
        con.commit()
        b = siparis_vade_baglam(con, 759)
        self.assertEqual(b['onaylanan_vade_gun'], 220)

    def test_12_hedef_vade_hesap(self):
        """Sevk 2026-08-10 + 220 = 2027-03-18 (route tarafından hesaplanır; bağlam 220 taşır)."""
        sevk = date(2026, 8, 10)
        hedef = (sevk + timedelta(days=220)).isoformat()
        self.assertEqual(hedef, '2027-03-18')

    def test_13_kolon_185_korunur(self):
        """PZM-2026-0222 benzeri: vade_gun=185 → kolon kazanır."""
        con = _mem_con()
        _siparis(con, 760, vade_gun=185, talep_ref=_PZM_V2_220)
        con.commit()
        b = siparis_vade_baglam(con, 760)
        self.assertEqual(b['onaylanan_vade_gun'], 185)


# ── acik_planlar ──────────────────────────────────────────────────────────

class TestAcikPlanlarVadeFallback(unittest.TestCase):
    """Kontrat 10, 14."""

    def setUp(self):
        self.con = _mem_con()
        self.con.execute(
            "INSERT INTO nexgen_cari (id, unvan) VALUES (5,'3E Ayakkabi')"
        )
        # Pilot: sip=759, CEK, vade_gun=NULL, cek_vade_gun=220 in JSON
        _siparis(self.con, 759, cari_id=5, odeme='CEK',
                 vade_gun=None, talep_ref=_PZM_V2_220, pb='USD')
        # Sevkiyat
        _sevk(self.con, 227, 759, cari_id=5, tarih='2026-08-10')
        self.con.commit()

    def test_10_acik_planlar_onaylanan_220(self):
        plans = acik_planlar(self.con, cari_ids=[5])
        matched = [p for p in plans if p.get('id') == 759]
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0]['onaylanan_vade_gun'], 220)

    def test_14_eligibility_sevk_kalan_pb_unchanged(self):
        plans = acik_planlar(self.con, cari_ids=[5])
        matched = [p for p in plans if p.get('id') == 759]
        self.assertEqual(len(matched), 1)
        p = matched[0]
        self.assertEqual(p['tahsilat_uygunluk'], 'sevk_yapildi')
        self.assertEqual(p['anlasma_para_birimi'], 'USD')
        self.assertIsNotNone(p['gercek_sevk_tarihi'])

    def test_15_manuel_kur_unchanged(self):
        """acik_planlar sonucunda siparis_kur None (kur kolonu boş fixture); kur davranışı değişmez."""
        plans = acik_planlar(self.con, cari_ids=[5])
        matched = [p for p in plans if p.get('id') == 759]
        self.assertEqual(len(matched), 1)
        # kur alanı None — manuel kur akışı etkilenmemiş
        self.assertIsNone(matched[0].get('siparis_kur'))

    def test_hedef_vade_tarihi_hesaplaniyor(self):
        """acik_planlar hedef_vade_tarihi = 2026-08-10 + 220 = 2027-03-18."""
        plans = acik_planlar(self.con, cari_ids=[5])
        matched = [p for p in plans if p.get('id') == 759]
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0].get('hedef_vade_tarihi'), '2027-03-18')


# ── Canonical SHA guard ───────────────────────────────────────────────────

class TestCanonicalDbSafety(unittest.TestCase):
    def test_sha_unchanged(self):
        sha_after = hashlib.sha256(open(_CANONICAL, 'rb').read()).hexdigest()
        self.assertEqual(sha_after, _SHA_BEFORE,
                         'Canonical DB SHA değişti — write yapılmış olabilir!')


if __name__ == '__main__':
    unittest.main()
