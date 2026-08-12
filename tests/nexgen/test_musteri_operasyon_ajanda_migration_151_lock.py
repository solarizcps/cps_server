# -*- coding: utf-8 -*-
"""Migration 151 — musteri_operasyon_ajanda — regression lock (temp DB only)."""
from __future__ import annotations

import hashlib
import importlib
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'app'))

from modules.nexgen.mo_ajanda_config import TABLO
from modules.nexgen.mo_ajanda_service import MoAjandaError, ajanda_olustur
from modules.nexgen.mo_gorusme_config import GORUSME_TIPLERI_ALL

CANONICAL_DB = Path(__file__).resolve().parents[2] / 'app' / 'mock_data.db'

MIGRATION_VERSION = 151
EXPECTED_COLUMNS = (
    'id', 'cari_id', 'kullanici_id', 'plan_tarihi', 'gorusme_tipi', 'plan_notu',
    'durum', 'gorusme_id', 'idempotency_key', 'aktif', 'olusturma_tarihi',
    'guncelleme_tarihi', 'olusturan_kullanici_id',
)
EXPECTED_INDEXES = (
    'idx_moa_kullanici_plan', 'idx_moa_cari', 'idx_moa_gorusme', 'idx_moa_durum',
)


def _tablo_var(con: sqlite3.Connection, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,),
    ).fetchone())


def _count(con: sqlite3.Connection, table: str) -> int:
    if not _tablo_var(con, table):
        return 0
    return int(con.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0])


def _simulate_server_pre151(db_path: str) -> None:
    """Server benzeri: gorusme var, ajanda yok, migration 151 yok."""
    con = sqlite3.connect(db_path, timeout=60)
    try:
        if _tablo_var(con, TABLO):
            con.execute(f'DROP TABLE {TABLO}')
        if _tablo_var(con, 'schema_migrations'):
            con.execute(
                "DELETE FROM schema_migrations WHERE version=?",
                (str(MIGRATION_VERSION),),
            )
        con.commit()
        if not _tablo_var(con, 'musteri_operasyon_gorusme'):
            raise RuntimeError('fixture requires musteri_operasyon_gorusme')
        if _tablo_var(con, TABLO):
            raise RuntimeError('ajanda table still present after strip')
        mig = con.execute(
            "SELECT 1 FROM schema_migrations WHERE version=?",
            (str(MIGRATION_VERSION),),
        ).fetchone()
        if mig:
            raise RuntimeError('migration 151 still present after strip')
    finally:
        con.close()


def _run_migration_151(db_path: str) -> None:
    mod = importlib.import_module('migrations.151_musteri_operasyon_ajanda')
    mod.run(db_path)


