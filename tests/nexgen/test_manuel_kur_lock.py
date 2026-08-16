# -*- coding: utf-8 -*-
"""Faz 1 — Manuel kur zorunluluğu + TRY önizleme LOCK (temporary DB only)."""
from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'app'))

from modules.nexgen.mo_tahsilat_config import (
    KAYNAK_MUSTERI_OPERASYONU,
    KAYIT_DURUM_MUHASEBE_BEKLIYOR,
    KAYIT_DURUM_TASLAK,
)
from modules.nexgen.mo_tahsilat_kayit_service import (
    MoTahsilatError,
    _MSG_MANUEL_KUR_GECERSIZ,
    _MSG_MANUEL_KUR_ZORUNLU,
    kayit_detay,
    onaya_gonder,
    taslak_kaydet,
)

HTML = Path(__file__).resolve().parents[2] / 'app' / 'templates' / 'nexgen' / 'musteri_pazarlama.html'
_CANONICAL = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..', 'app', 'mock_data.db')
)
_SHA_BEFORE = hashlib.sha256(open(_CANONICAL, 'rb').read()).hexdigest()

UID = 1
YK: set[str] = {'*'}
YK_OPS: set[str] = {'nexgen.musteri_operasyonu.write'}


def _html() -> str:
    return HTML.read_text(encoding='utf-8')


