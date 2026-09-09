# -*- coding: utf-8 -*-
"""Target-commit contract resolution and migration-free deploy tests."""
from __future__ import annotations

import getpass
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
OLD_HEAD = 'ebb04ca8765fa2a2370bafff4b7056ec401866de'
NEXGEN_CONTRACT = WT / 'tools' / 'module_schema_contracts' / 'nexgen.toml'
PLANLAMA_CONTRACT = WT / 'tools' / 'module_schema_contracts' / 'planlama.toml'
CANONICAL = Path(os.environ.get(
    'CPS_CANONICAL_DB_SOURCE', r'C:\Solariz_CPS_SERVER\app\mock_data.db',
))
COMPUTER = platform.node()
POPUP_TEMPLATE = WT / 'app' / 'templates' / 'nexgen' / 'musteri_pazarlama.html'
POPUP_BASE = '7a93a537710dee6e296abf0c7db6f62d617e2fee'

if str(WT) not in sys.path:
    sys.path.insert(0, str(WT))

from tools.release_manifest import create_manifest, save_manifest
from tools.deploy_preflight import (
    run_preflight,
    PreflightError,
    resolve_target_contract,
    normalize_contract_relative_path,
)
from tools.deploy_and_rollback import run_deploy


def _write_manifest(tmp: Path, **kwargs) -> str:
    manifest = create_manifest(
        release_id=kwargs.get('release_id', 'r-target-contract'),
        module=kwargs.get('module', 'nexgen'),
        base_commit=OLD_HEAD,
        tested_commit=kwargs.get('tested_commit', COMMIT),
        target_branch=kwargs.get('target_branch', 'fix/infra-deploy-powershell51-v1'),
        allowed_files=kwargs.get('allowed_files', ['app/templates/nexgen/musteri_pazarlama.html']),
        forbidden_paths=kwargs.get('forbidden_paths', ['app/migrations/']),
        schema_contract=kwargs.get('schema_contract', str(NEXGEN_CONTRACT)),
        required_migrations=kwargs.get('required_migrations', []),
        test_result='PASS',
        test_pass_count=19,
        test_fail_count=0,
        pilot_baseline=OLD_HEAD,
    )
    p = tmp / 'manifest.json'
    save_manifest(manifest, p)
    return str(p)


def _make_temp_db() -> tuple[str, str]:
    if not CANONICAL.is_file():
        pytest.skip(f'canonical DB missing: {CANONICAL}')
    tmpdir = tempfile.mkdtemp(prefix='tc_db_')
    db = str(Path(tmpdir) / 'test.db')
    src = sqlite3.connect(f'file:{CANONICAL.as_posix()}?mode=ro', uri=True)
    dst = sqlite3.connect(db)
    try:
        src.backup(dst)
        dst.commit()
    finally:
        src.close()
        dst.close()
    return tmpdir, db


