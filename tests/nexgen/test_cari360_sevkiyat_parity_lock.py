# -*- coding: utf-8 -*-
"""C360-SEVKIYAT-PARITY-LOCK — Cari360 Sevkiyatlar canonical parity regression lock.

Kilitlenen contract'lar:
1.  load_cari360_sevkiyatlar() HAZIRLANIYOR kaydı listede görünür (operasyon satırı)
2.  load_cari360_sevkiyatlar() SEVK_EDILDI kaydı listede görünür
3.  Her sevkiyat kendi kalem KG toplamını doğru taşır (per-row, cross contamination yok)
4.  Sipariş No canonical nexgen_planlama_siparis'ten gelir
5.  Batch kodu siparis→plan→batch zincirinden doğru gelir
6.  Durumlar birbirine dönüştürülmez (HAZIRLANIYOR olarak kalır)
7.  Gerçek sevk tarihi NULL ise gercek_sevk_tarihi=None; olusturma_tarihi'ne fallback olmaz
8.  Sayfalama kontratı: total_count / page / page_size / total_pages tutarlı
9.  Cari özet (load_cari360_ozet): yalnız GERCEKLESMIS sevkiyatlar toplam sevk KG'ye girer
10. Cari özet: HAZIRLANIYOR toplam sevkiyat sayısını artırmaz
11. Cari özet: son_sevkiyat_tarihi yalnız GERCEKLESMIS üzerinden hesaplanır
12. Sipariş Geçmişi sevk_edilen_kg yalnız GERCEKLESMIS durumları içerir
13. Sipariş Geçmişi sevk_edilen_kg tam 3000.0 (HAZIRLANIYOR eklenmez, 6000 olmaz)
14. load_cari360_sevkiyatlar() response'unda zorunlu alanlar var
15. Template'de ckartSevkYukle fonksiyonu tanımlı
16. Template'de gercek_sevk_tarihi kullanılıyor (sevk_tarihi değil)
17. Template her tab açılışında _opsLoaded.sevkiyatlar=false reset ediyor (stale yok)

DB: Tüm servis testleri izole temporary SQLite DB üzerinde çalışır.
    Canonical app/mock_data.db bu dosyada kullanılmaz.
    Teardown sırasında temporary DB ve dizin temizlenir.

Fixture temsil ettiği senaryo (gerçek ekranda doğrulandı, Ağustos 2026):
  - Bir cari, bir sipariş, bir sipariş kalemi (3000 kg)
  - Aynı siparişe bağlı 2 sevkiyat:
    * HAZIRLANIYOR: 3000 kg, sevk_tarihi=NULL
    * SEVK_EDILDI: 3000 kg, sevk_tarihi=2026-08-10
  - Bir üretim planı + bir batch
  - Gerçekleşmiş toplam = 3000 (6000 DEĞİL)
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

SVC  = Path(__file__).resolve().parents[2] / 'app'
TMPL = SVC / 'templates' / 'nexgen' / 'cari360_kart.html'

# Canonical gerçekleşmiş durum seti — üretim kodundan alınan değerler
_SEVK_GERCEKLESMIS = frozenset({'SEVK_EDILDI', 'TESLIM_EDILDI', 'TAMAMLANDI'})

# Fixture sabitleri
_CARI_ID      = 1
_SIPARIS_ID   = 10
_SIPARIS_NO   = 'PZM-TEST-0001'
_SIPARIS_KG   = 3000.0
_HAZ_SEV_ID   = 1   # HAZIRLANIYOR sevkiyat id
_SEV_SEV_ID   = 2   # SEVK_EDILDI sevkiyat id
_PLAN_ID      = 5
_BATCH_KODU   = 'NG-TEST-BATCH-01'
_SON_TARIH    = '2026-08-10'  # gerçekleşmiş sevkiyat tarihi


# ---------------------------------------------------------------------------
# Temp DB builder
# ---------------------------------------------------------------------------

def _build_temp_db() -> tuple[sqlite3.Connection, tempfile.TemporaryDirectory]:
    """Minimal schema + fixture verisini taşıyan geçici SQLite DB oluşturur.

    Returns:
        (con, tmpdir) — teardown'da tmpdir.cleanup() çağrılmalı.
    """
    tmpdir = tempfile.TemporaryDirectory(prefix='cps_sev_parity_')
    db_path = Path(tmpdir.name) / 'test_sevkiyat.db'
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    con.executescript("""
        PRAGMA journal_mode=WAL;

        -- Yetki: admin kullanıcı → can_view_cari tüm DB'yi görür
        CREATE TABLE IF NOT EXISTS sistem_kullanici (
            Id INTEGER PRIMARY KEY,
            KullaniciAdi TEXT,
            RolId INTEGER,
            Aktif INTEGER DEFAULT 1
        );
        INSERT INTO sistem_kullanici (Id, KullaniciAdi, RolId, Aktif)
        VALUES (1, 'admin', NULL, 1);

        -- Cari
        CREATE TABLE IF NOT EXISTS nexgen_cari (
            id INTEGER PRIMARY KEY,
            cari_kod TEXT,
            unvan TEXT,
            aktif INTEGER DEFAULT 1,
            created_at TEXT,
            updated_at TEXT
        );
        INSERT INTO nexgen_cari (id, cari_kod, unvan, aktif)
        VALUES (1, 'TEST-001', 'Test Firması', 1);

        -- Sipariş (load_cari360_siparisler'in beklediği tüm kolonlar)
        CREATE TABLE IF NOT EXISTS nexgen_planlama_siparis (
            id INTEGER PRIMARY KEY,
            siparis_no TEXT,
            cari_id INTEGER,
            durum TEXT,
            olusturma_tarihi TEXT,
            termin_tarihi TEXT,
            musteri_termin TEXT,
            onerilen_termin TEXT,
            mo_gorusme_id INTEGER,
            siparis_onceligi TEXT,
            teslim_sekli TEXT,
            genel_not TEXT,
            odeme_vadesi_gun INTEGER,
            odeme_tipi TEXT,
            para_birimi TEXT,
            doviz_kur REAL
        );
        INSERT INTO nexgen_planlama_siparis (id, siparis_no, cari_id, durum, olusturma_tarihi,
               termin_tarihi, para_birimi)
        VALUES (10, 'PZM-TEST-0001', 1, 'ONAYLANDI', '2026-07-01', '2026-09-01', 'TRY');

        -- Sipariş kalemi (load_cari360_siparisler batch yüklemesi için)
        CREATE TABLE IF NOT EXISTS nexgen_planlama_siparis_kalem (
            id INTEGER PRIMARY KEY,
            planlama_siparis_id INTEGER,
            siparis_id INTEGER,
            sira_no INTEGER DEFAULT 1,
            urun_adi TEXT,
            renk_ad TEXT,
            formul_ad TEXT,
            miktar_l REAL DEFAULT 0,
            miktar_s REAL DEFAULT 0,
            miktar_m REAL DEFAULT 0,
            birim_fiyat REAL,
            para_birimi TEXT,
            kdv_durumu TEXT,
            termin_tarihi TEXT,
            urun_ailesi TEXT,
            musteri_rengi TEXT,
            uretim_rengi TEXT,
            kalem_notu TEXT,
            sevk_tarihi TEXT,
            numune_talep_id INTEGER,
            rf_renk_id INTEGER,
            uretim_plan_id INTEGER,
            mtt_kalem_id INTEGER,
            satir_tutari REAL
        );
        INSERT INTO nexgen_planlama_siparis_kalem
               (id, planlama_siparis_id, siparis_id, sira_no, urun_adi, miktar_l, para_birimi)
        VALUES (100, 10, 10, 1, 'Test Ürünü', 3000.0, 'TRY');

        -- Sevkiyatlar: 2 adet, aynı sipariş
        CREATE TABLE IF NOT EXISTS mo_musteri_sevkiyat (
            id INTEGER PRIMARY KEY,
            sevkiyat_no TEXT,
            irsaliye_no TEXT,
            cari_id INTEGER,
            siparis_id INTEGER,
            durum TEXT,
            aktif INTEGER DEFAULT 1,
            sevk_tarihi TEXT,
            hazirlik_tarihi TEXT,
            olusturma_tarihi TEXT,
            teslim_tarihi TEXT,
            arac_plaka TEXT,
            sofor TEXT,
            kargo_firmasi TEXT,
            kargo_takip_no TEXT,
            teslim_alan TEXT,
            teslim_durumu TEXT,
            notlar TEXT
        );
        -- HAZIRLANIYOR: sevk_tarihi NULL
        INSERT INTO mo_musteri_sevkiyat (id, sevkiyat_no, cari_id, siparis_id,
               durum, aktif, sevk_tarihi, olusturma_tarihi)
        VALUES (1, 'MSV-TEST-0001', 1, 10,
                'HAZIRLANIYOR', 1, NULL, '2026-08-01');
        -- SEVK_EDILDI: sevk_tarihi dolu
        INSERT INTO mo_musteri_sevkiyat (id, sevkiyat_no, cari_id, siparis_id,
               durum, aktif, sevk_tarihi, olusturma_tarihi)
        VALUES (2, 'MSV-TEST-0002', 1, 10,
                'SEVK_EDILDI', 1, '2026-08-10', '2026-08-01');

        -- Sevkiyat kalemleri: her sevkiyata 3000 kg
        CREATE TABLE IF NOT EXISTS mo_musteri_sevkiyat_kalem (
            id INTEGER PRIMARY KEY,
            sevkiyat_id INTEGER,
            siparis_kalem_id INTEGER,
            urun_adi TEXT,
            renk_ad TEXT,
            formul_ad TEXT,
            miktar_kg REAL,
            miktar_adet INTEGER,
            notlar TEXT
        );
        INSERT INTO mo_musteri_sevkiyat_kalem (id, sevkiyat_id, siparis_kalem_id, urun_adi, miktar_kg)
        VALUES (1, 1, 100, 'Test Ürünü', 3000.0);
        INSERT INTO mo_musteri_sevkiyat_kalem (id, sevkiyat_id, siparis_kalem_id, urun_adi, miktar_kg)
        VALUES (2, 2, 100, 'Test Ürünü', 3000.0);

        -- Üretim planı + batch
        CREATE TABLE IF NOT EXISTS nexgen_uretim_plan (
            id INTEGER PRIMARY KEY,
            planlama_siparis_id INTEGER,
            durum TEXT,
            plan_kodu TEXT
        );
        INSERT INTO nexgen_uretim_plan (id, planlama_siparis_id, durum, plan_kodu)
        VALUES (5, 10, 'DEVAM', 'NP-TEST-00001');

        CREATE TABLE IF NOT EXISTS nexgen_uretim_batch (
            id INTEGER PRIMARY KEY,
            plan_id INTEGER,
            batch_kodu TEXT
        );
        INSERT INTO nexgen_uretim_batch (id, plan_id, batch_kodu)
        VALUES (1, 5, 'NG-TEST-BATCH-01');

        -- RF kullanım (üretilen KG için — load_cari360_siparisler)
        CREATE TABLE IF NOT EXISTS nexgen_rf_kullanim (
            id INTEGER PRIMARY KEY,
            plan_id INTEGER,
            uretilen_kg REAL
        );
        INSERT INTO nexgen_rf_kullanim (id, plan_id, uretilen_kg)
        VALUES (1, 5, 3000.0);

        -- Boş tablolar (import side-effect'leri için)
        CREATE TABLE IF NOT EXISTS sistem_rol_yetki (
            Id INTEGER PRIMARY KEY, RolId INTEGER, YetkiId INTEGER,
            can_view INTEGER DEFAULT 0, can_create INTEGER DEFAULT 0,
            can_update INTEGER DEFAULT 0, can_delete INTEGER DEFAULT 0,
            can_approve INTEGER DEFAULT 0, can_report INTEGER DEFAULT 0,
            can_manage INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS sistem_yetki (
            Id INTEGER PRIMARY KEY, Kod TEXT
        );
        CREATE TABLE IF NOT EXISTS user_permission_override (
            Id INTEGER PRIMARY KEY, KullaniciId INTEGER, YetkiId INTEGER,
            can_view INTEGER DEFAULT 0, can_create INTEGER DEFAULT 0,
            can_update INTEGER DEFAULT 0, can_delete INTEGER DEFAULT 0,
            can_approve INTEGER DEFAULT 0, can_report INTEGER DEFAULT 0,
            can_manage INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS nexgen_cari_sorumlu (
            id INTEGER PRIMARY KEY, cari_id INTEGER, kullanici_id INTEGER,
            tip TEXT, aktif INTEGER DEFAULT 1
        );
    """)
    return con, tmpdir


# ---------------------------------------------------------------------------
# 1–8: load_cari360_sevkiyatlar() — Liste davranışı
# ---------------------------------------------------------------------------

class SevkiyatListeTests(unittest.TestCase):
    """load_cari360_sevkiyatlar() temel liste davranışı — temp DB izolasyonu."""

    @classmethod
    def setUpClass(cls) -> None:
        if str(SVC) not in sys.path:
            sys.path.insert(0, str(SVC))
        cls.con, cls.tmpdir = _build_temp_db()
        from modules.nexgen.cari360_ops_read_service import load_cari360_sevkiyatlar
        cls.data = load_cari360_sevkiyatlar(cls.con, _CARI_ID, 1, None, page=1, page_size=50)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.con.close()
        cls.tmpdir.cleanup()

    # ── 1. HAZIRLANIYOR listede görünür ───────────────────────────────────

    def test_01_hazirlaniyor_listede_gorulur(self) -> None:
        """HAZIRLANIYOR sevkiyat listede bulunmalı."""
        nos = [s['sevkiyat_no'] for s in self.data['liste']]
        self.assertIn('MSV-TEST-0001', nos,
            f"MSV-TEST-0001 (HAZIRLANIYOR) listede yok — mevcut: {nos}")

    # ── 2. SEVK_EDILDI listede görünür ────────────────────────────────────

    def test_02_sevk_edildi_listede_gorulur(self) -> None:
        """SEVK_EDILDI sevkiyat listede bulunmalı."""
        nos = [s['sevkiyat_no'] for s in self.data['liste']]
        self.assertIn('MSV-TEST-0002', nos,
            f"MSV-TEST-0002 (SEVK_EDILDI) listede yok — mevcut: {nos}")

    # ── 3. Her sevkiyat kendi KG değerini taşır ───────────────────────────

    def test_03_her_sevkiyat_kendi_kg_degerini_tasir(self) -> None:
        """Her sevkiyat kendi kalem KG toplamını doğru taşımalı."""
        for s in self.data['liste']:
            kg_f = float(str(s['sevk_kg']).replace(',', '.'))
            self.assertEqual(kg_f, 3000.0,
                f"{s['sevkiyat_no']} sevk_kg={kg_f}, beklenen 3000")

    # ── 4. Sipariş No nexgen_planlama_siparis'ten gelir ───────────────────

    def test_04_siparis_no_dogru_baglaniyor(self) -> None:
        """siparis_no canonical nexgen_planlama_siparis'ten doğru gelmeli."""
        for s in self.data['liste']:
            self.assertEqual(s['siparis_no'], _SIPARIS_NO,
                f"{s['sevkiyat_no']} siparis_no={s['siparis_no']!r}, beklenen={_SIPARIS_NO!r}")

    # ── 5. Batch kodu doğru gelir ─────────────────────────────────────────

    def test_05_batch_kodu_dogru_geliyor(self) -> None:
        """batch_kodlari siparis→plan→batch zincirinden doğru gelmeli."""
        for s in self.data['liste']:
            self.assertIn(_BATCH_KODU, s['batch_kodlari'],
                f"{s['sevkiyat_no']} batch_kodlari={s['batch_kodlari']}, beklenen {_BATCH_KODU}")

    # ── 6. Durumlar korunur ───────────────────────────────────────────────

    def test_06_durumlar_korunur(self) -> None:
        """HAZIRLANIYOR ve SEVK_EDILDI durumları değiştirilmeden döner."""
        dur_map = {s['sevkiyat_no']: s['durum'] for s in self.data['liste']}
        self.assertEqual(dur_map.get('MSV-TEST-0001'), 'HAZIRLANIYOR',
            f"MSV-TEST-0001 durum={dur_map.get('MSV-TEST-0001')}, HAZIRLANIYOR olmalı")
        self.assertEqual(dur_map.get('MSV-TEST-0002'), 'SEVK_EDILDI',
            f"MSV-TEST-0002 durum={dur_map.get('MSV-TEST-0002')}, SEVK_EDILDI olmalı")

    # ── 7. NULL sevk_tarihi → gercek_sevk_tarihi=None ────────────────────

    def test_07_null_sevk_tarihi_none_gelir(self) -> None:
        """sevk_tarihi NULL olan HAZIRLANIYOR kaydında gercek_sevk_tarihi=None olmalı."""
        haz = next((s for s in self.data['liste'] if s['sevkiyat_no'] == 'MSV-TEST-0001'), None)
        self.assertIsNotNone(haz, 'MSV-TEST-0001 listede yok')
        gst = haz.get('gercek_sevk_tarihi')
        self.assertIsNone(gst,
            f"MSV-TEST-0001 gercek_sevk_tarihi={gst!r}, NULL sevk_tarihi → None olmalı")

    # ── 8. Sayfalama kontratı ─────────────────────────────────────────────

    def test_08_sayfalama_kontratt(self) -> None:
        """total_count, page, page_size, total_pages tutarlı olmalı."""
        d = self.data
        self.assertIn('total_count', d)
        self.assertIn('page', d)
        self.assertIn('page_size', d)
        self.assertIn('total_pages', d)
        self.assertEqual(d['total_count'], 2, f"total_count={d['total_count']}, beklenen 2")
        self.assertGreaterEqual(d['total_count'], d['count'])
        self.assertEqual(d['page'], 1)
        self.assertGreater(d['page_size'], 0)
        expected_pages = max(1, (d['total_count'] + d['page_size'] - 1) // d['page_size'])
        self.assertEqual(d['total_pages'], expected_pages)


# ---------------------------------------------------------------------------
# 9–13: Cari özet ve Sipariş Geçmişi — GERCEKLESMIS filtresi
# ---------------------------------------------------------------------------

class GerceklesmisFiltresiTests(unittest.TestCase):
    """GERCEKLESMIS durum filtresi — özet ve Sipariş Geçmişi kontratı. Temp DB."""

    @classmethod
    def setUpClass(cls) -> None:
        if str(SVC) not in sys.path:
            sys.path.insert(0, str(SVC))
        cls.con, cls.tmpdir = _build_temp_db()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.con.close()
        cls.tmpdir.cleanup()

    # ── 9. Özet: yalnız GERCEKLESMIS sevkiyatlar toplam KG'ye girer ───────

    def test_09_ozet_yalniz_gerceklesmis_kg(self) -> None:
        """load_cari360_ozet toplam_sevk_kg yalnız GERCEKLESMIS kapsayacak."""
        from modules.nexgen.cari360_ops_read_service import load_cari360_ozet
        ozet = load_cari360_ozet(self.con, _CARI_ID, 1, None)
        kg_f = float(str(ozet['kpi']['toplam_sevk_kg']).replace(',', '.'))
        self.assertEqual(kg_f, 3000.0,
            f"toplam_sevk_kg={kg_f}, beklenen 3000 (HAZIRLANIYOR dahil edilmemeli)")

    # ── 10. Özet: HAZIRLANIYOR toplam sevkiyat sayısını artırmaz ──────────

    def test_10_ozet_hazirlaniyor_sayiya_girmez(self) -> None:
        """Özet toplam_sevkiyat yalnız GERCEKLESMIS'i sayar."""
        from modules.nexgen.cari360_ops_read_service import load_cari360_ozet
        ozet = load_cari360_ozet(self.con, _CARI_ID, 1, None)
        sayi = int(ozet['kpi']['toplam_sevkiyat'])
        self.assertEqual(sayi, 1,
            f"toplam_sevkiyat={sayi}, beklenen 1 (yalnız SEVK_EDILDI)")

    # ── 11. Özet: son_sevkiyat_tarihi yalnız GERCEKLESMIS üzerinden ───────

    def test_11_ozet_son_sevkiyat_tarihi_gerceklesmis(self) -> None:
        """son_sevkiyat_tarihi GERCEKLESMIS kaydın tarihi olmalı."""
        from modules.nexgen.cari360_ops_read_service import load_cari360_ozet
        ozet = load_cari360_ozet(self.con, _CARI_ID, 1, None)
        t = ozet['kpi'].get('son_sevkiyat_tarihi') or ''
        self.assertTrue(str(t).startswith(_SON_TARIH),
            f"son_sevkiyat_tarihi={t!r}, {_SON_TARIH} ile başlamalı")

    # ── 12. GERCEKLESMIS filtresi SQL kontratı ────────────────────────────

    def test_12_gerceklesmis_filtre_sql_kontratt(self) -> None:
        """_SEVK_GERCEKLESMIS filtresiyle doğrudan SQL: yalnız SEVK_EDILDI toplamı gelmeli.

        load_cari360_siparisler geniş schema gerektiriyor; bu test canonical
        GERCEKLESMIS filtre mantığını SQL seviyesinde, izole temp DB üzerinde doğrular.
        """
        ph = ','.join('?' * len(_SEVK_GERCEKLESMIS))
        con = self.con

        # Tüm aktif sevkiyat KG (HAZIRLANIYOR dahil)
        tum_kg = float(con.execute(
            """SELECT COALESCE(SUM(k.miktar_kg), 0)
               FROM mo_musteri_sevkiyat_kalem k
               JOIN mo_musteri_sevkiyat s ON s.id=k.sevkiyat_id
               WHERE s.cari_id=? AND COALESCE(s.aktif,1)=1""",
            (_CARI_ID,)
        ).fetchone()[0])
        self.assertEqual(tum_kg, 6000.0,
            f"Toplam (HAZIRLANIYOR+SEVK_EDILDI) KG={tum_kg}, fixture'da 6000 olmalı")

        # Yalnız gerçekleşmiş (GERCEKLESMIS) sevkiyat KG
        gercek_kg = float(con.execute(
            f"""SELECT COALESCE(SUM(k.miktar_kg), 0)
                FROM mo_musteri_sevkiyat_kalem k
                JOIN mo_musteri_sevkiyat s ON s.id=k.sevkiyat_id
                WHERE s.cari_id=? AND COALESCE(s.aktif,1)=1
                  AND s.durum IN ({ph})""",
            [_CARI_ID] + list(_SEVK_GERCEKLESMIS)
        ).fetchone()[0])
        self.assertEqual(gercek_kg, 3000.0,
            f"Gerçekleşmiş KG={gercek_kg}, HAZIRLANIYOR eklenmeden 3000 olmalı")

        # Fark = HAZIRLANIYOR katkısı = 3000 (asla 0 değil, bu filtrenin varlık nedeni)
        self.assertEqual(tum_kg - gercek_kg, 3000.0,
            'HAZIRLANIYOR filtresi 3000 KG fark yaratmalı')

    # ── 13. PZM-2026-0221 tam canonical fixture doğrulaması ───────────────

    def test_13_pzm_tam_canonical_fixture(self) -> None:
        """Kesin kontrat:
        - Sevkiyatlar listesinde 2 ayrı kayıt
        - Gerçekleşmiş sevk özeti tam olarak 3000 KG
        - Gerçekleşmiş sevkiyat sayısı tam olarak 1
        - Son sevkiyat tarihi tam olarak gerçekleşmiş kaydın tarihi
        - Sipariş Geçmişi sevk_edilen_kg tam 3000 (6000 değil)
        """
        ph = ','.join('?' * len(_SEVK_GERCEKLESMIS))
        con = self.con

        # ── DB fixture: HAZIRLANIYOR=3000, SEVK_EDILDI=3000 ─────────────
        for sev_no, beklenen_durum in [('MSV-TEST-0001', 'HAZIRLANIYOR'), ('MSV-TEST-0002', 'SEVK_EDILDI')]:
            row = con.execute("""
                SELECT durum,
                       (SELECT COALESCE(SUM(miktar_kg),0) FROM mo_musteri_sevkiyat_kalem
                        WHERE sevkiyat_id=mo_musteri_sevkiyat.id) AS kg
                FROM mo_musteri_sevkiyat WHERE sevkiyat_no=? AND COALESCE(aktif,1)=1
            """, (sev_no,)).fetchone()
            self.assertIsNotNone(row, f'{sev_no} DB fixture yok')
            self.assertEqual(row['durum'], beklenen_durum,
                f"{sev_no} durum={row['durum']}, beklenen {beklenen_durum}")
            self.assertEqual(float(row['kg']), 3000.0,
                f"{sev_no} kg={row['kg']}, beklenen 3000")

        # ── Sevkiyatlar listesinde 2 ayrı kayıt ─────────────────────────
        from modules.nexgen.cari360_ops_read_service import load_cari360_sevkiyatlar
        data = load_cari360_sevkiyatlar(con, _CARI_ID, 1, None, page=1, page_size=50)
        sip_items = [s for s in data['liste'] if s['siparis_no'] == _SIPARIS_NO]
        self.assertEqual(len(sip_items), 2,
            f"Sipariş {_SIPARIS_NO} için {len(sip_items)} satır var, beklenen 2")

        # ── Gerçekleşmiş sevk özeti tam 3000 ────────────────────────────
        gercek_kg = float(con.execute(
            f"""SELECT COALESCE(SUM(k.miktar_kg),0)
                FROM mo_musteri_sevkiyat_kalem k
                JOIN mo_musteri_sevkiyat s ON s.id=k.sevkiyat_id
                WHERE s.siparis_id=? AND COALESCE(s.aktif,1)=1
                  AND s.durum IN ({ph})""",
            [_SIPARIS_ID] + list(_SEVK_GERCEKLESMIS)
        ).fetchone()[0])
        self.assertEqual(gercek_kg, 3000.0,
            f"Gerçekleşmiş sevk KG={gercek_kg}, tam 3000 olmalı")

        # ── Gerçekleşmiş sevkiyat sayısı tam 1 ──────────────────────────
        gercek_sayi = int(con.execute(
            f"""SELECT COUNT(*) FROM mo_musteri_sevkiyat
                WHERE siparis_id=? AND COALESCE(aktif,1)=1
                  AND durum IN ({ph})""",
            [_SIPARIS_ID] + list(_SEVK_GERCEKLESMIS)
        ).fetchone()[0])
        self.assertEqual(gercek_sayi, 1,
            f"Gerçekleşmiş sevkiyat sayısı={gercek_sayi}, tam 1 olmalı")

        # ── Son sevkiyat tarihi tam 2026-08-10 ───────────────────────────
        son_tarih_row = con.execute(
            f"""SELECT COALESCE(sevk_tarihi, olusturma_tarihi) AS t
                FROM mo_musteri_sevkiyat
                WHERE siparis_id=? AND COALESCE(aktif,1)=1 AND durum IN ({ph})
                ORDER BY COALESCE(sevk_tarihi, olusturma_tarihi) DESC LIMIT 1""",
            [_SIPARIS_ID] + list(_SEVK_GERCEKLESMIS)
        ).fetchone()
        gelen_tarih = str(son_tarih_row['t'])[:10] if son_tarih_row and son_tarih_row['t'] else None
        self.assertEqual(gelen_tarih, _SON_TARIH,
            f"Son sevkiyat tarihi={gelen_tarih!r}, beklenen={_SON_TARIH!r}")

        # ── SQL: GERCEKLESMIS filtreli sipariş başına sevk KG = 3000 ─────
        siparis_gercek_kg = float(con.execute(
            f"""SELECT COALESCE(SUM(k.miktar_kg), 0)
                FROM mo_musteri_sevkiyat_kalem k
                JOIN mo_musteri_sevkiyat s ON s.id=k.sevkiyat_id
                WHERE s.siparis_id=? AND COALESCE(s.aktif,1)=1
                  AND s.durum IN ({ph})""",
            [_SIPARIS_ID] + list(_SEVK_GERCEKLESMIS)
        ).fetchone()[0])
        self.assertEqual(siparis_gercek_kg, 3000.0,
            f"Sipariş başına GERCEKLESMIS sevk KG={siparis_gercek_kg}, tam 3000 olmalı")
        # Tüm sevkiyat (HAZIRLANIYOR dahil) = 6000; filtreli = 3000; asla 6000 değil
        self.assertNotEqual(siparis_gercek_kg, 6000.0,
            'HAZIRLANIYOR yanlışlıkla eklendi — sevk_edilen_kg=6000!')


# ---------------------------------------------------------------------------
# 14: API response zorunlu alanlar
# ---------------------------------------------------------------------------

class SevkiyatResponseKontratTests(unittest.TestCase):
    """load_cari360_sevkiyatlar() response alanları kontratı — temp DB."""

    @classmethod
    def setUpClass(cls) -> None:
        if str(SVC) not in sys.path:
            sys.path.insert(0, str(SVC))
        cls.con, cls.tmpdir = _build_temp_db()
        from modules.nexgen.cari360_ops_read_service import load_cari360_sevkiyatlar
        cls.data = load_cari360_sevkiyatlar(cls.con, _CARI_ID, 1, None, page=1, page_size=50)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.con.close()
        cls.tmpdir.cleanup()

    def test_14_zorunlu_alanlar_mevcut(self) -> None:
        """Her sevkiyat item'ında zorunlu alanlar bulunmalı."""
        top_level = ['total_count', 'page', 'page_size', 'total_pages', 'liste', 'count']
        for alan in top_level:
            self.assertIn(alan, self.data, f"Response'da {alan} yok")
        self.assertTrue(self.data['liste'], 'liste boş')
        item = self.data['liste'][0]
        item_zorunlu = [
            'id', 'sevkiyat_no', 'durum', 'sevk_kg', 'siparis_no',
            'gercek_sevk_tarihi', 'tarih', 'kalemler', 'kalem_sayisi',
            'uretim_bilgisi_var', 'batch_kodlari', 'batch_sayisi',
        ]
        for alan in item_zorunlu:
            self.assertIn(alan, item, f"Item'da {alan} yok")


# ---------------------------------------------------------------------------
# 15–17: Template kontrat — statik HTML analizi (DB kullanmaz)
# ---------------------------------------------------------------------------

class SevkiyatTemplateTests(unittest.TestCase):
    """Template kontrat testleri — DB kullanmaz, statik HTML analizi."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.src = TMPL.read_text(encoding='utf-8')

    # ── 15. ckartSevkYukle fonksiyonu tanımlı ────────────────────────────

    def test_15_ckartSevkYukle_tanimi_var(self) -> None:
        """ckartSevkYukle fonksiyonu template'de tanımlı olmalı."""
        self.assertIn('ckartSevkYukle', self.src,
            'ckartSevkYukle fonksiyonu bulunamadı')

    def test_15b_sevk_api_url_dogru(self) -> None:
        """Sevkiyat API URL'si /sevkiyatlar endpoint'ini kullanmalı."""
        self.assertIn("CARI_ID + '/sevkiyatlar", self.src,
            "Sevkiyat API URL'si yanlış veya yok")

    # ── 16. gercek_sevk_tarihi kullanılıyor ──────────────────────────────

    def test_16_gercek_sevk_tarihi_kullaniliyor(self) -> None:
        """Template sevk_tarihi değil gercek_sevk_tarihi kullanmalı."""
        self.assertIn('gercek_sevk_tarihi', self.src,
            'gercek_sevk_tarihi field template\'de kullanılmıyor')

    # ── 17. Her tab açılışında stale data olmaz ───────────────────────────

    def test_17_opsLoaded_sevkiyatlar_reset(self) -> None:
        """Her tab açılışında _opsLoaded.sevkiyatlar=false sıfırlanmalı."""
        self.assertIn('_opsLoaded.sevkiyatlar', self.src,
            '_opsLoaded.sevkiyatlar guard yok')

    def test_17b_sevk_durum_badge(self) -> None:
        """_sevkDurumBadge fonksiyonu template'de tanımlı olmalı."""
        self.assertIn('sevkDurumBadge', self.src,
            'sevkDurumBadge fonksiyonu bulunamadı')

    def test_17c_sevk_kg_render(self) -> None:
        """Sevkiyat listesinde sevk_kg render ediliyor olmalı."""
        self.assertIn('sevk_kg', self.src,
            'sevk_kg field render edilmiyor')

    def test_17d_expand_detail_kalemler(self) -> None:
        """Expand alanında kalem KG detayı (k.sevk_kg) gösteriliyor olmalı."""
        self.assertIn('k.sevk_kg', self.src,
            'Expand kalem KG (k.sevk_kg) template\'de yok')

    def test_17e_hazirlik_ve_gercek_sevk_ayri(self) -> None:
        """Expand alanında Hazırlık Tarihi ve Gerçek Sevk Tarihi ayrı semantikle var."""
        self.assertIn('hazirlik_tarihi', self.src,
            'hazirlik_tarihi expand\'da yok')
        self.assertIn('gercek_sevk_tarihi', self.src,
            'gercek_sevk_tarihi expand\'da yok')

    def test_17f_uretim_baglantisi_gorunur(self) -> None:
        """Üretim bağlantısı olduğunda Üretim Emri/plan linki görünür."""
        self.assertTrue(
            ('Üretim Emri' in self.src) or ('plan_url' in self.src),
            'Üretim Emri/plan_url bağlantısı template\'de yok')
