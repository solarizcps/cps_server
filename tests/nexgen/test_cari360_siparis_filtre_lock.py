# -*- coding: utf-8 -*-
"""C360-FILTER-SIPARIS-01 LOCK — Sipariş filtre regression testi.

Kapanan davranışlar:
1.  Filtre yok → mevcut pagination sonucu değişmedi
2.  siparis_no LIKE → doğru sipariş gelir
3.  Bulunamayan siparis_no → rows=[], total_count=0
4.  durum tek seçim
5.  durum çoklu seçim
6.  tarih_baslangic only
7.  tarih_bitis only
8.  tarih range
9.  termin_baslangic / termin_bitis
10. iki filtre AND
11. filtered total_count doğru
12. filtered pagination: page1/page2 overlap yok
13. SQL parametre güvenliği (quote/wildcard crash yok)
UI contract:
14. .ckart-sip-fbtn butonları template'de mevcut
15. _ckartSipFilterUrl, _ckartSipFilters JS template'de mevcut
16. ckartSiparisYukle'de _ckartSipFilterUrl() kullanılıyor
"""
from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB   = ROOT / 'app' / 'mock_data.db'
SVC  = ROOT / 'app'
TMPL = ROOT / 'app' / 'templates' / 'nexgen' / 'cari360_kart.html'

CARI_AYM  = 7
PAGE_SIZE = 50


def _con() -> sqlite3.Connection:
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def _uid(con: sqlite3.Connection) -> int:
    row = con.execute(
        "SELECT id FROM sistem_kullanici WHERE KullaniciAdi='admin' AND Aktif=1"
    ).fetchone()
    return int(row['id']) if row else 1


def _load():
    if str(SVC) not in sys.path:
        sys.path.insert(0, str(SVC))
    from modules.nexgen.cari360_ops_read_service import load_cari360_siparisler
    return load_cari360_siparisler