def _init_contract_repo(tmp_path: Path) -> tuple[Path, str, str]:
    """Two-commit repo: base lacks contract, target adds nexgen.toml."""
    repo = tmp_path / 'repo'
    repo.mkdir()
    subprocess.run(['git', 'init', '-b', 'main'], cwd=repo, check=True)
    subprocess.run(['git', 'config', 'user.email', 'tc@test.local'], cwd=repo, check=True)
    subprocess.run(['git', 'config', 'user.name', 'TC Test'], cwd=repo, check=True)
    (repo / 'README.md').write_text('base\n', encoding='utf-8')
    subprocess.run(['git', 'add', '.'], cwd=repo, check=True)
    subprocess.run(['git', 'commit', '-m', 'base'], cwd=repo, check=True)
    base = subprocess.run(
        ['git', 'rev-parse', 'HEAD'], cwd=repo,
        capture_output=True, text=True, check=True,
    ).stdout.strip()

    rel = Path('tools/module_schema_contracts')
    (repo / rel).mkdir(parents=True)
    shutil.copy2(NEXGEN_CONTRACT, repo / rel / 'nexgen.toml')
    subprocess.run(['git', 'add', '.'], cwd=repo, check=True)
    subprocess.run(['git', 'commit', '-m', 'add contract'], cwd=repo, check=True)
    target = subprocess.run(
        ['git', 'rev-parse', 'HEAD'], cwd=repo,
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    subprocess.run(['git', 'checkout', base], cwd=repo, check=True)
    return repo, base, target


class TestTargetContractResolution:
    def test_old_head_lacks_contract_target_has_contract(self, tmp_path):
        repo, base, target = _init_contract_repo(tmp_path)
        rel = 'tools/module_schema_contracts/nexgen.toml'
        assert not (repo / rel).is_file()
        contract_path, tmpdir, rel_out = resolve_target_contract(
            str(repo), target, rel,
        )
        try:
            assert rel_out == rel
            assert Path(contract_path).is_file()
            assert 'nexgen' in Path(contract_path).read_text(encoding='utf-8')
        finally:
            tmpdir.cleanup()

    def test_target_contract_read_only_resolution(self, tmp_path):
        repo, base, target = _init_contract_repo(tmp_path)
        contract_path, tmpdir, _ = resolve_target_contract(
            str(repo), target, 'tools/module_schema_contracts/nexgen.toml',
        )
        try:
            before = Path(contract_path).read_text(encoding='utf-8')
            Path(contract_path).write_text('mutated', encoding='utf-8')
            assert Path(contract_path).read_text(encoding='utf-8') == 'mutated'
            assert not (repo / 'tools/module_schema_contracts/nexgen.toml').exists()
        finally:
            tmpdir.cleanup()

    def test_target_also_lacks_contract_blocked(self, tmp_path):
        repo, base, _target = _init_contract_repo(tmp_path)
        with pytest.raises(PreflightError) as exc:
            resolve_target_contract(
                str(repo), base, 'tools/module_schema_contracts/nexgen.toml',
            )
        assert exc.value.gate == 'CONTRACT_NOT_FOUND'

    def test_contract_path_traversal_blocked(self, tmp_path):
        repo = tmp_path / 'repo'
        repo.mkdir()
        with pytest.raises(PreflightError) as exc:
            normalize_contract_relative_path(str(repo), '../../etc/passwd')
        assert exc.value.gate == 'CONTRACT_PATH'


class TestEmptyRequiredMigrations:
    def test_empty_required_migrations_plan(self, tmp_path):
        td, db = _make_temp_db()
        mp = _write_manifest(tmp_path, schema_contract=str(NEXGEN_CONTRACT))
        try:
            r = run_deploy(
                manifest_path=mp, repo=str(WT), db=db,
                target_commit=COMMIT, execute=False,
                expected_computer=COMPUTER,
                skip_process_check=True, _fake_pids=[],
            )
            assert r['DEPLOY_RESULT'] == 'PLAN_PASS'
            assert r['MIGRATION_PLAN'] == 'NONE_REQUIRED'
            assert r['PREFLIGHT_RESULT'] == 'PASS'
        finally:
            shutil.rmtree(td)

    def test_empty_required_migrations_execute_skipped(self, tmp_path):
        td, db = _make_temp_db()
        mp = _write_manifest(tmp_path, schema_contract=str(NEXGEN_CONTRACT))
        try:
            r = run_deploy(
                manifest_path=mp, repo=str(WT), db=db,
                target_commit=COMMIT, execute=True,
                confirm_release='r-target-contract',
                expected_computer=COMPUTER,
                expected_head=COMMIT,
                skip_process_check=True, _fake_pids=[],
                _fake_start=lambda repo, env=None: {'ok': True, 'pid': '11111'},
                _fake_health=lambda url: {'ok': True, 'status': 200},
                _fake_stop=lambda pid: True,
            )
            assert r['MIGRATION_RESULT'] == 'SKIPPED_NO_MIGRATIONS'
            assert r['DEPLOY_RESULT'] == 'PASS'
        finally:
            shutil.rmtree(td)


class TestNonemptyMigrationBehavior:
    def test_nonempty_migration_behavior_unchanged(self, tmp_path):
        td, db = _make_temp_db()
        mp = _write_manifest(
            tmp_path,
            module='planlama_uretim',
            schema_contract=str(PLANLAMA_CONTRACT),
            required_migrations=['190'],
            allowed_files=['tools/migration_runner.py'],
        )
        try:
            from tools.migration_runner import run_migration_runner
            run_migration_runner(
                repo=str(WT), db=db, contract=str(PLANLAMA_CONTRACT),
                expected_commit=COMMIT, mode='apply', computer=COMPUTER,
            )
            r = run_deploy(
                manifest_path=mp, repo=str(WT), db=db,
                target_commit=COMMIT, execute=False,
                expected_computer=COMPUTER,
                skip_process_check=True, _fake_pids=[],
            )
            assert r['DEPLOY_RESULT'] == 'PLAN_PASS'
            assert r['MIGRATION_PLAN'] == ''
            assert r['PARITY_BEFORE'] == 'PASS'
        finally:
            shutil.rmtree(td)


class TestParityBeforeTargetContract:
    def test_parity_before_uses_target_contract(self, tmp_path):
        repo, base, target = _init_contract_repo(tmp_path)
        td, db = _make_temp_db()
        mp = _write_manifest(
            tmp_path,
            tested_commit=target,
            schema_contract='tools/module_schema_contracts/nexgen.toml',
        )
        try:
            with mock.patch('tools.deploy_preflight._git') as mock_git:
                def _fake_git(args, cwd):
                    if args[:2] == ['rev-parse', 'HEAD']:
                        return base
                    if args[0] == 'branch':
                        return 'main'
                    if args[0] == 'merge-base':
                        return base
                    if args[0] == 'fetch':
                        return ''
                    if args[0] == 'status':
                        return ''
                    if args[0] == 'diff':
                        return ''
                    return subprocess.run(
                        ['git'] + args, cwd=cwd,
                        capture_output=True, text=True, check=True,
                    ).stdout.strip()

                mock_git.side_effect = _fake_git
                pf = run_preflight(
                    manifest_path=mp, repo=str(repo), db=db,
                    target_commit=target,
                    skip_process_check=True, _fake_pids=[],
                )
            assert pf['PREFLIGHT_RESULT'] == 'PASS'
            assert pf['MIGRATION_PLAN'] == 'NONE_REQUIRED'
            assert pf['PARITY_BEFORE'] in ('PASS', 'BLOCKED')
        finally:
            shutil.rmtree(td)


class TestPopupAndAtpGuard:
    def test_popup_template_unchanged(self):
        expected = subprocess.run(
            ['git', 'show', f'{POPUP_BASE}:app/templates/nexgen/musteri_pazarlama.html'],
            cwd=str(WT), capture_output=True, text=True, check=True,
        ).stdout
        assert POPUP_TEMPLATE.read_text(encoding='utf-8') == expected

    def test_atp_diff_from_fix_is_zero(self):
        changed = subprocess.run(
            ['git', 'diff', '--name-only', 'HEAD'],
            cwd=str(WT), capture_output=True, text=True, check=True,
        ).stdout.splitlines()
        manifest_path = WT / 'docs' / 'atp-lock' / 'atp_touchpoints.sha256'
        touchpoints = {
            line.split('  ', 1)[1].strip()
            for line in manifest_path.read_text(encoding='utf-8', errors='ignore').splitlines()
            if '  ' in line
        }
        overlap = [f for f in changed if f in touchpoints]
        assert overlap == []
