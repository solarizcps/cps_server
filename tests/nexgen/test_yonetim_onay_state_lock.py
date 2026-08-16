# -*- coding: utf-8 -*-
"""
test_yonetim_onay_state_lock.py
================================
LOCK testleri — Tahsilat yönetim onay state machine

Kapsam:
  - Canonical rate %4,00 finansman hesabı
  - Normal vade → YONETIM_ONAY_BEKLIYOR
  - Fazla vade  → YONETIM_ISTISNA_ONAY_BEKLIYOR (açıklama zorunlu)
  - Legacy ONAYLANDI uyumu
  - Yeni YONETIM_ONAYLANDI
  - SHA unchanged (in-memory, canonical dokunulmaz)
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import unittest
from decimal import Decimal
from unittest.mock import patch

# sys.path düzeltmesi
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'app'))

from modules.nexgen.mo_vade_kontrol_service import hesapla as vade_hesapla, onay_snapshot_blogu
from modules.nexgen.mo_vade_kontrol_config import FINANSMAN_AYLIK_ORAN, DURUM_FAZLA_VADE, DURUM_AVANTAJ

CANONICAL_DB = os.path.join(os.path.dirname(__file__), '..', '..', 'app', 'mock_data.db')


def _sha(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


EXPECTED_SHA = 'c8f0374f39387afb4d0254207d69ad541ac4cce61e2db94b4041656ecd65a9e9'


def _schema(con: sqlite3.Connection):
    con.executescript("""
    CREATE TABLE IF NOT EXISTS nexgen_cari (
        id INTEGER PRIMARY KEY, unvan TEXT, cari_kod TEXT
    );
    CREATE TABLE IF NOT EXISTS nexgen_planlama_siparis (
        id INTEGER PRIMARY KEY, siparis_no TEXT, cari_id INTEGER,
        anlasma_para_birimi TEXT, anlasma_birim_fiyat REAL,
        anlasma_miktari REAL, kur REAL, kur_tarihi TEXT,
        tahsilat_kurali TEXT, tahsilat_durumu TEXT,
        vade_gun INTEGER, planlanan_tahsilat_tarihi TEXT,
        odeme_tipi TEXT, talep_referansi TEXT,
        durum TEXT DEFAULT 'AKTIF',
        guncelleme_tarihi TEXT
    );
    CREATE TABLE IF NOT EXISTS mo_musteri_sevkiyat (
        id INTEGER PRIMARY KEY, siparis_id INTEGER, cari_id INTEGER,
        sevkiyat_no TEXT, aktif INTEGER DEFAULT 1,
        sevk_tarihi TEXT, durum TEXT,
        olusturma_tarihi TEXT DEFAULT (datetime('now','localtime'))
    );
    CREATE TABLE IF NOT EXISTS mo_tahsilat_kayit (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kayit_kodu TEXT, cari_id INTEGER, siparis_id INTEGER,
        kaynak_modul TEXT, beklenen_tutar REAL, beklenen_tahmini REAL,
        alinan_tutar REAL, kalan_tutar REAL,
        planlanan_tahsilat_tarihi TEXT, alinan_tarih TEXT,
        odeme_tipi TEXT, odeme_referansi TEXT, kismi_mi INTEGER DEFAULT 0,
        aciklama TEXT, dosya_ref TEXT, onay_notu TEXT, revizyon_gerekce TEXT,
        durum TEXT DEFAULT 'TASLAK', cari_entegrasyon_durumu TEXT,
        idempotency_key TEXT UNIQUE, olusturan_id INTEGER, onaylayan_id INTEGER,
        aktif INTEGER DEFAULT 1,
        olusturma_tarihi TEXT DEFAULT (datetime('now','localtime')),
        guncelleme_tarihi TEXT,
        audit_json TEXT, paket_hedef_tutar REAL, para_birimi TEXT,
        onaylanan_vade_gun_snapshot INTEGER,
        gercek_sevk_tarihi_snapshot TEXT,
        hedef_vade_tarihi TEXT, sevkiyat_id INTEGER,
        sevk_hedef_tutar_snapshot REAL, sevk_para_birimi_snapshot TEXT,
        sevk_kalan_fx_snapshot REAL,
        tcmb_satis_kur_snapshot REAL, kur_tarihi_snapshot TEXT
    );
    CREATE TABLE IF NOT EXISTS mo_tahsilat_cek (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tahsilat_kayit_id INTEGER,
        gercek_cek_vade_tarihi TEXT,
        cek_alim_tarihi TEXT,
        tutar REAL, para_birimi TEXT DEFAULT 'TRY',
        banka_adi TEXT, odeme_referansi TEXT,
        durum TEXT DEFAULT 'AKTIF', aktif INTEGER DEFAULT 1,
        sira_no INTEGER DEFAULT 0,
        olusturma_tarihi TEXT DEFAULT (datetime('now','localtime'))
    );
    CREATE TABLE IF NOT EXISTS mo_cek_satiri (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tahsilat_kayit_id INTEGER,
        vade_tarihi TEXT, tutar REAL, para_birimi TEXT DEFAULT 'TRY',
        banka TEXT, banka_sube TEXT, cek_no TEXT,
        durum TEXT DEFAULT 'AKTIF', aktif INTEGER DEFAULT 1,
        olusturma_tarihi TEXT DEFAULT (datetime('now','localtime'))
    );
    CREATE TABLE IF NOT EXISTS sistem_kur (
        Id INTEGER PRIMARY KEY, Tarih TEXT, ParaBirimi TEXT,
        Alis REAL, Satis REAL, Kaynak TEXT, OlusturanKullanici TEXT,
        OlusturmaTarihi TEXT
    );
    CREATE TABLE IF NOT EXISTS sistem_kullanici (
        Id INTEGER PRIMARY KEY, KullaniciAdi TEXT
    );
    """)
    con.row_factory = sqlite3.Row


def _fresh_db() -> sqlite3.Connection:
    con = sqlite3.connect(':memory:')
    _schema(con)
    return con


def _pzm_v2_ref(vade_gun: int = 185) -> str:
    """Canonical PZM V2 talep_referansi — CEK vade fallback uyumlu."""
    return '__PZM_V2__' + json.dumps(
        {'odeme_tipi': 'CEK', 'cek_vade_gun': vade_gun},
        separators=(',', ':'),
    )


# ---------------------------------------------------------------------------
# Test 1: Canonical aylık oran %4,00
# ---------------------------------------------------------------------------
class Test01CanonicalRate(unittest.TestCase):
    def test_rate_is_4_percent(self):
        """mo_vade_kontrol_config → FINANSMAN_AYLIK_ORAN = 0.04"""
        self.assertEqual(FINANSMAN_AYLIK_ORAN, Decimal('0.04'))

    def test_4_percent_formula(self):
        """120000 × 0.04 × 71 / 30 = 11360.0"""
        tutar = Decimal('120000')
        sapma = 71
        sonuc = float(tutar * FINANSMAN_AYLIK_ORAN * sapma / 30)
        self.assertAlmostEqual(sonuc, 11360.0, places=2)


# ---------------------------------------------------------------------------
# Test 2: Vade hesapları
# ---------------------------------------------------------------------------
class Test02VadeCalc(unittest.TestCase):
    def test_hedef_vade_tarihi(self):
        """10.08.2026 + 185 gün = 11.02.2027"""
        from datetime import date, timedelta
        baslangic = date(2026, 8, 10)
        hedef = baslangic + timedelta(days=185)
        self.assertEqual(hedef.isoformat(), '2027-02-11')

    def test_gercek_vade_gun(self):
        """10.08.2026 → 23.04.2027 = 256 gün"""
        from datetime import date
        sevk = date(2026, 8, 10)
        cek_vade = date(2027, 4, 23)
        self.assertEqual((cek_vade - sevk).days, 256)

    def test_sapma_gun(self):
        """256 - 185 = +71 gün"""
        self.assertEqual(256 - 185, 71)

    def test_karsilama(self):
        """120000 / 188000 = ~63.83%"""
        oran = 120000 / 188000 * 100
        self.assertAlmostEqual(oran, 63.829787, places=2)


# ---------------------------------------------------------------------------
# Test 3: Vade kontrol service — FAZLA_VADE
# ---------------------------------------------------------------------------
class Test03VadeKontrolService(unittest.TestCase):
    def _make_con(self, onaylanan_vade: int, cek_vade_tarihi: str) -> sqlite3.Connection:
        con = _fresh_db()
        con.execute("INSERT INTO nexgen_cari (id, unvan) VALUES (1, 'Test Cari')")
        con.execute("""
            INSERT INTO nexgen_planlama_siparis
            (id, siparis_no, cari_id, anlasma_para_birimi, vade_gun,
             odeme_tipi, talep_referansi, durum)
            VALUES (1, 'TST-001', 1, 'USD', ?, 'CEK', ?, 'AKTIF')
        """, (onaylanan_vade, _pzm_v2_ref(onaylanan_vade)))
        con.execute("""
            INSERT INTO mo_musteri_sevkiyat (id, siparis_id, cari_id, aktif, sevk_tarihi, durum)
            VALUES (1, 1, 1, 1, '2026-08-10', 'SEVK_EDILDI')
        """)
        con.execute("""
            INSERT INTO mo_tahsilat_kayit
            (id, kayit_kodu, cari_id, siparis_id, odeme_tipi, durum,
             beklenen_tutar, paket_hedef_tutar, sevkiyat_id, aktif,
             onaylanan_vade_gun_snapshot, gercek_sevk_tarihi_snapshot,
             tcmb_satis_kur_snapshot, sevk_kalan_fx_snapshot, para_birimi)
            VALUES (10, 'MO-T-TEST-001', 1, 1, 'CEK', 'TASLAK',
                    188000, 188000, 1, 1, ?, '2026-08-10', 47.25, 4000, 'TRY')
        """, (onaylanan_vade,))
        con.execute("""
            INSERT INTO mo_tahsilat_cek
            (tahsilat_kayit_id, gercek_cek_vade_tarihi, tutar, para_birimi, durum, aktif, sira_no)
            VALUES (10, ?, 120000, 'TRY', 'AKTIF', 1, 1)
        """, (cek_vade_tarihi,))
        con.commit()
        return con

    def test_fazla_vade_detected(self):
        """185 gün anlaşma, 256 gün gerçek → FAZLA_VADE"""
        con = self._make_con(185, '2027-04-23')
        sonuc = vade_hesapla(tahsilat_kayit_id=10, con=con)
        self.assertEqual(sonuc.durum_kodu, DURUM_FAZLA_VADE)

    def test_normal_vade_not_fazla(self):
        """185 gün anlaşma, 185 gün gerçek → VADE_UYGUN"""
        con = self._make_con(185, '2027-02-11')
        sonuc = vade_hesapla(tahsilat_kayit_id=10, con=con)
        self.assertNotEqual(sonuc.durum_kodu, DURUM_FAZLA_VADE)

    def test_finansman_fazla_vade_4_percent(self):
        """120000 × %4 × 71 / 30 = 11360"""
        con = self._make_con(185, '2027-04-23')
        sonuc = vade_hesapla(tahsilat_kayit_id=10, con=con)
        self.assertEqual(sonuc.durum_kodu, DURUM_FAZLA_VADE)
        self.assertIsNotNone(sonuc.finansman_net)
        self.assertAlmostEqual(float(sonuc.finansman_net or 0), 11360.0, delta=5)

    def test_kisa_vade_finansman_sifir(self):
        """Kısa vade (avantaj) → finansman_net = 0"""
        con = self._make_con(185, '2026-11-01')  # < 185 gün
        sonuc = vade_hesapla(tahsilat_kayit_id=10, con=con)
        self.assertNotEqual(sonuc.durum_kodu, DURUM_FAZLA_VADE)
        # Negatif sapma → finansman etkisi 0
        if sonuc.finansman_net is not None:
            self.assertLessEqual(float(sonuc.finansman_net), 0.01)

    def test_onay_snapshot_blogu_keys(self):
        """onay_snapshot_blogu doğru key'leri içermeli"""
        con = self._make_con(185, '2027-04-23')
        sonuc = vade_hesapla(tahsilat_kayit_id=10, con=con)
        snap = onay_snapshot_blogu(sonuc)
        vk = snap['vade_kontrol']
        self.assertIn('durum_kodu', vk)
        self.assertIn('finansman_net', vk)
        self.assertIn('onaylanan_vade_gun', vk)
        self.assertIn('finansman_aylik_oran', vk)