class FiltreServiceTests(unittest.TestCase):
    """load_cari360_siparisler — filtre parametreleri davranışı."""

    def setUp(self):
        self.con = _con()
        self.uid = _uid(self.con)
        self.fn  = _load()

    def tearDown(self):
        self.con.close()

    def _call(self, **kw):
        return self.fn(self.con, CARI_AYM, self.uid, None, **kw)

    # 1 — filtre yok → pagination değişmedi
    def test_01_no_filter_pagination_unchanged(self):
        r = self._call(limit=PAGE_SIZE, offset=0)
        self.assertIn('total_count', r)
        self.assertIn('total_pages', r)
        self.assertIn('page', r)
        self.assertGreater(r['total_count'], 0)
        self.assertLessEqual(len(r['liste']), PAGE_SIZE)

    # 2 — siparis_no LIKE
    def test_02_siparis_no_text_filter(self):
        # Var olan bir no'nun parçasını al
        r0 = self._call(limit=1, offset=0)
        if not r0['liste']:
            self.skipTest('Sipariş yok')
        fragment = r0['liste'][0]['siparis_no'][:4]
        r = self._call(siparis_no=fragment)
        for s in r['liste']:
            self.assertIn(fragment.upper(), (s['siparis_no'] or '').upper())

    # 3 — bulunamayan siparis_no
    def test_03_siparis_no_not_found(self):
        r = self._call(siparis_no='__YOKTUR_XYZ_9999__')
        self.assertEqual(r['total_count'], 0)
        self.assertEqual(r['liste'], [])
        # total_count=0 → canonical service total_pages=1 döner (mevcut contract korunur)
        self.assertGreaterEqual(r['total_pages'], 0)

    # 4 — durum tek seçim
    def test_04_durum_single(self):
        r = self._call(durumlar=['ONAYLANDI'])
        for s in r['liste']:
            self.assertEqual(s['durum'], 'ONAYLANDI')

    # 5 — durum çoklu seçim
    def test_05_durum_multi(self):
        allowed = {'ONAYLANDI', 'TASLAK'}
        r = self._call(durumlar=list(allowed))
        for s in r['liste']:
            self.assertIn(s['durum'], allowed)

    # 6 — tarih_baslangic only
    def test_06_tarih_baslangic_only(self):
        r = self._call(tarih_baslangic='2025-01-01')
        for s in r['liste']:
            tarih = (s.get('olusturma_tarihi') or '')[:10]
            if tarih:
                self.assertGreaterEqual(tarih, '2025-01-01')

    # 7 — tarih_bitis only
    def test_07_tarih_bitis_only(self):
        r = self._call(tarih_bitis='2024-12-31')
        for s in r['liste']:
            tarih = (s.get('olusturma_tarihi') or '')[:10]
            if tarih:
                self.assertLessEqual(tarih, '2024-12-31')

    # 8 — tarih range
    def test_08_tarih_range(self):
        r = self._call(tarih_baslangic='2025-01-01', tarih_bitis='2026-12-31')
        for s in r['liste']:
            tarih = (s.get('olusturma_tarihi') or '')[:10]
            if tarih:
                self.assertGreaterEqual(tarih, '2025-01-01')
                self.assertLessEqual(tarih, '2026-12-31')

    # 9 — termin range
    def test_09_termin_range(self):
        r = self._call(termin_baslangic='2025-01-01', termin_bitis='2027-12-31')
        for s in r['liste']:
            t = (s.get('termin_tarihi') or '')[:10]
            if t:
                self.assertGreaterEqual(t, '2025-01-01')

    # 10 — iki filtre AND
    def test_10_two_filters_and(self):
        r = self._call(durumlar=['ONAYLANDI'], tarih_baslangic='2025-01-01')
        for s in r['liste']:
            self.assertEqual(s['durum'], 'ONAYLANDI')

    # 11 — filtered total_count doğru
    def test_11_filtered_total_count_accurate(self):
        r = self._call(durumlar=['ONAYLANDI'])
        db_count = self.con.execute(
            "SELECT COUNT(*) FROM nexgen_planlama_siparis WHERE cari_id=? AND durum='ONAYLANDI'",
            (CARI_AYM,)
        ).fetchone()[0]
        self.assertEqual(r['total_count'], db_count)

    # 12 — filtered pagination overlap yok
    def test_12_filtered_pagination_no_overlap(self):
        r1 = self._call(durumlar=['ONAYLANDI'], limit=5, offset=0)
        if r1['total_count'] <= 5:
            self.skipTest('5\'ten az ONAYLANDI sipariş var')
        r2 = self._call(durumlar=['ONAYLANDI'], limit=5, offset=5)
        ids1 = {s['id'] for s in r1['liste']}
        ids2 = {s['id'] for s in r2['liste']}
        self.assertEqual(ids1 & ids2, set(), 'page1/page2 overlap!')

    # 13 — SQL parametre güvenliği
    def test_13_sql_injection_safety(self):
        payloads = ["'; DROP TABLE nexgen_planlama_siparis; --", '%', "O'Neil", '%%', '\\']
        for p in payloads:
            try:
                r = self._call(siparis_no=p)
                self.assertIsInstance(r['liste'], list)
            except Exception as e:
                self.fail(f'Payload crash: {p!r} → {e}')

    # 20 — ödeme single
    def test_20_odeme_single(self):
        r = self._call(odeme_tipleri=['NAKIT'])
        for s in r['liste']:
            self.assertEqual((s.get('odeme_tipi') or '').upper(), 'NAKIT')

    # 21 — ödeme multi
    def test_21_odeme_multi(self):
        r = self._call(odeme_tipleri=['NAKIT', 'CEK'])
        allowed = {'NAKIT', 'CEK'}
        for s in r['liste']:
            self.assertIn((s.get('odeme_tipi') or '').upper(), allowed)

    # 22 — PB single
    def test_22_pb_single(self):
        r = self._call(para_birimleri=['TRY'])
        for s in r['liste']:
            self.assertEqual((s.get('para_birimi') or 'TRY').upper(), 'TRY')

    # 23 — vade range
    def test_23_vade_range(self):
        r = self._call(vade_min=0, vade_max=30)
        for s in r['liste']:
            vg = s.get('vade_gun')
            if vg not in (None, ''):
                self.assertGreaterEqual(int(vg), 0)
                self.assertLessEqual(int(vg), 30)

    # 24 — toplam min
    def test_24_toplam_min(self):
        r = self._call(toplam_min=1000)
        for s in r['liste']:
            tt = s.get('toplam_tutar')
            if tt not in (None, ''):
                self.assertGreaterEqual(float(str(tt).replace(',', '.')), 1000)

    # 25 — plan kodu text
    def test_25_plan_kodu(self):
        r = self._call(plan_kodu='NP-2026')
        self.assertIsInstance(r['liste'], list)

    # 26 — batch kodu text
    def test_26_batch_kodu(self):
        r = self._call(batch_kodu='BATCH')
        self.assertIsInstance(r['liste'], list)

    # 27 — kombinasyon odeme + pb
    def test_27_combined_odeme_pb(self):
        r = self._call(odeme_tipleri=['VADELI'], para_birimleri=['TRY'])
        for s in r['liste']:
            self.assertEqual((s.get('odeme_tipi') or '').upper(), 'VADELI')
            self.assertEqual((s.get('para_birimi') or 'TRY').upper(), 'TRY')

    # 28 — filtered pagination odeme
    def test_28_filtered_pagination_odeme(self):
        r1 = self._call(odeme_tipleri=['NAKIT'], limit=5, offset=0)
        total = r1['total_count']
        if total <= 5:
            self.skipTest('5 ten az NAKIT siparis')
        r2 = self._call(odeme_tipleri=['NAKIT'], limit=5, offset=5)
        ids1 = {s['id'] for s in r1['liste']}
        ids2 = {s['id'] for s in r2['liste']}
        self.assertTrue(ids1.isdisjoint(ids2))

    # 29 — son sevkiyat date range
    def test_29_son_sevk_date_range(self):
        r = self._call(sevk_baslangic='2020-01-01', sevk_bitis='2030-12-31')
        self.assertIsInstance(r['liste'], list)
        for s in r['liste']:
            ss = (s.get('son_sevkiyat_tarihi') or '')[:10]
            if ss:
                self.assertGreaterEqual(ss, '2020-01-01')
                self.assertLessEqual(ss, '2030-12-31')

    # 30 — PB multi
    def test_30_pb_multi(self):
        r = self._call(para_birimleri=['TRY', 'USD'])
        allowed = {'TRY', 'USD'}
        for s in r['liste']:
            self.assertIn((s.get('para_birimi') or 'TRY').upper(), allowed)

    # 31 — TRY min
    def test_31_try_min(self):
        r = self._call(try_min=1000)
        self.assertIsInstance(r['liste'], list)
        for s in r['liste']:
            tt = s.get('toplam_tutar_try')
            if tt not in (None, ''):
                self.assertGreaterEqual(float(str(tt).replace(',', '.')), 1000)

    # 32 — fiyat tipi COKLU
    def test_32_fiyat_tipi_coklu(self):
        r = self._call(fiyat_tipleri=['COKLU'])
        self.assertIsInstance(r['liste'], list)

    # 33 — fiyat tipi BELIRTILMEMIS
    def test_33_fiyat_tipi_belirtilmemis(self):
        r = self._call(fiyat_tipleri=['BELIRTILMEMIS'])
        for s in r['liste']:
            has_price = any(
                (k.get('net_birim_fiyat') or k.get('birim_fiyat')) not in (None, '')
                for k in (s.get('kalemler') or [])
            )
            self.assertFalse(has_price)

    # 34 — kalem min
    def test_34_kalem_min(self):
        r = self._call(kalem_min=1)
        for s in r['liste']:
            ks = s.get('kalem_sayisi')
            if ks is not None:
                self.assertGreaterEqual(int(ks), 1)

    # 35 — numune VAR
    def test_35_numune_var(self):
        r = self._call(numune_durumlari=['VAR'])
        for s in r['liste']:
            self.assertGreater(int(s.get('bagli_numune_sayisi') or 0), 0)

    # 36 — numune YOK
    def test_36_numune_yok(self):
        r = self._call(numune_durumlari=['YOK'])
        for s in r['liste']:
            self.assertEqual(int(s.get('bagli_numune_sayisi') or 0), 0)

    # 37 — uretilen kg min
    def test_37_uretilen_kg_min(self):
        r = self._call(uretilen_kg_min=0)
        self.assertIsInstance(r['liste'], list)

    # 38 — sevk kg min
    def test_38_sevk_kg_min(self):
        r = self._call(sevk_kg_min=0)
        self.assertIsInstance(r['liste'], list)

    # 39 — kombinasyon geniş
    def test_39_combined_multi_filters(self):
        r = self._call(
            durumlar=['TASLAK'],
            numune_durumlari=['YOK'],
            kalem_min=1,
        )
        for s in r['liste']:
            self.assertEqual(s['durum'], 'TASLAK')
            self.assertEqual(int(s.get('bagli_numune_sayisi') or 0), 0)
            self.assertGreaterEqual(int(s.get('kalem_sayisi') or 0), 1)

    # 40 — filtered pagination kalem
    def test_40_filtered_pagination_kalem(self):
        r1 = self._call(kalem_min=1, limit=5, offset=0)
        total = r1['total_count']
        if total <= 5:
            self.skipTest('5 ten az kalem>=1 siparis')
        r2 = self._call(kalem_min=1, limit=5, offset=5)
        ids1 = {s['id'] for s in r1['liste']}
        ids2 = {s['id'] for s in r2['liste']}
        self.assertTrue(ids1.isdisjoint(ids2))


