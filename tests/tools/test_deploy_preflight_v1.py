# -*- coding: utf-8 -*-
"""Deploy preflight tests — no canonical DB, no port 8080, no real process."""
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
COMMIT = 'aac27ed8e7407cd16199749b0f3696a635b66467'
CANONICAL = Path(os.environ.get('CPS_CANONICAL_DB_SOURCE',
                                r'C:\Solariz_CPS_SERVER\app\mock_data.db'))
CONTRACT = str(WT / 'tools' / 'module_schema_contracts' / 'planlama.toml')
COMPUTER = platform.node()
USER = getpass.getuser()

if str(WT) not in sys.path:
    sys.path.insert(0, str(WT))

from tools.release_manifest import create_manifest, save_manifest
from tools.deploy_preflight import run_preflight, PreflightError


# ── helpers ───────────────────────────────────────────────────────────────────

def _good_manifest(tested_commit=COMMIT, test_fail=0, test_result='PASS',
                   allowed_files=None, forbidden_paths=None):
    return create_manifest(
        release_id='r-test-001',
        module='planlama_uretim',
        base_commit='ebb04ca8765fa2a2370bafff4b7056ec401866de',
        tested_commit=tested_commit,
        target_branch='release/infra-safe-deploy-v1',
        allowed_files=allowed_files or ['tools/migration_runner.py'],
        forbidden_paths=forbidden_paths or [],
        schema_contract=CONTRACT,
        required_migrations=['190'],
        test_result=test_result,
        test_pass_count=109,
        test_fail_count=test_fail,
        pilot_baseline='ebb04ca8765fa2a2370bafff4b7056ec401866de',
    )


def _write_manifest(tmp: Path, manifest: dict) -> str:
    p = tmp / 'manifest.json'
    save_manifest(manifest, p)
    return str(p)


def _make_temp_db() -> tuple[str, str]:
    if not CANONICAL.is_file():
        pytest.skip(f'canonical DB missing: {CANONICAL}')
    tmpdir = tempfile.mkdtemp(prefix='pf_db_')
    db = str(Path(tmpdir) / 'test.db')
    src = sqlite3.connect(f'file:{CANONICAL.as_posix()}?mode=ro', uri=True)
    dst = sqlite3.connect(db)
    try:
        src.backup(dst); dst.commit()
    finally:
        src.close(); dst.close()
    return tmpdir, db


def _preflight_ok(manifest_path: str, db: str, **kwargs) -> dict:
    return run_preflight(
        manifest_path=manifest_path,
        repo=str(WT),
        db=db,
        target_commit=COMMIT,
        expected_computer=COMPUTER,
        skip_process_check=True,
        _fake_pids=[],
        **kwargs,
    )


# ── guard tests ───────────────────────────────────────────────────────────────

