# -*- coding: utf-8 -*-
"""Migration Runner V1 — guarded plan/apply tests (temp DB only)."""
from __future__ import annotations

import importlib.util
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

import pytest

WT = Path(__file__).resolve().parents[2]
CONTRACT = str(WT / 'tools' / 'module_schema_contracts' / 'planlama.toml')
COMMIT = 'ebb04ca8765fa2a2370bafff4b7056ec401866de'
CANONICAL = Path(os.environ.get(
    'CPS_CANONICAL_DB_SOURCE',
    r'C:\Solariz_CPS_SERVER\app\mock_data.db',
))
COMPUTER = platform.node()

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


def _repo() -> str:
    return str(WT.resolve())


def _runner():
    if str(WT) not in sys.path:
        sys.path.insert(0, str(WT))
    from tools.migration_runner import run_migration_runner
    return run_migration_runner


def _db_mtime_size(path: str) -> tuple[float, int]:
    st = os.stat(path)
    return st.st_mtime, st.st_size


def _make_old_server_db() -> tuple[str, str]:
    tmpdir = tempfile.mkdtemp(prefix='runner_old_')
    db_path = str(Path(tmpdir) / 'old_server.db')
    with sqlite3.connect(db_path) as c:
        c.execute(OLD_PARENT_DDL.strip())
        c.execute(SCHEMA_MIGRATIONS_DDL)
        c.commit()
    return tmpdir, db_path


def _backup_canonical() -> tuple[str, str]:
    if not CANONICAL.is_file():
        pytest.skip(f'canonical DB missing: {CANONICAL}')
    tmpdir = tempfile.mkdtemp(prefix='runner_mod_')
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


def _count_writes(db_path: str) -> int:
    """Rough write detector via journal mode + page count delta proxy."""
    with sqlite3.connect(f'file:{db_path.replace(chr(92), "/")}?mode=ro', uri=True) as c:
        return c.execute('PRAGMA page_count').fetchone()[0]


class TestMigrationRunnerGuards:
    def test_absolute_db_path_required(self):
        run = _runner()
        r = run(
            repo=_repo(), db='relative.db', contract=CONTRACT,
            expected_commit=COMMIT, mode='plan', computer=COMPUTER,
        )
        assert r['RUNNER_RESULT'] == 'BLOCKED'
        assert 'absolute' in (r.get('error') or '').lower()

    def test_relative_db_path_blocked(self):
        run = _runner()
        r = run(
            repo=_repo(), db='app/mock_data.db', contract=CONTRACT,
            expected_commit=COMMIT, mode='plan', computer=COMPUTER,
        )
        assert r['RUNNER_RESULT'] == 'BLOCKED'

    def test_zero_byte_db_blocked(self):
        run = _runner()
        tmpdir = tempfile.mkdtemp(prefix='runner_zero_')
        db = str(Path(tmpdir) / 'zero.db')
        Path(db).touch()
        try:
            r = run(
                repo=_repo(), db=db, contract=CONTRACT,
                expected_commit=COMMIT, mode='plan', computer=COMPUTER,
            )
            assert r['RUNNER_RESULT'] == 'BLOCKED'
            assert 'zero' in (r.get('error') or '').lower()
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_wrong_computer_blocked(self):
        run = _runner()
        tmpdir, db = _make_old_server_db()
        try:
            r = run(
                repo=_repo(), db=db, contract=CONTRACT,
                expected_commit=COMMIT, mode='plan',
                computer='NOT_A_REAL_HOSTNAME_XYZ',
            )
            assert r['RUNNER_RESULT'] == 'BLOCKED'
            assert r['COMPUTER_CHECK'].startswith('BLOCKED')
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_wrong_repo_blocked(self):
        run = _runner()
        tmpdir, db = _make_old_server_db()
        fake_repo = tempfile.mkdtemp(prefix='runner_fake_repo_')
        try:
            r = run(
                repo=fake_repo, db=db, contract=CONTRACT,
                expected_commit=COMMIT, mode='plan', computer=COMPUTER,
            )
            assert r['RUNNER_RESULT'] == 'BLOCKED'
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
            shutil.rmtree(fake_repo, ignore_errors=True)

    def test_wrong_commit_blocked(self):
        run = _runner()
        tmpdir, db = _make_old_server_db()
        try:
            r = run(
                repo=_repo(), db=db, contract=CONTRACT,
                expected_commit='0' * 40, mode='plan', computer=COMPUTER,
            )
            assert r['RUNNER_RESULT'] == 'BLOCKED'
            assert r['ACTUAL_COMMIT'] == COMMIT
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_dirty_tracked_worktree_blocked(self):
        run = _runner()
        tmpdir, db = _make_old_server_db()
        probe = WT / 'README.md'
        if not probe.is_file():
            probe = WT / '.gitignore'
        orig = probe.read_text(encoding='utf-8')
        probe.write_text(orig + '\n# dirty-test\n', encoding='utf-8')
        try:
            r = run(
                repo=_repo(), db=db, contract=CONTRACT,
                expected_commit=COMMIT, mode='plan', computer=COMPUTER,
            )
            assert r['RUNNER_RESULT'] == 'BLOCKED'
            assert 'dirty' in r['WORKTREE_CHECK'].lower()
        finally:
            probe.write_text(orig, encoding='utf-8')
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_apply_without_allow_canonical_blocked(self):
        run = _runner()
        if not CANONICAL.is_file():
            pytest.skip('canonical DB missing')
        canonical = str((WT / 'app' / 'mock_data.db').resolve())
        seeded = False
        if not os.path.isfile(canonical) or os.path.getsize(canonical) == 0:
            shutil.copy2(CANONICAL, canonical)
            seeded = True
        try:
            r = run(
                repo=_repo(), db=canonical, contract=CONTRACT,
                expected_commit=COMMIT, mode='apply', computer=COMPUTER,
                allow_canonical=False,
            )
            assert r['RUNNER_RESULT'] == 'BLOCKED'
            assert 'allow-canonical' in (r.get('error') or '').lower()
        finally:
            if seeded and os.path.isfile(canonical):
                os.remove(canonical)


