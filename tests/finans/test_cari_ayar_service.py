# -*- coding: utf-8 -*-
"""
Test: cari_ayar_service.py direction-safe CRUD + isolation.
"""
import os, sys, sqlite3, tempfile, unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'app'))

from modules.finans.services.cari_ayar_service import (
    ensure_table, get_ayar, save_ayar, build_default_dto,
    compute_system_suggestion_calisma_sekli,
    compute_system_suggestion_odeme_yontemi,
    CariAyarError, AYAR_TABLO
)


def _tmp_db():
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    return path


class TestEnsureTable(unittest.TestCase):
    def test_idempotent(self):
        p = _tmp_db()
        try:
            ensure_table(p)
            ensure_table(p)  # ikinci çağrı hata vermesin
            con = sqlite3.connect(p)
            row = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (AYAR_TABLO,)).fetchone()
            con.close()
            self.assertIsNotNone(row)
        finally:
            os.unlink(p)


class TestGetAyarDefault(unittest.TestCase):
    def test_no_record_returns_default(self):
        p = _tmp_db()
        try:
            ensure_table(p)
            dto = get_ayar('RECEIVABLE', 'SA001', '120.01.001', db_path=p)
            self.assertFalse(dto['has_settings'])
            self.assertEqual(dto['calisma_sekli_mode'], 'OTOMATIK')
            self.assertIsNone(dto['anlasmali_vade_gun'])
        finally:
            os.unlink(p)


class TestSaveAyar(unittest.TestCase):
    def setUp(self):
        self.p = _tmp_db()
        ensure_table(self.p)

    def tearDown(self):
        os.unlink(self.p)

    def test_create_receivable(self):
        result = save_ayar('RECEIVABLE', 'SA001', '120.01.001',
            {'calisma_sekli_mode': 'VADELI', 'anlasmali_vade_gun': 90, 'odeme_yontemi_mode': 'HAVALE'},
            updated_by='test', db_path=self.p)
        self.assertTrue(result['has_settings'])
        self.assertEqual(result['calisma_sekli_mode'], 'VADELI')
        self.assertEqual(result['anlasmali_vade_gun'], 90)
        self.assertEqual(result['odeme_yontemi_mode'], 'HAVALE')

    def test_update_upsert(self):
        save_ayar('RECEIVABLE', 'SA001', '120.01.001',
            {'calisma_sekli_mode': 'PESIN', 'anlasmali_vade_gun': 0, 'odeme_yontemi_mode': 'NAKIT'},
            updated_by='test', db_path=self.p)
        result = save_ayar('RECEIVABLE', 'SA001', '120.01.001',
            {'calisma_sekli_mode': 'VADELI', 'anlasmali_vade_gun': 60, 'odeme_yontemi_mode': 'CEK'},
            updated_by='test2', db_path=self.p)
        self.assertEqual(result['calisma_sekli_mode'], 'VADELI')
        self.assertEqual(result['anlasmali_vade_gun'], 60)

    def test_receivable_payable_isolation(self):
        save_ayar('RECEIVABLE', 'SA001', '120.01.001',
            {'calisma_sekli_mode': 'VADELI', 'anlasmali_vade_gun': 90, 'odeme_yontemi_mode': 'HAVALE'},
            updated_by='test', db_path=self.p)
        # PAYABLE farklı cari kodu kullanalım (320.*)
        save_ayar('PAYABLE', 'SA001', '320.01.001',
            {'calisma_sekli_mode': 'PESIN', 'anlasmali_vade_gun': 0, 'odeme_yontemi_mode': 'NAKIT'},
            updated_by='test', db_path=self.p)
        r_recv = get_ayar('RECEIVABLE', 'SA001', '120.01.001', db_path=self.p)
        r_pay = get_ayar('PAYABLE', 'SA001', '320.01.001', db_path=self.p)
        self.assertEqual(r_recv['calisma_sekli_mode'], 'VADELI')
        self.assertEqual(r_pay['calisma_sekli_mode'], 'PESIN')

    def test_direction_mismatch_120_payable(self):
        with self.assertRaises(CariAyarError):
            save_ayar('PAYABLE', 'SA001', '120.01.001',
                {'calisma_sekli_mode': 'PESIN', 'odeme_yontemi_mode': 'NAKIT'},
                updated_by='test', db_path=self.p)

    def test_direction_mismatch_320_receivable(self):
        with self.assertRaises(CariAyarError):
            save_ayar('RECEIVABLE', 'SA001', '320.01.001',
                {'calisma_sekli_mode': 'PESIN', 'odeme_yontemi_mode': 'NAKIT'},
                updated_by='test', db_path=self.p)

    def test_invalid_vade(self):
        with self.assertRaises(CariAyarError):
            save_ayar('RECEIVABLE', 'SA001', '120.01.001',
                {'calisma_sekli_mode': 'VADELI', 'anlasmali_vade_gun': -5, 'odeme_yontemi_mode': 'NAKIT'},
                updated_by='test', db_path=self.p)

    def test_otomatik_clears_manual(self):
        result = save_ayar('RECEIVABLE', 'SA001', '120.01.001',
            {'calisma_sekli_mode': 'OTOMATIK', 'calisma_sekli_manual': 'VADELI', 'odeme_yontemi_mode': 'OTOMATIK'},
            updated_by='test', db_path=self.p)
        self.assertIsNone(result['calisma_sekli_manual'])


class TestSystemSuggestion(unittest.TestCase):
    def test_no_hareketler_returns_no_data(self):
        result = compute_system_suggestion_calisma_sekli('RECEIVABLE', 'SA001', '120.01.001', [])
        self.assertIn('veri', result.lower())

    def test_no_hareketler_odeme_belirlenemedi(self):
        result = compute_system_suggestion_odeme_yontemi('RECEIVABLE', 'SA001', '120.01.001', [])
        self.assertIn('lenemedi', result.lower())


if __name__ == '__main__':
    unittest.main()
