# -*- coding: utf-8 -*-
"""
test_cari360_genel_ozet_parity_lock.py
======================================
Cari360 Genel Bilgiler + üst KPI özet parity kontrat kilitleri.
25+ kontrat — temporary SQLite / template fixture, canonical DB write yok.
"""
from __future__ import annotations

import re
import sqlite3
import sys
import unittest
from pathlib import Path

SVC = Path(__file__).resolve().parents[2] / 'app'
TMPL = SVC / 'templates' / 'nexgen' / 'cari360_kart.html'
YK = {'*'}

_CARI_ID = 5
_PASIF_CARI_ID = 6
_ADMIN_UID = 1


def _format_tr_sayi(n, ondalik=None) -> str:
    """JS formatTrSayi ile aynı kural (template parity)."""
    if n is None or n == '':
        return ''
    num = float(n)
    if ondalik is not None:
        s = f'{num:.{ondalik}f}'.replace('.', ',')
    elif num == int(num):
        s = str(int(num))
    else:
        s = str(num).replace('.', ',')
    parts = s.split(',')
    parts[0] = re.sub(r'\B(?=(\d{3})+(?!\d))', '.', parts[0])
    return ','.join(parts)


def _build_fixture_db() -> sqlite3.Connection:
    con = sqlite3.connect(':memory:')
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE sistem_kullanici (
            Id INTEGER PRIMARY KEY,
            KullaniciAdi TEXT,
            AdSoyad TEXT,
            RolId INTEGER,
            Aktif INTEGER DEFAULT 1
        );
        INSERT INTO sistem_kullanici (Id, KullaniciAdi, AdSoyad, RolId, Aktif)
        VALUES (1, 'admin', 'Admin', NULL, 1),
               (49, 'erhan', 'Erhan Atlar', NULL, 1),
               (50, 'yedek', 'Yedek Pazarlamaci', NULL, 1);

        CREATE TABLE cari_yetkili (
            id INTEGER PRIMARY KEY,
            cari_id INTEGER,
            ad_soyad TEXT,
            aktif INTEGER DEFAULT 1
        );

        CREATE TABLE nexgen_cari (
            id INTEGER PRIMARY KEY,
            cari_kod TEXT,
            unvan TEXT,
            kisa_ad TEXT,
            aktif INTEGER DEFAULT 1,
            created_at TEXT,
            updated_at TEXT,
            telefon TEXT,
            eposta TEXT
        );
        INSERT INTO nexgen_cari (id, cari_kod, unvan, aktif, created_at, updated_at, telefon, eposta)
        VALUES (5, '120.NX.009', '3E Ayakkabı Taban San.Tic.Ltd.Şti', 1,
                '2026-06-24 00:50:55', '2026-06-24 00:50:55', NULL, NULL);
        INSERT INTO nexgen_cari (id, cari_kod, unvan, aktif, created_at, updated_at)
        VALUES (6, 'PASIF-001', 'Pasif Firma', 0, '2026-01-01', '2026-01-01');

        CREATE TABLE cari_sorumlu (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cari_id INTEGER,
            kullanici_id INTEGER,
            sorumluluk_rolu TEXT,
            aktif INTEGER DEFAULT 1,
            bitis_tarihi TEXT,
            baslangic_tarihi TEXT,
            created_at TEXT,
            atayan_kullanici_id INTEGER
        );
        INSERT INTO cari_sorumlu (cari_id, kullanici_id, sorumluluk_rolu, aktif, baslangic_tarihi)
        VALUES (5, 50, 'YEDEK', 1, '2026-01-01');
        INSERT INTO cari_sorumlu (cari_id, kullanici_id, sorumluluk_rolu, aktif, baslangic_tarihi)
        VALUES (5, 49, 'ANA', 1, '2026-02-01');

        CREATE TABLE nexgen_planlama_siparis (
            id INTEGER PRIMARY KEY,
            siparis_no TEXT,
            cari_id INTEGER,
            durum TEXT,
            olusturma_tarihi TEXT
        );
        INSERT INTO nexgen_planlama_siparis (id, siparis_no, cari_id, durum, olusturma_tarihi)
        VALUES (101, 'SIP-AKTIF', 5, 'ONAYLANDI', '2026-07-01'),
               (102, 'SIP-TAMAM', 5, 'TAMAMLANDI', '2026-06-01'),
               (103, 'SIP-IPTAL', 5, 'IPTAL', '2026-05-01');

        CREATE TABLE mo_musteri_sevkiyat (
            id INTEGER PRIMARY KEY,
            sevkiyat_no TEXT,
            cari_id INTEGER,
            siparis_id INTEGER,
            durum TEXT,
            aktif INTEGER DEFAULT 1,
            sevk_tarihi TEXT,
            olusturma_tarihi TEXT
        );
        INSERT INTO mo_musteri_sevkiyat (id, sevkiyat_no, cari_id, siparis_id, durum, aktif,
               sevk_tarihi, olusturma_tarihi)
        VALUES (226, 'MSV-HAZ', 5, 101, 'HAZIRLANIYOR', 1, NULL, '2026-08-10 08:23:01'),
               (227, 'MSV-SEVK', 5, 101, 'SEVK_EDILDI', 1, '2026-08-10', '2026-08-10 08:23:22');

        CREATE TABLE mo_musteri_sevkiyat_kalem (
            id INTEGER PRIMARY KEY,
            sevkiyat_id INTEGER,
            siparis_kalem_id INTEGER,
            urun_adi TEXT,
            miktar_kg REAL
        );
        INSERT INTO mo_musteri_sevkiyat_kalem (id, sevkiyat_id, siparis_kalem_id, urun_adi, miktar_kg)
        VALUES (1, 226, 1, 'Urun', 3000.0),
               (2, 227, 1, 'Urun', 3000.0);

        CREATE TABLE musteri_operasyon_gorusme (
            id INTEGER PRIMARY KEY,
            cari_id INTEGER,
            kullanici_id INTEGER,
            gorusme_tarihi TEXT,
            gorusme_tipi TEXT,
            takip_durumu TEXT DEFAULT 'BEKLEMEDE',
            aktif INTEGER DEFAULT 1
        );
        INSERT INTO musteri_operasyon_gorusme (id, cari_id, kullanici_id, gorusme_tarihi, gorusme_tipi, aktif)
        VALUES (648, 5, 49, '2026-08-10 08:17:52', 'Telefon', 1),
               (650, 5, 49, '2026-08-10 12:41:00', 'Fabrika Ziyareti', 1),
               (651, 5, 49, '2026-08-10 12:41:00', 'Telefon', 1);

        CREATE TABLE musteri_operasyon_ajanda (
            id INTEGER PRIMARY KEY,
            cari_id INTEGER,
            kullanici_id INTEGER NOT NULL,
            plan_tarihi TEXT NOT NULL,
            gorusme_tipi TEXT NOT NULL,
            plan_notu TEXT,
            durum TEXT NOT NULL DEFAULT 'PLANLANDI',
            gorusme_id INTEGER,
            idempotency_key TEXT NOT NULL UNIQUE,
            aktif INTEGER NOT NULL DEFAULT 1,
            plan_yetkili_metin TEXT
        );
        INSERT INTO musteri_operasyon_ajanda
               (id, cari_id, kullanici_id, plan_tarihi, gorusme_tipi, plan_notu, durum,
                gorusme_id, idempotency_key, aktif)
        VALUES (11, 5, 49, '2026-08-22 09:00:00', 'WhatsApp', 'plan', 'PLANLANDI',
                NULL, 'plan-11', 1);

        CREATE TABLE sistem_rol (Id INTEGER PRIMARY KEY, Ad TEXT);
        CREATE TABLE sistem_yetki (Id INTEGER PRIMARY KEY, Kod TEXT);
        CREATE TABLE user_permission_override (
            Id INTEGER PRIMARY KEY, KullaniciId INTEGER, YetkiId INTEGER,
            can_view INTEGER DEFAULT 0, can_create INTEGER DEFAULT 0,
            can_update INTEGER DEFAULT 0, can_delete INTEGER DEFAULT 0,
            can_approve INTEGER DEFAULT 0, can_report INTEGER DEFAULT 0,
            can_manage INTEGER DEFAULT 0
        );
        CREATE TABLE sistem_rol_yetki (
            Id INTEGER PRIMARY KEY, RolId INTEGER, YetkiId INTEGER,
            can_view INTEGER DEFAULT 0, can_create INTEGER DEFAULT 0,
            can_update INTEGER DEFAULT 0, can_delete INTEGER DEFAULT 0,
            can_approve INTEGER DEFAULT 0, can_report INTEGER DEFAULT 0,
            can_manage INTEGER DEFAULT 0
        );
    """)
    con.commit()
    return con


def _kg_ozet_db(extra_sql: str = '') -> sqlite3.Connection:
    """Minimal schema — load_cari360_ozet toplam_sevk_kg senaryoları."""
    con = sqlite3.connect(':memory:')
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE nexgen_cari (
            id INTEGER PRIMARY KEY,
            cari_kod TEXT,
            unvan TEXT,
            aktif INTEGER DEFAULT 1,
            created_at TEXT,
            updated_at TEXT
        );
        INSERT INTO nexgen_cari (id, cari_kod, unvan, aktif, created_at, updated_at)
        VALUES (1, 'KG-TEST', 'KG Test Cari', 1, '2026-01-01', '2026-01-01');

        CREATE TABLE nexgen_planlama_siparis (
            id INTEGER PRIMARY KEY,
            siparis_no TEXT,
            cari_id INTEGER,
            durum TEXT,
            olusturma_tarihi TEXT
        );

        CREATE TABLE nexgen_planlama_siparis_kalem (
            id INTEGER PRIMARY KEY,
            planlama_siparis_id INTEGER,
            siparis_id INTEGER,
            miktar_l REAL DEFAULT 0
        );

        CREATE TABLE nexgen_uretim_plan (
            id INTEGER PRIMARY KEY,
            planlama_siparis_id INTEGER,
            durum TEXT,
            plan_kodu TEXT
        );

        CREATE TABLE nexgen_rf_kullanim (
            id INTEGER PRIMARY KEY,
            plan_id INTEGER,
            uretilen_kg REAL
        );

        CREATE TABLE mo_musteri_sevkiyat (
            id INTEGER PRIMARY KEY,
            sevkiyat_no TEXT,
            cari_id INTEGER,
            siparis_id INTEGER,
            durum TEXT,
            aktif INTEGER DEFAULT 1,
            sevk_tarihi TEXT,
            olusturma_tarihi TEXT
        );

        CREATE TABLE mo_musteri_sevkiyat_kalem (
            id INTEGER PRIMARY KEY,
            sevkiyat_id INTEGER,
            siparis_kalem_id INTEGER,
            urun_adi TEXT,
            miktar_kg REAL
        );
    """ + extra_sql)
    con.commit()
    return con


