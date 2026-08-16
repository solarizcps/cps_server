# -*- coding: utf-8 -*-
"""
test_tahsilat_modal_async_state_lock.py
Lock: modal session/request guard — stale async fetch'lerin
yeni modal DOM/state'ine yazamamasini kanıtlar.
DB kullanmaz. Deterministic HTML statik inceleme.
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


def _reset_body(src=None):
    s = src or _src()
    m = re.search(r'function resetTahsilatModal\s*\([^)]*\)\s*\{(.*?)(?=\n  function )', s, re.S)
    if not m:
        raise AssertionError('resetTahsilatModal bulunamadı')
    return m.group(1)


def _load_body(src=None):
    s = src or _src()
    m = re.search(r'function loadTahsilatPlanlar\s*\([^)]*\)\s*\{(.*?)(?=\n  function )', s, re.S)
    if not m:
        raise AssertionError('loadTahsilatPlanlar bulunamadı')
    return m.group(1)


# ── A. Statik kontrat ─────────────────────────────────────────────────────

class TestModalSessionGuardStatic(unittest.TestCase):
    """HTML/JS kaynak kodunun session guard kontratını içerdiğini doğrular."""

    def test_01_tahsilat_modal_session_var_declared(self):
        self.assertIn('var tahsilatModalSession', _src())

    def test_02_tahsilat_plan_abort_var_declared(self):
        self.assertIn('var tahsilatPlanAbort', _src())

    def test_03_modal_session_incremented_on_reset(self):
        body = _reset_body()
        self.assertIn('tahsilatModalSession += 1', body)

    def test_04_plan_abort_called_on_reset(self):
        body = _reset_body()
        self.assertIn('tahsilatPlanAbort', body)
        self.assertIn('.abort()', body)

    def test_05_plan_abort_reset_to_null_on_reset(self):
        body = _reset_body()
        self.assertIn('tahsilatPlanAbort = null', body)

    def test_06_load_plan_captures_my_session(self):
        body = _load_body()
        self.assertIn('mySession', body)
        self.assertIn('tahsilatModalSession', body)

    def test_07_then_block_checks_session_before_writing_dom(self):
        body = _load_body()
        self.assertIn('tahsilatModalSession !== mySession', body)

    def test_08_catch_block_silences_abort_error(self):
        body = _load_body()
        self.assertIn('AbortError', body)

    def test_09_catch_block_checks_session_before_error_display(self):
        body = _load_body()
        catch_part = body.split('.catch(')[1] if '.catch(' in body else ''
        self.assertIn('mySession', catch_part,
            'catch bloğu da mySession kontrolü yapmalı')

    def test_10_abort_controller_created_in_load(self):
        body = _load_body()
        self.assertIn('AbortController', body)

    def test_11_abort_controller_assigned_to_global(self):
        body = _load_body()
        self.assertIn('tahsilatPlanAbort =', body)

    def test_12_fetch_uses_abort_signal(self):
        body = _load_body()
        self.assertIn('signal', body)

    def test_13_old_plan_abort_cancelled_on_new_load(self):
        body = _load_body()
        self.assertIn('tahsilatPlanAbort', body)
        self.assertIn('abort()', body)


# ── B. Reset kontrat ──────────────────────────────────────────────────────

class TestResetContractStatic(unittest.TestCase):
    """resetTahsilatModal'in tam reset kontratını doğrular."""

    def test_14_reset_clears_hedef_display(self):
        body = _reset_body()
        self.assertIn("hedefDisplay.textContent = '—'", body)

    def test_15_reset_clears_kalan_display(self):
        body = _reset_body()
        self.assertIn("kalanDisplay.textContent = '—'", body)

    def test_16_reset_calls_clear_tahsilat_sevk(self):
        body = _reset_body()
        self.assertIn('clearTahsilatSevk()', body)

    def test_17_reset_calls_clear_manuel_kur(self):
        body = _reset_body()
        self.assertIn('clearManuelKurInput()', body)

    def test_18_reset_nullifies_tcmb_frozen(self):
        body = _reset_body()
        self.assertIn('tahsilatTcmbFrozen = false', body)


# ── C. Typo + API field + vade kontrat ───────────────────────────────────

class TestTypoAndApiField(unittest.TestCase):

    def test_typo_beklened_tutar_exists_in_template(self):
        """`beklened_tutar` (typo) template'de legacy compat olarak bulunuyor."""
        self.assertIn('beklened_tutar', _src())

    def test_api_key_is_beklenen_tutar(self):
        """acik_planlar servis çıktısında alan adı `beklenen_tutar` (typo değil)."""
        from modules.nexgen.mo_tahsilat_kayit_service import acik_planlar
        con = sqlite3.connect('file:' + DB.replace('\\', '/') + '?mode=ro', uri=True)
        con.row_factory = sqlite3.Row
        plans = acik_planlar(con, [5])
        con.close()
        for p in plans:
            self.assertIn('beklenen_tutar', p)
            self.assertNotIn('beklened_tutar', p,
                'API beklened_tutar (typo) dönmemeli')

    def test_vade_220_preserved_in_api(self):
        """PZM-2026-0221 onaylanan_vade_gun=220, hedef=2027-03-18 korunuyor."""
        from modules.nexgen.mo_tahsilat_kayit_service import acik_planlar
        con = sqlite3.connect('file:' + DB.replace('\\', '/') + '?mode=ro', uri=True)
        con.row_factory = sqlite3.Row
        plans = acik_planlar(con, [5])
        con.close()
        target = next((p for p in plans if p.get('siparis_no') == 'PZM-2026-0221'), None)
        self.assertIsNotNone(target, 'PZM-2026-0221 planı bulunamadı')
        self.assertEqual(target.get('onaylanan_vade_gun'), 220)
        self.assertEqual(target.get('hedef_vade_tarihi'), '2027-03-18')


if __name__ == '__main__':
    unittest.main()
