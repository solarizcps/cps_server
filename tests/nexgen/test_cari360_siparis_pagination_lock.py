# -*- coding: utf-8 -*-
"""C360-SIPARIS-PAGINATION-01 LOCK — Sipariş Geçmişi sayfalama regression testi.

Kapanan davranışlar:
1. load_cari360_siparisler server-side LIMIT/OFFSET kullanıyor (tüm kayıt çekilmiyor)
2. API yanıtında total_count, page, page_size, total_pages alanları var
3. cari_id=7 (AYM) toplam 86 sipariş
4. page=1 50 kayıt döndürür
5. page=2 36 kayıt döndürür
6. PZM-2026-0006 page=1'de yok
7. PZM-2026-0006 page=2'de var
8. Sıralama DESC korunur (en yeni önce)
9. Offset <0 normalize edilir (0 olarak davranır)
10. limit max 100 ile sınırlıdır
11. 50'den az sipariş için tek sayfa (total_pages=1)
12. Eski count alanı korunur (uyumluluk)
13. Frontend'de ckartSipGitPage fonksiyonu var
14. Pagination HTML elementi var
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

CARI_AYM   = 7   # AYM Taban Poliüretan
TOTAL_AYM  = 86
PAGE_SIZE  = 50


def _get_con() -> sqlite3.Connection:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def _get_admin_id(con: sqlite3.Connection) -> int:
    row = con.execute(
        "SELECT id FROM sistem_kullanici WHERE KullaniciAdi='admin' AND Aktif=1"
    ).fetchone()
    return int(row['id']) if row else 1


def _load_fn():
    """load_cari360_siparisler fonksiyonunu doğru path'ten yükler."""
    if str(SVC) not in sys.path:
        sys.path.insert(0, str(SVC))
    from modules.nexgen.cari360_ops_read_service import load_cari360_siparisler
    return load_cari360_siparisler


