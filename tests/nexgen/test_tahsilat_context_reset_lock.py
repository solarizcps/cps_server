# -*- coding: utf-8 -*-
"""
test_tahsilat_context_reset_lock.py
Lock: cari/siparis/sevkiyat baglamı degistiginde eski finansal state'in
aninda temizlenmesini kanitlar.
DB kullanmaz — deterministic statik HTML inceleme.
"""
from __future__ import annotations

import os
import re
import sqlite3
import sys
import unittest

TEMPLATE = os.path.join(
    os.path.dirname(__file__), '..', '..',
    'app', 'templates', 'nexgen', 'musteri_pazarlama.html'
)
DB = os.path.join(
    os.path.dirname(__file__), '..', '..',
    'app', 'mock_data.db'
)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'app'))


def _src():
    with open(TEMPLATE, encoding='utf-8') as f:
        return f.read()


def _helper_body(src=None):
    s = src or _src()
    m = re.search(
        r'function clearTahsilatFinancialContext\s*\(\s*\)\s*\{(.*?)(?=\n  function |\n  /\*\*)',
        s, re.S
    )
    if not m:
        raise AssertionError('clearTahsilatFinancialContext bulunamadi')
    return m.group(1)


def _cari_handler(src=None):
    s = src or _src()
    m = re.search(
        r"getElementById\('mp-t-cari'\)\.addEventListener\('change'.*?\}\);",
        s, re.S
    )
    if not m:
        raise AssertionError('mp-t-cari change listener bulunamadi')
    return m.group(0)


def _siparis_handler(src=None):
    s = src or _src()
    m = re.search(
        r"getElementById\('mp-t-siparis'\)\.addEventListener\('change'.*?\}\);",
        s, re.S
    )
    if not m:
        raise AssertionError('mp-t-siparis change listener bulunamadi')
    return m.group(0)


def _sevk_handler(src=None):
    s = src or _src()
    m = re.search(
        r"sevkSel\.addEventListener\('change'.*?\}\);",
        s, re.S
    )
    if not m:
        raise AssertionError('sevkSel change listener bulunamadi')
    return m.group(0)


# ── A. clearTahsilatFinancialContext helper kontrati ────────────────────

class TestClearFinancialContextHelper(unittest.TestCase):

    def test_01_helper_declared(self):
        """clearTahsilatFinancialContext fonksiyonu bildirilmis olmali."""
        self.assertIn('function clearTahsilatFinancialContext', _src())

    def test_02_clears_hedef_display(self):
        """mp-t-hedef-display em-dash yapilmali."""
        body = _helper_body()
        # em-dash karakteri (U+2014) — farkli encoding olabilir; hedefDisp.textContent ataması yeterli
        self.assertIn("hedefDisp.textContent", body)
        # Atama '—' veya '\u2014' icerir
        self.assertTrue(
            "hedefDisp.textContent = '\u2014'" in body or
            "hedefDisp.textContent = '—'" in body,
            "hedefDisp.textContent em-dash atamasi bulunamadi"
        )

    def test_03_clears_hedef_formula(self):
        """mp-t-hedef-formula bosaltilmali."""
        body = _helper_body()
        self.assertIn("hedefFormula.textContent = ''", body)

    def test_04_clears_beklenen_input(self):
        """mp-t-beklenen value bosaltilmali."""
        body = _helper_body()
        self.assertIn("bekEl.value = ''", body)

    def test_05_clears_kalan_display(self):
        """mp-t-kalan-display em-dash yapilmali."""
        body = _helper_body()
        self.assertIn("kalanDisp.textContent", body)
        self.assertTrue(
            "kalanDisp.textContent = '\u2014'" in body or
            "kalanDisp.textContent = '—'" in body,
            "kalanDisp.textContent em-dash atamasi bulunamadi"
        )

    def test_06_calls_clear_manuel_kur(self):
        """clearManuelKurInput() cagrisi olmali."""
        body = _helper_body()
        self.assertIn('clearManuelKurInput()', body)

    def test_07_hides_manuel_kur_wrap(self):
        """manuel kur wrapper gizlenmeli."""
        body = _helper_body()
        self.assertIn("kurWrap.hidden = true", body)

    def test_08_resets_sevk_pb(self):
        """tahsilatSevkPb = null yapilmali."""
        body = _helper_body()
        self.assertIn('tahsilatSevkPb = null', body)

    def test_09_resets_sevk_fx_kalan(self):
        """tahsilatSevkFxKalan = null yapilmali."""
        body = _helper_body()
        self.assertIn('tahsilatSevkFxKalan = null', body)

    def test_10_resets_tcmb_frozen(self):
        """tahsilatTcmbFrozen = false yapilmali."""
        body = _helper_body()
        self.assertIn('tahsilatTcmbFrozen = false', body)

    def test_11_resets_sevk_bound(self):
        """tahsilatSevkBound = false yapilmali."""
        body = _helper_body()
        self.assertIn('tahsilatSevkBound = false', body)


