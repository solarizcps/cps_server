# -*- coding: utf-8 -*-
"""
TAHSİLAT AVANS — LOCK Tests
==============================
Migration 164: mo_tahsilat_kayit.tahsilat_tipi kolonu + AVANS canonical davranışı.

Test A: siparis var + sevk yok → AVANS modu (DB kaydi)
Test B: DB tahsilat_tipi=AVANS yazılıyor
Test C: siparis_id dolu (Model 1)
Test D: sevkiyat_id IS NULL
Test E: AVANS + CEK → birden fazla çek satırı
Test F: Her çek — tutar, alim_tarihi, vade_tarihi, cek_no, banka korunuyor
Test G: Taslak reopen/hydrate — tüm çek tarihleri aynen geliyor
Test H: vade_tarihi - alim_tarihi hesabı yapılabilecek veri eksiksiz
Test I: Tutar ağırlıklı ortalama vade hesaplanabilir
Test J: Onaya gönder başarılı
Test K: Normal sevkiyatlı tahsilat NORMAL tipini koruyor
Test L: Normal FX — kur tarihi gerçek sevk tarihi
Test M: Normal manuel TCMB kur girişi aynen çalışıyor
Test N: Hiçbir kod internetten TCMB kuru almıyor

In-memory DB — canonical mock_data.db'ye dokunulmaz.
"""
from __future__ import annotations

import importlib
import re
import sqlite3
import sys
import unittest
from datetime import date, timedelta
from decimal import Decimal

sys.path.insert(0, "app")

# ---------------------------------------------------------------------------
# Migration 164 import (isim rakamla başlıyor — importlib ile)
# ---------------------------------------------------------------------------
_m164 = importlib.import_module("migrations.164_mo_tahsilat_avans_tipi")


# ---------------------------------------------------------------------------
# DDL — tahsilat test fixture (tüm relevant tablolar)
# ---------------------------------------------------------------------------
_DDL = """
CREATE TABLE IF NOT EXISTS nexgen_cari (
    id INTEGER PRIMARY KEY, unvan TEXT, aktif INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS nexgen_planlama_siparis (
    id INTEGER PRIMARY KEY, siparis_no TEXT, cari_id INTEGER,
    durum TEXT DEFAULT 'ONAYLANDI',
    anlasma_para_birimi TEXT DEFAULT 'TRY',
    anlasma_birim_fiyat REAL,
    vade_gun INTEGER,
    tahsilat_kurali TEXT,
    tahsilat_durumu TEXT,
    odeme_tipi TEXT,
    kur REAL, kur_tarihi TEXT,
    aktif INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS mo_musteri_sevkiyat (
    id INTEGER PRIMARY KEY, sevkiyat_no TEXT, siparis_id INTEGER,
    cari_id INTEGER, durum TEXT DEFAULT 'SEVK_EDILDI',
    sevk_tarihi TEXT, aktif INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS mo_musteri_sevkiyat_kalem (
    id INTEGER PRIMARY KEY, sevkiyat_id INTEGER,
    miktar_l REAL, miktar_s REAL, miktar_m REAL,
    birim_fiyat_snapshot REAL, aktif INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS mo_tahsilat_kayit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kayit_kodu TEXT, cari_id INTEGER NOT NULL,
    siparis_id INTEGER, sevkiyat_id INTEGER,
    kaynak_modul TEXT NOT NULL DEFAULT 'MUSTERI_OPERASYONU',
    beklened_tutar REAL, beklenen_tahmini INTEGER NOT NULL DEFAULT 1,
    beklenen_tutar REAL,
    paket_hedef_tutar REAL, alinan_tutar REAL, kalan_tutar REAL,
    para_birimi TEXT, sevk_hedef_tutar_snapshot REAL,
    sevk_para_birimi_snapshot TEXT, sevk_kalan_fx_snapshot REAL,
    tcmb_satis_kur_snapshot REAL, kur_tarihi_snapshot TEXT,
    onaylanan_vade_gun_snapshot INTEGER,
    gercek_sevk_tarihi_snapshot TEXT, hedef_vade_tarihi TEXT,
    planlanan_tahsilat_tarihi TEXT, alinan_tarih TEXT,
    odeme_tipi TEXT, odeme_referansi TEXT, kismi_mi INTEGER DEFAULT 0,
    aciklama TEXT, dosya_ref TEXT, onay_notu TEXT, revizyon_gerekce TEXT,
    durum TEXT NOT NULL DEFAULT 'TASLAK',
    cari_entegrasyon_durumu TEXT NOT NULL DEFAULT 'BEKLIYOR',
    idempotency_key TEXT NOT NULL UNIQUE,
    olusturan_id INTEGER NOT NULL, onaylayan_id INTEGER,
    aktif INTEGER NOT NULL DEFAULT 1,
    olusturma_tarihi TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    guncelleme_tarihi TEXT, audit_json TEXT
);
CREATE TABLE IF NOT EXISTS mo_tahsilat_cek (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tahsilat_kayit_id INTEGER NOT NULL,
    sira_no INTEGER NOT NULL DEFAULT 1,
    tutar REAL NOT NULL, para_birimi TEXT NOT NULL,
    cek_alim_tarihi TEXT NOT NULL,
    gercek_cek_vade_tarihi TEXT NOT NULL,
    odeme_referansi TEXT, banka_adi TEXT,
    durum TEXT NOT NULL DEFAULT 'AKTIF',
    aktif INTEGER NOT NULL DEFAULT 1,
    idempotency_key TEXT UNIQUE,
    olusturan_id INTEGER,
    olusturma_tarihi TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    guncelleme_tarihi TEXT, audit_json TEXT,
    CHECK (durum IN ('AKTIF', 'IPTAL')),
    CHECK (aktif IN (0, 1)),
    FOREIGN KEY (tahsilat_kayit_id) REFERENCES mo_tahsilat_kayit(id)
);
CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS nexgen_yetki (
    kullanici_id INTEGER, yetki TEXT,
    PRIMARY KEY (kullanici_id, yetki)
);
CREATE TABLE IF NOT EXISTS cari_sorumlu (
    id INTEGER PRIMARY KEY, cari_id INTEGER, kullanici_id INTEGER, aktif INTEGER DEFAULT 1
);
"""


def _make_con() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    for stmt in _DDL.strip().split(";"):
        s = stmt.strip()
        if s:
            con.execute(s)
    # Migration 164 uygula
    _m164._ensure_columns(con)
    _m164._ensure_indexes(con)
    con.commit()
    # Test verisi
    con.execute("INSERT INTO nexgen_cari (id, unvan) VALUES (1, 'Eva Time Taban San')")
    con.execute(
        "INSERT INTO nexgen_planlama_siparis (id, siparis_no, cari_id, durum, anlasma_para_birimi, vade_gun) "
        "VALUES (10, 'PZM-2026-0019', 1, 'ONAYLANDI', 'TRY', 30)"
    )
    # Normal tahsilat için sevkiyatlı sipariş
    con.execute(
        "INSERT INTO nexgen_planlama_siparis (id, siparis_no, cari_id, durum, anlasma_para_birimi, vade_gun) "
        "VALUES (20, 'PZM-2026-0020', 1, 'ONAYLANDI', 'TRY', 30)"
    )
    con.execute(
        "INSERT INTO mo_musteri_sevkiyat (id, sevkiyat_no, siparis_id, cari_id, durum, sevk_tarihi) "
        "VALUES (100, 'SVK-001', 20, 1, 'SEVK_EDILDI', '2026-08-10')"
    )
    con.execute("INSERT INTO schema_migrations (version) VALUES (164)")
    con.commit()
    return con


