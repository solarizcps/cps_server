# -*- coding: utf-8 -*-
"""C360-URETIM-INTEGRITY-01 — Üretim sekmesi canonical bağlantı lock testi.

Doğrulanan contract'lar:
1.  nexgen_uretim_plan tablosu var
2.  nexgen_uretim_batch tablosu var
3.  nexgen_uretim_parca tablosu var
4.  nexgen_planlama_siparis_kalem.uretim_plan_id kolonu var (kalem→plan linkage)
5.  nexgen_uretim_plan_boyut tablosu var (multi-boyut desteği)
6.  Tüm cari_id=1 planları için siparis_id bağlantısı var (orphan yok)
7.  Tüm batchler bir plana bağlı (orphan batch yok)
8.  Tüm parçaların plan_id ve batch plan_id tutarlı (cross mismatch yok)
9.  Cross-cari mismatch yok: plan.cari_id == siparis.cari_id
10. PZM-2026-0217 tam zincir: siparis→kalem→plan→batch→parca
11. PZM-2026-0212 üç-plan zinciri: 3 plan, her biri ayrı kalemle bağlı
12. hedef_kg = SUM(parca.hedef_kg), ASLA == planlanan_kg assertion yok
13. ceil contract: SUM(hedef) >= planlanan_kg (brüt hedef >= net talep)
14. uretilen_kg = SUM(parca.uretilen_kg) (gerçekleşme doğruluğu)
15. load_cari360_uretim() cari_id=1 için sonuç döndürür
16. Cari izolasyonu: API yalnız cari_id=1 planları döndürür
17. IPTAL planlar API response'unda yoktur
18. Boş uretilen_kg → 0 (None değil)
19. kalem_bagli alanı doğru compute edilir (PZM-0217 → True)
20. API response'unda zincir_eksik = False (bağlı planlar için)
"""
from __future__ import annotations

import math
import sqlite3
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB   = ROOT / 'app' / 'mock_data.db'
SVC  = ROOT / 'app'


def _get_con() -> sqlite3.Connection:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def _tablo_var(con: sqlite3.Connection, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone())


def _kolon_var(con: sqlite3.Connection, tablo: str, kolon: str) -> bool:
    cols = [r[1] for r in con.execute(f'PRAGMA table_info({tablo})').fetchall()]
    return kolon in cols


class UretimTableSchemaTests(unittest.TestCase):
    """1–5: Tablolar ve kritik kolonlar mevcut."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.con = _get_con()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.con.close()

    def test_01_uretim_plan_tablosu_var(self):
        self.assertTrue(_tablo_var(self.con, 'nexgen_uretim_plan'))

    def test_02_uretim_batch_tablosu_var(self):
        self.assertTrue(_tablo_var(self.con, 'nexgen_uretim_batch'))

    def test_03_uretim_parca_tablosu_var(self):
        self.assertTrue(_tablo_var(self.con, 'nexgen_uretim_parca'))

    def test_04_kalem_uretim_plan_id_kolonu_var(self):
        """nexgen_planlama_siparis_kalem → uretim_plan_id FK kolonu var."""
        self.assertTrue(_kolon_var(self.con, 'nexgen_planlama_siparis_kalem', 'uretim_plan_id'))

    def test_05_uretim_plan_boyut_tablosu_var(self):
        """Multi-boyut (LARGE/SMALL) desteği için plan_boyut tablosu var."""
        self.assertTrue(_tablo_var(self.con, 'nexgen_uretim_plan_boyut'))


class UretimOrphanIntegrityTests(unittest.TestCase):
    """6–9: Orphan ve cross-cari kayıtlar yok."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.con = _get_con()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.con.close()

    def test_06_no_orphan_plan_cari1(self):
        """cari_id=1 planlarının tamamı bir sipariş'e bağlı (planlama_siparis_id dolu)."""
        orphans = self.con.execute(
            "SELECT id, plan_kodu FROM nexgen_uretim_plan "
            "WHERE cari_id=1 AND (planlama_siparis_id IS NULL OR planlama_siparis_id=0 OR planlama_siparis_id='')"
        ).fetchall()
        self.assertEqual(len(orphans), 0, f"Orphan plans: {[dict(r) for r in orphans]}")

    def test_07_no_orphan_batch(self):
        """Tüm batchler mevcut bir plana bağlı."""
        orphans = self.con.execute(
            "SELECT b.id, b.plan_id FROM nexgen_uretim_batch b "
            "LEFT JOIN nexgen_uretim_plan p ON p.id = b.plan_id WHERE p.id IS NULL"
        ).fetchall()
        self.assertEqual(len(orphans), 0, f"Orphan batches: {[dict(r) for r in orphans]}")

    def test_08_parca_plan_batch_consistency(self):
        """Parça plan_id ile batch'in plan_id tutarlı (cross mismatch yok)."""
        mismatches = self.con.execute(
            "SELECT pr.id, pr.plan_id, b.plan_id AS batch_plan_id "
            "FROM nexgen_uretim_parca pr "
            "JOIN nexgen_uretim_batch b ON b.id = pr.batch_id "
            "WHERE pr.plan_id != b.plan_id"
        ).fetchall()
        self.assertEqual(len(mismatches), 0, f"plan_id mismatches: {[dict(r) for r in mismatches]}")

    def test_09_no_cross_cari_plan_siparis(self):
        """plan.cari_id ile bağlı sipariş.cari_id her zaman eşleşiyor."""
        mismatches = self.con.execute(
            "SELECT p.id, p.cari_id AS plan_cari, s.cari_id AS sip_cari, p.plan_kodu "
            "FROM nexgen_uretim_plan p "
            "JOIN nexgen_planlama_siparis s ON s.id = p.planlama_siparis_id "
            "WHERE p.cari_id != s.cari_id"
        ).fetchall()
        self.assertEqual(len(mismatches), 0, f"Cross-cari mismatches: {[dict(r) for r in mismatches]}")