class Migration151LockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not CANONICAL_DB.exists():
            raise unittest.SkipTest(f'canonical DB missing: {CANONICAL_DB}')
        cls.canonical_sha_before = hashlib.sha256(CANONICAL_DB.read_bytes()).hexdigest()
        cls._tmpdir = tempfile.mkdtemp(prefix='mig151_')
        cls.temp_db = os.path.join(cls._tmpdir, 'mock_data.db')
        shutil.copy2(str(CANONICAL_DB), cls.temp_db)
        _simulate_server_pre151(cls.temp_db)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls._tmpdir, ignore_errors=True)
        sha_after = hashlib.sha256(CANONICAL_DB.read_bytes()).hexdigest()
        if sha_after != cls.canonical_sha_before:
            raise AssertionError(
                f'canonical DB SHA changed: before={cls.canonical_sha_before} after={sha_after}'
            )

    def setUp(self) -> None:
        self.con = sqlite3.connect(self.temp_db)
        self.con.row_factory = sqlite3.Row

    def tearDown(self) -> None:
        self.con.close()

    def test_a_pre_migration_ajanda_absent(self) -> None:
        self.assertFalse(_tablo_var(self.con, TABLO))

    def test_b_pre_migration_tablo_var_false(self) -> None:
        from modules.nexgen.mo_ajanda_service import _tablo_var as svc_tablo_var
        self.assertFalse(svc_tablo_var(self.con, TABLO))

    def test_c_migration_creates_table(self) -> None:
        gorusme_before = _count(self.con, 'musteri_operasyon_gorusme')
        siparis_before = _count(self.con, 'nexgen_planlama_siparis')
        cari_har_before = _count(self.con, 'Cari_Har')
        self.con.close()

        _run_migration_151(self.temp_db)

        con = sqlite3.connect(self.temp_db)
        try:
            self.assertTrue(_tablo_var(con, TABLO))
            cols = [r[1] for r in con.execute(f'PRAGMA table_info({TABLO})').fetchall()]
            self.assertEqual(tuple(cols), EXPECTED_COLUMNS)
            indexes = [
                r[0] for r in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name=?",
                    (TABLO,),
                ).fetchall()
            ]
            for idx in EXPECTED_INDEXES:
                self.assertIn(idx, indexes)
            mig = con.execute(
                "SELECT version FROM schema_migrations WHERE version=?",
                (str(MIGRATION_VERSION),),
            ).fetchone()
            self.assertIsNotNone(mig)
            self.assertEqual(_count(con, 'musteri_operasyon_gorusme'), gorusme_before)
            self.assertEqual(_count(con, 'nexgen_planlama_siparis'), siparis_before)
            self.assertEqual(_count(con, 'Cari_Har'), cari_har_before)
            integrity = con.execute('PRAGMA integrity_check').fetchone()[0]
            self.assertEqual(integrity, 'ok')
        finally:
            con.close()
        self.con = sqlite3.connect(self.temp_db)
        self.con.row_factory = sqlite3.Row

    def test_d_post_migration_tablo_var_true(self) -> None:
        if not _tablo_var(self.con, TABLO):
            _run_migration_151(self.temp_db)
            self.con.close()
            self.con = sqlite3.connect(self.temp_db)
            self.con.row_factory = sqlite3.Row
        from modules.nexgen.mo_ajanda_service import _tablo_var as svc_tablo_var
        self.assertTrue(svc_tablo_var(self.con, TABLO))

    def test_e_idempotent_second_run(self) -> None:
        if not _tablo_var(self.con, TABLO):
            _run_migration_151(self.temp_db)
        gorusme_before = _count(self.con, 'musteri_operasyon_gorusme')
        ajanda_before = _count(self.con, TABLO)
        self.con.close()
        _run_migration_151(self.temp_db)
        con = sqlite3.connect(self.temp_db)
        try:
            self.assertEqual(_count(con, 'musteri_operasyon_gorusme'), gorusme_before)
            self.assertEqual(_count(con, TABLO), ajanda_before)
            integrity = con.execute('PRAGMA integrity_check').fetchone()[0]
            self.assertEqual(integrity, 'ok')
        finally:
            con.close()
        self.con = sqlite3.connect(self.temp_db)
        self.con.row_factory = sqlite3.Row

    @patch('modules.nexgen.mo_ajanda_service.can_mo_gorusme_yaz', return_value=True)
    @patch('modules.nexgen.mo_ajanda_service.can_mo_view_cari', return_value=True)
    def test_f_ajanda_olustur_after_migration(self, _view, _yaz) -> None:
        if not _tablo_var(self.con, TABLO):
            _run_migration_151(self.temp_db)
            self.con.close()
            self.con = sqlite3.connect(self.temp_db)
            self.con.row_factory = sqlite3.Row

        cari = self.con.execute(
            'SELECT id FROM nexgen_cari WHERE aktif=1 LIMIT 1'
        ).fetchone()
        self.assertIsNotNone(cari, 'nexgen_cari fixture required')
        cari_id = int(cari['id'])

        payload = {
            'cari_id': cari_id,
            'plan_tarihi': '2099-01-15T10:00',
            'gorusme_tipi': GORUSME_TIPLERI_ALL[0],
            'plan_notu': 'MIG151-LOCK-TEST',
            'idempotency_key': 'MIG151-LOCK-TEST-001',
        }
        uid = 49
        yk = {'cari360.view': {'can_view': True}, 'cari360.crm_write': {'can_write': True}}
        result = ajanda_olustur(self.con, payload, uid, yk, commit=True)
        self.assertTrue(result.get('ok'))
        row = self.con.execute(
            "SELECT id FROM musteri_operasyon_ajanda WHERE idempotency_key=?",
            ('MIG151-LOCK-TEST-001',),
        ).fetchone()
        self.assertIsNotNone(row)

    def test_g_apply_script_preflight(self) -> None:
        from tools.apply_migration_151_ajanda import preflight
        pre = preflight(self.temp_db)
        self.assertEqual(pre['integrity'], 'ok')
        if _tablo_var(self.con, TABLO):
            self.assertTrue(pre['ajanda_exists'])
            self.assertFalse(pre['needs_apply'])
        else:
            self.assertFalse(pre['ajanda_exists'])
            self.assertTrue(pre['needs_apply'])


class Migration151DependencyTests(unittest.TestCase):
    def test_151_independent_of_150(self) -> None:
        src = (Path(__file__).resolve().parents[2] / 'app' / 'migrations'
               / '151_musteri_operasyon_ajanda.py').read_text(encoding='utf-8')
        self.assertNotIn('AuthVersion', src)
        self.assertNotIn('150', src.replace('151', ''))
        self.assertNotIn('sistem_kullanici', src)

        from migrations.nexgen_manifest import BY_VERSION
        entry = BY_VERSION[151]
        self.assertEqual(entry.dependencies, (149,))
        self.assertNotIn(150, entry.dependencies)


if __name__ == '__main__':
    unittest.main()