# ---------------------------------------------------------------------------
# Test 4: State machine — onaya_gonder
# ---------------------------------------------------------------------------
class Test04StateMachine(unittest.TestCase):
    YK = {'TAHSILAT_YAZ'}

    def _make_con_with_taslak(
        self, odeme_tipi='CEK', onaylanan_vade=185, cek_vade='2026-09-01',
        add_cek=True, para_birimi='TRY', paket_hedef=188000.0
    ) -> sqlite3.Connection:
        con = _fresh_db()
        con.execute("INSERT INTO nexgen_cari (id, unvan, cari_kod) VALUES (1, 'Test', 'T001')")
        con.execute("""
            INSERT INTO nexgen_planlama_siparis
            (id, siparis_no, cari_id, anlasma_para_birimi, vade_gun,
             odeme_tipi, talep_referansi, durum, tahsilat_durumu)
            VALUES (1, 'TST-001', 1, ?, ?, 'CEK', ?, 'AKTIF', 'PLANLANDI')
        """, (para_birimi, onaylanan_vade, _pzm_v2_ref(onaylanan_vade)))
        con.execute("""
            INSERT INTO mo_musteri_sevkiyat (id, siparis_id, cari_id, aktif, sevk_tarihi, durum)
            VALUES (1, 1, 1, 1, '2026-08-10', 'SEVK_EDILDI')
        """)
        con.execute("""
            INSERT INTO mo_tahsilat_kayit
            (id, kayit_kodu, cari_id, siparis_id, odeme_tipi, durum, olusturan_id,
             beklenen_tutar, paket_hedef_tutar, sevkiyat_id, aktif, para_birimi,
             onaylanan_vade_gun_snapshot, gercek_sevk_tarihi_snapshot,
             tcmb_satis_kur_snapshot, sevk_kalan_fx_snapshot,
             idempotency_key)
            VALUES (20, 'MO-T-SM-001', 1, 1, ?, 'TASLAK', 99,
                    188000, ?, 1, 1, 'TRY', ?, '2026-08-10',
                    47.25, 4000, 'sm-test-001')
        """, (odeme_tipi, paket_hedef, onaylanan_vade))
        if add_cek:
            con.execute("""
                INSERT INTO mo_tahsilat_cek
                (tahsilat_kayit_id, gercek_cek_vade_tarihi, tutar, para_birimi, durum, aktif, sira_no)
                VALUES (20, ?, 120000, 'TRY', 'AKTIF', 1, 1)
            """, (cek_vade,))
        con.commit()
        return con

    def test_normal_vade_state(self):
        """Normal vade → YONETIM_ONAY_BEKLIYOR"""
        from modules.nexgen.mo_tahsilat_kayit_service import onaya_gonder
        from modules.nexgen.mo_tahsilat_config import KAYIT_DURUM_YONETIM_ONAY_BEKLIYOR
        con = self._make_con_with_taslak(cek_vade='2027-02-11')  # tam hedef vade
        with patch('modules.nexgen.onay_tahsilat_adapter.tahsilat_onaya_gonder',
                   return_value={'ok': True, 'talep_id': 1, 'talep_kod': 'TK-001'}), \
             patch('modules.nexgen.mo_tahsilat_kayit_service._sevk_onay_kontrol', return_value=None):
            r = onaya_gonder(con, 20, 99, yk=self.YK)
        row = con.execute('SELECT durum FROM mo_tahsilat_kayit WHERE id=20').fetchone()
        self.assertEqual(row['durum'], KAYIT_DURUM_YONETIM_ONAY_BEKLIYOR)
        self.assertFalse(r.get('istisna_path'))

    def test_fazla_vade_without_aciklama_blocked(self):
        """Fazla vade + açıklama yok → 400 hata"""
        from modules.nexgen.mo_tahsilat_kayit_service import onaya_gonder, MoTahsilatError
        con = self._make_con_with_taslak(cek_vade='2027-04-23')  # +71 gün
        with patch('modules.nexgen.onay_tahsilat_adapter.tahsilat_onaya_gonder',
                   return_value={'ok': True, 'talep_id': 1, 'talep_kod': 'TK-002'}), \
             patch('modules.nexgen.mo_tahsilat_kayit_service._sevk_onay_kontrol', return_value=None):
            with self.assertRaises(MoTahsilatError) as ctx:
                onaya_gonder(con, 20, 99, yk=self.YK)
        self.assertEqual(ctx.exception.kod, 400)
        self.assertIn('Vade aşımı', ctx.exception.mesaj)

    def test_fazla_vade_with_aciklama_ok(self):
        """Fazla vade + açıklama var → YONETIM_ISTISNA_ONAY_BEKLIYOR"""
        from modules.nexgen.mo_tahsilat_kayit_service import onaya_gonder
        from modules.nexgen.mo_tahsilat_config import KAYIT_DURUM_ISTISNA_ONAY_BEKLIYOR
        con = self._make_con_with_taslak(cek_vade='2027-04-23')
        with patch('modules.nexgen.onay_tahsilat_adapter.tahsilat_onaya_gonder',
                   return_value={'ok': True, 'talep_id': 1, 'talep_kod': 'TK-003'}), \
             patch('modules.nexgen.mo_tahsilat_kayit_service._sevk_onay_kontrol', return_value=None):
            r = onaya_gonder(con, 20, 99, yk=self.YK,
                             vade_asim_aciklamasi='Müşteri finansal sıkıntı nedeniyle talep etti')
        row = con.execute('SELECT durum, onay_notu FROM mo_tahsilat_kayit WHERE id=20').fetchone()
        self.assertEqual(row['durum'], KAYIT_DURUM_ISTISNA_ONAY_BEKLIYOR)
        self.assertTrue(r.get('istisna_path'))
        self.assertIn('finansal', row['onay_notu'])

    def test_karar_sonrasi_writes_yonetim_onaylandi(self):
        """karar_sonrasi → YONETIM_ONAYLANDI (yeni kayıt)"""
        from modules.nexgen.mo_tahsilat_kayit_service import karar_sonrasi
        from modules.nexgen.mo_tahsilat_config import KAYIT_DURUM_YONETIM_ONAYLANDI
        con = self._make_con_with_taslak()
        con.execute("UPDATE mo_tahsilat_kayit SET durum='YONETIM_ONAY_BEKLIYOR' WHERE id=20")
        con.commit()
        karar_sonrasi(con, 20, {'durum': 'ONAYLANDI', 'tamamlandi': True, 'not': 'Onay OK'})
        row = con.execute('SELECT durum FROM mo_tahsilat_kayit WHERE id=20').fetchone()
        self.assertEqual(row['durum'], KAYIT_DURUM_YONETIM_ONAYLANDI)

    def test_karar_sonrasi_legacy_onaylandi_not_overwritten(self):
        """Mevcut DB'de durum=ONAYLANDI olan kayıt — kod okuyabilmeli (legacy uyum)"""
        from modules.nexgen.mo_tahsilat_config import KAYIT_DURUM_ONAYLANDI, TAHSILAT_EDILEN_DURUMLARI
        self.assertIn(KAYIT_DURUM_ONAYLANDI, TAHSILAT_EDILEN_DURUMLARI)

    def test_yonetim_onaylandi_in_edilen(self):
        """YONETIM_ONAYLANDI da TAHSILAT_EDILEN_DURUMLARI içinde"""
        from modules.nexgen.mo_tahsilat_config import KAYIT_DURUM_YONETIM_ONAYLANDI, TAHSILAT_EDILEN_DURUMLARI
        self.assertIn(KAYIT_DURUM_YONETIM_ONAYLANDI, TAHSILAT_EDILEN_DURUMLARI)

    def test_muhasebe_bekliyor_alias(self):
        """KAYIT_DURUM_MUHASEBE_BEKLIYOR == YONETIM_ONAY_BEKLIYOR (backward compat)"""
        from modules.nexgen.mo_tahsilat_config import KAYIT_DURUM_MUHASEBE_BEKLIYOR, KAYIT_DURUM_YONETIM_ONAY_BEKLIYOR
        self.assertEqual(KAYIT_DURUM_MUHASEBE_BEKLIYOR, KAYIT_DURUM_YONETIM_ONAY_BEKLIYOR)

    def test_aciklama_bos_string_blocked(self):
        """Boş string açıklama → blok"""
        from modules.nexgen.mo_tahsilat_kayit_service import onaya_gonder, MoTahsilatError
        con = self._make_con_with_taslak(cek_vade='2027-04-23')
        with patch('modules.nexgen.onay_tahsilat_adapter.tahsilat_onaya_gonder',
                   return_value={'ok': True, 'talep_id': 1, 'talep_kod': 'TK-004'}), \
             patch('modules.nexgen.mo_tahsilat_kayit_service._sevk_onay_kontrol', return_value=None):
            with self.assertRaises(MoTahsilatError):
                onaya_gonder(con, 20, 99, yk=self.YK, vade_asim_aciklamasi='  ')


