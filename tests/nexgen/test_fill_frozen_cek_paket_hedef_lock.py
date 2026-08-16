# -*- coding: utf-8 -*-
"""
tests/nexgen/test_fill_frozen_cek_paket_hedef_lock.py
======================================================
LOCK tests for _fill_missing_cek_paket_hedef and the full frozen-snapshot
recovery path in mo_tahsilat_kayit_service.

All tests run on isolated in-memory SQLite.
Canonical app/mock_data.db is NEVER touched.
"""
from __future__ import annotations

import hashlib
import math
import os
import sqlite3
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'app'))

from modules.nexgen.mo_tahsilat_config import (
    KAYNAK_MUSTERI_OPERASYONU,
    KAYIT_DURUM_MUHASEBE_BEKLIYOR,
    KAYIT_DURUM_TASLAK,
)
from modules.nexgen.mo_tahsilat_kayit_service import (
    MoTahsilatError,
    _fill_missing_cek_paket_hedef,
    onaya_gonder,
    taslak_kaydet,
)

# ---------------------------------------------------------------------------
# Canonical SHA guard
# ---------------------------------------------------------------------------
_CANONICAL = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..', 'app', 'mock_data.db')
)
_SHA_BEFORE = hashlib.sha256(open(_CANONICAL, 'rb').read()).hexdigest()

UID = 1
YK_ALL: set[str] = {'*'}
YK_OPS: set[str] = {'nexgen.musteri_operasyonu.write'}  # no muhasebe yetki

REAL_KUR = 47.25
REAL_FX = 4000.0
REAL_BEKLENEN = 189000.0
REAL_VADE = 185
REAL_SEVK = '2026-08-10'
REAL_KUR_TARIHI = '2026-08-01'


# ---------------------------------------------------------------------------
# Unit tests — _fill_missing_cek_paket_hedef (no DB needed)
# ---------------------------------------------------------------------------