def _insert_avans_cek(con, sira=1, tutar=200000.0, alim='2026-08-19', vade='2027-02-19',
                       cek_no='CHK001', banka='Garanti', tahsilat_kayit_id=1) -> int:
    cur = con.execute(
        "INSERT INTO mo_tahsilat_cek "
        "(tahsilat_kayit_id, sira_no, tutar, para_birimi, cek_alim_tarihi, gercek_cek_vade_tarihi, "
        "odeme_referansi, banka_adi, idempotency_key, olusturan_id) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (tahsilat_kayit_id, sira, tutar, 'TRY', alim, vade, cek_no, banka,
         f'cek-{tahsilat_kayit_id}-{sira}-{cek_no}', 99)
    )
    con.commit()
    return int(cur.lastrowid)


# ---------------------------------------------------------------------------
# TEST A: Sipariş var + sevkiyat yok → AVANS modu
# ---------------------------------------------------------------------------
class TestA_AvansModuTetikleme(unittest.TestCase):
    def test_siparis_var_sevk_yok_avans_db(self):
        con = _make_con()
        cur = con.execute(
            "INSERT INTO mo_tahsilat_kayit "
            "(cari_id, siparis_id, sevkiyat_id, odeme_tipi, tahsilat_tipi, durum, idempotency_key, olusturan_id) "
            "VALUES (1, 10, NULL, 'CEK', 'AVANS', 'TASLAK', 'avans-a-1', 99)"
        )
        con.commit()
        row = con.execute("SELECT * FROM mo_tahsilat_kayit WHERE id=?", (cur.lastrowid,)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row['cari_id'], 1)
        self.assertEqual(row['siparis_id'], 10)
        self.assertIsNone(row['sevkiyat_id'])
        self.assertEqual(row['tahsilat_tipi'], 'AVANS')
        con.close()


# ---------------------------------------------------------------------------
# TEST B: DB tahsilat_tipi=AVANS yazılıyor
# ---------------------------------------------------------------------------
class TestB_AvansDbDiscriminator(unittest.TestCase):
    def test_tahsilat_tipi_avans_kolon(self):
        con = _make_con()
        cols = [c[1] for c in con.execute("PRAGMA table_info(mo_tahsilat_kayit)").fetchall()]
        self.assertIn('tahsilat_tipi', cols, "tahsilat_tipi kolonu yok — Migration 164 uygulanmamış")

        cur = con.execute(
            "INSERT INTO mo_tahsilat_kayit "
            "(cari_id, siparis_id, sevkiyat_id, odeme_tipi, tahsilat_tipi, durum, idempotency_key, olusturan_id) "
            "VALUES (1, 10, NULL, 'CEK', 'AVANS', 'TASLAK', 'avans-b-1', 99)"
        )
        con.commit()
        row = con.execute("SELECT tahsilat_tipi FROM mo_tahsilat_kayit WHERE id=?", (cur.lastrowid,)).fetchone()
        self.assertEqual(row['tahsilat_tipi'], 'AVANS')
        con.close()

    def test_mevcut_kayit_null_kalir(self):
        """Backfill yok — eski kayıtlar NULL kalır."""
        con = _make_con()
        cur = con.execute(
            "INSERT INTO mo_tahsilat_kayit "
            "(cari_id, odeme_tipi, durum, idempotency_key, olusturan_id) "
            "VALUES (1, 'NAKIT', 'TASLAK', 'eski-1', 99)"
        )
        con.commit()
        row = con.execute("SELECT tahsilat_tipi FROM mo_tahsilat_kayit WHERE id=?", (cur.lastrowid,)).fetchone()
        self.assertIsNone(row['tahsilat_tipi'], "Backfill olmamali — NULL bekleniyor")
        con.close()


# ---------------------------------------------------------------------------
# TEST C: siparis_id dolu (Model 1)
# ---------------------------------------------------------------------------
class TestC_SiparisIdDolu(unittest.TestCase):
    def test_avans_siparis_id_korunur(self):
        con = _make_con()
        cur = con.execute(
            "INSERT INTO mo_tahsilat_kayit "
            "(cari_id, siparis_id, sevkiyat_id, tahsilat_tipi, odeme_tipi, durum, idempotency_key, olusturan_id) "
            "VALUES (1, 10, NULL, 'AVANS', 'CEK', 'TASLAK', 'avans-c-1', 99)"
        )
        con.commit()
        row = con.execute(
            "SELECT siparis_id, sevkiyat_id, tahsilat_tipi FROM mo_tahsilat_kayit WHERE id=?",
            (cur.lastrowid,)
        ).fetchone()
        self.assertEqual(row['siparis_id'], 10)
        self.assertIsNone(row['sevkiyat_id'])
        self.assertEqual(row['tahsilat_tipi'], 'AVANS')
        con.close()


# ---------------------------------------------------------------------------
# TEST D: sevkiyat_id IS NULL
# ---------------------------------------------------------------------------
class TestD_SevkiyatIdNull(unittest.TestCase):
    def test_avans_sevkiyat_id_null(self):
        con = _make_con()
        cur = con.execute(
            "INSERT INTO mo_tahsilat_kayit "
            "(cari_id, siparis_id, sevkiyat_id, tahsilat_tipi, odeme_tipi, durum, idempotency_key, olusturan_id) "
            "VALUES (1, 10, NULL, 'AVANS', 'CEK', 'TASLAK', 'avans-d-1', 99)"
        )
        con.commit()
        count = con.execute(
            "SELECT COUNT(*) FROM mo_tahsilat_kayit WHERE tahsilat_tipi='AVANS' AND sevkiyat_id IS NULL"
        ).fetchone()[0]
        self.assertGreater(count, 0)
        con.close()


# ---------------------------------------------------------------------------
# TEST E: AVANS + CEK → birden fazla çek satırı
# ---------------------------------------------------------------------------
class TestE_AvansCekSatirlari(unittest.TestCase):
    def test_cok_cek_satiri_eklenebilir(self):
        con = _make_con()
        cur = con.execute(
            "INSERT INTO mo_tahsilat_kayit "
            "(cari_id, siparis_id, sevkiyat_id, tahsilat_tipi, odeme_tipi, durum, idempotency_key, olusturan_id) "
            "VALUES (1, 10, NULL, 'AVANS', 'CEK', 'TASLAK', 'avans-e-1', 99)"
        )
        con.commit()
        kid = int(cur.lastrowid)

        _insert_avans_cek(con, sira=1, tutar=200000.0, cek_no='CHK001', tahsilat_kayit_id=kid)
        _insert_avans_cek(con, sira=2, tutar=200000.0, cek_no='CHK002', tahsilat_kayit_id=kid)
        _insert_avans_cek(con, sira=3, tutar=150000.0, cek_no='CHK003', tahsilat_kayit_id=kid)

        rows = con.execute(
            "SELECT COUNT(*) AS c FROM mo_tahsilat_cek WHERE tahsilat_kayit_id=? AND aktif=1", (kid,)
        ).fetchone()
        self.assertEqual(rows['c'], 3)

        toplam = con.execute(
            "SELECT SUM(tutar) AS t FROM mo_tahsilat_cek WHERE tahsilat_kayit_id=? AND aktif=1", (kid,)
        ).fetchone()['t']
        self.assertAlmostEqual(toplam, 550000.0)
        con.close()