# C360-SIPARIS-FILTER-COVERAGE-01 — 17/17 kolon filtre zorunluluğu
_TICARI_FILTER_COLS = (
    'siparis_no', 'tarih', 'durum', 'odeme', 'vade', 'pb', 'toplam',
    'try', 'fiyat', 'termin', 'plan', 'batch', 'uretilen_kg', 'kalem',
    'numune', 'son_sevk', 'sevk_kg',
)


def _extract_ticari_thead_block(html: str) -> str:
    marker = "if (ticari) {"
    idx = html.find(marker)
    if idx < 0:
        return ''
    sub = html[idx:idx + 2500]
    end = sub.find('} else {')
    return sub[:end] if end > 0 else sub


class FilterCoverageLockTests(unittest.TestCase):
    """C360-SIPARIS-FILTER-COVERAGE-01 — İşlem hariç 17/17 filtre butonu."""

    @classmethod
    def setUpClass(cls):
        cls.html = TMPL.read_text(encoding='utf-8')
        cls.ticari_block = _extract_ticari_thead_block(cls.html)

    def test_coverage_17_filter_buttons(self):
        self.assertTrue(self.ticari_block, 'ticari thead block bulunamadi')
        fb_count = self.ticari_block.count("_fb('")
        self.assertEqual(fb_count, 17, f'ticari _fb count={fb_count}, beklenen=17')

    def test_coverage_islem_no_filter(self):
        self.assertNotIn("_fb('islem'", self.ticari_block)
        self.assertIn('İşlem</th>', self.ticari_block)

    def test_coverage_each_column_has_filter(self):
        for col in _TICARI_FILTER_COLS:
            self.assertIn("_fb('" + col + "'", self.ticari_block,
                          f'{col} kolonunda filtre butonu yok')

    def test_coverage_column_count_18_with_islem(self):
        th_count = self.ticari_block.count('<th')
        self.assertEqual(th_count, 18, f'th count={th_count}, beklenen=18 (17+İşlem)')