class TestFillHelperUnit(unittest.TestCase):
    """Direct unit tests for _fill_missing_cek_paket_hedef."""

    def _norm(self, **kw) -> dict:
        base = {
            'odeme_tipi': 'CEK',
            'paket_hedef_tutar': None,
            'tcmb_satis_kur_snapshot': REAL_KUR,
            'sevk_kalan_fx_snapshot': REAL_FX,
        }
        base.update(kw)
        return base

    # 1. CEK + NULL → 189000
    def test_01_cek_null_hedef_frozen_fx_kur(self):
        norm = self._norm()
        _fill_missing_cek_paket_hedef(norm)
        self.assertEqual(norm['paket_hedef_tutar'], REAL_BEKLENEN)

    # 2. CEK + mevcut hedef=189000 → overwrite edilmez
    def test_02_cek_dolu_hedef_not_overwritten(self):
        norm = self._norm(paket_hedef_tutar=189000.0)
        _fill_missing_cek_paket_hedef(norm)
        self.assertEqual(norm['paket_hedef_tutar'], 189000.0)

    # 3. CEK + farklı dolu hedef → aynen korunur
    def test_03_cek_different_hedef_preserved(self):
        norm = self._norm(paket_hedef_tutar=99999.0)
        _fill_missing_cek_paket_hedef(norm)
        self.assertEqual(norm['paket_hedef_tutar'], 99999.0)

    # 4. CEK + kur=None → hedef NULL kalır
    def test_04_cek_kur_none_no_fill(self):
        norm = self._norm(tcmb_satis_kur_snapshot=None)
        _fill_missing_cek_paket_hedef(norm)
        self.assertIsNone(norm['paket_hedef_tutar'])

    # 5. CEK + FX=None → hedef NULL kalır
    def test_05_cek_fx_none_no_fill(self):
        norm = self._norm(sevk_kalan_fx_snapshot=None)
        _fill_missing_cek_paket_hedef(norm)
        self.assertIsNone(norm['paket_hedef_tutar'])

    # 6. CEK + kur negatif → recovery yapılmaz
    def test_06_cek_negative_kur_no_fill(self):
        norm = self._norm(tcmb_satis_kur_snapshot=-1.0)
        _fill_missing_cek_paket_hedef(norm)
        self.assertIsNone(norm['paket_hedef_tutar'])

    # 7. CEK + FX negatif → recovery yapılmaz
    def test_07_cek_negative_fx_no_fill(self):
        norm = self._norm(sevk_kalan_fx_snapshot=-1.0)
        _fill_missing_cek_paket_hedef(norm)
        self.assertIsNone(norm['paket_hedef_tutar'])

    # 8a. CEK + kur=Infinity → recovery yapılmaz
    def test_08a_cek_inf_kur_no_fill(self):
        norm = self._norm(tcmb_satis_kur_snapshot=math.inf)
        _fill_missing_cek_paket_hedef(norm)
        self.assertIsNone(norm['paket_hedef_tutar'])

    # 8b. CEK + kur=NaN → recovery yapılmaz
    def test_08b_cek_nan_kur_no_fill(self):
        norm = self._norm(tcmb_satis_kur_snapshot=math.nan)
        _fill_missing_cek_paket_hedef(norm)
        self.assertIsNone(norm['paket_hedef_tutar'])

    # 8c. CEK + geçersiz string kur → recovery yapılmaz
    def test_08c_cek_invalid_string_kur_no_fill(self):
        norm = self._norm(tcmb_satis_kur_snapshot='INVALID')
        _fill_missing_cek_paket_hedef(norm)
        self.assertIsNone(norm['paket_hedef_tutar'])

    # 9. NAKIT + aynı snapshot → paket hedef üretilmez
    def test_09_nakit_no_paket_hedef(self):
        norm = self._norm(odeme_tipi='NAKIT')
        _fill_missing_cek_paket_hedef(norm)
        self.assertIsNone(norm['paket_hedef_tutar'])

    # 10. VADELI + aynı snapshot → paket hedef üretilmez
    def test_10_vadeli_no_paket_hedef(self):
        norm = self._norm(odeme_tipi='VADELI')
        _fill_missing_cek_paket_hedef(norm)
        self.assertIsNone(norm['paket_hedef_tutar'])

    # 11. Frozen snapshot alanları değişmez
    def test_11_frozen_snapshot_fields_unchanged(self):
        norm = self._norm(kur_tarihi_snapshot=REAL_KUR_TARIHI)
        _fill_missing_cek_paket_hedef(norm)
        self.assertEqual(norm['tcmb_satis_kur_snapshot'], REAL_KUR)
        self.assertEqual(norm['sevk_kalan_fx_snapshot'], REAL_FX)
        self.assertEqual(norm['kur_tarihi_snapshot'], REAL_KUR_TARIHI)

    # CEK + FX=0 → hedef=0 (0 × kur = 0 iş kuralı, geçerli contract)
    def test_fx_zero_gives_zero_hedef(self):
        norm = self._norm(sevk_kalan_fx_snapshot=0.0)
        _fill_missing_cek_paket_hedef(norm)
        self.assertEqual(norm['paket_hedef_tutar'], 0.0)

    # Canonical rounding: 3 × 47.25 = 141.75
    def test_rounding_canonical(self):
        norm = self._norm(sevk_kalan_fx_snapshot=3.0, tcmb_satis_kur_snapshot=47.25)
        _fill_missing_cek_paket_hedef(norm)
        self.assertEqual(norm['paket_hedef_tutar'], 141.75)


# ---------------------------------------------------------------------------
# Isolated DB helpers (reuse schema from previous proof test)
# ---------------------------------------------------------------------------