# ---------------------------------------------------------------------------
# TEST F: Her çek — tutar, alim_tarihi, vade_tarihi, cek_no, banka korunuyor
# ---------------------------------------------------------------------------
class TestF_CekAlanlarKorunur(unittest.TestCase):
    def test_cek_alanlari_eksiksiz(self):
        con = _make_con()
        cur = con.execute(
            "INSERT INTO mo_tahsilat_kayit "
            "(cari_id, siparis_id, sevkiyat_id, tahsilat_tipi, odeme_tipi, durum, idempotency_key, olusturan_id) "
            "VALUES (1, 10, NULL, 'AVANS', 'CEK', 'TASLAK', 'avans-f-1', 99)"
        )
        con.commit()
        kid = int(cur.lastrowid)

        _insert_avans_cek(
            con, sira=1, tutar=350000.0, alim='2026-08-19', vade='2027-02-19',
            cek_no='CHK-TEST-001', banka='İş Bankası', tahsilat_kayit_id=kid
        )

        row = con.execute(
            "SELECT tutar, cek_alim_tarihi, gercek_cek_vade_tarihi, odeme_referansi, banka_adi "
            "FROM mo_tahsilat_cek WHERE tahsilat_kayit_id=? AND aktif=1", (kid,)
        ).fetchone()

        self.assertAlmostEqual(row['tutar'], 350000.0)
        self.assertEqual(row['cek_alim_tarihi'], '2026-08-19')
        self.assertEqual(row['gercek_cek_vade_tarihi'], '2027-02-19')
        self.assertEqual(row['odeme_referansi'], 'CHK-TEST-001')
        self.assertEqual(row['banka_adi'], 'İş Bankası')
        con.close()


# ---------------------------------------------------------------------------
# TEST G: Taslak reopen/hydrate — tüm çek tarihleri aynen geliyor
# (Simulated: SELECT geri okunuyor — gerçek hydrate API aracılığıyla)
# ---------------------------------------------------------------------------
class TestG_HydrateVeriKorunumu(unittest.TestCase):
    def test_cek_tarihleri_db_den_eksiksiz_okunur(self):
        con = _make_con()
        cur = con.execute(
            "INSERT INTO mo_tahsilat_kayit "
            "(cari_id, siparis_id, sevkiyat_id, tahsilat_tipi, odeme_tipi, durum, idempotency_key, olusturan_id) "
            "VALUES (1, 10, NULL, 'AVANS', 'CEK', 'TASLAK', 'avans-g-1', 99)"
        )
        con.commit()
        kid = int(cur.lastrowid)

        satirlar = [
            (1, 100000.0, '2026-08-19', '2026-11-19', 'CHK-G1', 'Garanti'),
            (2, 250000.0, '2026-08-19', '2027-02-19', 'CHK-G2', 'Yapı Kredi'),
        ]
        for sira, tutar, alim, vade, no, banka in satirlar:
            _insert_avans_cek(con, sira=sira, tutar=tutar, alim=alim, vade=vade,
                               cek_no=no, banka=banka, tahsilat_kayit_id=kid)

        rows = con.execute(
            "SELECT sira_no, tutar, cek_alim_tarihi, gercek_cek_vade_tarihi, odeme_referansi, banka_adi "
            "FROM mo_tahsilat_cek WHERE tahsilat_kayit_id=? AND aktif=1 ORDER BY sira_no", (kid,)
        ).fetchall()

        self.assertEqual(len(rows), 2)
        for i, (sira, tutar, alim, vade, no, banka) in enumerate(satirlar):
            self.assertEqual(rows[i]['sira_no'], sira)
            self.assertAlmostEqual(rows[i]['tutar'], tutar)
            self.assertEqual(rows[i]['cek_alim_tarihi'], alim)
            self.assertEqual(rows[i]['gercek_cek_vade_tarihi'], vade)
            self.assertEqual(rows[i]['odeme_referansi'], no)
            self.assertEqual(rows[i]['banka_adi'], banka)
        con.close()


# ---------------------------------------------------------------------------
# TEST H: vade_tarihi - alim_tarihi hesabı yapılabilecek veri eksiksiz
# ---------------------------------------------------------------------------
class TestH_VadeGunuHesaplanabilir(unittest.TestCase):
    def test_vade_gun_hesaplanabilir(self):
        con = _make_con()
        cur = con.execute(
            "INSERT INTO mo_tahsilat_kayit "
            "(cari_id, siparis_id, sevkiyat_id, tahsilat_tipi, odeme_tipi, durum, idempotency_key, olusturan_id) "
            "VALUES (1, 10, NULL, 'AVANS', 'CEK', 'TASLAK', 'avans-h-1', 99)"
        )
        con.commit()
        kid = int(cur.lastrowid)

        _insert_avans_cek(
            con, sira=1, tutar=200000.0,
            alim='2026-08-19', vade='2027-02-19',
            cek_no='CHK-H1', banka='Test', tahsilat_kayit_id=kid
        )

        row = con.execute(
            "SELECT cek_alim_tarihi, gercek_cek_vade_tarihi FROM mo_tahsilat_cek "
            "WHERE tahsilat_kayit_id=? AND aktif=1", (kid,)
        ).fetchone()

        alim = date.fromisoformat(row['cek_alim_tarihi'])
        vade = date.fromisoformat(row['gercek_cek_vade_tarihi'])
        vade_gun = (vade - alim).days
        self.assertGreater(vade_gun, 0, "Vade günü pozitif olmalı")
        # 19 Ağustos → 19 Şubat = 184 gün (yaklaşık)
        self.assertGreater(vade_gun, 150)
        self.assertLess(vade_gun, 220)
        con.close()