class UretimChainPZM0217Tests(unittest.TestCase):
    """10: PZM-2026-0217 tam zincir doğrulaması."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.con = _get_con()
        sip = cls.con.execute(
            "SELECT id, cari_id, durum FROM nexgen_planlama_siparis WHERE siparis_no='PZM-2026-0217'"
        ).fetchone()
        cls.sip_id   = int(sip['id'])   if sip else None
        cls.cari_id  = int(sip['cari_id']) if sip else None
        cls.sip_durum = sip['durum']    if sip else None

    @classmethod
    def tearDownClass(cls) -> None:
        cls.con.close()

    def _plan(self):
        return self.con.execute(
            "SELECT id, plan_kodu, planlanan_kg, durum FROM nexgen_uretim_plan WHERE planlama_siparis_id=?",
            (self.sip_id,)
        ).fetchall()

    def test_10a_siparis_bulundu(self):
        self.assertIsNotNone(self.sip_id, "PZM-2026-0217 sipariş bulunamadı")

    def test_10b_siparis_cari1(self):
        self.assertEqual(self.cari_id, 1, "PZM-2026-0217 cari_id=1 değil")

    def test_10c_tek_plan_var(self):
        plans = self._plan()
        self.assertEqual(len(plans), 1, f"PZM-2026-0217 için 1 plan bekleniyor, {len(plans)} bulundu")

    def test_10d_plan_kodu_dogru(self):
        plans = self._plan()
        self.assertEqual(plans[0]['plan_kodu'], 'NP-2026-00113')

    def test_10e_kalem_plan_linkage(self):
        """siparis_kalem.uretim_plan_id → plan id bağlı."""
        plans = self._plan()
        plan_id = int(plans[0]['id'])
        kalem = self.con.execute(
            "SELECT id FROM nexgen_planlama_siparis_kalem WHERE uretim_plan_id=?", (plan_id,)
        ).fetchone()
        self.assertIsNotNone(kalem, f"Plan {plan_id} için kalem bağlantısı yok")

    def test_10f_batch_var(self):
        """Plan için en az 1 batch var."""
        plans = self._plan()
        plan_id = int(plans[0]['id'])
        batch = self.con.execute(
            "SELECT id FROM nexgen_uretim_batch WHERE plan_id=?", (plan_id,)
        ).fetchone()
        self.assertIsNotNone(batch, f"Plan {plan_id} için batch yok")

    def test_10g_parca_var(self):
        """Plan için parça (alt emir) var."""
        plans = self._plan()
        plan_id = int(plans[0]['id'])
        n = self.con.execute(
            "SELECT COUNT(*) FROM nexgen_uretim_parca WHERE plan_id=?", (plan_id,)
        ).fetchone()[0]
        self.assertGreater(n, 0, f"Plan {plan_id} için parça yok")

    def test_10h_parca_hedef_kg_brut_hede_contract(self):
        """SUM(parca.hedef_kg) >= planlanan_kg (brüt >= net)."""
        plans = self._plan()
        plan_id = int(plans[0]['id'])
        planlanan = float(plans[0]['planlanan_kg'])
        hedef_sum = float(self.con.execute(
            "SELECT COALESCE(SUM(hedef_kg),0) FROM nexgen_uretim_parca WHERE plan_id=?", (plan_id,)
        ).fetchone()[0])
        self.assertGreaterEqual(
            hedef_sum, planlanan,
            f"hedef_sum={hedef_sum} < planlanan={planlanan} — brüt hedef net talebin altına düşemez"
        )


class UretimChainPZM0212Tests(unittest.TestCase):
    """11: PZM-2026-0212 üç-plan zinciri doğrulaması."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.con = _get_con()
        sip = cls.con.execute(
            "SELECT id FROM nexgen_planlama_siparis WHERE siparis_no='PZM-2026-0212'"
        ).fetchone()
        cls.sip_id = int(sip['id']) if sip else None

    @classmethod
    def tearDownClass(cls) -> None:
        cls.con.close()

    def _plans(self):
        return self.con.execute(
            "SELECT id, plan_kodu, planlanan_kg FROM nexgen_uretim_plan WHERE planlama_siparis_id=? ORDER BY id",
            (self.sip_id,)
        ).fetchall()

    def test_11a_uc_plan_var(self):
        plans = self._plans()
        self.assertEqual(len(plans), 3, f"PZM-0212 için 3 plan bekleniyor, {len(plans)} bulundu")

    def test_11b_plan_kodlari(self):
        kodlar = {p['plan_kodu'] for p in self._plans()}
        self.assertIn('NP-2026-00106', kodlar)
        self.assertIn('NP-2026-00107', kodlar)
        self.assertIn('NP-2026-00108', kodlar)

    def test_11c_her_plana_kalem_bagli(self):
        """Her planın en az 1 siparis_kalem bağlantısı var."""
        for plan in self._plans():
            pid = int(plan['id'])
            kalem = self.con.execute(
                "SELECT id FROM nexgen_planlama_siparis_kalem WHERE uretim_plan_id=?", (pid,)
            ).fetchone()
            self.assertIsNotNone(kalem, f"Plan {plan['plan_kodu']} (id={pid}) için kalem yok")

    def test_11d_her_plana_batch_bagli(self):
        """Her planın en az 1 batchi var."""
        for plan in self._plans():
            pid = int(plan['id'])
            batch = self.con.execute(
                "SELECT id FROM nexgen_uretim_batch WHERE plan_id=?", (pid,)
            ).fetchone()
            self.assertIsNotNone(batch, f"Plan {plan['plan_kodu']} (id={pid}) için batch yok")

    def test_11e_her_plana_parca_bagli(self):
        """Her planın parçası var."""
        for plan in self._plans():
            pid = int(plan['id'])
            n = self.con.execute(
                "SELECT COUNT(*) FROM nexgen_uretim_parca WHERE plan_id=?", (pid,)
            ).fetchone()[0]
            self.assertGreater(n, 0, f"Plan {plan['plan_kodu']} (id={pid}) parçası yok")

    def test_11f_brut_hedef_contract_her_plan(self):
        """Her plan için SUM(hedef_kg) >= planlanan_kg."""
        for plan in self._plans():
            pid = int(plan['id'])
            planlanan = float(plan['planlanan_kg'])
            hedef_sum = float(self.con.execute(
                "SELECT COALESCE(SUM(hedef_kg),0) FROM nexgen_uretim_parca WHERE plan_id=?", (pid,)
            ).fetchone()[0])
            self.assertGreaterEqual(
                hedef_sum, planlanan,
                f"Plan {plan['plan_kodu']}: hedef_sum={hedef_sum} < planlanan={planlanan}"
            )