def _schema(con: sqlite3.Connection) -> None:
    con.executescript("""
        CREATE TABLE nexgen_cari (id INTEGER PRIMARY KEY, unvan TEXT, aktif INTEGER DEFAULT 1);
        CREATE TABLE nexgen_planlama_siparis (
            id INTEGER PRIMARY KEY, siparis_no TEXT, cari_id INTEGER, durum TEXT,
            anlasma_para_birimi TEXT, anlasma_birim_fiyat REAL, vade_gun INTEGER,
            tahsilat_kurali TEXT, kaynak_modul TEXT, tahsilat_durumu TEXT,
            guncelleme_tarihi TEXT, talep_referansi TEXT, kur REAL, kur_tarihi TEXT,
            odeme_tipi TEXT, cek_vadesi TEXT
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
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kayit_kodu TEXT, cari_id INTEGER, siparis_id INTEGER, sevkiyat_id INTEGER,
            kaynak_modul TEXT, beklenen_tutar REAL, beklenen_tahmini INTEGER,
            paket_hedef_tutar REAL, alinan_tutar REAL, kalan_tutar REAL,
            planlanan_tahsilat_tarihi TEXT, alinan_tarih TEXT,
            odeme_tipi TEXT, odeme_referansi TEXT, kismi_mi INTEGER,
            aciklama TEXT, dosya_ref TEXT, onay_notu TEXT, durum TEXT,
            cari_entegrasyon_durumu TEXT, idempotency_key TEXT UNIQUE,
            olusturan_id INTEGER, onaylayan_id INTEGER, aktif INTEGER DEFAULT 1,
            olusturma_tarihi TEXT, guncelleme_tarihi TEXT, audit_json TEXT,
            revizyon_gerekce TEXT, para_birimi TEXT,
            onaylanan_vade_gun_snapshot INTEGER,
            gercek_sevk_tarihi_snapshot TEXT, hedef_vade_tarihi TEXT,
            sevk_hedef_tutar_snapshot REAL, sevk_para_birimi_snapshot TEXT,
            sevk_kalan_fx_snapshot REAL, tcmb_satis_kur_snapshot REAL,
            kur_tarihi_snapshot TEXT
        );
        CREATE TABLE mo_tahsilat_cek (
            id INTEGER PRIMARY KEY AUTOINCREMENT, tahsilat_kayit_id INTEGER,
            tutar REAL, cek_alim_tarihi TEXT, gercek_cek_vade_tarihi TEXT,
            para_birimi TEXT, aktif INTEGER DEFAULT 1,
            idempotency_key TEXT UNIQUE, sira_no INTEGER
        );
    """)


def _base_con(*, usd_tarih: str | None = None, usd_kur: float = 47.25,
              cari_id: int = 11, siparis_id: int = 760,
              sevkiyat_id: int = 228, vade_gun: int = 185) -> sqlite3.Connection:
    con = sqlite3.connect(':memory:')
    con.row_factory = sqlite3.Row
    _schema(con)
    con.execute('INSERT INTO nexgen_cari (id, unvan) VALUES (?, ?)', (cari_id, 'Test Cari'))
    con.execute(
        """
        INSERT INTO nexgen_planlama_siparis
            (id, siparis_no, cari_id, durum, anlasma_para_birimi, anlasma_birim_fiyat,
             vade_gun, tahsilat_kurali, kaynak_modul, odeme_tipi)
        VALUES (?, 'PZM-TEST', ?, 'TAMAMLANDI', 'USD', 2.0, ?, 'VADE_GUN', ?, 'CEK')
        """,
        (siparis_id, cari_id, vade_gun, KAYNAK_MUSTERI_OPERASYONU),
    )
    con.execute(
        """
        INSERT INTO mo_musteri_sevkiyat
            (id, sevkiyat_no, siparis_id, cari_id, durum, aktif, sevk_tarihi,
             idempotency_key, olusturan_id, olusturma_tarihi)
        VALUES (?, 'MSV-TEST', ?, ?, 'SEVK_EDILDI', 1, ?, 'idem-sevk', 1, '2026-08-10 08:00:00')
        """,
        (sevkiyat_id, siparis_id, cari_id, REAL_SEVK),
    )
    con.execute(
        """
        INSERT INTO mo_musteri_sevkiyat_kalem (sevkiyat_id, miktar_kg, birim_fiyat_snapshot, para_birimi_snapshot)
        VALUES (?, 2000.0, 2.0, 'USD')
        """,
        (sevkiyat_id,),
    )
    if usd_tarih:
        con.execute(
            'INSERT INTO sistem_kur (Tarih, ParaBirimi, Alis, Satis, MerkezKur) VALUES (?,?,?,?,?)',
            (usd_tarih, 'USD', usd_kur - 0.5, usd_kur, 99.99),
        )
    con.commit()
    return con