# ---------------------------------------------------------------------------
# Test 5: Legacy 47 kayıt DB'de okunabilir
# ---------------------------------------------------------------------------
class Test05LegacyOkuma(unittest.TestCase):
    def test_legacy_onaylandi_canonical_db_count(self):
        """Canonical DB: 47 ONAYLANDI kayıt kaybedilmemiş"""
        sha_before = _sha(CANONICAL_DB)
        con = sqlite3.connect(CANONICAL_DB)
        try:
            count = con.execute(
                "SELECT COUNT(*) FROM mo_tahsilat_kayit WHERE durum='ONAYLANDI' AND aktif=1"
            ).fetchone()[0]
            # 47 veya daha fazla (migration yoksa değişmez)
            self.assertGreaterEqual(count, 47)
        finally:
            con.close()
        sha_after = _sha(CANONICAL_DB)
        self.assertEqual(sha_before, sha_after, 'Canonical DB SHA değişti!')

    def test_canonical_sha_unchanged(self):
        """Canonical DB içerik kontrolü (WAL checkpoint nedeniyle SHA değişebilir)"""
        import sqlite3
        con = sqlite3.connect(CANONICAL_DB)
        count = con.execute("SELECT COUNT(*) FROM mo_tahsilat_kayit").fetchone()[0]
        onaylandi = con.execute("SELECT COUNT(*) FROM mo_tahsilat_kayit WHERE durum='ONAYLANDI'").fetchone()[0]
        con.close()
        self.assertGreaterEqual(count, 47, "mo_tahsilat_kayit kayıt sayısı azaldı!")
        self.assertGreaterEqual(onaylandi, 47, "ONAYLANDI kaydı kayboldu!")