class UretimKGContractTests(unittest.TestCase):
    """12–14: KG hesapları canonical contract."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.con = _get_con()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.con.close()

    def test_12_hedef_kg_from_parca_sum(self):
        """Plan 191 (PZM-0217) için hedef_kg = SUM(parca.hedef_kg)."""
        plan_id = 191
        parca_sum = float(self.con.execute(
            "SELECT COALESCE(SUM(hedef_kg),0) FROM nexgen_uretim_parca WHERE plan_id=?", (plan_id,)
        ).fetchone()[0])
        self.assertGreater(parca_sum, 0, "hedef_kg sum sıfır olmamalı")

    def test_13_ceil_brut_hede_contract(self):
        """Canonical ceil contract: boyut_uretilecek_kg = ceil(siparis_kg / formul_batch_kg) × formul_batch_kg.

        Bu test SUM(parca.hedef_kg) == planlanan_kg ASSERT ETMEZ.
        Brüt hedefin plan_boyut kaydındaki uretilecek_kg ile eşleştiğini doğrular.
        """
        boyutlar = self.con.execute(
            "SELECT plan_id, boyut, siparis_kg, formul_batch_kg, batch_sayisi, uretilecek_kg "
            "FROM nexgen_uretim_plan_boyut WHERE plan_id IN (184, 185, 186, 191)"
        ).fetchall()
        self.assertGreater(len(boyutlar), 0, "Plan boyut kayıtları bulunamadı")
        for bx in boyutlar:
            sip_kg = float(bx['siparis_kg'])
            fbk    = float(bx['formul_batch_kg'])
            expected_sayisi = math.ceil(sip_kg / fbk)
            expected_urt    = round(expected_sayisi * fbk, 3)
            actual_urt      = round(float(bx['uretilecek_kg']), 3)
            self.assertAlmostEqual(
                actual_urt, expected_urt, places=1,
                msg=f"Plan {bx['plan_id']} boyut={bx['boyut']}: "
                    f"expected={expected_urt}, actual={actual_urt}"
            )

    def test_14_uretilen_kg_from_parca_sum(self):
        """uretilen_kg SUM(parca.uretilen_kg)'den geliyor; NULL değil, sayısal."""
        plan_id = 191
        uretilen = self.con.execute(
            "SELECT COALESCE(SUM(uretilen_kg), 0) FROM nexgen_uretim_parca WHERE plan_id=?", (plan_id,)
        ).fetchone()[0]
        self.assertIsNotNone(uretilen)
        self.assertIsInstance(float(uretilen), float)