class FiltreTemplateTests(unittest.TestCase):
    """HTML template — filtre contract."""

    def setUp(self):
        self.html = TMPL.read_text(encoding='utf-8')

    # 14 — filtre butonları mevcut
    def test_14_fbtn_buttons_present(self):
        self.assertIn('ckart-sip-fbtn', self.html)
        for col in ('siparis_no', 'tarih', 'durum', 'termin'):
            self.assertIn('data-fcol="' + col + '"', self.html)
        for col in _TICARI_FILTER_COLS:
            self.assertIn("_fb('" + col + "'", self.html)

    # 15 — JS filtre state ve URL builder mevcut
    def test_15_js_filter_state_present(self):
        self.assertIn('_sipFilters', self.html)
        self.assertIn('_ckartSipFilterUrl', self.html)
        self.assertIn('_ckartSipOpenPopup', self.html)
        self.assertIn('_ckartSipApplyFilter', self.html)

    # 16 — ckartSiparisYukle _ckartSipFilterUrl() kullanıyor
    def test_16_yukle_uses_filter_url(self):
        self.assertIn('_ckartSipFilterUrl()', self.html)

    # 17 — Pagination lock: ckartSipGitPage filtre korumalı
    def test_17_pagination_filter_preserved(self):
        # ckartSipGitPage'in URL'i artık _ckartSipFilterUrl üzerinden gitmeli
        # eski hardcoded '/siparisler?page=' + _sipPage pattern ckartSiparisYukle içinde olmamalı
        import re
        # _ckartSipFilterUrl tanımlı ve ckartSiparisYukle içinde kullanılıyor
        self.assertIn('var url = _ckartSipFilterUrl();', self.html)

    # 18 — Temizle butonu mevcut
    def test_18_clear_button_present(self):
        self.assertIn('ckf-clear', self.html)

    # 19 — Tek popup kural: _ckartSipClosePopup + _ckartSipPopupEl
    def test_19_single_popup_contract(self):
        self.assertIn('_ckartSipPopupEl', self.html)
        self.assertIn('_ckartSipClosePopup', self.html)


if __name__ == '__main__':
    unittest.main(verbosity=2)