class TestMigrationRunnerPlanApply:
    def test_plan_mode_db_write_zero(self):
        run = _runner()
        tmpdir, db = _make_old_server_db()
        before = _db_mtime_size(db)
        try:
            r = run(
                repo=_repo(), db=db, contract=CONTRACT,
                expected_commit=COMMIT, mode='plan', computer=COMPUTER,
            )
            after = _db_mtime_size(db)
            assert r['RUNNER_MODE'] == 'PLAN'
            assert r['BACKUP_PATH'] == ''
            assert before == after
            assert r['PENDING_MIGRATIONS'] == '190'
            assert r['RUNNER_RESULT'] == 'BLOCKED'
            assert r['PARITY_RESULT'] == 'BLOCKED'
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_backup_api_integrity(self):
        run = _runner()
        tmpdir, db = _make_old_server_db()
        backup_path = ''
        try:
            r = run(
                repo=_repo(), db=db, contract=CONTRACT,
                expected_commit=COMMIT, mode='apply', computer=COMPUTER,
            )
            backup_path = r.get('BACKUP_PATH') or ''
            assert backup_path
            assert os.path.isfile(backup_path)
            assert os.path.getsize(backup_path) > 0
            with sqlite3.connect(backup_path) as c:
                assert c.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
            if backup_path and backup_path.startswith(tempfile.gettempdir()):
                shutil.rmtree(os.path.dirname(backup_path), ignore_errors=True)

    def test_old_server_schema_plan_detects_pending_190(self):
        run = _runner()
        tmpdir, db = _make_old_server_db()
        try:
            r = run(
                repo=_repo(), db=db, contract=CONTRACT,
                expected_commit=COMMIT, mode='plan', computer=COMPUTER,
            )
            assert r['PENDING_MIGRATIONS'] == '190'
            pd = r.get('parity_detail') or {}
            missing_enj = [c for c in pd.get('MISSING_COLUMNS', []) if '.enj_' in c]
            assert len(missing_enj) == 18
            assert 'uretim_model_plan_enj_istasyon' in pd.get('MISSING_TABLES', [])
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_old_server_schema_apply_190(self):
        run = _runner()
        tmpdir, db = _make_old_server_db()
        try:
            r = run(
                repo=_repo(), db=db, contract=CONTRACT,
                expected_commit=COMMIT, mode='apply', computer=COMPUTER,
            )
            assert r['RUNNER_RESULT'] == 'PASS'
            assert '190=OK' in r['MIGRATION_RESULT']
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_post_apply_schema_parity(self):
        run = _runner()
        tmpdir, db = _make_old_server_db()
        try:
            r = run(
                repo=_repo(), db=db, contract=CONTRACT,
                expected_commit=COMMIT, mode='apply', computer=COMPUTER,
            )
            assert r['PARITY_RESULT'] == 'PASS'
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_second_run_noop(self):
        run = _runner()
        tmpdir, db = _make_old_server_db()
        try:
            first = run(
                repo=_repo(), db=db, contract=CONTRACT,
                expected_commit=COMMIT, mode='apply', computer=COMPUTER,
            )
            assert first['RUNNER_RESULT'] == 'PASS'
            second = run(
                repo=_repo(), db=db, contract=CONTRACT,
                expected_commit=COMMIT, mode='apply', computer=COMPUTER,
            )
            assert second['RUNNER_RESULT'] == 'PASS'
            assert '190=SKIP' in second['MIGRATION_RESULT']
            assert second['PENDING_MIGRATIONS'] == ''
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_modern_schema_plan_pass(self):
        run = _runner()
        tmpdir, db = _backup_canonical()
        try:
            applied = run(
                repo=_repo(), db=db, contract=CONTRACT,
                expected_commit=COMMIT, mode='apply', computer=COMPUTER,
            )
            assert applied['RUNNER_RESULT'] == 'PASS'
            plan = run(
                repo=_repo(), db=db, contract=CONTRACT,
                expected_commit=COMMIT, mode='plan', computer=COMPUTER,
            )
            assert plan['RUNNER_RESULT'] == 'PASS'
            assert plan['PENDING_MIGRATIONS'] == ''
            assert plan['PARITY_RESULT'] == 'PASS'
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_migration_failure_reported(self):
        import tools.migration_runner as mr

        tmpdir, db = _make_old_server_db()
        try:
            real_load = mr._load_migration_module
            mod190 = real_load(WT, 'app/migrations/190_uretim_model_plan_enj_istasyon.py')

            def _boom(db_path, *, allow_canonical=False, **_k):
                raise RuntimeError('injected migration failure')

            mod190.run = _boom

            with mock.patch.object(mr, '_load_migration_module', return_value=mod190):
                r = mr.run_migration_runner(
                    repo=_repo(), db=db, contract=CONTRACT,
                    expected_commit=COMMIT, mode='apply', computer=COMPUTER,
                )
            assert r['RUNNER_RESULT'] == 'BLOCKED'
            assert '190=FAIL' in r['MIGRATION_RESULT']
            assert r['BACKUP_PATH']
            assert r['PARITY_RESULT'] == 'BLOCKED'
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_canonical_db_unchanged_on_plan(self):
        if not CANONICAL.is_file():
            pytest.skip('canonical DB missing')
        before = _db_mtime_size(str(CANONICAL))
        run = _runner()
        r = run(
            repo=_repo(), db=str(CANONICAL.resolve()), contract=CONTRACT,
            expected_commit=COMMIT, mode='plan', computer=COMPUTER,
        )
        after = _db_mtime_size(str(CANONICAL))
        assert before == after
        assert r['RUNNER_MODE'] == 'PLAN'

    def test_required_migrations_chain_reported(self):
        run = _runner()
        tmpdir, db = _make_old_server_db()
        try:
            r = run(
                repo=_repo(), db=db, contract=CONTRACT,
                expected_commit=COMMIT, mode='plan', computer=COMPUTER,
            )
            assert r['REQUIRED_MIGRATIONS'] == '158,159,190'
            assert r['REGISTRY_PENDING'] == '158,159,190'
            assert r['PENDING_MIGRATIONS'] == '190'
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_dry_run_scenario_a_old_plan_cli(self):
        tmpdir, db = _make_old_server_db()
        try:
            proc = subprocess.run(
                [
                    sys.executable, str(WT / 'tools' / 'migration_runner.py'),
                    '--repo', _repo(),
                    '--db', db,
                    '--contract', CONTRACT,
                    '--expected-commit', COMMIT,
                    '--plan',
                    '--computer', COMPUTER,
                ],
                cwd=str(WT), capture_output=True, text=True,
            )
            assert 'RUNNER_MODE=PLAN' in proc.stdout
            assert 'PENDING_MIGRATIONS=190' in proc.stdout
            assert proc.returncode == 1
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_dry_run_scenario_b_old_apply_cli(self):
        tmpdir, db = _make_old_server_db()
        try:
            proc = subprocess.run(
                [
                    sys.executable, str(WT / 'tools' / 'migration_runner.py'),
                    '--repo', _repo(),
                    '--db', db,
                    '--contract', CONTRACT,
                    '--expected-commit', COMMIT,
                    '--apply',
                    '--computer', COMPUTER,
                ],
                cwd=str(WT), capture_output=True, text=True,
            )
            assert 'RUNNER_MODE=APPLY' in proc.stdout
            assert 'PARITY_RESULT=PASS' in proc.stdout
            assert 'RUNNER_RESULT=PASS' in proc.stdout
            assert proc.returncode == 0
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_dry_run_scenario_c_modern_plan_cli(self):
        tmpdir, db = _backup_canonical()
        try:
            subprocess.run(
                [
                    sys.executable, str(WT / 'tools' / 'migration_runner.py'),
                    '--repo', _repo(), '--db', db, '--contract', CONTRACT,
                    '--expected-commit', COMMIT, '--apply', '--computer', COMPUTER,
                ],
                cwd=str(WT), capture_output=True, text=True, check=True,
            )
            proc = subprocess.run(
                [
                    sys.executable, str(WT / 'tools' / 'migration_runner.py'),
                    '--repo', _repo(), '--db', db, '--contract', CONTRACT,
                    '--expected-commit', COMMIT, '--plan', '--computer', COMPUTER,
                ],
                cwd=str(WT), capture_output=True, text=True,
            )
            assert 'PENDING_MIGRATIONS=' in proc.stdout
            assert 'PARITY_RESULT=PASS' in proc.stdout
            assert 'RUNNER_RESULT=PASS' in proc.stdout
            assert proc.returncode == 0
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_dry_run_scenario_d_wrong_commit_cli(self):
        tmpdir, db = _make_old_server_db()
        try:
            proc = subprocess.run(
                [
                    sys.executable, str(WT / 'tools' / 'migration_runner.py'),
                    '--repo', _repo(), '--db', db, '--contract', CONTRACT,
                    '--expected-commit', '0' * 40,
                    '--plan', '--computer', COMPUTER,
                ],
                cwd=str(WT), capture_output=True, text=True,
            )
            assert 'RUNNER_RESULT=BLOCKED' in proc.stdout
            assert proc.returncode == 1
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