# ---------------------------------------------------------------------------
# TEST I: Tutar ağırlıklı ortalama vade hesaplanabilir
# ---------------------------------------------------------------------------
class TestI_TutarAgirlikliOrtalamaVade(unittest.TestCase):
    def test_agirlikli_ortalama_vade(self):
        """
        Canonical helper — duplicate kolon olmadan SQL üzerinden hesaplanabilir.
        Çek 1: 100.000 TL / 30 gün
        Çek 2: 500.000 TL / 180 gün
        Ağırlıklı ortalama: (100000×30 + 500000×180) / 600000 = 155 gün
        """
        con = _make_con()
        cur = con.execute(
            "INSERT INTO mo_tahsilat_kayit "
            "(cari_id, siparis_id, sevkiyat_id, tahsilat_tipi, odeme_tipi, durum, idempotency_key, olusturan_id) "
            "VALUES (1, 10, NULL, 'AVANS', 'CEK', 'TASLAK', 'avans-i-1', 99)"
        )
        con.commit()
        kid = int(cur.lastrowid)

        alim_base = date(2026, 8, 19)
        cekler = [
            (100000.0, alim_base, alim_base + timedelta(days=30)),
            (500000.0, alim_base, alim_base + timedelta(days=180)),
        ]
        for sira, (tutar, alim, vade) in enumerate(cekler, 1):
            _insert_avans_cek(
                con, sira=sira, tutar=tutar,
                alim=alim.isoformat(), vade=vade.isoformat(),
                cek_no=f'CHK-I{sira}', banka='Test', tahsilat_kayit_id=kid
            )

        # Hesap: tutar × vade_gun / toplam_tutar
        rows = con.execute(
            "SELECT tutar, cek_alim_tarihi, gercek_cek_vade_tarihi "
            "FROM mo_tahsilat_cek WHERE tahsilat_kayit_id=? AND aktif=1", (kid,)
        ).fetchall()

        toplam_tutar = sum(r['tutar'] for r in rows)
        agirlikli_toplam = sum(
            r['tutar'] * (
                date.fromisoformat(r['gercek_cek_vade_tarihi']) -
                date.fromisoformat(r['cek_alim_tarihi'])
            ).days
            for r in rows
        )
        ortalama_vade = agirlikli_toplam / toplam_tutar if toplam_tutar else 0

        beklenen = (100000 * 30 + 500000 * 180) / 600000  # = 155.0
        self.assertAlmostEqual(ortalama_vade, beklenen, places=1)
        con.close()


# ---------------------------------------------------------------------------
# TEST J: Onaya gönder başarılı (AVANS → YONETIM_ONAY_BEKLIYOR)
# ---------------------------------------------------------------------------
class TestJ_OnayaGonder(unittest.TestCase):
    def test_avans_onaya_gonderilebilir(self):
        con = _make_con()
        cur = con.execute(
            "INSERT INTO mo_tahsilat_kayit "
            "(cari_id, siparis_id, sevkiyat_id, tahsilat_tipi, odeme_tipi, alinan_tutar, durum, "
            "idempotency_key, olusturan_id) "
            "VALUES (1, 10, NULL, 'AVANS', 'NAKIT', 50000.0, 'TASLAK', 'avans-j-1', 99)"
        )
        con.commit()
        kid = int(cur.lastrowid)

        con.execute(
            "UPDATE mo_tahsilat_kayit SET durum='YONETIM_ONAY_BEKLIYOR' WHERE id=?", (kid,)
        )
        con.commit()

        row = con.execute("SELECT durum FROM mo_tahsilat_kayit WHERE id=?", (kid,)).fetchone()
        self.assertEqual(row['durum'], 'YONETIM_ONAY_BEKLIYOR')
        con.close()


# ---------------------------------------------------------------------------
# TEST K: Normal sevkiyatlı tahsilat NORMAL tipini koruyor
# ---------------------------------------------------------------------------
class TestK_NormalTahsilatNormal(unittest.TestCase):
    def test_normal_tahsilat_tipi(self):
        con = _make_con()
        cur = con.execute(
            "INSERT INTO mo_tahsilat_kayit "
            "(cari_id, siparis_id, sevkiyat_id, tahsilat_tipi, odeme_tipi, durum, idempotency_key, olusturan_id) "
            "VALUES (1, 20, 100, 'NORMAL', 'NAKIT', 'TASLAK', 'normal-k-1', 99)"
        )
        con.commit()
        row = con.execute("SELECT tahsilat_tipi, sevkiyat_id FROM mo_tahsilat_kayit WHERE id=?",
                          (cur.lastrowid,)).fetchone()
        self.assertEqual(row['tahsilat_tipi'], 'NORMAL')
        self.assertEqual(row['sevkiyat_id'], 100)
        con.close()

    def test_normal_ve_avans_birlikte_sorgulanabilir(self):
        con = _make_con()
        con.execute(
            "INSERT INTO mo_tahsilat_kayit "
            "(cari_id, siparis_id, sevkiyat_id, tahsilat_tipi, odeme_tipi, durum, idempotency_key, olusturan_id) "
            "VALUES (1, 20, 100, 'NORMAL', 'NAKIT', 'TASLAK', 'k-normal-1', 99)"
        )
        con.execute(
            "INSERT INTO mo_tahsilat_kayit "
            "(cari_id, siparis_id, sevkiyat_id, tahsilat_tipi, odeme_tipi, durum, idempotency_key, olusturan_id) "
            "VALUES (1, 10, NULL, 'AVANS', 'CEK', 'TASLAK', 'k-avans-1', 99)"
        )
        con.commit()
        normal_c = con.execute(
            "SELECT COUNT(*) FROM mo_tahsilat_kayit WHERE tahsilat_tipi='NORMAL'"
        ).fetchone()[0]
        avans_c = con.execute(
            "SELECT COUNT(*) FROM mo_tahsilat_kayit WHERE tahsilat_tipi='AVANS'"
        ).fetchone()[0]
        self.assertEqual(normal_c, 1)
        self.assertEqual(avans_c, 1)
        con.close()


# ---------------------------------------------------------------------------
# TEST L: Normal FX — kur tarihi hâlâ gerçek sevk tarihi (mo_tahsilat_config)
# ---------------------------------------------------------------------------
class TestL_NormalFxKurTarihi(unittest.TestCase):
    def test_kur_tarihi_sevk_tarihi(self):
        """_kur_tarihi_sevk_belirle fonksiyonu gerçek sevk tarihini döner."""
        from modules.nexgen.mo_tahsilat_kayit_service import _kur_tarihi_sevk_belirle
        con = _make_con()
        tarih = _kur_tarihi_sevk_belirle(con, 100)  # sevkiyat 100 → sevk_tarihi='2026-08-10'
        self.assertEqual(tarih, '2026-08-10')
        con.close()

    def test_kur_tarihi_sevk_yok_hata(self):
        """Sevkiyat yoksa MoTahsilatError fırlatır — AVANS'ta bu fonksiyon çağrılmaz."""
        from modules.nexgen.mo_tahsilat_kayit_service import _kur_tarihi_sevk_belirle, MoTahsilatError
        con = _make_con()
        with self.assertRaises(MoTahsilatError):
            _kur_tarihi_sevk_belirle(con, 9999)  # olmayan sevkiyat
        con.close()


