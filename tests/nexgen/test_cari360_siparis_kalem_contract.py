# -*- coding: utf-8 -*-
"""C360-2 — Sipariş kalem batch read-model contract testi (LOCK).

Doğrulanan:
- load_cari360_siparisler() her sipariş için kalemler[] döndürür
- Batch query (N+1 yok)
- PZM-2026-0221 / cari_id=5 beklenen kalem değerleri
- Kalemsiz sipariş: kalemler=[]
- Ticari yetki koruması: ticari_gorunur=False → fiyat alanları yok
"""
from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / 'app' / 'mock_data.db'
SVC = ROOT / 'app'


def _get_con() -> sqlite3.Connection:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


class SiparisKalemContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import sys
        if str(SVC) not in sys.path:
            sys.path.insert(0, str(SVC))
        # admin kullanici id
        con = _get_con()
        row = con.execute(
            "SELECT id FROM sistem_kullanici WHERE KullaniciAdi='admin' AND Aktif=1",
        ).fetchone()
        cls.admin_id = int(row['id']) if row else 1
        con.close()

    def _load(self, cari_id: int) -> dict:
        import sys
        if str(SVC) not in sys.path:
            sys.path.insert(0, str(SVC))
        from modules.nexgen.cari360_ops_read_service import load_cari360_siparisler
        con = _get_con()
        result = load_cari360_siparisler(con, cari_id, self.admin_id, None)
        con.close()
        return result

    # ── Temel varlık ─────────────────────────────────────────────────────────

    def test_a_response_shape(self) -> None:
        d = self._load(5)
        self.assertIn('liste', d)
        self.assertIn('count', d)
        self.assertIn('ticari_gorunur', d)
        self.assertGreater(d['count'], 0)

    def test_b_kalemler_key_in_every_siparis(self) -> None:
        d = self._load(5)
        for s in d['liste']:
            self.assertIn('kalemler', s, msg=f"kalemler key yok: {s.get('siparis_no')}")

    def test_c_pzm_kalem_count(self) -> None:
        d = self._load(5)
        pzm = next((s for s in d['liste'] if s['siparis_no'] == 'PZM-2026-0221'), None)
        self.assertIsNotNone(pzm, 'PZM-2026-0221 bulunamadı')
        self.assertEqual(len(pzm['kalemler']), 1)

    def test_d_pzm_kalem_urun_ailesi(self) -> None:
        d = self._load(5)
        pzm = next(s for s in d['liste'] if s['siparis_no'] == 'PZM-2026-0221')
        k = pzm['kalemler'][0]
        self.assertEqual(k['urun_ailesi'], 'TERLIK')

    def test_e_pzm_kalem_formul_ad(self) -> None:
        d = self._load(5)
        pzm = next(s for s in d['liste'] if s['siparis_no'] == 'PZM-2026-0221')
        k = pzm['kalemler'][0]
        self.assertEqual(k['formul_ad'], 'Terlik 18-28')

    def test_f_pzm_kalem_renk_ad(self) -> None:
        d = self._load(5)
        pzm = next(s for s in d['liste'] if s['siparis_no'] == 'PZM-2026-0221')
        k = pzm['kalemler'][0]
        self.assertIn('0250', k['renk_ad'])

    def test_g_pzm_kalem_miktar_kg(self) -> None:
        d = self._load(5)
        pzm = next(s for s in d['liste'] if s['siparis_no'] == 'PZM-2026-0221')
        k = pzm['kalemler'][0]
        self.assertEqual(k['miktar_kg'], 3000)

    def test_h_pzm_kalem_birim_fiyat(self) -> None:
        d = self._load(5)
        pzm = next(s for s in d['liste'] if s['siparis_no'] == 'PZM-2026-0221')
        k = pzm['kalemler'][0]
        self.assertEqual(k['birim_fiyat'], 4)

    def test_i_pzm_kalem_termin(self) -> None:
        d = self._load(5)
        pzm = next(s for s in d['liste'] if s['siparis_no'] == 'PZM-2026-0221')
        k = pzm['kalemler'][0]
        self.assertEqual(k['termin_tarihi'], '2026-08-27')

    def test_j_pzm_kalem_uretim_plan_id(self) -> None:
        d = self._load(5)
        pzm = next(s for s in d['liste'] if s['siparis_no'] == 'PZM-2026-0221')
        k = pzm['kalemler'][0]
        self.assertEqual(k['uretim_plan_id'], 193)

    def test_k_pzm_kalem_plan_kodu(self) -> None:
        d = self._load(5)
        pzm = next(s for s in d['liste'] if s['siparis_no'] == 'PZM-2026-0221')
        k = pzm['kalemler'][0]
        self.assertEqual(k['plan_kodu'], 'NP-2026-00115')

    def test_l_pzm_kalem_rf_label(self) -> None:
        d = self._load(5)
        pzm = next(s for s in d['liste'] if s['siparis_no'] == 'PZM-2026-0221')
        k = pzm['kalemler'][0]
        self.assertIsNotNone(k['rf_label'])
        self.assertIn('0250 TURUNCU', k['rf_label'])

    def test_m_pzm_kalem_try_null(self) -> None:
        """satir_tutari_try DB'de NULL ise null gelmeli; 0 veya sahte TRY üretilmemeli."""
        d = self._load(5)
        pzm = next(s for s in d['liste'] if s['siparis_no'] == 'PZM-2026-0221')
        k = pzm['kalemler'][0]
        self.assertIsNone(k['satir_tutari_try'])

    # ── Ticari yetki koruması ─────────────────────────────────────────────────

    def test_n_ticari_yetki_kapali_fiyat_gizli(self) -> None:
        """ticari_gorunur=False iken kalem fiyat alanları response'ta bulunmamalı."""
        from modules.nexgen.cari_sorumlu_service import can_view_cari_ticari
        con = _get_con()
        ticari_ok = can_view_cari_ticari(con, self.admin_id, 5, None)
        con.close()
        if ticari_ok:
            # Admin her zaman ticari görüyor; _load_siparis_kalemleri_batch'i doğrudan test et
            from modules.nexgen.cari360_ops_read_service import _load_siparis_kalemleri_batch
            con2 = _get_con()
            km = _load_siparis_kalemleri_batch(con2, [759], ticari_gorunur=False)
            con2.close()
            kl = km.get(759, [])
            if kl:
                k = kl[0]
                self.assertNotIn('birim_fiyat', k)
                self.assertNotIn('satir_tutari', k)
        else:
            self.skipTest('Ticari-kapalı yol test edilemedi')

    # ── Regression: kalemsiz sipariş ────────────────────────────────────────

    def test_o_kalemsiz_siparis_bos_liste(self) -> None:
        """Kalemi olmayan sipariş için kalemler=[] olmalı; hata oluşmamalı."""
        con = _get_con()
        row = con.execute(
            """
            SELECT s.id, s.cari_id FROM nexgen_planlama_siparis s
            WHERE NOT EXISTS (
                SELECT 1 FROM nexgen_planlama_siparis_kalem k
                WHERE k.planlama_siparis_id = s.id
            )
            LIMIT 1
            """,
        ).fetchone()
        con.close()
        if not row:
            self.skipTest("Kalemsiz sipariş DB'de yok")
        cari_id = int(row['cari_id'])
        from modules.nexgen.cari360_ops_read_service import load_cari360_siparisler
        con = _get_con()
        d = load_cari360_siparisler(con, cari_id, self.admin_id, None)
        con.close()
        for s in d['liste']:
            self.assertIn('kalemler', s)
            self.assertIsInstance(s['kalemler'], list)

    # ── Mevcut header aggregate'leri bozulmadı ───────────────────────────────

    def test_p_header_aggregates_preserved(self) -> None:
        """Mevcut sipariş header alanları (kalem_sayisi, plan_sayisi vb.) korunmalı."""
        d = self._load(5)
        pzm = next(s for s in d['liste'] if s['siparis_no'] == 'PZM-2026-0221')
        self.assertEqual(pzm['kalem_sayisi'], 1)
        self.assertGreaterEqual(pzm['plan_sayisi'], 1)
        self.assertEqual(pzm['durum'], 'TAMAMLANDI')
        self.assertIn('toplam_tutar', pzm)  # ticari enrich korunuyor

    def test_q_no_n1_batch_via_api(self) -> None:
        """Batch query çalışıyor mu: response'ta kalemler[] IN(...) ile geliyor."""
        # Service _load_siparis_kalemleri_batch doğrudan çağırarak batch davranışı doğrula
        from modules.nexgen.cari360_ops_read_service import _load_siparis_kalemleri_batch
        con = _get_con()
        # Birden fazla sipariş id'si ile batch çağrısı — hata olmadan çalışmalı
        km = _load_siparis_kalemleri_batch(con, [759, 999999], ticari_gorunur=True)
        con.close()
        self.assertIn(759, km)
        self.assertIn(999999, km)
        self.assertEqual(len(km[759]), 1)
        self.assertEqual(km[999999], [])  # olmayan sipariş → boş liste

    def test_r_kalem_sevk_tarihi_and_siparis_kdv_durumu(self) -> None:
        """C360-FIX: kalem sevk_tarihi read-model + sipariş kdv_durumu enrich."""
        d = self._load(1)
        pzm = next((s for s in d['liste'] if s.get('siparis_no') == 'PZM-2026-0212'), None)
        self.assertIsNotNone(pzm, 'PZM-2026-0212 bulunamadı')
        self.assertEqual(len(pzm['kalemler']), 3)
        self.assertIn('kdv_durumu', pzm)
        self.assertIn(pzm['kdv_durumu'], ('RESMI', 'GAYRI_RESMI', None))
        for k in pzm['kalemler']:
            self.assertIn('sevk_tarihi', k)
            self.assertIn('renk_ad', k)
            self.assertIn('formul_ad', k)
        # sevk edilmiş sipariş: TSVK1-bc8240
        tsvk = next((s for s in d['liste'] if s.get('siparis_no') == 'TSVK1-bc8240'), None)
        if tsvk and tsvk.get('kalemler'):
            has_sevk = any(k.get('sevk_tarihi') for k in tsvk['kalemler'])
            self.assertTrue(has_sevk or tsvk.get('son_sevkiyat_tarihi'),
                            'sevk edilmiş siparişte kalem veya sipariş sevk tarihi olmalı')


if __name__ == '__main__':
    unittest.main()
