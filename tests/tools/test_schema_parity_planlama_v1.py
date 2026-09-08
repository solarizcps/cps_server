# -*- coding: utf-8 -*-
"""Schema parity check — planlama contract tests (temp DB only)."""
from __future__ import annotations

import os
import platform
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

WT = Path(__file__).resolve().parents[2]
CONTRACT = str(WT / 'tools' / 'module_schema_contracts' / 'planlama.toml')
COMMIT = 'ebb04ca8765fa2a2370bafff4b7056ec401866de'
CANONICAL = Path(os.environ.get(
    'CPS_CANONICAL_DB_SOURCE',
    r'C:\Solariz_CPS_SERVER\app\mock_data.db',
))

OLD_PARENT_DDL = """
CREATE TABLE uretim_model_plan (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sip_no INTEGER NOT NULL,
    sip_harinx INTEGER NOT NULL,
    mamul_skod TEXT NOT NULL,
    rkod INTEGER NOT NULL DEFAULT 0,
    model_adi TEXT,
    renk_adi TEXT,
    miktar REAL,
    termin TEXT,
    plan_donemi TEXT NOT NULL,
    plan_baslangic TEXT,
    plan_bitis TEXT,
    oncelik INTEGER NOT NULL DEFAULT 3,
    plan_gerekce TEXT,
    plan_notu TEXT,
    aktif INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    created_by INTEGER,
    updated_at TEXT,
    updated_by INTEGER
)
"""

