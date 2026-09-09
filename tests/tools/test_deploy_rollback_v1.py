# -*- coding: utf-8 -*-
"""Deploy / rollback orchestrator tests — temp DB + fake process only."""
from __future__ import annotations

import getpass
import json
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
COMMIT = subprocess.run(
    ['git', 'rev-parse', 'HEAD'], cwd=str(WT),
    capture_output=True, text=True, check=True,
).stdout.strip()
CANONICAL = Path(os.environ.get('CPS_CANONICAL_DB_SOURCE',
                                r'C:\Solariz_CPS_SERVER\app\mock_data.db'))
CONTRACT = str(WT / 'tools' / 'module_schema_contracts' / 'planlama.toml')
COMPUTER = platform.node()
USER = getpass.getuser()

if str(WT) not in sys.path:
    sys.path.insert(0, str(WT))

from tools.release_manifest import create_manifest, save_manifest
from tools.deploy_and_rollback import (
    run_deploy, backup_db, verify_backup, restore_db,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _good_manifest(tested_commit=COMMIT, **kwargs):
    base = create_manifest(
        release_id='r-test-001',
        module='planlama_uretim',
        base_commit='ebb04ca8765fa2a2370bafff4b7056ec401866de',
        tested_commit=tested_commit,
        target_branch='release/infra-safe-deploy-v1',
        allowed_files=['tools/migration_runner.py', 'tools/schema_parity_check.py'],
        forbidden_paths=['app/modules/planlama/uretim_plan_routes.py'],
        schema_contract=CONTRACT,
        required_migrations=['190'],
        test_result='PASS',
        test_pass_count=109,
        test_fail_count=0,
        pilot_baseline='ebb04ca8765fa2a2370bafff4b7056ec401866de',
    )
    base.update(kwargs)
    return base


def _write_manifest(tmp: Path, manifest: dict) -> str:
    p = tmp / 'manifest.json'
    save_manifest(manifest, p)
    return str(p)


def _make_temp_db(apply_190=True) -> tuple[str, str]:
    """Create temp DB (backup from canonical, optionally apply migration 190)."""
    if not CANONICAL.is_file():
        pytest.skip(f'canonical DB missing: {CANONICAL}')
    tmpdir = tempfile.mkdtemp(prefix='dr_db_')
    db = str(Path(tmpdir) / 'test.db')
    src = sqlite3.connect(f'file:{CANONICAL.as_posix()}?mode=ro', uri=True)
    dst = sqlite3.connect(db)
    try:
        src.backup(dst); dst.commit()
    finally:
        src.close(); dst.close()

    if apply_190:
        from tools.migration_runner import run_migration_runner
        run_migration_runner(
            repo=str(WT), db=db, contract=CONTRACT,
            expected_commit=COMMIT, mode='apply',
            computer=COMPUTER,
        )
    return tmpdir, db


def _make_old_server_db() -> tuple[str, str]:
    OLD_DDL = """CREATE TABLE uretim_model_plan (
        id INTEGER PRIMARY KEY AUTOINCREMENT, sip_no INTEGER NOT NULL,
        sip_harinx INTEGER NOT NULL, mamul_skod TEXT NOT NULL,
        rkod INTEGER NOT NULL DEFAULT 0, model_adi TEXT, renk_adi TEXT,
        miktar REAL, termin TEXT, plan_donemi TEXT NOT NULL,
        plan_baslangic TEXT, plan_bitis TEXT, oncelik INTEGER NOT NULL DEFAULT 3,
        plan_gerekce TEXT, plan_notu TEXT, aktif INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL, created_by INTEGER, updated_at TEXT, updated_by INTEGER)"""
    tmpdir = tempfile.mkdtemp(prefix='dr_old_')
    db = str(Path(tmpdir) / 'old.db')
    con = sqlite3.connect(db)
    con.execute(OLD_DDL)
    con.execute('CREATE TABLE schema_migrations (version TEXT PRIMARY KEY, uygulama_zamani TEXT, aciklama TEXT)')
    con.commit(); con.close()
    return tmpdir, db


def _fake_start_ok(repo, env=None):
    return {'ok': True, 'pid': '99999'}


def _fake_start_fail(repo, env=None):
    return {'ok': False, 'pid': '', 'error': 'fake start failure'}


def _fake_health_ok(url):
    return {'ok': True, 'status': 200}


def _fake_health_fail(url):
    return {'ok': False, 'status': 0, 'error': 'fake health failure'}


def _fake_stop(pid):
    return True


# ── plan / dry-run tests ──────────────────────────────────────────────────────

class TestDeployPlanMode:
    def test_default_mode_dry_run(self, tmp_path):
        td, db = _make_temp_db()
        mp = _write_manifest(tmp_path, _good_manifest())
        try:
            r = run_deploy(
                manifest_path=mp, repo=str(WT), db=db,
                target_commit=COMMIT, execute=False,
                expected_computer=COMPUTER,
                skip_process_check=True, _fake_pids=[],
            )
            assert r['RUNNER_MODE'] == 'PLAN'
            assert r['DEPLOY_RESULT'] == 'PLAN_PASS'
            assert r['PREFLIGHT_RESULT'] == 'PASS'
            assert r['BACKUP_PATH'] == ''   # no backup in plan mode
        finally:
            shutil.rmtree(td)

    def test_plan_shows_migration_and_parity(self, tmp_path):
        td, db = _make_temp_db(apply_190=True)
        mp = _write_manifest(tmp_path, _good_manifest())
        try:
            r = run_deploy(
                manifest_path=mp, repo=str(WT), db=db,
                target_commit=COMMIT, execute=False,
                expected_computer=COMPUTER,
                skip_process_check=True, _fake_pids=[],
            )
            assert r['PARITY_BEFORE'] == 'PASS'
            assert r['ROLLBACK_PLAN']
            assert r['BACKUP_WOULD_CREATE']
        finally:
            shutil.rmtree(td)


class TestDeployBlockedGuards:
    def test_wrong_computer_blocked(self, tmp_path):
        td, db = _make_temp_db()
        mp = _write_manifest(tmp_path, _good_manifest())
        try:
            r = run_deploy(
                manifest_path=mp, repo=str(WT), db=db,
                target_commit=COMMIT, execute=False,
                expected_computer='NOT_A_REAL_HOST_XYZ',
                skip_process_check=True, _fake_pids=[],
            )
            assert r['DEPLOY_RESULT'] == 'BLOCKED'
            assert 'COMPUTER' in r['PREFLIGHT_RESULT']
        finally:
            shutil.rmtree(td)

    def test_wrong_head_blocked(self, tmp_path):
        td, db = _make_temp_db()
        mp = _write_manifest(tmp_path, _good_manifest())
        try:
            r = run_deploy(
                manifest_path=mp, repo=str(WT), db=db,
                target_commit='0' * 40,   # wrong commit
                execute=False,
                expected_computer=COMPUTER,
                skip_process_check=True, _fake_pids=[],
            )
            assert r['DEPLOY_RESULT'] == 'BLOCKED'
        finally:
            shutil.rmtree(td)

    def test_missing_execute_confirmation_blocked(self, tmp_path):
        td, db = _make_temp_db()
        mp = _write_manifest(tmp_path, _good_manifest())
        try:
            r = run_deploy(
                manifest_path=mp, repo=str(WT), db=db,
                target_commit=COMMIT, execute=True,
                confirm_release='',           # missing
                expected_computer=COMPUTER,
                expected_head=COMMIT,
                skip_process_check=True, _fake_pids=[],
            )
            assert r['DEPLOY_RESULT'] == 'BLOCKED'
            assert '--confirm-release' in r.get('error', '')
        finally:
            shutil.rmtree(td)

    def test_zero_byte_db_blocked(self, tmp_path):
        tmpdir = tempfile.mkdtemp()
        db = str(Path(tmpdir) / 'zero.db')
        Path(db).touch()
        mp = _write_manifest(tmp_path, _good_manifest())
        try:
            r = run_deploy(
                manifest_path=mp, repo=str(WT), db=db,
                target_commit=COMMIT, execute=False,
                expected_computer=COMPUTER,
                skip_process_check=True, _fake_pids=[],
            )
            assert r['DEPLOY_RESULT'] == 'BLOCKED'
        finally:
            shutil.rmtree(tmpdir)

    def test_migration_plan_blocked(self, tmp_path):
        td, db = _make_old_server_db()   # old schema → parity BLOCKED
        mp = _write_manifest(tmp_path, _good_manifest())
        try:
            r = run_deploy(
                manifest_path=mp, repo=str(WT), db=db,
                target_commit=COMMIT, execute=False,
                expected_computer=COMPUTER,
                skip_process_check=True, _fake_pids=[],
            )
            assert r['DEPLOY_RESULT'] == 'BLOCKED'
            assert r['DEPLOY_ALLOWED'] == 'NO'
            assert 'PARITY_BEFORE' in r['PREFLIGHT_RESULT']
        finally:
            shutil.rmtree(td)

    def test_schema_parity_blocked_before(self, tmp_path):
        td, db = _make_old_server_db()
        mp = _write_manifest(tmp_path, _good_manifest())
        try:
            r = run_deploy(
                manifest_path=mp, repo=str(WT), db=db,
                target_commit=COMMIT, execute=False,
                expected_computer=COMPUTER,
                skip_process_check=True, _fake_pids=[],
            )
            assert r['DEPLOY_RESULT'] == 'BLOCKED'
            assert r['DEPLOY_ALLOWED'] == 'NO'
        finally:
            shutil.rmtree(td)


# ── backup tests ──────────────────────────────────────────────────────────────

class TestBackup:
    def test_backup_api_pass(self):
        td, db = _make_temp_db()
        try:
            bak = backup_db(db)
            assert os.path.isfile(bak)
            assert os.path.getsize(bak) > 0
            with sqlite3.connect(bak) as c:
                assert c.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            v = verify_backup(db, bak)
            assert v['ok']
            assert v['backup_integrity'] == 'ok'
        finally:
            shutil.rmtree(td)

    def test_backup_failure_no_mutation(self, tmp_path):
        """If backup fails, deploy must not proceed."""
        td, db = _make_temp_db()
        mp = _write_manifest(tmp_path, _good_manifest())
        try:
            import tools.deploy_and_rollback as dar
            with mock.patch.object(dar, 'backup_db', side_effect=RuntimeError('disk full')):
                r = run_deploy(
                    manifest_path=mp, repo=str(WT), db=db,
                    target_commit=COMMIT, execute=True,
                    confirm_release='r-test-001',
                    expected_computer=COMPUTER,
                    expected_head=COMMIT,
                    skip_process_check=True, _fake_pids=[],
                )
            assert r['DEPLOY_RESULT'] == 'BLOCKED'
            assert 'backup' in r.get('error', '').lower()
        finally:
            shutil.rmtree(td)


# ── full deploy simulation ─────────────────────────────────────────────────────

class TestTempDeploySimulation:
    def test_temp_deploy_success(self, tmp_path):
        td, db = _make_temp_db()
        mp = _write_manifest(tmp_path, _good_manifest())
        try:
            r = run_deploy(
                manifest_path=mp, repo=str(WT), db=db,
                target_commit=COMMIT, execute=True,
                confirm_release='r-test-001',
                expected_computer=COMPUTER,
                expected_head=COMMIT,
                skip_process_check=True, _fake_pids=[],
                _fake_start=_fake_start_ok,
                _fake_health=_fake_health_ok,
                _fake_stop=_fake_stop,
            )
            assert r['DEPLOY_RESULT'] == 'PASS'
            assert r['BACKUP_PATH']
            assert r['PARITY_AFTER'] == 'PASS'
            assert r['HEALTH_AFTER'] == 'PASS'
            assert r['NEW_PID'] == '99999'
        finally:
            shutil.rmtree(td)

    def test_migration_failure_rollback(self, tmp_path):
        td, db = _make_old_server_db()
        mp = _write_manifest(tmp_path, _good_manifest())
        db_mtime_before = os.path.getmtime(db)
        try:
            import tools.deploy_and_rollback as dar
            real_runner = dar.run_migration_runner

            def _fail_runner(**kwargs):
                r = real_runner(**kwargs)
                r['RUNNER_RESULT'] = 'BLOCKED'
                r['MIGRATION_RESULT'] = '190=FAIL:injected'
                r['error'] = 'injected failure'
                return r

            with mock.patch.object(dar, 'run_migration_runner', side_effect=_fail_runner):
                r = run_deploy(
                    manifest_path=mp, repo=str(WT), db=db,
                    target_commit=COMMIT, execute=True,
                    confirm_release='r-test-001',
                    expected_computer=COMPUTER,
                    expected_head=COMMIT,
                    skip_process_check=True, _fake_pids=[],
                    _fake_start=_fake_start_ok,
                    _fake_health=_fake_health_ok,
                    _fake_stop=_fake_stop,
                )
            assert r['DEPLOY_RESULT'] == 'BLOCKED'
            assert r.get('ROLLBACK_APPLIED') == 'YES'
        finally:
            shutil.rmtree(td)

    def test_health_failure_rollback(self, tmp_path):
        td, db = _make_temp_db()
        mp = _write_manifest(tmp_path, _good_manifest())
        try:
            r = run_deploy(
                manifest_path=mp, repo=str(WT), db=db,
                target_commit=COMMIT, execute=True,
                confirm_release='r-test-001',
                expected_computer=COMPUTER,
                expected_head=COMMIT,
                skip_process_check=True, _fake_pids=[],
                _fake_start=_fake_start_ok,
                _fake_health=_fake_health_fail,   # health check fails
                _fake_stop=_fake_stop,
            )
            assert r['DEPLOY_RESULT'] == 'BLOCKED'
            assert r.get('ROLLBACK_APPLIED') == 'YES'
            assert r['HEALTH_AFTER'] == 'FAIL'
        finally:
            shutil.rmtree(td)

    def test_old_head_restored_after_rollback(self, tmp_path):
        td, db = _make_temp_db()
        mp = _write_manifest(tmp_path, _good_manifest())
        try:
            import tools.deploy_and_rollback as dar
            # force parity-after to fail → triggers rollback
            with mock.patch('tools.deploy_and_rollback.check_parity',
                            return_value={'PARITY_RESULT': 'BLOCKED'}):
                r = run_deploy(
                    manifest_path=mp, repo=str(WT), db=db,
                    target_commit=COMMIT, execute=True,
                    confirm_release='r-test-001',
                    expected_computer=COMPUTER,
                    expected_head=COMMIT,
                    skip_process_check=True, _fake_pids=[],
                    _fake_start=_fake_start_ok,
                    _fake_health=_fake_health_ok,
                    _fake_stop=_fake_stop,
                )
            assert r.get('ROLLBACK_APPLIED') == 'YES'
        finally:
            shutil.rmtree(td)

    def test_db_backup_restored(self, tmp_path):
        td, db = _make_old_server_db()
        bak = ''
        try:
            bak = backup_db(db)
            restore_result = restore_db(bak, db)
            assert restore_result
            with sqlite3.connect(db) as c:
                assert c.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        finally:
            shutil.rmtree(td, ignore_errors=True)
            if bak:
                bak_dir = os.path.dirname(bak)
                shutil.rmtree(bak_dir, ignore_errors=True)

    def test_untracked_files_preserved(self, tmp_path):
        td, db = _make_temp_db()
        mp = _write_manifest(tmp_path, _good_manifest())
        # create a temp untracked file in worktree (won't conflict with allowed_files)
        probe = WT / '_untracked_test_probe_xyz.txt'
        probe.write_text('untracked probe\n', encoding='utf-8')
        try:
            r = run_deploy(
                manifest_path=mp, repo=str(WT), db=db,
                target_commit=COMMIT, execute=False,
                expected_computer=COMPUTER,
                skip_process_check=True, _fake_pids=[],
            )
            # untracked is reported but not blocking in plan mode (no collision)
            assert probe.is_file()
        finally:
            probe.unlink(missing_ok=True)
            shutil.rmtree(td)

    def test_process_restart_simulation(self, tmp_path):
        td, db = _make_temp_db()
        mp = _write_manifest(tmp_path, _good_manifest())
        started: list[str] = []

        def _start(repo, env=None):
            started.append(repo)
            return {'ok': True, 'pid': '88888'}

        try:
            r = run_deploy(
                manifest_path=mp, repo=str(WT), db=db,
                target_commit=COMMIT, execute=True,
                confirm_release='r-test-001',
                expected_computer=COMPUTER,
                expected_head=COMMIT,
                skip_process_check=True, _fake_pids=[],
                _fake_start=_start,
                _fake_health=_fake_health_ok,
                _fake_stop=_fake_stop,
            )
            assert r['DEPLOY_RESULT'] == 'PASS'
            assert started  # start was called
            assert r['NEW_PID'] == '88888'
        finally:
            shutil.rmtree(td)