class TestPreflightGuards:
    def test_wrong_computer_blocked(self, tmp_path):
        td, db = _make_temp_db()
        mp = _write_manifest(tmp_path, _good_manifest())
        try:
            with pytest.raises(PreflightError) as exc_info:
                run_preflight(
                    manifest_path=mp, repo=str(WT), db=db,
                    target_commit=COMMIT,
                    expected_computer='NOT_A_REAL_HOST_XYZ',
                    skip_process_check=True, _fake_pids=[],
                )
            assert exc_info.value.gate == 'COMPUTER_CHECK'
        finally:
            shutil.rmtree(td)

    def test_wrong_user_blocked(self, tmp_path):
        td, db = _make_temp_db()
        mp = _write_manifest(tmp_path, _good_manifest())
        try:
            with pytest.raises(PreflightError) as exc_info:
                run_preflight(
                    manifest_path=mp, repo=str(WT), db=db,
                    target_commit=COMMIT,
                    expected_computer=COMPUTER,
                    expected_user='NOT_A_REAL_USER_XYZ',
                    skip_process_check=True, _fake_pids=[],
                )
            assert exc_info.value.gate == 'USER_CHECK'
        finally:
            shutil.rmtree(td)

    def test_wrong_repo_blocked(self, tmp_path):
        td, db = _make_temp_db()
        mp = _write_manifest(tmp_path, _good_manifest())
        fake_repo = tempfile.mkdtemp(prefix='pf_fake_repo_')
        try:
            with pytest.raises(PreflightError) as exc_info:
                run_preflight(
                    manifest_path=mp, repo=fake_repo, db=db,
                    target_commit=COMMIT,
                    expected_computer=COMPUTER,
                    skip_process_check=True, _fake_pids=[],
                )
            assert exc_info.value.gate in ('REPO_GIT', 'BRANCH_READ', 'HEAD_READ', 'MANIFEST_COMMIT')
        finally:
            shutil.rmtree(td)
            shutil.rmtree(fake_repo)

    def test_wrong_branch_blocked(self, tmp_path):
        td, db = _make_temp_db()
        mp = _write_manifest(tmp_path, _good_manifest())
        try:
            with pytest.raises(PreflightError) as exc_info:
                run_preflight(
                    manifest_path=mp, repo=str(WT), db=db,
                    target_commit=COMMIT,
                    expected_computer=COMPUTER,
                    expected_branch='main',
                    skip_process_check=True, _fake_pids=[],
                )
            assert exc_info.value.gate == 'BRANCH_CHECK'
        finally:
            shutil.rmtree(td)

    def test_short_hash_blocked(self, tmp_path):
        td, db = _make_temp_db()
        mp = _write_manifest(tmp_path, _good_manifest())
        try:
            with pytest.raises(PreflightError) as exc_info:
                run_preflight(
                    manifest_path=mp, repo=str(WT), db=db,
                    target_commit='aac27ed',   # short hash
                    expected_computer=COMPUTER,
                    skip_process_check=True, _fake_pids=[],
                )
            assert exc_info.value.gate == 'TARGET_HASH'
        finally:
            shutil.rmtree(td)

    def test_dirty_tracked_blocked(self, tmp_path):
        td, db = _make_temp_db()
        mp = _write_manifest(tmp_path, _good_manifest())
        probe = WT / 'README.md'
        if not probe.is_file():
            probe = WT / '.gitignore'
        orig = probe.read_text(encoding='utf-8')
        probe.write_text(orig + '\n# dirty-test\n', encoding='utf-8')
        try:
            with pytest.raises(PreflightError) as exc_info:
                run_preflight(
                    manifest_path=mp, repo=str(WT), db=db,
                    target_commit=COMMIT,
                    expected_computer=COMPUTER,
                    skip_process_check=True, _fake_pids=[],
                )
            assert exc_info.value.gate == 'DIRTY_TRACKED'
        finally:
            probe.write_text(orig, encoding='utf-8')
            shutil.rmtree(td)

    def test_wrong_db_blocked(self, tmp_path):
        mp = _write_manifest(tmp_path, _good_manifest())
        with pytest.raises(PreflightError) as exc_info:
            run_preflight(
                manifest_path=mp, repo=str(WT),
                db=r'C:\nonexistent\path\db.db',
                target_commit=COMMIT,
                expected_computer=COMPUTER,
                skip_process_check=True, _fake_pids=[],
            )
        assert exc_info.value.gate in ('DB_ABS', 'DB_EXISTS')

    def test_zero_byte_db_blocked(self, tmp_path):
        tmpdir = tempfile.mkdtemp()
        db = str(Path(tmpdir) / 'zero.db')
        Path(db).touch()
        mp = _write_manifest(tmp_path, _good_manifest())
        try:
            with pytest.raises(PreflightError) as exc_info:
                run_preflight(
                    manifest_path=mp, repo=str(WT), db=db,
                    target_commit=COMMIT,
                    expected_computer=COMPUTER,
                    skip_process_check=True, _fake_pids=[],
                )
            assert exc_info.value.gate == 'DB_ZERO'
        finally:
            shutil.rmtree(tmpdir)

    def test_db_integrity_blocked(self, tmp_path):
        db = str(tmp_path / 'corrupt.db')
        Path(db).write_bytes(b'SQLite format 3\x00' + b'\xff' * 200)
        mp = _write_manifest(tmp_path, _good_manifest())
        with pytest.raises(PreflightError) as exc_info:
            run_preflight(
                manifest_path=mp, repo=str(WT), db=db,
                target_commit=COMMIT,
                expected_computer=COMPUTER,
                skip_process_check=True, _fake_pids=[],
            )
        assert exc_info.value.gate in ('DB_OPEN', 'DB_INTEGRITY')

    def test_forbidden_file_blocked(self, tmp_path):
        td, db = _make_temp_db()
        manifest = _good_manifest(
            forbidden_paths=['app/modules/planlama/'],
            allowed_files=['tools/migration_runner.py'],
        )
        mp = _write_manifest(tmp_path, manifest)
        try:
            with mock.patch('tools.deploy_preflight._deploy_diff_files',
                            return_value=['app/modules/planlama/uretim_plan_routes.py']):
                with pytest.raises(PreflightError) as exc_info:
                    run_preflight(
                        manifest_path=mp, repo=str(WT), db=db,
                        target_commit=COMMIT,
                        expected_computer=COMPUTER,
                        skip_process_check=True, _fake_pids=[],
                    )
                assert exc_info.value.gate == 'FORBIDDEN_FILES'
        finally:
            shutil.rmtree(td)

    def test_manifest_short_hash_blocked(self, tmp_path):
        td, db = _make_temp_db()
        manifest = _good_manifest(tested_commit='aac27ed' + '0' * 33)  # wrong length
        mp = _write_manifest(tmp_path, manifest)
        try:
            from tools.release_manifest import ManifestError
            with pytest.raises((PreflightError, ManifestError)):
                run_preflight(
                    manifest_path=mp, repo=str(WT), db=db,
                    target_commit=COMMIT,
                    expected_computer=COMPUTER,
                    skip_process_check=True, _fake_pids=[],
                )
        finally:
            shutil.rmtree(td)

    def test_missing_execute_confirmation_blocked(self, tmp_path):
        td, db = _make_temp_db()
        mp = _write_manifest(tmp_path, _good_manifest())
        try:
            from tools.deploy_and_rollback import run_deploy
            r = run_deploy(
                manifest_path=mp, repo=str(WT), db=db,
                target_commit=COMMIT,
                execute=True,
                confirm_release='',       # missing
                expected_computer=COMPUTER,
                expected_head=COMMIT,
                skip_process_check=True,
                _fake_pids=[],
            )
            assert r['DEPLOY_RESULT'] == 'BLOCKED'
            assert '--confirm-release' in r.get('error', '')
        finally:
            shutil.rmtree(td)