def _insert_frozen_draft(con, *, kayit_id=165, idem='test-frozen-idem',
                         paket_hedef=None, cari_id=11, siparis_id=760, sevkiyat_id=228,
                         tcmb_kur=REAL_KUR, fx_kalan=REAL_FX, kur_tarihi=REAL_KUR_TARIHI,
                         beklenen=REAL_BEKLENEN, vade_gun=REAL_VADE):
    con.execute(
        """
        INSERT INTO mo_tahsilat_kayit (
            id, kayit_kodu, cari_id, siparis_id, sevkiyat_id, kaynak_modul,
            beklenen_tutar, beklenen_tahmini, paket_hedef_tutar,
            alinan_tutar, kalan_tutar, alinan_tarih, odeme_tipi,
            kismi_mi, durum, cari_entegrasyon_durumu, idempotency_key,
            olusturan_id, aktif, olusturma_tarihi, guncelleme_tarihi,
            para_birimi, onaylanan_vade_gun_snapshot, gercek_sevk_tarihi_snapshot,
            hedef_vade_tarihi, sevk_hedef_tutar_snapshot, sevk_para_birimi_snapshot,
            sevk_kalan_fx_snapshot, tcmb_satis_kur_snapshot, kur_tarihi_snapshot
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            kayit_id, f'MO-T-TEST-{kayit_id:04d}', cari_id, siparis_id, sevkiyat_id,
            KAYNAK_MUSTERI_OPERASYONU, beklenen, 0, paket_hedef,
            None, beklenen, '2026-08-10', 'CEK',
            0, KAYIT_DURUM_TASLAK, 'BEKLIYOR', idem,
            UID, 1, '2026-08-10 09:11:45', '2026-08-10 09:11:53',
            'TRY', vade_gun, REAL_SEVK,
            '2027-02-11', fx_kalan, 'USD',
            fx_kalan, tcmb_kur, kur_tarihi,
        ),
    )
    con.commit()


# ---------------------------------------------------------------------------
# Integration tests using isolated DB + taslak_kaydet
# ---------------------------------------------------------------------------

class TestFrozenDraftRecoveryIntegration(unittest.TestCase):
    """Integration tests — full service path through taslak_kaydet."""

    def _run_recovery(self, con, idem, kayit_id=165):
        payload = {
            'idempotency_key': idem,
            'cari_id': 11,
            'siparis_id': 760,
            'sevkiyat_id': 228,
            'odeme_tipi': 'CEK',
            'alinan_tarih': '2026-08-10',
        }
        return taslak_kaydet(con, payload, UID, YK_ALL, kayit_id=kayit_id)

    # 12. USD=0 + existing frozen draft → recovery PASS
    def test_12_usd_zero_frozen_draft_recovery_pass(self):
        con = _base_con()  # no USD row
        _insert_frozen_draft(con, paket_hedef=None)
        usd_count = con.execute("SELECT COUNT(*) FROM sistem_kur WHERE ParaBirimi='USD'").fetchone()[0]
        self.assertEqual(usd_count, 0)
        result = self._run_recovery(con, 'test-frozen-idem')
        self.assertEqual(float(result['paket_hedef_tutar']), REAL_BEKLENEN)
        self.assertEqual(float(result['tcmb_satis_kur_snapshot']), REAL_KUR)
        self.assertEqual(result['kur_tarihi_snapshot'], REAL_KUR_TARIHI)
        self.assertEqual(float(result['beklenen_tutar']), REAL_BEKLENEN)

    # 13. Yeni draft + USD=0 → hata, partial row yok
    def test_13_new_draft_usd_zero_error_no_partial(self):
        con = _base_con()
        payload = {
            'idempotency_key': 'new-draft-no-usd',
            'cari_id': 11,
            'siparis_id': 760,
            'sevkiyat_id': 228,
            'odeme_tipi': 'CEK',
            'alinan_tarih': '2026-08-10',
        }
        with self.assertRaises(MoTahsilatError):
            taslak_kaydet(con, payload, UID, YK_ALL)
        count = con.execute('SELECT COUNT(*) FROM mo_tahsilat_kayit').fetchone()[0]
        self.assertEqual(count, 0)

    # 14. CEK vade_gun=185 korunur
    def test_14_cek_vade_185_preserved(self):
        con = _base_con(usd_tarih='2026-08-10')
        payload = {
            'idempotency_key': 'new-cek-vade-lock',
            'cari_id': 11,
            'siparis_id': 760,
            'sevkiyat_id': 228,
            'odeme_tipi': 'CEK',
            'alinan_tarih': '2026-08-10',
            'tcmb_satis_kur_snapshot': REAL_KUR,
        }
        result = taslak_kaydet(con, payload, UID, YK_ALL)
        self.assertEqual(result['onaylanan_vade_gun_snapshot'], REAL_VADE)

    # 15. Recovered hedef _cek_onay_validate tarafından kabul edilir
    @patch('modules.nexgen.onay_tahsilat_adapter.tahsilat_onaya_gonder')
    def test_15_recovered_hedef_accepted_by_validate(self, mock_onay):
        mock_onay.return_value = {'ok': True, 'talep_id': 1}
        con = _base_con()
        _insert_frozen_draft(con, paket_hedef=None)
        self._run_recovery(con, 'test-frozen-idem')
        # add cek row
        con.execute(
            """
            INSERT INTO mo_tahsilat_cek
                (tahsilat_kayit_id, tutar, cek_alim_tarihi, gercek_cek_vade_tarihi,
                 para_birimi, aktif, idempotency_key, sira_no)
            VALUES (165, 189000, '2026-08-10', '2027-02-11', 'TRY', 1, 'cek-t15', 1)
            """
        )
        con.commit()
        result = onaya_gonder(con, 165, UID, YK_OPS)
        self.assertTrue(result.get('ok'))

    # 16. Aktif çek satırı yoksa validation FAIL
    @patch('modules.nexgen.onay_tahsilat_adapter.tahsilat_onaya_gonder')
    def test_16_no_cek_row_validation_fail(self, mock_onay):
        mock_onay.return_value = {'ok': True, 'talep_id': 1}
        con = _base_con()
        _insert_frozen_draft(con, paket_hedef=None)
        self._run_recovery(con, 'test-frozen-idem')
        with self.assertRaises(MoTahsilatError) as ctx:
            onaya_gonder(con, 165, UID, YK_OPS)
        self.assertIn('çek', ctx.exception.mesaj.lower())

    # 17. Aktif çek satırı varsa TASLAK → MUHASEBE_ONAY_BEKLIYOR
    @patch('modules.nexgen.onay_tahsilat_adapter.tahsilat_onaya_gonder')
    def test_17_with_cek_row_state_transition(self, mock_onay):
        mock_onay.return_value = {'ok': True, 'talep_id': 1}
        con = _base_con()
        _insert_frozen_draft(con, paket_hedef=None)
        self._run_recovery(con, 'test-frozen-idem')
        con.execute(
            """
            INSERT INTO mo_tahsilat_cek
                (tahsilat_kayit_id, tutar, cek_alim_tarihi, gercek_cek_vade_tarihi,
                 para_birimi, aktif, idempotency_key, sira_no)
            VALUES (165, 189000, '2026-08-10', '2027-02-11', 'TRY', 1, 'cek-t17', 1)
            """
        )
        con.commit()
        onaya_gonder(con, 165, UID, YK_OPS)
        row = con.execute('SELECT durum FROM mo_tahsilat_kayit WHERE id=165').fetchone()
        self.assertEqual(row['durum'], KAYIT_DURUM_MUHASEBE_BEKLIYOR)

    # Dolu paket_hedef→ overwrite edilmez (full service path)
    def test_nooverwrite_existing_hedef_full_path(self):
        con = _base_con()
        _insert_frozen_draft(con, paket_hedef=99000.0)
        result = self._run_recovery(con, 'test-frozen-idem')
        self.assertEqual(float(result['paket_hedef_tutar']), 99000.0)

    # Canonical snapshot değerleri korunur (service path sonrası)
    def test_frozen_snapshot_values_preserved_after_service(self):
        con = _base_con()
        _insert_frozen_draft(con, paket_hedef=None)
        result = self._run_recovery(con, 'test-frozen-idem')
        self.assertEqual(float(result['tcmb_satis_kur_snapshot']), REAL_KUR)
        self.assertEqual(result['kur_tarihi_snapshot'], REAL_KUR_TARIHI)
        self.assertEqual(float(result['sevk_kalan_fx_snapshot']), REAL_FX)


# ---------------------------------------------------------------------------
# Canonical SHA guard
# ---------------------------------------------------------------------------

class TestCanonicalUnchanged(unittest.TestCase):
    def test_sha_unchanged(self):
        sha_after = hashlib.sha256(open(_CANONICAL, 'rb').read()).hexdigest()
        self.assertEqual(_SHA_BEFORE, sha_after, f"CANONICAL DB CHANGED!\n{_SHA_BEFORE}\n{sha_after}")


if __name__ == '__main__':
    unittest.main(verbosity=2)