# ---------------------------------------------------------------------------
# TEST M: Normal manuel TCMB kur girişi aynen çalışıyor
# ---------------------------------------------------------------------------
class TestM_ManuelTcmbKur(unittest.TestCase):
    def test_manuel_kur_parse(self):
        from modules.nexgen.mo_tahsilat_kayit_service import _parse_manuel_kur_raw, MoTahsilatError
        # Virgüllü format
        self.assertAlmostEqual(_parse_manuel_kur_raw("47,25"), 47.25)
        # Noktalı format
        self.assertAlmostEqual(_parse_manuel_kur_raw("47.25"), 47.25)
        # Sıfır → hata
        with self.assertRaises(MoTahsilatError):
            _parse_manuel_kur_raw(0)
        # Negatif → hata
        with self.assertRaises(MoTahsilatError):
            _parse_manuel_kur_raw(-5.0)
        # Zorunlu + boş → hata
        with self.assertRaises(MoTahsilatError):
            _parse_manuel_kur_raw(None, zorunlu=True)

    def test_normal_kur_db_kaydi(self):
        con = _make_con()
        cur = con.execute(
            "INSERT INTO mo_tahsilat_kayit "
            "(cari_id, siparis_id, sevkiyat_id, tahsilat_tipi, odeme_tipi, "
            "tcmb_satis_kur_snapshot, kur_tarihi_snapshot, durum, idempotency_key, olusturan_id) "
            "VALUES (1, 20, 100, 'NORMAL', 'NAKIT', 47.25, '2026-08-10', 'TASLAK', 'normal-m-1', 99)"
        )
        con.commit()
        row = con.execute(
            "SELECT tcmb_satis_kur_snapshot, kur_tarihi_snapshot FROM mo_tahsilat_kayit WHERE id=?",
            (cur.lastrowid,)
        ).fetchone()
        self.assertAlmostEqual(row['tcmb_satis_kur_snapshot'], 47.25)
        self.assertEqual(row['kur_tarihi_snapshot'], '2026-08-10')
        con.close()


# ---------------------------------------------------------------------------
# TEST N: Hiçbir kod internetten TCMB kuru almıyor
# ---------------------------------------------------------------------------
class TestN_TcmbInternetYok(unittest.TestCase):
    def _scan_python_file(self, path: str) -> None:
        with open(path, encoding='utf-8') as f:
            src = f.read()
        forbidden_patterns = [
            r'requests\.get\s*\(',
            r'urllib\.request',
            r'httpx\.',
            r'aiohttp\.',
            r'evds\.tcmb\.gov',
            r'tcmb\.gov\.tr',
            r'fetch.*tcmb',
        ]
        for pat in forbidden_patterns:
            self.assertIsNone(
                re.search(pat, src, re.IGNORECASE),
                f"İnternet TCMB kur çağrısı tespit edildi: {pat} — {path}"
            )

    def test_servis_dosyasi_internet_yok(self):
        self._scan_python_file("app/modules/nexgen/mo_tahsilat_kayit_service.py")

    def test_kur_servis_internet_yok(self):
        self._scan_python_file("app/modules/nexgen/mo_tahsilat_kur_service.py")

    def test_config_internet_yok(self):
        self._scan_python_file("app/modules/nexgen/mo_tahsilat_config.py")

    def test_html_internet_tcmb_yok(self):
        with open("app/templates/nexgen/musteri_pazarlama.html", encoding='utf-8') as f:
            src = f.read()
        self.assertNotIn('evds.tcmb.gov', src)
        self.assertNotIn('tcmb.gov.tr', src)


# ---------------------------------------------------------------------------
# AVANS veri modeli entegrasyon — Frontend HTML kontratları
# ---------------------------------------------------------------------------
class TestFrontendAvansKontrat(unittest.TestCase):
    def _src(self):
        with open("app/templates/nexgen/musteri_pazarlama.html", encoding='utf-8') as f:
            return f.read()

    def test_avans_bilgi_mesaji_var(self):
        src = self._src()
        self.assertIn(
            "AVANS — Henüz sevkiyat yapılmadı",
            src,
            "AVANS bilgi mesajı HTML'de bulunamadı"
        )

    def test_eski_blokaj_mesaji_kaldirildi(self):
        src = self._src()
        self.assertNotIn(
            "Sevk bekleniyor — tahsilat oluşturulamaz.",
            src,
            "Eski blokaj mesajı hâlâ HTML'de var"
        )

    def test_tahsilat_tipi_hidden_input_var(self):
        src = self._src()
        self.assertIn('id="mp-t-tahsilat-tipi"', src)
        self.assertIn('name="tahsilat_tipi"', src)

    def test_avans_hedef_mesaj_elementi_var(self):
        src = self._src()
        self.assertIn('id="mp-t-avans-hedef-mesaj"', src)

    def test_payload_tahsilat_tipi_iceriyor(self):
        src = self._src()
        self.assertIn("tahsilat_tipi:", src)
        self.assertIn("tahsilatTipi", src)

    def test_setSevkYokGuard_buton_disable_etmiyor(self):
        src = self._src()
        # Eski blokaj: buton disabled=true + eski başlık
        self.assertNotIn(
            "submitBtn.disabled = true; submitBtn.title = 'Sevk bekleniyor",
            src,
            "Eski buton disable mantığı hâlâ mevcut"
        )

    def test_avans_modu_tahsilat_tipi_set(self):
        src = self._src()
        self.assertIn("tipEl.value = 'AVANS'", src)
        self.assertIn("tipEl.value = 'NORMAL'", src)


# ---------------------------------------------------------------------------
# AVANS canonical sorgulama — Cari360 read-model uyumu
# ---------------------------------------------------------------------------
class TestCari360ReadModel(unittest.TestCase):
    def test_cari_tum_tahsilat_avans_dahil(self):
        """Canonical sorgu: cari360 tüm tahsilat tiplerini birleşik görebilir."""
        con = _make_con()
        con.execute(
            "INSERT INTO mo_tahsilat_kayit "
            "(cari_id, siparis_id, sevkiyat_id, tahsilat_tipi, odeme_tipi, alinan_tutar, durum, "
            "idempotency_key, olusturan_id) "
            "VALUES (1, 20, 100, 'NORMAL', 'NAKIT', 80000.0, 'YONETIM_ONAYLANDI', 'c360-normal', 99)"
        )
        con.execute(
            "INSERT INTO mo_tahsilat_kayit "
            "(cari_id, siparis_id, sevkiyat_id, tahsilat_tipi, odeme_tipi, alinan_tutar, durum, "
            "idempotency_key, olusturan_id) "
            "VALUES (1, 10, NULL, 'AVANS', 'CEK', 350000.0, 'TASLAK', 'c360-avans', 99)"
        )
        con.commit()

        rows = con.execute(
            "SELECT tahsilat_tipi, odeme_tipi, alinan_tutar, siparis_id, sevkiyat_id "
            "FROM mo_tahsilat_kayit WHERE cari_id=1 AND aktif=1 ORDER BY id"
        ).fetchall()

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['tahsilat_tipi'], 'NORMAL')
        self.assertIsNotNone(rows[0]['sevkiyat_id'])
        self.assertEqual(rows[1]['tahsilat_tipi'], 'AVANS')
        self.assertIsNone(rows[1]['sevkiyat_id'])
        con.close()

    def test_avans_cek_zinciri_sorgulanabilir(self):
        """Cari → Tahsilat → Çek zinciri çalışıyor."""
        con = _make_con()
        cur = con.execute(
            "INSERT INTO mo_tahsilat_kayit "
            "(cari_id, siparis_id, sevkiyat_id, tahsilat_tipi, odeme_tipi, durum, "
            "idempotency_key, olusturan_id) "
            "VALUES (1, 10, NULL, 'AVANS', 'CEK', 'TASLAK', 'chain-avans', 99)"
        )
        con.commit()
        kid = int(cur.lastrowid)

        _insert_avans_cek(con, sira=1, tutar=200000.0, alim='2026-08-19', vade='2027-02-19',
                           cek_no='CHK-Z1', banka='Akbank', tahsilat_kayit_id=kid)

        result = con.execute(
            """
            SELECT tk.tahsilat_tipi, tk.odeme_tipi, tk.siparis_id,
                   tc.tutar, tc.cek_alim_tarihi, tc.gercek_cek_vade_tarihi,
                   tc.odeme_referansi, tc.banka_adi
            FROM mo_tahsilat_kayit tk
            JOIN mo_tahsilat_cek tc ON tc.tahsilat_kayit_id = tk.id AND tc.aktif=1
            WHERE tk.cari_id=1 AND tk.tahsilat_tipi='AVANS'
            """
        ).fetchone()

        self.assertIsNotNone(result)
        self.assertEqual(result['tahsilat_tipi'], 'AVANS')
        self.assertEqual(result['odeme_tipi'], 'CEK')
        self.assertAlmostEqual(result['tutar'], 200000.0)
        self.assertEqual(result['cek_alim_tarihi'], '2026-08-19')
        self.assertEqual(result['gercek_cek_vade_tarihi'], '2027-02-19')
        self.assertEqual(result['odeme_referansi'], 'CHK-Z1')
        self.assertEqual(result['banka_adi'], 'Akbank')
        con.close()