def _load_kpi_sevk_kg(con: sqlite3.Connection, cari_id: int = 1) -> float:
    from modules.nexgen.cari360_ops_read_service import load_cari360_ozet

    oz = load_cari360_ozet(con, cari_id, _ADMIN_UID, YK)
    return float(oz['kpi']['toplam_sevk_kg'])


class GenelOzetParityLockTests(unittest.TestCase):
    """25 kontrat — Genel Bilgiler + üst KPI özet parity."""

    src: str
    con: sqlite3.Connection
    kart: dict
    ozet: dict

    @classmethod
    def setUpClass(cls) -> None:
        if str(SVC) not in sys.path:
            sys.path.insert(0, str(SVC))
        cls.src = TMPL.read_text(encoding='utf-8')
        cls.con = _build_fixture_db()
        from modules.nexgen.cari360_kart_service import load_cari_kart
        from modules.nexgen.cari360_ops_read_service import load_cari360_ozet

        cls.kart = load_cari_kart(cls.con, _CARI_ID, _ADMIN_UID, YK)
        cls.ozet = load_cari360_ozet(cls.con, _CARI_ID, _ADMIN_UID, YK)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.con.close()

    # 1 — Cari kimliği nexgen_cari kaynağı
    def test_01_cari_kimligi_nexgen_cari(self) -> None:
        row = self.con.execute('SELECT id FROM nexgen_cari WHERE id=?', (_CARI_ID,)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(self.kart['cari']['id'], _CARI_ID)

    # 2 — Cari kodu
    def test_02_cari_kodu(self) -> None:
        self.assertEqual(self.kart['cari']['cari_kod'], '120.NX.009')

    # 3 — Unvan
    def test_03_unvan(self) -> None:
        self.assertEqual(self.kart['cari']['unvan'], '3E Ayakkabı Taban San.Tic.Ltd.Şti')

    # 4 — Aktif/pasif durumu
    def test_04_aktif_pasif(self) -> None:
        self.assertEqual(self.kart['cari']['aktif'], 1)
        pasif = self.con.execute(
            'SELECT aktif FROM nexgen_cari WHERE id=?', (_PASIF_CARI_ID,)
        ).fetchone()
        self.assertEqual(int(pasif['aktif']), 0)

    # 5 — Sorumlu pazarlamacı cari_sorumlu kaynağı
    def test_05_sorumlu_canonical(self) -> None:
        self.assertEqual(self.kart['sorumlu_adi'], 'Erhan Atlar')
        cnt = self.con.execute(
            'SELECT COUNT(*) FROM cari_sorumlu WHERE cari_id=? AND aktif=1', (_CARI_ID,)
        ).fetchone()[0]
        self.assertGreaterEqual(cnt, 1)

    # 6 — ANA sorumlu önceliği
    def test_06_ana_sorumlu_onceligi(self) -> None:
        self.assertEqual(self.kart['sorumlu']['sorumluluk_rolu'], 'ANA')
        self.assertEqual(self.kart['sorumlu_adi'], 'Erhan Atlar')

    # 7 — Toplam Sipariş canonical count
    def test_07_toplam_siparis(self) -> None:
        db_cnt = self.con.execute(
            'SELECT COUNT(*) FROM nexgen_planlama_siparis WHERE cari_id=?', (_CARI_ID,)
        ).fetchone()[0]
        self.assertEqual(self.ozet['kpi']['toplam_siparis'], db_cnt)
        self.assertEqual(self.ozet['kpi']['toplam_siparis'], 3)

    # 8 — Aktif Sipariş pasif durumları dışlar
    def test_08_aktif_siparis_pasif_dislar(self) -> None:
        self.assertEqual(self.ozet['kpi']['aktif_siparis'], 1)

    # 9 — TAMAMLANDI aktif sayılmaz
    def test_09_tamamlandi_aktif_degil(self) -> None:
        pasif = {'TAMAMLANDI', 'IPTAL', 'REDDEDILDI', 'IPTAL_EDILDI', 'KAPANDI', 'IPTALEDILDI'}
        rows = self.con.execute(
            'SELECT durum FROM nexgen_planlama_siparis WHERE cari_id=?', (_CARI_ID,)
        ).fetchall()
        aktif_cnt = sum(1 for r in rows if (r['durum'] or '').upper() not in pasif)
        self.assertEqual(self.ozet['kpi']['aktif_siparis'], aktif_cnt)

    # 10 — IPTAL aktif sayılmaz
    def test_10_iptal_aktif_degil(self) -> None:
        iptal = self.con.execute(
            "SELECT COUNT(*) FROM nexgen_planlama_siparis WHERE cari_id=? AND durum='IPTAL'",
            (_CARI_ID,),
        ).fetchone()[0]
        self.assertEqual(iptal, 1)
        self.assertEqual(self.ozet['kpi']['aktif_siparis'], 1)

    # 11 — Toplam Sevkiyat yalnız gerçekleşmiş
    def test_11_toplam_sevkiyat_gerceklesmis(self) -> None:
        self.assertEqual(self.ozet['kpi']['toplam_sevkiyat'], 1)

    # 12 — HAZIRLANIYOR Toplam Sevkiyata girmez
    def test_12_hazirlaniyor_sayiya_girmez(self) -> None:
        haz = self.con.execute(
            "SELECT COUNT(*) FROM mo_musteri_sevkiyat WHERE cari_id=? AND durum='HAZIRLANIYOR'",
            (_CARI_ID,),
        ).fetchone()[0]
        self.assertEqual(haz, 1)
        self.assertEqual(self.ozet['kpi']['toplam_sevkiyat'], 1)

    # 13 — Toplam Sevk KG yalnız gerçekleşmiş kalemler
    def test_13_toplam_sevk_kg_gerceklesmis(self) -> None:
        self.assertEqual(float(self.ozet['kpi']['toplam_sevk_kg']), 3000.0)

    # 14 — HAZIRLANIYOR KG toplama girmez
    def test_14_hazirlaniyor_kg_girmez(self) -> None:
        self.assertNotEqual(float(self.ozet['kpi']['toplam_sevk_kg']), 6000.0)

    # 15 — Son Sevkiyat yalnız gerçekleşmiş
    def test_15_son_sevkiyat_gerceklesmis(self) -> None:
        self.assertEqual(self.ozet['kpi']['son_sevkiyat_tarihi'], '2026-08-10')

    # 16 — Son Görüşme gorusme_tarihi DESC, id DESC
    def test_16_son_gorusme_siralama(self) -> None:
        self.assertEqual(self.ozet['kpi']['son_gorusme_tarihi'], '2026-08-10 12:41')
        top = self.con.execute(
            """
            SELECT id, gorusme_tarihi FROM musteri_operasyon_gorusme
            WHERE cari_id=? AND COALESCE(aktif,1)=1
            ORDER BY gorusme_tarihi DESC, id DESC LIMIT 1
            """,
            (_CARI_ID,),
        ).fetchone()
        self.assertEqual(int(top['id']), 651)

    # 17 — PLANLANDI Ajanda Son Görüşmeye girmez
    def test_17_planli_ajanda_son_goruse_girmez(self) -> None:
        plan = self.con.execute(
            """
            SELECT plan_tarihi FROM musteri_operasyon_ajanda
            WHERE cari_id=? AND durum='PLANLANDI' AND aktif=1
            ORDER BY plan_tarihi DESC LIMIT 1
            """,
            (_CARI_ID,),
        ).fetchone()
        self.assertIsNotNone(plan)
        self.assertNotIn('2026-08-22', self.ozet['kpi']['son_gorusme_tarihi'] or '')

    # 18 — Genel Bilgiler null alanları — template
    def test_18_genel_null_dash(self) -> None:
        self.assertIn("{{ c.telefon or '—' }}", self.src)
        self.assertIn("{{ c.eposta or '—' }}", self.src)
        self.assertIsNone(self.kart['cari']['telefon'])

    # 19 — Template KPI KG formatTrSayi kullanır
    def test_19_template_kg_formatTrSayi(self) -> None:
        m = re.search(
            r"setText\('kpi-toplam-sevk-kg',\s*formatTrSayi\([^)]+\)\)",
            self.src,
        )
        self.assertIsNotNone(m, 'kpi-toplam-sevk-kg formatTrSayi ile render edilmeli')

    # 20 — 3000 → 3.000
    def test_20_kg_3000_tr_format(self) -> None:
        self.assertEqual(_format_tr_sayi(3000), '3.000')
        self.assertEqual(_format_tr_sayi(self.ozet['kpi']['toplam_sevk_kg']), '3.000')

    # 21 — 3000.5 → 3.000,5
    def test_21_kg_3000_5_tr_format(self) -> None:
        self.assertEqual(_format_tr_sayi(3000.5), '3.000,5')

    # 22 — 0 → 0
    def test_22_kg_sifir_format(self) -> None:
        self.assertEqual(_format_tr_sayi(0), '0')

    # 23 — KPI her tab geçişinde fresh ozet
    def test_23_tab_fresh_ozet(self) -> None:
        idx = self.src.find('window.ckartTab = function(tab)')
        blk = self.src[idx: idx + 2500]
        self.assertIn('ckartOzetYukle()', blk)

    # 24 — Genel Bilgiler alan başlıkları
    def test_24_genel_basliklar(self) -> None:
        for lbl in (
            'Firma Bilgileri',
            'İletişim ve Adres',
            'Ticari / Resmi Bilgiler',
            'Cari kodu',
            'İç sorumlu pazarlamacı',
        ):
            self.assertIn(lbl, self.src)

    # 25 — Sekme davranışları korunur
    def test_25_sekme_davranislari(self) -> None:
        tab_blk = self.src[self.src.find('window.ckartTab = function(tab)'):][:2500]
        self.assertIn("tab === 'siparisler'", tab_blk)
        self.assertIn('ckartSiparisYukle(true)', tab_blk)
        self.assertIn("tab === 'sevkiyatlar'", tab_blk)
        self.assertIn('ckartSevkYukle(true)', tab_blk)
        self.assertIn("tab === 'gorusmeler'", tab_blk)
        self.assertIn('ckartGorusmeYukle(true)', tab_blk)


class KpiSevkKgCanonicalContractTests(unittest.TestCase):
    """Canonical Toplam Sevk KG kontratları — izole in-memory fixture."""

    @classmethod
    def setUpClass(cls) -> None:
        if str(SVC) not in sys.path:
            sys.path.insert(0, str(SVC))

    # 26 — Sipariş KG sevk KG yerine kullanılmaz
    def test_26_siparis_kg_sevk_kg_yerine_kullanilmaz(self) -> None:
        con = _kg_ozet_db("""
            INSERT INTO nexgen_planlama_siparis (id, siparis_no, cari_id, durum, olusturma_tarihi)
            VALUES (10, 'SIP-5000', 1, 'ONAYLANDI', '2026-07-01');
            INSERT INTO nexgen_planlama_siparis_kalem (id, planlama_siparis_id, siparis_id, miktar_l)
            VALUES (100, 10, 10, 5000.0);
            INSERT INTO mo_musteri_sevkiyat (id, sevkiyat_no, cari_id, siparis_id, durum, aktif, sevk_tarihi)
            VALUES (1, 'MSV-1', 1, 10, 'SEVK_EDILDI', 1, '2026-08-10');
            INSERT INTO mo_musteri_sevkiyat_kalem (id, sevkiyat_id, siparis_kalem_id, urun_adi, miktar_kg)
            VALUES (1, 1, 100, 'Urun', 2987.5);
        """)
        try:
            kg = _load_kpi_sevk_kg(con)
            self.assertEqual(kg, 2987.5)
            self.assertNotEqual(kg, 5000.0)
        finally:
            con.close()

    # 27 — Üretilen KG sevk KG yerine kullanılmaz
    def test_27_uretim_kg_sevk_kg_yerine_kullanilmaz(self) -> None:
        con = _kg_ozet_db("""
            INSERT INTO nexgen_planlama_siparis (id, siparis_no, cari_id, durum, olusturma_tarihi)
            VALUES (10, 'SIP-U', 1, 'ONAYLANDI', '2026-07-01');
            INSERT INTO nexgen_planlama_siparis_kalem (id, planlama_siparis_id, siparis_id, miktar_l)
            VALUES (100, 10, 10, 3000.0);
            INSERT INTO nexgen_uretim_plan (id, planlama_siparis_id, durum, plan_kodu)
            VALUES (5, 10, 'DEVAM', 'NP-01');
            INSERT INTO nexgen_rf_kullanim (id, plan_id, uretilen_kg)
            VALUES (1, 5, 3055.9);
            INSERT INTO mo_musteri_sevkiyat (id, sevkiyat_no, cari_id, siparis_id, durum, aktif, sevk_tarihi)
            VALUES (1, 'MSV-1', 1, 10, 'SEVK_EDILDI', 1, '2026-08-10');
            INSERT INTO mo_musteri_sevkiyat_kalem (id, sevkiyat_id, siparis_kalem_id, urun_adi, miktar_kg)
            VALUES (1, 1, 100, 'Urun', 3000.0);
        """)
        try:
            kg = _load_kpi_sevk_kg(con)
            self.assertEqual(kg, 3000.0)
            self.assertNotEqual(kg, 3055.9)
        finally:
            con.close()

    # 28 — SEVK_EDILDI 3000 + HAZIRLANIYOR 3000 → KPI tam 3000
    def test_28_sevk_edildi_3000_hazirlaniyor_3000_kpi_3000(self) -> None:
        con = _kg_ozet_db("""
            INSERT INTO mo_musteri_sevkiyat (id, sevkiyat_no, cari_id, siparis_id, durum, aktif, sevk_tarihi)
            VALUES (1, 'MSV-HAZ', 1, NULL, 'HAZIRLANIYOR', 1, NULL),
                   (2, 'MSV-SEVK', 1, NULL, 'SEVK_EDILDI', 1, '2026-08-10');
            INSERT INTO mo_musteri_sevkiyat_kalem (id, sevkiyat_id, siparis_kalem_id, urun_adi, miktar_kg)
            VALUES (1, 1, NULL, 'Urun', 3000.0),
                   (2, 2, NULL, 'Urun', 3000.0);
        """)
        try:
            kg = _load_kpi_sevk_kg(con)
            self.assertEqual(kg, 3000.0)
            self.assertNotEqual(kg, 6000.0)
        finally:
            con.close()

    # 29 — Sipariş 3000, gerçek sevk 2987.5 → KPI tam 2987.5
    def test_29_siparis_3000_gercek_sevk_2987_5(self) -> None:
        con = _kg_ozet_db("""
            INSERT INTO nexgen_planlama_siparis (id, siparis_no, cari_id, durum, olusturma_tarihi)
            VALUES (10, 'SIP-3000', 1, 'ONAYLANDI', '2026-07-01');
            INSERT INTO nexgen_planlama_siparis_kalem (id, planlama_siparis_id, siparis_id, miktar_l)
            VALUES (100, 10, 10, 3000.0);
            INSERT INTO mo_musteri_sevkiyat (id, sevkiyat_no, cari_id, siparis_id, durum, aktif, sevk_tarihi)
            VALUES (1, 'MSV-1', 1, 10, 'SEVK_EDILDI', 1, '2026-08-10');
            INSERT INTO mo_musteri_sevkiyat_kalem (id, sevkiyat_id, siparis_kalem_id, urun_adi, miktar_kg)
            VALUES (1, 1, 100, 'Urun', 2987.5);
        """)
        try:
            kg = _load_kpi_sevk_kg(con)
            self.assertEqual(kg, 2987.5)
            self.assertNotEqual(kg, 3000.0)
        finally:
            con.close()

    # 30 — Üretim 3055.9, gerçek sevk 3000 → KPI tam 3000
    def test_30_uretim_3055_9_gercek_sevk_3000(self) -> None:
        con = _kg_ozet_db("""
            INSERT INTO nexgen_planlama_siparis (id, siparis_no, cari_id, durum, olusturma_tarihi)
            VALUES (10, 'SIP-3000', 1, 'ONAYLANDI', '2026-07-01');
            INSERT INTO nexgen_planlama_siparis_kalem (id, planlama_siparis_id, siparis_id, miktar_l)
            VALUES (100, 10, 10, 3000.0);
            INSERT INTO nexgen_uretim_plan (id, planlama_siparis_id, durum, plan_kodu)
            VALUES (5, 10, 'DEVAM', 'NP-01');
            INSERT INTO nexgen_rf_kullanim (id, plan_id, uretilen_kg)
            VALUES (1, 5, 3055.9);
            INSERT INTO mo_musteri_sevkiyat (id, sevkiyat_no, cari_id, siparis_id, durum, aktif, sevk_tarihi)
            VALUES (1, 'MSV-1', 1, 10, 'SEVK_EDILDI', 1, '2026-08-10');
            INSERT INTO mo_musteri_sevkiyat_kalem (id, sevkiyat_id, siparis_kalem_id, urun_adi, miktar_kg)
            VALUES (1, 1, 100, 'Urun', 3000.0);
        """)
        try:
            kg = _load_kpi_sevk_kg(con)
            self.assertEqual(kg, 3000.0)
        finally:
            con.close()

    # 31 — İki gerçekleşmiş kısmi sevkiyat → tam 2950.75
    def test_31_iki_kismi_sevkiyat_2950_75(self) -> None:
        con = _kg_ozet_db("""
            INSERT INTO mo_musteri_sevkiyat (id, sevkiyat_no, cari_id, siparis_id, durum, aktif, sevk_tarihi)
            VALUES (1, 'MSV-A', 1, NULL, 'SEVK_EDILDI', 1, '2026-08-01'),
                   (2, 'MSV-B', 1, NULL, 'SEVK_EDILDI', 1, '2026-08-10');
            INSERT INTO mo_musteri_sevkiyat_kalem (id, sevkiyat_id, siparis_kalem_id, urun_adi, miktar_kg)
            VALUES (1, 1, NULL, 'Urun', 1200.5),
                   (2, 2, NULL, 'Urun', 1750.25);
        """)
        try:
            kg = _load_kpi_sevk_kg(con)
            self.assertAlmostEqual(kg, 2950.75, places=2)
        finally:
            con.close()

    # 32 — Template format: 2987.5 → 2.987,5
    def test_32_template_format_2987_5(self) -> None:
        self.assertEqual(_format_tr_sayi(2987.5), '2.987,5')

    # 33 — Template format: 2950.75 → 2.950,75
    def test_33_template_format_2950_75(self) -> None:
        self.assertEqual(_format_tr_sayi(2950.75), '2.950,75')


if __name__ == '__main__':
    unittest.main()