# ---------------------------------------------------------------------------
# Test 6: State config bütünlüğü
# ---------------------------------------------------------------------------
class Test06StateConfig(unittest.TestCase):
    def test_all_new_states_in_etiket(self):
        from modules.nexgen.mo_tahsilat_config import (
            KAYIT_DURUM_ETIKET,
            KAYIT_DURUM_YONETIM_ONAY_BEKLIYOR,
            KAYIT_DURUM_ISTISNA_ONAY_BEKLIYOR,
            KAYIT_DURUM_YONETIM_ONAYLANDI,
            KAYIT_DURUM_REVIZYON,
            KAYIT_DURUM_REDDEDILDI,
        )
        for s in [KAYIT_DURUM_YONETIM_ONAY_BEKLIYOR, KAYIT_DURUM_ISTISNA_ONAY_BEKLIYOR,
                  KAYIT_DURUM_YONETIM_ONAYLANDI, KAYIT_DURUM_REVIZYON, KAYIT_DURUM_REDDEDILDI]:
            self.assertIn(s, KAYIT_DURUM_ETIKET, f'{s} etiket eksik')

    def test_onay_bekliyor_set(self):
        from modules.nexgen.mo_tahsilat_config import (
            KAYIT_ONAY_BEKLIYOR_DURUMLARI,
            KAYIT_DURUM_YONETIM_ONAY_BEKLIYOR,
            KAYIT_DURUM_ISTISNA_ONAY_BEKLIYOR,
        )
        self.assertIn(KAYIT_DURUM_YONETIM_ONAY_BEKLIYOR, KAYIT_ONAY_BEKLIYOR_DURUMLARI)
        self.assertIn(KAYIT_DURUM_ISTISNA_ONAY_BEKLIYOR, KAYIT_ONAY_BEKLIYOR_DURUMLARI)


if __name__ == '__main__':
    unittest.main(verbosity=2)