# ---------------------------------------------------------------------------
# TestO — AVANS CEK Vade Özeti (Real E2E Bug Lock)
# PZM-2026-0119: sevkiyat yok, 1 çek 125.000 TL, alım 29.07 → vade 30.07
# ---------------------------------------------------------------------------

class TestO_AvansCekVadeOzeti(unittest.TestCase):
    """
    LOCK: AVANS + CEK → vade_kontrol_service.hesapla()
    Sevkiyat yokken SEVK_BEKLIYOR erken çıkışı BYPASS edilmeli.
    Çek adedi, toplam, ağırlıklı ortalama vade hesaplanmalı.
    """

    def _make_satirlar(self, *, tutar, alim, vade):
        from modules.nexgen.mo_vade_kontrol_service import CekSatiriInput
        return [CekSatiriInput(
            tutar=Decimal(str(tutar)),
            gercek_cek_vade_tarihi=vade,
            para_birimi="TRY",
            cek_alim_tarihi=alim,
        )]

    def test_avans_cek_sevk_yok_ozet_hesaplanir(self):
        """Pilot: 125.000 TL, alım 29.07, vade 30.07 → adedi=1, toplam=125000, ort_vade=1 gün."""
        from modules.nexgen.mo_vade_kontrol_service import hesapla
        satirlar = self._make_satirlar(tutar=125000, alim='2026-07-29', vade='2026-07-30')
        sonuc = hesapla(
            cek_satirlari=satirlar,
            para_birimi='TRY',
            onaylanan_vade_gun=30,
            sevk_tarihi=None,
            tahsilat_tipi='AVANS',
        )
        self.assertEqual(sonuc.cek_adedi, 1)
        self.assertAlmostEqual(sonuc.toplam_cek_tutari, 125000.0)
        self.assertEqual(sonuc.agirlikli_ortalama_vade_gun_gosterim, 1)
        self.assertEqual(sonuc.durum_kodu, 'AVANS_CEK')
        self.assertEqual(sonuc.durum_etiket, 'Avans Çeki')

    def test_avans_cek_ort_vade_tarihi(self):
        """Ağırlıklı ort. vade tarihi = alım + 1 gün = 2026-07-30."""
        from modules.nexgen.mo_vade_kontrol_service import hesapla
        satirlar = self._make_satirlar(tutar=125000, alim='2026-07-29', vade='2026-07-30')
        sonuc = hesapla(
            cek_satirlari=satirlar,
            para_birimi='TRY',
            onaylanan_vade_gun=30,
            sevk_tarihi=None,
            tahsilat_tipi='AVANS',
        )
        self.assertEqual(sonuc.agirlikli_ortalama_vade_tarihi, '2026-07-30')

    def test_avans_cek_finansman_none(self):
        """AVANS'ta finansman_net = None (sevkiyat yok, karşılaştırma anlamsız)."""
        from modules.nexgen.mo_vade_kontrol_service import hesapla
        satirlar = self._make_satirlar(tutar=125000, alim='2026-07-29', vade='2026-07-30')
        sonuc = hesapla(
            cek_satirlari=satirlar,
            para_birimi='TRY',
            onaylanan_vade_gun=30,
            sevk_tarihi=None,
            tahsilat_tipi='AVANS',
        )
        self.assertIsNone(sonuc.finansman_net)

    def test_avans_cek_sapma_none(self):
        """AVANS'ta vade_sapma_gun_gosterim = None (sevkiyatsız sapma hesaplanamaz)."""
        from modules.nexgen.mo_vade_kontrol_service import hesapla
        satirlar = self._make_satirlar(tutar=125000, alim='2026-07-29', vade='2026-07-30')
        sonuc = hesapla(
            cek_satirlari=satirlar,
            para_birimi='TRY',
            onaylanan_vade_gun=30,
            sevk_tarihi=None,
            tahsilat_tipi='AVANS',
        )
        self.assertIsNone(sonuc.vade_sapma_gun_gosterim)

    def test_normal_sevk_var_sevk_bekliyor_degil(self):
        """NORMAL + sevk_tarihi var → SEVK_BEKLIYOR değil, çek analizi çalışır."""
        from modules.nexgen.mo_vade_kontrol_service import hesapla
        satirlar = self._make_satirlar(tutar=125000, alim='2026-07-29', vade='2026-07-30')
        sonuc = hesapla(
            cek_satirlari=satirlar,
            para_birimi='TRY',
            onaylanan_vade_gun=30,
            sevk_tarihi='2026-07-01',
            tahsilat_tipi='NORMAL',
        )
        self.assertNotEqual(sonuc.durum_kodu, 'SEVK_BEKLIYOR')
        self.assertEqual(sonuc.cek_adedi, 1)

    def test_normal_sevk_yok_sevk_bekliyor(self):
        """NORMAL + sevk_tarihi=None → SEVK_BEKLIYOR erken çıkış, cek_adedi=0."""
        from modules.nexgen.mo_vade_kontrol_service import hesapla
        satirlar = self._make_satirlar(tutar=125000, alim='2026-07-29', vade='2026-07-30')
        sonuc = hesapla(
            cek_satirlari=satirlar,
            para_birimi='TRY',
            onaylanan_vade_gun=30,
            sevk_tarihi=None,
            tahsilat_tipi='NORMAL',
        )
        self.assertEqual(sonuc.durum_kodu, 'SEVK_BEKLIYOR')
        self.assertEqual(sonuc.cek_adedi, 0)

    def test_avans_cek_agirlikli_iki_satir(self):
        """2 çek: 100k 0 gün + 25k 4 gün → ağırlıklı ort = (100k×0 + 25k×4)/125k = 0.8 → 1 gün."""
        from modules.nexgen.mo_vade_kontrol_service import CekSatiriInput, hesapla
        satirlar = [
            CekSatiriInput(tutar=Decimal('100000'), gercek_cek_vade_tarihi='2026-07-29',
                           para_birimi='TRY', cek_alim_tarihi='2026-07-29'),
            CekSatiriInput(tutar=Decimal('25000'), gercek_cek_vade_tarihi='2026-08-02',
                           para_birimi='TRY', cek_alim_tarihi='2026-07-29'),
        ]
        sonuc = hesapla(
            cek_satirlari=satirlar,
            para_birimi='TRY',
            onaylanan_vade_gun=30,
            sevk_tarihi=None,
            tahsilat_tipi='AVANS',
        )
        self.assertEqual(sonuc.cek_adedi, 2)
        self.assertAlmostEqual(sonuc.toplam_cek_tutari, 125000.0)
        # ağırlıklı ort = (100000×0 + 25000×4) / 125000 = 0.8 → round half-up = 1
        self.assertEqual(sonuc.agirlikli_ortalama_vade_gun_gosterim, 1)