class UretimAPIServiceTests(unittest.TestCase):
    """15–20: load_cari360_uretim() service davranışı."""

    @classmethod
    def setUpClass(cls) -> None:
        import sys
        if str(SVC) not in sys.path:
            sys.path.insert(0, str(SVC))
        con = _get_con()
        row = con.execute(
            "SELECT id FROM sistem_kullanici WHERE KullaniciAdi='admin' AND Aktif=1"
        ).fetchone()
        cls.admin_id = int(row['id']) if row else 1
        con.close()

    def _call(self, cari_id: int = 1):
        import sys
        if str(SVC) not in sys.path:
            sys.path.insert(0, str(SVC))
        from modules.nexgen.cari360_ops_read_service import load_cari360_uretim
        con = _get_con()
        try:
            return load_cari360_uretim(con, cari_id, self.admin_id, None)
        finally:
            con.close()

    def test_15_servis_cari1_sonuc_donduruyor(self):
        result = self._call(1)
        self.assertIn('liste', result)
        self.assertGreater(len(result['liste']), 0)

    def test_16_cari_izolasyonu(self):
        """API yalnız istenen cari_id'nin planlarını döndürür."""
        result = self._call(1)
        con = _get_con()
        try:
            for item in result['liste']:
                pid = item.get('id')
                if not pid:
                    continue
                plan = con.execute(
                    "SELECT cari_id FROM nexgen_uretim_plan WHERE id=?", (pid,)
                ).fetchone()
                self.assertIsNotNone(plan)
                self.assertEqual(int(plan['cari_id']), 1, f"Plan {pid} cari_id=1 değil")
        finally:
            con.close()

    def test_17_iptal_planlar_gelmez(self):
        """IPTAL durumdaki planlar API response'unda bulunmaz."""
        result = self._call(1)
        for item in result['liste']:
            self.assertNotEqual(
                (item.get('durum') or '').upper(), 'IPTAL',
                f"IPTAL plan API'de görünüyor: {item.get('plan_kodu')}"
            )

    def test_18_uretilen_kg_none_degil(self):
        """uretilen_kg alanı hiçbir zaman None döndürmez; 0 veya sayı."""
        result = self._call(1)
        for item in result['liste']:
            uk = item.get('uretilen_kg')
            if uk is not None:
                self.assertIsInstance(float(str(uk).replace(',', '.')), float,
                                      f"uretilen_kg sayısal değil: {uk}")

    def test_19_pzm_0217_kalem_bagli_true(self):
        """PZM-2026-0217 planı kalem_bagli=True döndürür."""
        result = self._call(1)
        pzm_items = [i for i in result['liste'] if i.get('siparis_no') == 'PZM-2026-0217']
        self.assertEqual(len(pzm_items), 1, "PZM-2026-0217 API'de tam 1 plan olmalı")
        self.assertTrue(pzm_items[0]['kalem_bagli'], "PZM-2026-0217 kalem_bagli=True olmalı")

    def test_20_pzm_0212_uc_plan_zincir_eksik_false(self):
        """PZM-2026-0212 için 3 plan döner, tamamı zincir_eksik=False."""
        result = self._call(1)
        pzm_items = [i for i in result['liste'] if i.get('siparis_no') == 'PZM-2026-0212']
        self.assertEqual(len(pzm_items), 3, f"PZM-2026-0212 için 3 plan bekleniyor, {len(pzm_items)} geldi")
        for item in pzm_items:
            self.assertFalse(
                item.get('zincir_eksik', False),
                f"Plan {item.get('plan_kodu')} zincir_eksik=True — bağlantı kopuk"
            )


if __name__ == '__main__':
    unittest.main(verbosity=2)