def _stub_git(args: list[str], cwd: str) -> str:
    """Stub _git for tests that mock _deploy_diff_files."""
    import subprocess
    proc = subprocess.run(
        ['git'] + args, cwd=cwd,
        capture_output=True, text=True, check=True,
    )
    return proc.stdout.strip()


class TestPreflightPass:
    def test_default_mode_dry_run(self, tmp_path):
        td, db = _make_temp_db()
        mp = _write_manifest(tmp_path, _good_manifest())
        try:
            report = run_preflight(
                manifest_path=mp, repo=str(WT), db=db,
                target_commit=COMMIT,
                expected_computer=COMPUTER,
                skip_process_check=True, _fake_pids=[],
            )
            assert report['PREFLIGHT_RESULT'] == 'PASS'
        finally:
            shutil.rmtree(td)

    def test_untracked_collision_blocked(self, tmp_path):
        td, db = _make_temp_db()
        # allowed_files collides with an untracked file we'll fake
        manifest = _good_manifest(allowed_files=['tools/migration_runner.py'])
        mp = _write_manifest(tmp_path, manifest)
        try:
            with mock.patch('tools.deploy_preflight._untracked',
                            return_value=['tools/migration_runner.py']):
                with pytest.raises(PreflightError) as exc_info:
                    run_preflight(
                        manifest_path=mp, repo=str(WT), db=db,
                        target_commit=COMMIT,
                        expected_computer=COMPUTER,
                        skip_process_check=True, _fake_pids=[],
                    )
                assert exc_info.value.gate == 'UNTRACKED_COLLISION'
        finally:
            shutil.rmtree(td)

    def test_non_fast_forward_blocked(self, tmp_path):
        td, db = _make_temp_db()
        mp = _write_manifest(tmp_path, _good_manifest())
        fake_head = 'a' * 40
        try:
            with mock.patch('tools.deploy_preflight._git', side_effect=_stub_git_ff_no):
                with pytest.raises(PreflightError) as exc_info:
                    run_preflight(
                        manifest_path=mp, repo=str(WT), db=db,
                        target_commit=fake_head,
                        expected_computer=COMPUTER,
                        skip_process_check=True, _fake_pids=[],
                    )
                assert exc_info.value.gate in ('TARGET_HASH', 'FAST_FORWARD', 'MANIFEST_COMMIT')
        finally:
            shutil.rmtree(td)


def _stub_git_ff_no(args: list[str], cwd: str) -> str:
    if args[0] == 'merge-base':
        # return different value → not ff
        return 'b' * 40
    import subprocess
    proc = subprocess.run(['git'] + args, cwd=cwd, capture_output=True, text=True, check=True)
    return proc.stdout.strip()