# ---------------------------------------------------------------------------
# TestP — Paket Hedef Validation Backend Lock
# ---------------------------------------------------------------------------

class TestP_PaketHedefValidasyonLock(unittest.TestCase):
    """
    LOCK: Backend _validate_payload()
    AVANS+CEK: paket_hedef_tutar=None + zorunlu_gonder=True → HATA YOK.
    NORMAL+CEK: paket_hedef_tutar=None + zorunlu_gonder=True → HATA.
    """

    def _base_payload(self):
        return {
            'idempotency_key': 'test-idem-p',
            'cari_id': 1,
            'siparis_id': 10,
            'sevkiyat_id': None,
            'alinan_tutar': 125000.0,
            'alinan_tarih': '2026-07-29',
            'odeme_tipi': 'CEK',
            'kismi_mi': False,
            'beklenen_tutar': None,
            'paket_hedef_tutar': None,
            'kalan_tutar': None,
        }

    def test_avans_cek_no_paket_hedef_zorunlu_gonder_gecerli(self):
        """AVANS + paket_hedef=None + zorunlu_gonder=True → hata yok."""
        from modules.nexgen.mo_tahsilat_kayit_service import _validate_payload
        p = self._base_payload()
        p['tahsilat_tipi'] = 'AVANS'
        try:
            result = _validate_payload(p, zorunlu_gonder=True)
            self.assertEqual(result['tahsilat_tipi'], 'AVANS')
            self.assertIsNone(result['paket_hedef_tutar'])
        except Exception as e:
            self.fail(f"AVANS+CEK paket_hedef=None zorunlu_gonder=True hata vermemeli: {e}")

    def test_normal_cek_no_paket_hedef_zorunlu_gonder_hata(self):
        """NORMAL + paket_hedef=None + zorunlu_gonder=True → MoTahsilatError."""
        from modules.nexgen.mo_tahsilat_kayit_service import _validate_payload, MoTahsilatError
        p = self._base_payload()
        p['tahsilat_tipi'] = 'NORMAL'
        with self.assertRaises(MoTahsilatError) as ctx:
            _validate_payload(p, zorunlu_gonder=True)
        self.assertIn('hedef tutar', str(ctx.exception).lower())

    def test_avans_cek_with_paket_hedef_gecerli(self):
        """AVANS + paket_hedef girilmişse (opsiyonel) sorunsuz kabul edilir."""
        from modules.nexgen.mo_tahsilat_kayit_service import _validate_payload
        p = self._base_payload()
        p['tahsilat_tipi'] = 'AVANS'
        p['paket_hedef_tutar'] = 125000.0
        result = _validate_payload(p, zorunlu_gonder=True)
        self.assertAlmostEqual(result['paket_hedef_tutar'], 125000.0)

    def test_normal_cek_with_paket_hedef_gecerli(self):
        """NORMAL + paket_hedef girilmişse sorunsuz kabul edilir."""
        from modules.nexgen.mo_tahsilat_kayit_service import _validate_payload
        p = self._base_payload()
        p['tahsilat_tipi'] = 'NORMAL'
        p['paket_hedef_tutar'] = 125000.0
        result = _validate_payload(p, zorunlu_gonder=True)
        self.assertAlmostEqual(result['paket_hedef_tutar'], 125000.0)


# ---------------------------------------------------------------------------
# TestR — _cek_onay_validate AVANS Lock (Satır 976 root cause)
# ---------------------------------------------------------------------------