SCHEMA_MIGRATIONS_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    uygulama_zamani TEXT,
    aciklama TEXT
)
"""

ENJ_COLS = [
    'enj_makine_id', 'enj_istasyon_no', 'enj_slot', 'enj_kalip_id', 'enj_kalip_kod',
    'enj_aktif_goz', 'enj_kalip_basi_cift', 'enj_tur_cift', 'enj_gunluk_tur_plan',
    'enj_gunluk_kapasite', 'enj_plan_baslangic', 'enj_plan_bitis', 'enj_tahmini_gun',
    'enj_planlanacak_cift', 'enj_calisma_modu', 'enj_hafta_sonu_calisma',
    'enj_hafta_sonu_vardiya', 'enj_kapasite_snapshot',
]


def _repo() -> str:
    return str(WT.resolve())


def _make_old_server_db() -> tuple[str, str]:
    tmpdir = tempfile.mkdtemp(prefix='parity_old_')
    db_path = str(Path(tmpdir) / 'old_server.db')
    with sqlite3.connect(db_path) as c:
        c.execute(OLD_PARENT_DDL.strip())
        c.execute(SCHEMA_MIGRATIONS_DDL)
        c.commit()
    return tmpdir, db_path


def _backup_canonical() -> tuple[str, str]:
    if not CANONICAL.is_file():
        pytest.skip(f'canonical DB missing: {CANONICAL}')
    tmpdir = tempfile.mkdtemp(prefix='parity_mod_')
    db_path = str(Path(tmpdir) / 'modern.db')
    src = sqlite3.connect(f'file:{CANONICAL.as_posix()}?mode=ro', uri=True)
    dst = sqlite3.connect(db_path)
    try:
        src.backup(dst)
        dst.commit()
    finally:
        src.close()
        dst.close()
    return tmpdir, db_path


@pytest.fixture
def parity_mod():
    if str(WT) not in sys.path:
        sys.path.insert(0, str(WT))
    from tools.schema_parity_check import check_parity
    return check_parity


class TestSchemaParityGuards:
    def test_absolute_db_path_required(self, parity_mod):
        tmpdir, db = _make_old_server_db()
        try:
            rel = 'old_server.db'
            r = parity_mod(contract_path=CONTRACT, db_path=rel)
            assert r['PARITY_RESULT'] == 'BLOCKED'
            assert 'absolute' in (r.get('error') or '').lower()
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_relative_db_path_blocked(self, parity_mod):
        tmpdir, db = _make_old_server_db()
        try:
            r = parity_mod(contract_path=CONTRACT, db_path='relative/mock.db')
            assert r['PARITY_RESULT'] == 'BLOCKED'
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_zero_byte_db_blocked(self, parity_mod):
        tmpdir = tempfile.mkdtemp(prefix='parity_zero_')
        db = str(Path(tmpdir) / 'zero.db')
        Path(db).touch()
        try:
            r = parity_mod(contract_path=CONTRACT, db_path=db, repo_path=_repo(), expected_commit=COMMIT)
            assert r['PARITY_RESULT'] == 'BLOCKED'
            assert 'zero' in (r.get('error') or '').lower()
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_wrong_commit_blocked(self, parity_mod):
        tmpdir, db = _make_old_server_db()
        try:
            r = parity_mod(
                contract_path=CONTRACT, db_path=db,
                repo_path=_repo(), expected_commit='0' * 40,
            )
            assert r['PARITY_RESULT'] == 'BLOCKED'
            assert 'commit' in (r.get('error') or '').lower()
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class TestSchemaParityPlanlama:
    def test_old_server_detects_18_columns(self, parity_mod):
        tmpdir, db = _make_old_server_db()
        try:
            r = parity_mod(
                contract_path=CONTRACT, db_path=db,
                repo_path=_repo(), expected_commit=COMMIT,
            )
            assert r['PARITY_RESULT'] == 'BLOCKED'
            missing_enj = [c for c in r['MISSING_COLUMNS'] if '.enj_' in c]
            assert len(missing_enj) == 18
            assert 'uretim_model_plan_enj_istasyon' in r['MISSING_TABLES']
            assert '190' in r['MISSING_MIGRATIONS']
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_code_new_db_old_blocked(self, parity_mod):
        tmpdir, db = _make_old_server_db()
        try:
            r = parity_mod(
                contract_path=CONTRACT, db_path=db,
                repo_path=_repo(), expected_commit=COMMIT,
            )
            assert r['PARITY_RESULT'] == 'BLOCKED'
            assert r['ACTUAL_COMMIT'] == COMMIT
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_child_table_contract(self, parity_mod):
        tmpdir, db = _make_old_server_db()
        try:
            from tools.migration_runner import run_migration_runner
            r = run_migration_runner(
                repo=_repo(), db=db, contract=CONTRACT,
                expected_commit=COMMIT, mode='apply',
                computer=platform.node(),
            )
            assert r['RUNNER_RESULT'] == 'PASS'
            chk = parity_mod(
                contract_path=CONTRACT, db_path=db,
                repo_path=_repo(), expected_commit=COMMIT,
            )
            assert chk['PARITY_RESULT'] == 'PASS'
            assert 'uretim_model_plan_enj_istasyon' not in chk['MISSING_TABLES']
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_child_index_contract(self, parity_mod):
        tmpdir, db = _make_old_server_db()
        try:
            from tools.migration_runner import run_migration_runner
            run_migration_runner(
                repo=_repo(), db=db, contract=CONTRACT,
                expected_commit=COMMIT, mode='apply',
                computer=platform.node(),
            )
            with sqlite3.connect(db) as c:
                assert c.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='index' AND name='idx_ump_enj_ist_mak_slot'"
                ).fetchone()
            chk = parity_mod(
                contract_path=CONTRACT, db_path=db,
                repo_path=_repo(), expected_commit=COMMIT,
            )
            assert 'idx_ump_enj_ist_mak_slot' not in chk['MISSING_INDEXES']
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_modern_db_parity_after_apply(self, parity_mod):
        tmpdir, db = _backup_canonical()
        try:
            from tools.migration_runner import run_migration_runner
            run_migration_runner(
                repo=_repo(), db=db, contract=CONTRACT,
                expected_commit=COMMIT, mode='apply',
                computer=platform.node(),
            )
            r = parity_mod(
                contract_path=CONTRACT, db_path=db,
                repo_path=_repo(), expected_commit=COMMIT,
            )
            assert r['PARITY_RESULT'] == 'PASS'
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_code_old_db_new_reported(self, parity_mod):
        """DB has 190 registry + schema; legacy 158/159 absent from registry."""
        tmpdir, db = _make_old_server_db()
        try:
            from tools.migration_runner import run_migration_runner
            apply = run_migration_runner(
                repo=_repo(), db=db, contract=CONTRACT,
                expected_commit=COMMIT, mode='apply',
                computer=platform.node(),
            )
            assert apply['RUNNER_RESULT'] == 'PASS'
            plan = run_migration_runner(
                repo=_repo(), db=db, contract=CONTRACT,
                expected_commit=COMMIT, mode='plan',
                computer=platform.node(),
            )
            assert plan['PENDING_MIGRATIONS'] == ''
            assert plan['REGISTRY_PENDING'] == '158,159'
            assert plan['PARITY_RESULT'] == 'PASS'
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_migration_registry_verified(self, parity_mod):
        tmpdir, db = _make_old_server_db()
        try:
            from tools.migration_runner import run_migration_runner
            run_migration_runner(
                repo=_repo(), db=db, contract=CONTRACT,
                expected_commit=COMMIT, mode='apply',
                computer=platform.node(),
            )
            with sqlite3.connect(db) as c:
                row = c.execute(
                    "SELECT version FROM schema_migrations WHERE version='190'"
                ).fetchone()
            assert row is not None
            r = parity_mod(
                contract_path=CONTRACT, db_path=db,
                repo_path=_repo(), expected_commit=COMMIT,
            )
            assert '190' not in r['MISSING_MIGRATIONS']
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_cli_machine_readable_output(self):
        tmpdir, db = _make_old_server_db()
        try:
            proc = subprocess.run(
                [
                    sys.executable, str(WT / 'tools' / 'schema_parity_check.py'),
                    '--contract', CONTRACT,
                    '--db', db,
                    '--repo', _repo(),
                    '--expected-commit', COMMIT,
                    '--mode', 'check',
                ],
                cwd=str(WT), capture_output=True, text=True,
            )
            assert 'PARITY_RESULT=BLOCKED' in proc.stdout
            assert 'MISSING_COLUMNS=' in proc.stdout
            assert proc.returncode == 1
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