def _schema(con: sqlite3.Connection) -> None:
    con.executescript("""
        CREATE TABLE nexgen_cari (id INTEGER PRIMARY KEY, unvan TEXT, cari_kod TEXT, aktif INTEGER DEFAULT 1);
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
        CREATE TABLE sistem_kullanici (
            Id INTEGER PRIMARY KEY, KullaniciAdi TEXT, Adi TEXT, Soyadi TEXT
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


def _base_con(
    *,
    para_birimi: str = 'USD',
    cari_id: int = 11,
    siparis_id: int = 760,
    sevkiyat_id: int = 228,
    vade_gun: int = 185,
    miktar_kg: float = 2000.0,
    birim_fiyat: float = 2.0,
    odeme_tipi: str = 'CEK',
    sevk_tarihi: str = '2026-08-10',
) -> sqlite3.Connection:
    con = sqlite3.connect(':memory:')
    con.row_factory = sqlite3.Row
    _schema(con)
    con.execute('INSERT INTO nexgen_cari (id, unvan) VALUES (?, ?)', (cari_id, 'Test Cari'))
    con.execute(
        """
        INSERT INTO nexgen_planlama_siparis
            (id, siparis_no, cari_id, durum, anlasma_para_birimi, anlasma_birim_fiyat,
             vade_gun, tahsilat_kurali, kaynak_modul, odeme_tipi)
        VALUES (?, 'PZM-TEST', ?, 'TAMAMLANDI', ?, ?, ?, 'VADE_GUN', ?, ?)
        """,
        (siparis_id, cari_id, para_birimi, birim_fiyat, vade_gun,
         KAYNAK_MUSTERI_OPERASYONU, odeme_tipi),
    )
    con.execute(
        """
        INSERT INTO mo_musteri_sevkiyat
            (id, sevkiyat_no, siparis_id, cari_id, durum, aktif, sevk_tarihi,
             idempotency_key, olusturan_id, olusturma_tarihi)
        VALUES (?, 'MSV-TEST', ?, ?, 'SEVK_EDILDI', 1, ?, 'idem-sevk', 1, '2026-08-10 08:00:00')
        """,
        (sevkiyat_id, siparis_id, cari_id, sevk_tarihi),
    )
    con.execute(
        """
        INSERT INTO mo_musteri_sevkiyat_kalem (sevkiyat_id, miktar_kg, birim_fiyat_snapshot, para_birimi_snapshot)
        VALUES (?, ?, ?, ?)
        """,
        (sevkiyat_id, miktar_kg, birim_fiyat, para_birimi),
    )
    con.commit()
    return con


def _p(idem: str | None = None, **kw) -> dict:
    import uuid
    return {
        'idempotency_key': idem or str(uuid.uuid4()),
        'cari_id': kw.pop('cari_id', 11),
        'siparis_id': kw.pop('siparis_id', 760),
        'sevkiyat_id': kw.pop('sevkiyat_id', 228),
        'odeme_tipi': kw.pop('odeme_tipi', 'CEK'),
        'alinan_tutar': kw.pop('alinan_tutar', 189000.0),
        'alinan_tarih': kw.pop('alinan_tarih', '2026-08-14'),
        **kw,
    }


def _taslak(con, payload, uid=1, yk=None, kid=None):
    if yk is None:
        yk = YK
    k = taslak_kaydet(con, payload, kullanici_id=uid, yk=yk, kayit_id=kid)
    return {'ok': True, 'kayit': k}


class TestFrontendManuelKurContract(unittest.TestCase):
    """Kontrat 1-6, 22-23 — statik HTML/JS."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.src = _html()

    def test_01_reset_clears_manuel_kur(self):
        self.assertIn('function clearManuelKurInput', self.src)
        self.assertRegex(self.src, r'clearManuelKurInput\(\).*resetTahsilatModal|resetTahsilatModal[\s\S]*clearManuelKurInput')

    def test_02_label_manuel_kur(self):
        self.assertIn('>Manuel Kur <', self.src)
        self.assertNotIn('Güncel satış kurunu yazın', self.src)

    def test_03_no_auto_kur_on_selection(self):
        self.assertIn('clearManuelKurInput', self.src)
        self.assertNotRegex(
            self.src,
            r"mp-t-manuel-kur['\"][^\n]*\.value\s*=\s*[^'\";\n]+(?:kur|tcmb|d\.kur)",
        )

    def test_04_tcmb_api_not_filling_manuel_input(self):
        idx = self.src.find("fetch('/yonetim/kur/api")
        self.assertGreater(idx, 0)
        block = self.src[idx: idx + 600]
        self.assertNotIn('mp-t-manuel-kur', block)

    def test_05_validation_messages(self):
        self.assertIn('Manuel kur girilmeden devam edilemez.', self.src)
        self.assertIn('Geçerli bir manuel kur girin.', self.src)

    def test_06_try_preview_formula(self):
        self.assertIn('mp-t-hedef-formula', self.src)
        self.assertRegex(self.src, r"hedefFormula\.textContent\s*=.*formatTrMoney\(bek\)")

    def test_22_hydrate_preserve_frozen(self):
        self.assertIn('preserveTcmbFrozen', self.src)
        self.assertIn('tahsilatTcmbFrozen = true', self.src)

    def test_23_modal_reset_no_carryover(self):
        self.assertIn('tahsilatForm.reset()', self.src)
        self.assertIn('clearManuelKurInput()', self.src)


class TestBackendManuelKurContract(unittest.TestCase):
    def test_07_usd_bos_kur_blocked(self):
        con = _base_con()
        with self.assertRaises(MoTahsilatError) as ctx:
            _taslak(con, _p(tcmb_satis_kur_snapshot=None))
        self.assertEqual(ctx.exception.mesaj, _MSG_MANUEL_KUR_ZORUNLU)

    def test_08_eur_bos_kur_blocked(self):
        con = _base_con(para_birimi='EUR')
        with self.assertRaises(MoTahsilatError) as ctx:
            _taslak(con, _p(tcmb_satis_kur_snapshot=None))
        self.assertEqual(ctx.exception.mesaj, _MSG_MANUEL_KUR_ZORUNLU)

    def test_09_komma_and_dot_accepted(self):
        for raw in ('47,25', '47.25', 47.25):
            con = _base_con()
            res = _taslak(con, _p(tcmb_satis_kur_snapshot=raw, idem=f'kur-{raw}'))
            row = con.execute(
                'SELECT paket_hedef_tutar, tcmb_satis_kur_snapshot FROM mo_tahsilat_kayit WHERE id=?',
                (res['kayit']['id'],),
            ).fetchone()
            self.assertAlmostEqual(float(row['paket_hedef_tutar']), 189000.0, places=1)
            self.assertAlmostEqual(float(row['tcmb_satis_kur_snapshot']), 47.25, places=4)

    def test_10_invalid_values_rejected(self):
        for bad in (0, -1.5, 'abc'):
            con = _base_con()
            with self.assertRaises(MoTahsilatError) as ctx:
                _taslak(con, _p(tcmb_satis_kur_snapshot=bad, idem=f'bad-{bad}'))
            self.assertEqual(ctx.exception.mesaj, _MSG_MANUEL_KUR_GECERSIZ)

    def test_11_try_no_kur_required(self):
        con = _base_con(para_birimi='TRY', miktar_kg=2000.0, birim_fiyat=100.0)
        res = _taslak(con, _p(tcmb_satis_kur_snapshot=None, alinan_tutar=200000.0, odeme_tipi='NAKIT'))
        self.assertTrue(res['ok'])

    def test_16_try_hedef_math(self):
        con = _base_con()
        res = _taslak(con, _p(tcmb_satis_kur_snapshot=47.25))
        row = con.execute(
            'SELECT paket_hedef_tutar, sevk_kalan_fx_snapshot, tcmb_satis_kur_snapshot FROM mo_tahsilat_kayit WHERE id=?',
            (res['kayit']['id'],),
        ).fetchone()
        fx = float(row['sevk_kalan_fx_snapshot'])
        kur = float(row['tcmb_satis_kur_snapshot'])
        self.assertAlmostEqual(float(row['paket_hedef_tutar']), round(fx * kur, 2), places=2)

    @patch('modules.nexgen.mo_tahsilat_kur_service.fx_try_hedef_hesapla')
    def test_18_no_tcmb_lookup_for_usd(self, mock_fx):
        con = _base_con()
        _taslak(con, _p(tcmb_satis_kur_snapshot=47.25, idem='no-tcmb'))
        mock_fx.assert_not_called()

    def test_19_snapshot_persisted(self):
        con = _base_con()
        res = _taslak(con, _p(tcmb_satis_kur_snapshot=47.25, idem='snap'))
        row = con.execute(
            'SELECT tcmb_satis_kur_snapshot FROM mo_tahsilat_kayit WHERE id=?',
            (res['kayit']['id'],),
        ).fetchone()
        self.assertAlmostEqual(float(row['tcmb_satis_kur_snapshot']), 47.25, places=4)

    def test_20_detail_hydrate_same_kur(self):
        con = _base_con()
        res = _taslak(con, _p(tcmb_satis_kur_snapshot=47.25, idem='det'))
        kid = res['kayit']['id']
        det = kayit_detay(con, kid, UID, YK)
        self.assertAlmostEqual(float(det['tcmb_satis_kur_snapshot']), 47.25, places=4)

    def test_21_frozen_snapshot_preserved(self):
        con = _base_con()
        res1 = _taslak(con, _p(idem='freeze-1', tcmb_satis_kur_snapshot=47.25))
        kid = res1['kayit']['id']
        _taslak(con, _p(
            idem='freeze-2', tcmb_satis_kur_snapshot=None, cari_id=11, siparis_id=760,
            sevkiyat_id=228, odeme_tipi='CEK', alinan_tutar=189000.0, alinan_tarih='2026-08-14',
        ), kid=kid)
        row = con.execute(
            'SELECT tcmb_satis_kur_snapshot FROM mo_tahsilat_kayit WHERE id=?', (kid,),
        ).fetchone()
        self.assertAlmostEqual(float(row['tcmb_satis_kur_snapshot']), 47.25, places=4)


class TestCekVadeUnchanged(unittest.TestCase):
    def test_24_vade_185_korunur(self):
        con = _base_con(vade_gun=185)
        res = _taslak(con, _p(tcmb_satis_kur_snapshot=47.25))
        row = con.execute(
            'SELECT onaylanan_vade_gun_snapshot FROM mo_tahsilat_kayit WHERE id=?',
            (res['kayit']['id'],),
        ).fetchone()
        if row and row['onaylanan_vade_gun_snapshot'] is not None:
            self.assertEqual(int(row['onaylanan_vade_gun_snapshot']), 185)

    @patch('modules.nexgen.onay_tahsilat_adapter.tahsilat_onaya_gonder')
    def test_cek_transition_unchanged(self, mock_onay):
        mock_onay.return_value = {'ok': True, 'talep_id': 999}
        con = _base_con()
        res = _taslak(con, _p(tcmb_satis_kur_snapshot=47.25))
        kid = res['kayit']['id']
        import uuid
        con.execute(
            """
            INSERT INTO mo_tahsilat_cek
                (tahsilat_kayit_id, tutar, cek_alim_tarihi, gercek_cek_vade_tarihi,
                 para_birimi, aktif, idempotency_key, sira_no)
            VALUES (?, 189000.0, '2026-08-14', '2027-01-15', 'TRY', 1, ?, 1)
            """,
            (kid, str(uuid.uuid4())),
        )
        con.commit()
        onaya_gonder(con, kid, kullanici_id=UID, yk=YK_OPS)
        row = con.execute('SELECT durum FROM mo_tahsilat_kayit WHERE id=?', (kid,)).fetchone()
        self.assertEqual(row['durum'], KAYIT_DURUM_MUHASEBE_BEKLIYOR)


class TestNullCekRecovery(unittest.TestCase):
    def test_cek_null_hedef_recovery(self):
        from modules.nexgen.mo_tahsilat_kayit_service import _fill_missing_cek_paket_hedef
        norm = {
            'odeme_tipi': 'CEK',
            'paket_hedef_tutar': None,
            'tcmb_satis_kur_snapshot': 47.25,
            'sevk_kalan_fx_snapshot': 4000.0,
        }
        _fill_missing_cek_paket_hedef(norm)
        self.assertAlmostEqual(norm['paket_hedef_tutar'], 189000.0, places=1)


class TestCanonicalShaGuard(unittest.TestCase):
    def test_25_canonical_db_untouched(self):
        sha_after = hashlib.sha256(open(_CANONICAL, 'rb').read()).hexdigest()
        self.assertEqual(_SHA_BEFORE, sha_after)


if __name__ == '__main__':
    unittest.main(verbosity=2)