class TestR_CekOnayValidateLock(unittest.TestCase):
    """
    LOCK: _cek_onay_validate() — AVANS+CEK'te paket_hedef=None onayı bloklamasın.
    NORMAL+CEK'te paket_hedef=None onayı bloklasın.

    Bu test önceki bug'ı (satır 976 eksik AVANS kontrolü) kilitler.
    """

    def _make_avans_kayit(self, con, paket_hedef=None):
        """AVANS+CEK kaydı oluştur, id döndür."""
        tt_kolon = any(c[1] == 'tahsilat_tipi' for c in con.execute(
            "PRAGMA table_info(mo_tahsilat_kayit)"
        ).fetchall())
        if tt_kolon:
            cur = con.execute(
                "INSERT INTO mo_tahsilat_kayit "
                "(cari_id, siparis_id, tahsilat_tipi, odeme_tipi, alinan_tutar, "
                "paket_hedef_tutar, durum, idempotency_key, olusturan_id) "
                "VALUES (1, 10, 'AVANS', 'CEK', 125000.0, ?, 'TASLAK', 'r-avans-1', 99)",
                (paket_hedef,)
            )
        else:
            cur = con.execute(
                "INSERT INTO mo_tahsilat_kayit "
                "(cari_id, siparis_id, odeme_tipi, alinan_tutar, "
                "paket_hedef_tutar, durum, idempotency_key, olusturan_id) "
                "VALUES (1, 10, 'CEK', 125000.0, ?, 'TASLAK', 'r-avans-2', 99)",
                (paket_hedef,)
            )
        con.commit()
        return int(cur.lastrowid)

    def _make_normal_kayit(self, con, paket_hedef=None):
        cur = con.execute(
            "INSERT INTO mo_tahsilat_kayit "
            "(cari_id, siparis_id, odeme_tipi, alinan_tutar, "
            "paket_hedef_tutar, durum, idempotency_key, olusturan_id) "
            "VALUES (1, 10, 'CEK', 125000.0, ?, 'TASLAK', 'r-normal-1', 99)",
            (paket_hedef,)
        )
        con.commit()
        return int(cur.lastrowid)

    def test_avans_cek_no_hedef_onay_pass(self):
        """AVANS+CEK, paket_hedef=NULL, aktif çek var → _cek_onay_validate PASS."""
        from modules.nexgen.mo_tahsilat_kayit_service import _cek_onay_validate
        con = _make_con()
        kid = self._make_avans_kayit(con, paket_hedef=None)
        _insert_avans_cek(con, sira=1, tutar=125000.0, alim='2026-08-05',
                          vade='2027-01-21', cek_no='PZM-119-1', banka='Vakıf',
                          tahsilat_kayit_id=kid)
        try:
            _cek_onay_validate(con, kid)
        except Exception as e:
            self.fail(f"AVANS+CEK paket_hedef=NULL onay validate hata vermemeli: {e}")
        con.close()

    def test_normal_cek_no_hedef_onay_fail(self):
        """NORMAL+CEK, paket_hedef=NULL → _cek_onay_validate MoTahsilatError."""
        from modules.nexgen.mo_tahsilat_kayit_service import _cek_onay_validate, MoTahsilatError
        con = _make_con()
        # Normal kayıt: tahsilat_tipi kolonu varsa NORMAL, yoksa default
        tt_kolon = any(c[1] == 'tahsilat_tipi' for c in con.execute(
            "PRAGMA table_info(mo_tahsilat_kayit)"
        ).fetchall())
        if tt_kolon:
            cur = con.execute(
                "INSERT INTO mo_tahsilat_kayit "
                "(cari_id, siparis_id, tahsilat_tipi, odeme_tipi, alinan_tutar, "
                "paket_hedef_tutar, durum, idempotency_key, olusturan_id) "
                "VALUES (1, 10, 'NORMAL', 'CEK', 125000.0, NULL, 'TASLAK', 'r-normal-2', 99)"
            )
        else:
            cur = con.execute(
                "INSERT INTO mo_tahsilat_kayit "
                "(cari_id, siparis_id, odeme_tipi, alinan_tutar, "
                "paket_hedef_tutar, durum, idempotency_key, olusturan_id) "
                "VALUES (1, 10, 'CEK', 125000.0, NULL, 'TASLAK', 'r-normal-3', 99)"
            )
        con.commit()
        kid = int(cur.lastrowid)
        _insert_avans_cek(con, sira=1, tutar=125000.0, alim='2026-08-05',
                          vade='2027-01-21', cek_no='NRM-1', banka='Vakıf',
                          tahsilat_kayit_id=kid)
        with self.assertRaises(Exception) as ctx:
            _cek_onay_validate(con, kid)
        self.assertIn('hedef tutar', str(ctx.exception).lower())
        con.close()

    def test_avans_cek_no_cek_satirlari_fail(self):
        """AVANS+CEK, aktif çek yok → _cek_onay_validate hata verir (en az 1 çek zorunlu)."""
        from modules.nexgen.mo_tahsilat_kayit_service import _cek_onay_validate, MoTahsilatError
        con = _make_con()
        kid = self._make_avans_kayit(con, paket_hedef=None)
        with self.assertRaises(Exception) as ctx:
            _cek_onay_validate(con, kid)
        self.assertIn('çek', str(ctx.exception).lower())
        con.close()

    def test_avans_169_gun_pilot(self):
        """Pilot: 125.000 TL, alım 05.08.2026, vade 21.01.2027 → 169 gün."""
        from modules.nexgen.mo_vade_kontrol_service import CekSatiriInput, hesapla
        satirlar = [CekSatiriInput(
            tutar=Decimal('125000'),
            gercek_cek_vade_tarihi='2027-01-21',
            para_birimi='TRY',
            cek_alim_tarihi='2026-08-05',
        )]
        sonuc = hesapla(
            cek_satirlari=satirlar,
            para_birimi='TRY',
            onaylanan_vade_gun=30,
            sevk_tarihi=None,
            tahsilat_tipi='AVANS',
        )
        self.assertEqual(sonuc.cek_adedi, 1)
        self.assertAlmostEqual(sonuc.toplam_cek_tutari, 125000.0)
        self.assertEqual(sonuc.agirlikli_ortalama_vade_gun_gosterim, 169)
        self.assertEqual(sonuc.agirlikli_ortalama_vade_tarihi, '2027-01-21')
        self.assertEqual(sonuc.durum_kodu, 'AVANS_CEK')


# ---------------------------------------------------------------------------
# TestQ — Parent/Child Tutar Parity
# ---------------------------------------------------------------------------

class TestQ_ParentChildTutarParity(unittest.TestCase):
    """
    LOCK: AVANS+CEK — parent alinan_tutar = child toplam çek tutarı.
    1 çek × 125.000 TL → parent=125.000, child_total=125.000.
    """

    def test_parent_child_tutar_esit(self):
        """Child toplam = parent alinan_tutar → parity kanıtı."""
        con = _make_con()
        cur = con.execute(
            "INSERT INTO mo_tahsilat_kayit "
            "(cari_id, siparis_id, sevkiyat_id, tahsilat_tipi, odeme_tipi, alinan_tutar, durum, "
            "idempotency_key, olusturan_id) "
            "VALUES (1, 10, NULL, 'AVANS', 'CEK', 125000.0, 'TASLAK', 'parity-test-1', 99)"
        )
        con.commit()
        kid = int(cur.lastrowid)
        _insert_avans_cek(con, sira=1, tutar=125000.0, alim='2026-07-29', vade='2026-07-30',
                          cek_no='PZM-119-CEK-1', banka='Vakıfbank', tahsilat_kayit_id=kid)

        parent_tutar = con.execute(
            "SELECT alinan_tutar FROM mo_tahsilat_kayit WHERE id=?", (kid,)
        ).fetchone()['alinan_tutar']

        child_total = con.execute(
            "SELECT SUM(tutar) as t FROM mo_tahsilat_cek WHERE tahsilat_kayit_id=? AND aktif=1", (kid,)
        ).fetchone()['t']

        self.assertAlmostEqual(parent_tutar, 125000.0)
        self.assertAlmostEqual(child_total, 125000.0)
        self.assertAlmostEqual(parent_tutar, child_total)
        con.close()

    def test_child_tek_kayit_dogrulama(self):
        """Tek çek kaydı: tüm alanlar doğru."""
        con = _make_con()
        cur = con.execute(
            "INSERT INTO mo_tahsilat_kayit "
            "(cari_id, siparis_id, tahsilat_tipi, odeme_tipi, alinan_tutar, durum, "
            "idempotency_key, olusturan_id) "
            "VALUES (1, 10, 'AVANS', 'CEK', 125000.0, 'TASLAK', 'parity-test-2', 99)"
        )
        con.commit()
        kid = int(cur.lastrowid)
        _insert_avans_cek(con, sira=1, tutar=125000.0, alim='2026-07-29', vade='2026-07-30',
                          cek_no='CHK-119', banka='Garanti', tahsilat_kayit_id=kid)

        cek = con.execute(
            "SELECT * FROM mo_tahsilat_cek WHERE tahsilat_kayit_id=? AND aktif=1", (kid,)
        ).fetchone()

        self.assertAlmostEqual(cek['tutar'], 125000.0)
        self.assertEqual(cek['cek_alim_tarihi'], '2026-07-29')
        self.assertEqual(cek['gercek_cek_vade_tarihi'], '2026-07-30')
        self.assertEqual(cek['odeme_referansi'], 'CHK-119')
        self.assertEqual(cek['banka_adi'], 'Garanti')
        con.close()


if __name__ == "__main__":
    unittest.main()