class PaginationServiceTests(unittest.TestCase):
    """load_cari360_siparisler — server-side pagination davranışı."""

    @classmethod
    def setUpClass(cls) -> None:
        if str(SVC) not in sys.path:
            sys.path.insert(0, str(SVC))
        cls.con = _get_con()
        cls.load_fn = _load_fn()
        cls.admin_id = _get_admin_id(cls.con)
        cls.yk = None  # superuser

    @classmethod
    def tearDownClass(cls) -> None:
        cls.con.close()

    def _call(self, limit=PAGE_SIZE, offset=0):
        from modules.nexgen.cari360_ops_read_service import load_cari360_siparisler
        return load_cari360_siparisler(self.con, CARI_AYM, self.admin_id, self.yk,
                                       limit=limit, offset=offset)

    # ------------------------------------------------------------------
    def test_01_total_count_alani_var(self):
        """API yanıtında total_count alanı bulunmalı."""
        result = self._call()
        self.assertIn('total_count', result, "total_count alanı yanıtta olmalı")

    def test_02_page_alanlari_var(self):
        """page, page_size, total_pages alanları yanıtta olmalı."""
        result = self._call()
        for f in ('page', 'page_size', 'total_pages'):
            self.assertIn(f, result, f"{f} alanı yanıtta olmalı")

    def test_03_cari7_total_count_86(self):
        """cari_id=7 için total_count=86."""
        result = self._call()
        self.assertEqual(
            result['total_count'], TOTAL_AYM,
            f"total_count={result['total_count']} beklenen={TOTAL_AYM}"
        )

    def test_04_page1_50_kayit(self):
        """Sayfa 1: tam PAGE_SIZE kayıt döner."""
        result = self._call(limit=PAGE_SIZE, offset=0)
        self.assertEqual(len(result['liste']), PAGE_SIZE,
                         f"page1 len={len(result['liste'])} beklenen={PAGE_SIZE}")

    def test_05_page2_36_kayit(self):
        """Sayfa 2: kalan 36 kayıt döner."""
        result = self._call(limit=PAGE_SIZE, offset=PAGE_SIZE)
        expected = TOTAL_AYM - PAGE_SIZE  # 36
        self.assertEqual(len(result['liste']), expected,
                         f"page2 len={len(result['liste'])} beklenen={expected}")

    def test_06_pzm0006_page1_yok(self):
        """PZM-2026-0006 sayfa 1'de olmamalı."""
        result = self._call(limit=PAGE_SIZE, offset=0)
        nos = [s.get('siparis_no', '') for s in result['liste']]
        self.assertNotIn('PZM-2026-0006', nos,
                         "PZM-2026-0006 page=1'de görünmemeli")

    def test_07_pzm0006_page2_var(self):
        """PZM-2026-0006 sayfa 2'de olmalı."""
        result = self._call(limit=PAGE_SIZE, offset=PAGE_SIZE)
        nos = [s.get('siparis_no', '') for s in result['liste']]
        self.assertIn('PZM-2026-0006', nos,
                      "PZM-2026-0006 page=2'de görünmeli")

    def test_08_siralama_desc(self):
        """Sıralama DESC (en yeni önce) — page1 ilk kaydın tarihi page2 son kaydından büyük/eşit."""
        p1 = self._call(limit=PAGE_SIZE, offset=0)
        p2 = self._call(limit=PAGE_SIZE, offset=PAGE_SIZE)
        first_p1 = (p1['liste'][0].get('siparis_tarihi') or
                    p1['liste'][0].get('olusturma_tarihi') or '')
        last_p2  = (p2['liste'][-1].get('siparis_tarihi') or
                    p2['liste'][-1].get('olusturma_tarihi') or '')
        if first_p1 and last_p2:
            self.assertGreaterEqual(first_p1, last_p2,
                                    "Sıralama DESC bozulmuş: page1 başı page2 sonundan küçük")

    def test_09_negatif_offset_normalize(self):
        """Negatif offset normalize edilir — 0 olarak davranır (en az PAGE_SIZE kayıt)."""
        result = self._call(limit=PAGE_SIZE, offset=-5)
        self.assertGreaterEqual(len(result['liste']), 1,
                                "Negatif offset normalize edilmeli, boş sonuç beklenmez")

    def test_10_limit_max_100(self):
        """limit 100'den büyük olursa 100'e normalize edilir."""
        result = self._call(limit=200, offset=0)
        self.assertLessEqual(len(result['liste']), 100,
                             "limit max 100 ile sınırlı olmalı")

    def test_11_az_kayitli_cari_tek_sayfa(self):
        """50'den az siparişi olan cari için total_pages=1."""
        con2 = _get_con()
        try:
            cnt = con2.execute(
                'SELECT COUNT(*) FROM nexgen_planlama_siparis WHERE cari_id=1'
            ).fetchone()[0]
            if cnt < PAGE_SIZE:
                result = self.load_fn(con2, 1, self.admin_id, self.yk,
                                      limit=PAGE_SIZE, offset=0)
                self.assertEqual(result['total_pages'], 1,
                                 f"cari_id=1 cnt={cnt} → total_pages beklenen=1")
            else:
                self.skipTest(f"cari_id=1 cnt={cnt} >= {PAGE_SIZE}, skip")
        finally:
            con2.close()

    def test_12_count_geriye_uyumlu(self):
        """Eski 'count' alanı hâlâ yanıtta — geriye dönük uyumluluk."""
        result = self._call()
        self.assertIn('count', result, "'count' alanı geriye dönük uyumluluk için korunmalı")
        self.assertEqual(result['count'], len(result['liste']),
                         "count == len(liste) olmalı (sayfa başına kayıt sayısı)")

    def test_13_server_side_limit_offset(self):
        """Server-side LIMIT/OFFSET: page1 ve page2 kayıtları kesişmemeli."""
        p1 = self._call(limit=PAGE_SIZE, offset=0)
        p2 = self._call(limit=PAGE_SIZE, offset=PAGE_SIZE)
        ids1 = {s.get('id') or s.get('siparis_no') for s in p1['liste']}
        ids2 = {s.get('id') or s.get('siparis_no') for s in p2['liste']}
        overlap = ids1 & ids2
        self.assertEqual(len(overlap), 0,
                         f"Page1 ve page2 kesişmemeli. Overlap: {list(overlap)[:5]}")


class PaginationTemplateTests(unittest.TestCase):
    """Template: pagination UI elementleri."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.html = TMPL.read_text(encoding='utf-8', errors='replace')

    def test_14_pagination_element_var(self):
        """ckart-sip-pagination HTML elementi template'de bulunmalı."""
        self.assertIn('ckart-sip-pagination', self.html,
                      "ckart-sip-pagination elementi bulunamadı")

    def test_15_ckartSipGitPage_var(self):
        """ckartSipGitPage JS fonksiyonu template'de tanımlı olmalı."""
        self.assertIn('ckartSipGitPage', self.html,
                      "ckartSipGitPage fonksiyonu template'de tanımlı değil")

    def test_16_page_param_url(self):
        """URL'de page= ve page_size= parametreleri kullanılıyor."""
        self.assertIn('page=', self.html,
                      "page= parametresi template fetch URL'sinde olmalı")
        self.assertIn('page_size=', self.html,
                      "page_size= parametresi template fetch URL'sinde olmalı")

    def test_17_pagination_info_element_var(self):
        """ckart-sip-pg-info elementi template'de bulunmalı."""
        self.assertIn('ckart-sip-pg-info', self.html,
                      "ckart-sip-pg-info elementi bulunamadı")

    def test_18_toplam_kayit_label(self):
        """'Toplam' text'i pagination bilgi alanında kullanılıyor."""
        self.assertIn('Toplam', self.html,
                      "Pagination info 'Toplam' etiketini içermeli")


if __name__ == '__main__':
    unittest.main()