# ── B. Handler entegrasyon kontrati ────────────────────────────────────

class TestHandlerIntegration(unittest.TestCase):

    def test_12_cari_change_calls_clear_financial_context(self):
        """Cari change handler (non-draft) clearTahsilatFinancialContext cagrismali."""
        handler = _cari_handler()
        self.assertIn('clearTahsilatFinancialContext()', handler)

    def test_13_cari_change_draft_path_uses_clear_sevk(self):
        """Cari change handler draft dalinda clearTahsilatSevk cagrisi olmali."""
        handler = _cari_handler()
        self.assertIn('clearTahsilatSevk()', handler)

    def test_14_siparis_change_calls_clear_financial_context(self):
        """Siparis change handler clearTahsilatFinancialContext cagrismali."""
        handler = _siparis_handler()
        self.assertIn('clearTahsilatFinancialContext()', handler)

    def test_15_siparis_change_respects_hydrate_flag(self):
        """Siparis change handler hydrate sirasinda temizleme yapmamali."""
        handler = _siparis_handler()
        self.assertIn('tahsilatHydrateKayit', handler)

    def test_16_sevkiyat_change_calls_clear_financial_context(self):
        """Sevkiyat change handler clearTahsilatFinancialContext cagrismali."""
        handler = _sevk_handler()
        self.assertIn('clearTahsilatFinancialContext()', handler)

    def test_17_sevkiyat_change_respects_hydrate_flag(self):
        """Sevkiyat change handler hydrate sirasinda temizleme yapmamali."""
        handler = _sevk_handler()
        self.assertIn('tahsilatHydrateKayit', handler)


# ── C. Request guard — cari id eslesmesi ───────────────────────────────

class TestCariBoundRequestGuard(unittest.TestCase):

    def test_18_load_plan_checks_current_cari_vs_response_cari(self):
        """loadTahsilatPlanlar then blogu guncel cari id ile response cari id'yi karsilastirmali."""
        src = _src()
        m = re.search(
            r'function loadTahsilatPlanlar\s*\([^)]*\)\s*\{(.*?)(?=\n  function )',
            src, re.S
        )
        self.assertIsNotNone(m, 'loadTahsilatPlanlar bulunamadi')
        body = m.group(1)
        self.assertIn('currentCari', body)
        self.assertIn('cariId', body)
        # Eski cari response'u guncel cari ile eslesip eslesmedigi kontrol edilmeli
        self.assertIn("String(cariId) !== String(currentCari.value)", body)


# ── D. Vade ve API kontrat (regression) ────────────────────────────────

class TestVadeAndApiContractRegression(unittest.TestCase):

    def test_vade_220_preserved_after_context_changes(self):
        """acik_planlar hala PZM-2026-0221 icin 220 gun / 2027-03-18 donduruyor."""
        from modules.nexgen.mo_tahsilat_kayit_service import acik_planlar
        con = sqlite3.connect(
            'file:' + DB.replace('\\', '/') + '?mode=ro', uri=True
        )
        con.row_factory = sqlite3.Row
        plans = acik_planlar(con, [5])
        con.close()
        target = next((p for p in plans if p.get('siparis_no') == 'PZM-2026-0221'), None)
        self.assertIsNotNone(target, 'PZM-2026-0221 plani bulunamadi')
        self.assertEqual(target.get('onaylanan_vade_gun'), 220)
        self.assertEqual(target.get('hedef_vade_tarihi'), '2027-03-18')

    def test_modal_session_guard_still_present(self):
        """Onceki session guard degismeden korunuyor olmali."""
        src = _src()
        self.assertIn('var tahsilatModalSession', src)
        self.assertIn('var tahsilatPlanAbort', src)
        self.assertIn('tahsilatModalSession += 1', src)


if __name__ == '__main__':
    unittest.main()
