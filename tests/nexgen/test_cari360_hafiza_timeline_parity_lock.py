# -*- coding: utf-8 -*-
"""
Cari360 Hafıza / Timeline dar canonical parity lock.
Temporary in-memory SQLite + template fixture — canonical DB write yok.
"""
from __future__ import annotations

import re
import sqlite3
import sys
import unittest
from pathlib import Path

SVC = Path(__file__).resolve().parents[2] / 'app'
TMPL = SVC / 'templates' / 'nexgen' / 'cari360_kart.html'
TSVC = SVC / 'modules' / 'nexgen' / 'cari360_timeline_service.py'

sys.path.insert(0, str(SVC))

from modules.nexgen.cari360_timeline_service import (  # noqa: E402
    build_ops_timeline,
    _ajanda_adhoc_idempotency,
    _sevk_timeline_baslik,
)

_CARI_ID = 1
_UID = 1
_YK = {'*'}


def _build_fixture_db() -> sqlite3.Connection:
    con = sqlite3.connect(':memory:')
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE sistem_kullanici (
            Id INTEGER PRIMARY KEY, KullaniciAdi TEXT, AdSoyad TEXT, Aktif INTEGER DEFAULT 1
        );
        INSERT INTO sistem_kullanici VALUES (1, 'erhan', 'Erhan Atlar', 1);

        CREATE TABLE nexgen_cari (
            id INTEGER PRIMARY KEY, cari_kod TEXT, unvan TEXT, aktif INTEGER DEFAULT 1
        );
        INSERT INTO nexgen_cari VALUES (1, '120.NX.009', '3E Test', 1);

        CREATE TABLE musteri_operasyon_gorusme (
            id INTEGER PRIMARY KEY, cari_id INTEGER, kullanici_id INTEGER,
            olusturan_kullanici_id INTEGER, gorusme_tipi TEXT, sonuc_tipi TEXT,
            kisa_not TEXT, gorusme_tarihi TEXT, olusturma_tarihi TEXT, aktif INTEGER DEFAULT 1,
            takip_durumu TEXT, konu TEXT, numune_talep_id INTEGER, idempotency_key TEXT
        );
        INSERT INTO musteri_operasyon_gorusme
        VALUES (501, 1, 1, 1, 'Telefon', 'Olumlu', 'Gercek gorusme',
                '2026-08-10 12:00:00', '2026-08-10 12:00:00', 1, NULL, 'Konu', NULL, NULL);

        CREATE TABLE musteri_operasyon_ajanda (
            id INTEGER PRIMARY KEY, cari_id INTEGER, kullanici_id INTEGER,
            plan_tarihi TEXT, gorusme_tipi TEXT, plan_notu TEXT, durum TEXT,
            gorusme_id INTEGER, idempotency_key TEXT, aktif INTEGER DEFAULT 1,
            olusturma_tarihi TEXT, guncelleme_tarihi TEXT, olusturan_kullanici_id INTEGER,
            plan_yetkili_metin TEXT, musteri_aday_id INTEGER, firma_adi_gorunum TEXT
        );
        INSERT INTO musteri_operasyon_ajanda VALUES
        (10, 1, 1, '2026-09-01 10:30:00', 'Telefon', 'Plan notu test', 'PLANLANDI',
         NULL, 'aj-plan-10', 1, '2026-08-08 14:00:00', '2026-08-08 14:00:00', 1, NULL, NULL, '3E'),
        (11, 1, 1, '2026-08-09 11:00:00', 'Yuz yuze', 'Tamamlanan plan', 'GERCEKLESTI',
         501, 'aj-plan-11', 1, '2026-08-07 09:00:00', '2026-08-08 15:00:00', 1, NULL, NULL, '3E'),
        (12, 1, 1, '2026-08-20 09:00:00', 'Telefon', 'Iptal', 'IPTAL',
         NULL, 'aj-plan-12', 1, '2026-08-06 08:00:00', '2026-08-06 08:00:00', 1, NULL, NULL, '3E'),
        (13, 1, 1, '2026-08-10 08:00:00', 'Telefon', 'Adhoc', 'PLANLANDI',
         501, 'ADHOC-GOR-501', 1, '2026-08-10 07:00:00', '2026-08-10 07:00:00', 1, NULL, NULL, '3E');

        CREATE TABLE nexgen_planlama_siparis (
            id INTEGER PRIMARY KEY, siparis_no TEXT, cari_id INTEGER, durum TEXT,
            olusturma_tarihi TEXT, guncelleme_tarihi TEXT, olusturan_id INTEGER,
            notlar TEXT, talep_referansi TEXT, idempotency_key TEXT
        );
        INSERT INTO nexgen_planlama_siparis VALUES
        (100, 'PZM-TEST-100', 1, 'ONAYLANDI', '2026-08-01 10:00:00', '2026-08-01 10:00:00', 1, '', '', '');

        CREATE TABLE nexgen_uretim_plan (
            id INTEGER PRIMARY KEY, plan_kodu TEXT, durum TEXT, created_at TEXT,
            plan_tarihi TEXT, created_by INTEGER, cari_id INTEGER,
            planlama_siparis_id INTEGER, siparis_no TEXT, termin_tarihi TEXT
        );
        INSERT INTO nexgen_uretim_plan VALUES
        (20, 'NP-TEST-20', 'TAMAMLANDI', '2026-08-02 08:00:00', '2026-08-02', 1, 1, 100, 'PZM-TEST-100', NULL);

        CREATE TABLE nexgen_uretim_batch (
            id INTEGER PRIMARY KEY, plan_id INTEGER
        );
        INSERT INTO nexgen_uretim_batch VALUES (1, 20);

        CREATE TABLE nexgen_uretim_parca (
            id INTEGER PRIMARY KEY, plan_id INTEGER, batch_id INTEGER, durum TEXT,
            baslama_zamani TEXT, bitis_zamani TEXT
        );
        INSERT INTO nexgen_uretim_parca VALUES
        (1, 20, 1, 'TAMAMLANDI', '2026-08-03 09:00:00', '2026-08-04 17:00:00');

        CREATE TABLE mo_musteri_sevkiyat (
            id INTEGER PRIMARY KEY, sevkiyat_no TEXT, siparis_id INTEGER, cari_id INTEGER,
            durum TEXT, sevk_tarihi TEXT, olusturma_tarihi TEXT, guncelleme_tarihi TEXT,
            olusturan_id INTEGER, aktif INTEGER DEFAULT 1
        );
        INSERT INTO mo_musteri_sevkiyat VALUES
        (301, 'SV-HAZ', 100, 1, 'HAZIRLANIYOR', NULL, '2026-08-10 08:00:00', '2026-08-10 08:00:00', 1, 1),
        (302, 'SV-SEVK', 100, 1, 'SEVK_EDILDI', '2026-08-10 12:00:00', '2026-08-09 10:00:00', '2026-08-10 12:00:00', 1, 1),
        (303, 'SV-TES', 100, 1, 'TESLIM_EDILDI', '2026-08-11 10:00:00', '2026-08-11 09:00:00', '2026-08-11 10:00:00', 1, 1);
    """)
    return con


def _timeline(con: sqlite3.Connection) -> list[dict]:
    evs, _ = build_ops_timeline(con, _CARI_ID)
    return evs


def _by_kod(evs: list[dict], kod: str) -> list[dict]:
    return [e for e in evs if e.get('olay_kodu') == kod]


def _tmpl() -> str:
    return TMPL.read_text(encoding='utf-8')


class EndpointTemplateLockTests(unittest.TestCase):
    """1–3: Aynı endpoint, limit kontratları."""

    def setUp(self):
        self.src = _tmpl()

    def test_01_son_hareketler_hafiza_endpoint(self):
        self.assertIn("'/nexgen/api/cari360/' + CARI_ID + '/hafiza?limit=20'", self.src)

    def test_02_son_hareketler_limit_20(self):
        m = re.search(r"ckartSonHareketlerYukle[\s\S]{0,400}limit=20", self.src)
        self.assertIsNotNone(m)

    def test_03_hafiza_tab_limit_200(self):
        self.assertIn("'/nexgen/api/cari360/' + CARI_ID + '/hafiza?limit=200'", self.src)


class SortParityLockTests(unittest.TestCase):
    """4–6: Sıralama ve ilk 20 parity."""

    @classmethod
    def setUpClass(cls):
        cls.con = _build_fixture_db()
        cls.evs = _timeline(cls.con)

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def test_04_first_20_from_same_canonical_list(self):
        first20 = self.evs[:20]
        self.assertGreaterEqual(len(self.evs), 5)
        self.assertEqual(first20, self.evs[:20])

    def test_05_event_order_date_desc(self):
        dates = [(e.get('event_date') or e.get('olay_tarihi') or '') for e in self.evs]
        self.assertEqual(dates, sorted(dates, reverse=True))

    def test_06_tie_break_deterministic(self):
        same = [e for e in self.evs if (e.get('event_date') or '')[:10] == '2026-08-10']
        if len(same) >= 2:
            keys = [
                (e.get('event_date') or '', e.get('oncelik') or 0, int(e.get('entity_id') or 0))
                for e in same
            ]
            self.assertEqual(keys, sorted(keys, reverse=True))


class UretimTimelineLockTests(unittest.TestCase):
    """7–10: Üretim whitelist ve URL."""

    @classmethod
    def setUpClass(cls):
        cls.con = _build_fixture_db()
        cls.evs = _timeline(cls.con)

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def test_07_uretim_started_in_whitelist_output(self):
        started = _by_kod(self.evs, 'URETIM_STARTED')
        self.assertEqual(len(started), 1)
        self.assertEqual(started[0]['baslik'], 'Üretim başladı')

    def test_08_uretim_completed_in_whitelist_output(self):
        done = _by_kod(self.evs, 'URETIM_COMPLETED')
        self.assertEqual(len(done), 1)
        self.assertEqual(done[0]['baslik'], 'Üretim tamamlandı')

    def test_09_no_duplicate_uretim_per_plan(self):
        started = _by_kod(self.evs, 'URETIM_STARTED')
        self.assertEqual(len({e['entity_id'] for e in started}), len(started))
        done = _by_kod(self.evs, 'URETIM_COMPLETED')
        self.assertEqual(len({e['entity_id'] for e in done}), len(done))

    def test_10_uretim_detay_url_tab_uretim(self):
        for kod in ('URETIM_STARTED', 'URETIM_COMPLETED'):
            for e in _by_kod(self.evs, kod):
                self.assertIn('?tab=uretim', e.get('detay_url') or '')
                self.assertEqual(int(e['entity_id']), 20)


class SevkiyatLabelLockTests(unittest.TestCase):
    """11–15: Sevkiyat etiketleri ve URL."""

    @classmethod
    def setUpClass(cls):
        cls.con = _build_fixture_db()
        cls.evs = _timeline(cls.con)

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def test_11_hazirlaniyor_label(self):
        haz = next(e for e in _by_kod(self.evs, 'SEVKIYAT') if e['entity_id'] == 301)
        self.assertEqual(haz['baslik'], 'Sevkiyat hazırlanıyor')

    def test_12_hazirlaniyor_not_yapildi(self):
        haz = next(e for e in _by_kod(self.evs, 'SEVKIYAT') if e['entity_id'] == 301)
        self.assertNotEqual(haz['baslik'], 'Sevkiyat yapıldı')

    def test_13_sevk_edildi_label(self):
        sevk = next(e for e in _by_kod(self.evs, 'SEVKIYAT') if e['entity_id'] == 302)
        self.assertEqual(sevk['baslik'], 'Sevkiyat yapıldı')

    def test_14_teslim_edildi_label(self):
        tes = next(e for e in _by_kod(self.evs, 'SEVKIYAT') if e['entity_id'] == 303)
        self.assertEqual(tes['baslik'], 'Sevkiyat teslim edildi')

    def test_15_sevkiyat_detay_url(self):
        for e in _by_kod(self.evs, 'SEVKIYAT'):
            self.assertIn('?tab=sevkiyatlar', e.get('detay_url') or '')


class AjandaTimelineLockTests(unittest.TestCase):
    """16–27: Ajanda planlama olayları."""

    @classmethod
    def setUpClass(cls):
        cls.con = _build_fixture_db()
        cls.evs = _timeline(cls.con)

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def test_16_gorusme_planlandi_from_ajanda(self):
        plans = _by_kod(self.evs, 'GORUSME_PLANLANDI')
        self.assertGreaterEqual(len(plans), 2)
        self.assertEqual(plans[0]['entity_type'], 'musteri_operasyon_ajanda')

    def test_17_ajanda_event_date_olusturma(self):
        p10 = next(e for e in self.evs if e.get('olay_kodu') == 'GORUSME_PLANLANDI' and e['entity_id'] == 10)
        self.assertTrue(str(p10.get('event_date') or '').startswith('2026-08-08 14:00'))

    def test_18_plan_tarihi_not_sort_date(self):
        p10 = next(e for e in self.evs if e.get('olay_kodu') == 'GORUSME_PLANLANDI' and e['entity_id'] == 10)
        self.assertFalse(str(p10.get('event_date') or '').startswith('2026-09-01'))

    def test_19_plan_tarihi_in_summary(self):
        p10 = next(e for e in self.evs if e.get('olay_kodu') == 'GORUSME_PLANLANDI' and e['entity_id'] == 10)
        self.assertIn('Plan: 2026-09-01', p10.get('aciklama') or '')

    def test_20_plan_notu_in_summary(self):
        p10 = next(e for e in self.evs if e.get('olay_kodu') == 'GORUSME_PLANLANDI' and e['entity_id'] == 10)
        self.assertIn('Plan notu test', p10.get('aciklama') or '')

    def test_21_planlandi_visible(self):
        ids = {e['entity_id'] for e in _by_kod(self.evs, 'GORUSME_PLANLANDI')}
        self.assertIn(10, ids)

    def test_22_gerceklesti_plan_historical_event(self):
        ids = {e['entity_id'] for e in _by_kod(self.evs, 'GORUSME_PLANLANDI')}
        self.assertIn(11, ids)

    def test_23_iptal_plan_hidden(self):
        ids = {e['entity_id'] for e in _by_kod(self.evs, 'GORUSME_PLANLANDI')}
        self.assertNotIn(12, ids)

    def test_24_adhoc_excluded(self):
        self.assertTrue(_ajanda_adhoc_idempotency('ADHOC-GOR-501'))
        ids = {e['entity_id'] for e in _by_kod(self.evs, 'GORUSME_PLANLANDI')}
        self.assertNotIn(13, ids)

    def test_25_no_duplicate_ajanda_id(self):
        plans = _by_kod(self.evs, 'GORUSME_PLANLANDI')
        self.assertEqual(len(plans), len({e['entity_id'] for e in plans}))

    def test_26_gorusme_created_preserved(self):
        g = _by_kod(self.evs, 'GORUSME_CREATED')
        self.assertEqual(len(g), 1)
        self.assertEqual(g[0]['entity_id'], 501)

    def test_27_no_sonuclandir_write_url(self):
        for e in _by_kod(self.evs, 'GORUSME_PLANLANDI'):
            url = e.get('detay_url') or ''
            self.assertIn('?tab=gorusmeler', url)
            self.assertNotIn('sonuclandir', url.lower())


class RefreshTemplateLockTests(unittest.TestCase):
    """28–32: Refresh zinciri ve renderer parity."""

    def setUp(self):
        self.src = _tmpl()

    def test_28_genel_tab_fresh_son_hareketler(self):
        tab_blk = self.src[self.src.find('window.ckartTab = function'): self.src.find('window.ckartTab = function') + 1200]
        self.assertIn("if (tab === 'genel') { ckartSonHareketlerYukle(); }", tab_blk)

    def test_29_gorusme_sonrasi_son_hareketler(self):
        idx = self.src.find('function gorusmeSonrasiYenile')
        blk = self.src[idx: idx + 350]
        self.assertIn('ckartSonHareketlerYukle()', blk)

    def test_30_gorusme_sonrasi_hafiza_invalidate(self):
        idx = self.src.find('function gorusmeSonrasiYenile')
        blk = self.src[idx: idx + 350]
        self.assertIn('_ckartHafizaTabYuklendi = false', blk)

    def test_31_hafiza_tab_uses_ckartHafizaDoldur(self):
        self.assertIn('ckartHafizaDoldur(ul, liste.slice(0, 200))', self.src)

    def test_32_kategori_filter_preserved(self):
        idx = self.src.find('function _ckartHafizaTabFiltrele')
        blk = self.src[idx: idx + 2500]
        self.assertIn('_kategoriAl(e)', blk)
        self.assertIn('_ckartHafizaTabTumVeri.filter', blk)


class EscapeAndTahsilatLockTests(unittest.TestCase):
    """33–35: esc() ve tahsilat dokunulmadı."""

    def test_33_esc_in_renderer(self):
        src = _tmpl()
        self.assertIn('function esc(s)', src)
        idx = src.find('function ckartHafizaDoldur')
        blk = src[idx: idx + 1500]
        self.assertIn('.textContent = ev.title', blk)
        chip = src.find('function ckartChipHtml')
        self.assertIn('esc(', src[chip: chip + 250])

    def test_34_first_20_fixture_keys_unique(self):
        con = _build_fixture_db()
        evs = _timeline(con)
        keys = [e.get('dedupe_key') for e in evs[:20]]
        self.assertEqual(len(keys), len(set(keys)))
        con.close()

    def test_35_tahsilat_block_untouched_in_service(self):
        svc = TSVC.read_text(encoding='utf-8')
        self.assertIn("olay_kodu='TAHSILAT'", svc)
        self.assertIn("'TAHSILAT',", svc)
        tah_idx = svc.find("olay_kodu='TAHSILAT'")
        tah_blk = svc[tah_idx: tah_idx + 500]
        self.assertIn('baslik=lbl', tah_blk)
        self.assertIn("'ONAYLANDI': 'Tahsilat alındı'", svc)
        self.assertNotIn('_sevk_timeline_baslik', tah_blk)


class SevkiyatHelperUnitTests(unittest.TestCase):
    def test_sevk_helper_matrix(self):
        self.assertEqual(_sevk_timeline_baslik('HAZIRLANIYOR'), 'Sevkiyat hazırlanıyor')
        self.assertEqual(_sevk_timeline_baslik('SEVK_EDILDI'), 'Sevkiyat yapıldı')
        self.assertEqual(_sevk_timeline_baslik('TESLIM_EDILDI'), 'Sevkiyat teslim edildi')
        self.assertEqual(_sevk_timeline_baslik('TAMAMLANDI'), 'Sevkiyat tamamlandı')


if __name__ == '__main__':
    unittest.main()
