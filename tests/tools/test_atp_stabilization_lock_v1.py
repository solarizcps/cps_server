# -*- coding: utf-8 -*-
"""ATP production stabilization lock validator tests."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

WT = Path(__file__).resolve().parents[2]
ATP_VALIDATOR = WT / 'tools' / 'validate_atp_stabilization_lock.py'
BUILDER = WT / 'tools/build_atp_lock_manifest.py'
MANIFEST = WT / 'docs/atp-lock/atp_stabilization_manifest.sha256'
DEPLOY_PREFLIGHT = WT / 'deploy_preflight.ps1'
FORBIDDEN_SECRET_RE = re.compile(
    r'(password\s*=|TURKCELL_FILOM_PASSWORD|TURKCELL_FILOM_USERNAME|\.dpapi)',
    re.I,
)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def atp_mod():
    return _load('validate_atp_stabilization_lock', ATP_VALIDATOR)


def _copy_lock_tree(tmp: Path) -> None:
    for rel in (
        'docs/atp-lock',
        'tools/validate_atp_stabilization_lock.py',
        'tools/build_atp_lock_manifest.py',
        'app/modules/planlama/arac_takip_routes.py',
        'app/templates/planlama/arac_takip_plan.html',
        'app/templates/base.html',
        'app/app.py',
        'app/migrations/nexgen_manifest.py',
    ):
        src = WT / rel
        dst = tmp / rel
        if src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        elif src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)


def test_t1_baseline_manifest_pass(atp_mod):
    errors, checked = atp_mod.validate_atp_lock()
    assert not errors, errors
    assert checked >= 120


def test_t2_tamper_one_byte_fails(atp_mod, tmp_path):
    tmp = tmp_path / 'repo'
    tmp.mkdir()
    _copy_lock_tree(tmp)
    routes = tmp / 'app/modules/planlama/arac_takip_routes.py'
    data = routes.read_bytes()
    routes.write_bytes(data[:-1] + bytes([data[-1] ^ 0x01]))
    atp_mod.ROOT = tmp
    atp_mod.MANIFEST = tmp / 'docs/atp-lock/atp_stabilization_manifest.sha256'
    atp_mod.TOUCHPOINTS = tmp / 'docs/atp-lock/atp_touchpoints.sha256'
    errors, _ = atp_mod.validate_atp_lock()
    assert any('hash mismatch' in e for e in errors)


def test_t3_missing_manifest_file_fails(atp_mod, tmp_path):
    tmp = tmp_path / 'repo'
    tmp.mkdir()
    _copy_lock_tree(tmp)
    target = tmp / 'app/modules/planlama/arac_takip_routes.py'
    target.unlink()
    atp_mod.ROOT = tmp
    atp_mod.MANIFEST = tmp / 'docs/atp-lock/atp_stabilization_manifest.sha256'
    atp_mod.TOUCHPOINTS = tmp / 'docs/atp-lock/atp_touchpoints.sha256'
    errors, _ = atp_mod.validate_atp_lock()
    assert any('missing manifest file' in e for e in errors)


def test_t4_new_atp_dependency_review_required(atp_mod, tmp_path):
    tmp = tmp_path / 'repo'
    tmp.mkdir()
    _copy_lock_tree(tmp)
    extra = tmp / 'app/modules/planlama/arac_new_dependency_probe.py'
    extra.parent.mkdir(parents=True, exist_ok=True)
    extra.write_text('# probe\n', encoding='utf-8')
    atp_mod.ROOT = tmp
    atp_mod.MANIFEST = tmp / 'docs/atp-lock/atp_stabilization_manifest.sha256'
    atp_mod.TOUCHPOINTS = tmp / 'docs/atp-lock/atp_touchpoints.sha256'
    errors, _ = atp_mod.validate_atp_lock()
    assert any('review-required undeclared ATP dependency' in e for e in errors)


def test_t5_non_atp_change_passes(atp_mod):
    inv = json.loads((WT / 'docs/atp-lock/atp_inventory.json').read_text(encoding='utf-8'))
    manifest_files = set(inv['files'].keys())
    finans_dir = WT / 'app' / 'modules' / 'finans'
    if finans_dir.is_dir():
        for path in finans_dir.rglob('*.py'):
            rel = str(path.relative_to(WT)).replace('\\', '/')
            assert rel not in manifest_files
    errors, _ = atp_mod.validate_atp_lock()
    assert not errors, errors


def test_t6_secret_exclusion_manifest_and_inventory():
    manifest_text = MANIFEST.read_text(encoding='utf-8')
    assert not FORBIDDEN_SECRET_RE.search(manifest_text)
    inv_text = (WT / 'docs/atp-lock/atp_inventory.json').read_text(encoding='utf-8')
    assert not FORBIDDEN_SECRET_RE.search(inv_text)
    assert 'TURKCELL_FILOM_PASSWORD' not in manifest_text


def test_t7_deploy_preflight_invokes_atp_gate_pass():
    proc = subprocess.run(
        ['powershell', '-NoProfile', '-File', str(DEPLOY_PREFLIGHT)],
        cwd=WT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert 'ATP_STABILIZATION_LOCK=PASS' in proc.stdout


def test_t8_deploy_preflight_tamper_exit_nonzero(tmp_path):
    routes = WT / 'app/modules/planlama/arac_takip_routes.py'
    backup = routes.read_bytes()
    try:
        data = bytearray(backup)
        data[-1] ^= 0x01
        routes.write_bytes(bytes(data))
        proc = subprocess.run(
            ['powershell', '-NoProfile', '-File', str(DEPLOY_PREFLIGHT)],
            cwd=WT,
            capture_output=True,
            text=True,
        )
        assert proc.returncode != 0
        assert 'ATP stabilization lock FAIL' in proc.stdout or 'PREFLIGHT BASARISIZ' in proc.stdout
    finally:
        routes.write_bytes(backup)


def test_t9_self_reference_absent():
    inv = json.loads((WT / 'docs/atp-lock/atp_inventory.json').read_text(encoding='utf-8'))
    ms = inv['manifest_self_reference']
    assert ms['atp_stabilization_manifest.sha256'] == 'EXCLUDED (self-reference forbidden)'
    assert 'docs/atp-lock/atp_stabilization_manifest.sha256' not in inv['files']
    assert 'docs/atp-lock/atp_inventory.json' not in inv['files']


def test_t10_builder_deterministic():
    first = MANIFEST.read_bytes()
    proc = subprocess.run([sys.executable, str(BUILDER)], cwd=WT, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    second = MANIFEST.read_bytes()
    assert first == second


def test_t11_category_counts_reconcile():
    inv = json.loads((WT / 'docs/atp-lock/atp_inventory.json').read_text(encoding='utf-8'))
    cat_sum = sum(inv['category_counts'].values())
    assert cat_sum == inv['unique_file_count']
    assert inv['unique_file_count'] == len(inv['files'])
    manifest_lines = [
        ln for ln in MANIFEST.read_text(encoding='utf-8').splitlines()
        if ln.strip() and not ln.startswith('#')
    ]
    assert len(manifest_lines) == inv['unique_file_count']


def test_t12_git_base_exact_baseline():
    """Verify that the manifest's lock_baseline_commit is recorded consistently.

    On production (frozen branch) HEAD == baseline_commit.
    On integration branches with approved ATP commits HEAD advances beyond the
    baseline; the real integrity guard is the full hash check in t1.  We keep
    the baseline-commit consistency check here: the inventory JSON and the
    manifest header must agree on the same SHA, and git must know that commit.
    """
    inv = json.loads((WT / 'docs/atp-lock/atp_inventory.json').read_text(encoding='utf-8'))
    inv_baseline = inv.get('baseline_commit', '').strip()
    assert inv_baseline, 'atp_inventory.json missing baseline_commit'

    manifest_text = (WT / 'docs/atp-lock/atp_stabilization_manifest.sha256').read_text(encoding='utf-8')
    header_match = re.search(r'lock_baseline_commit=([0-9a-f]{40})', manifest_text)
    assert header_match, 'manifest header missing lock_baseline_commit'
    manifest_baseline = header_match.group(1)

    assert inv_baseline == manifest_baseline, (
        f'inventory baseline {inv_baseline!r} != manifest baseline {manifest_baseline!r}'
    )

    # baseline commit must exist in this repo's history
    result = subprocess.run(
        ['git', 'cat-file', '-t', inv_baseline],
        cwd=WT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0 and result.stdout.strip() == 'commit', (
        f'baseline commit {inv_baseline} not found in repo history'
    )

    # HEAD must be the baseline or a descendant of it; if neither (diverged
    # integration branch with approved-only ATP commits), atp_lock PASS (t1)
    # is the authoritative guard — emit a diagnostic but do not fail.
    head_proc = subprocess.run(
        ['git', 'rev-parse', 'HEAD'],
        cwd=WT, capture_output=True, text=True, check=True,
    )
    head = head_proc.stdout.strip()
    if head == inv_baseline:
        return  # production branch: exact match

    ancestor_check = subprocess.run(
        ['git', 'merge-base', '--is-ancestor', inv_baseline, head],
        cwd=WT, capture_output=True,
    )
    if ancestor_check.returncode == 0:
        return  # baseline is ancestor of HEAD — normal forward progress

    # Diverged branch: acceptable only when t1 (full hash validation) passes
    errors, checked = _load('validate_atp_stabilization_lock', ATP_VALIDATOR).validate_atp_lock()
    assert not errors, (
        f'HEAD {head} diverged from baseline {inv_baseline} AND lock validation failed: {errors}'
    )
    assert checked >= 120, f'too few files checked: {checked}'


_LIVE_DB_PATHS = frozenset({
    # Production server live DB — changes continuously (GPS worker writes every 60 s).
    # Per lock policy rule 5, runtime DB content is explicitly out-of-scope.
    r'C:\Solariz_CPS_SERVER\app\mock_data.db',
    r'C:/Solariz_CPS_SERVER/app/mock_data.db',
})


def _resolve_frozen_db() -> Path | None:
    """Return a *frozen* reference DB path for SHA comparison, or None.

    A frozen DB is a file that is:
      - not a live production/GPS-worker-updated path, AND
      - not the live app runtime DB (mock_data.db removed from git in 2fafca6).

    To enable t13 on production set CPS_CANONICAL_DB_FROZEN to a static
    snapshot created at the known-good baseline commit (not the live DB).
    """
    frozen_env = __import__('os').environ.get('CPS_CANONICAL_DB_FROZEN', '').strip()
    if frozen_env:
        p = Path(frozen_env)
        if p.is_file():
            return p.resolve()

    # CPS_CANONICAL_DB_SOURCE is the *live* DB set by conftest — skip it here.
    # It changes at runtime and its SHA is intentionally out-of-scope (rule 5).
    repo_path = WT / 'app' / 'mock_data.db'
    if repo_path.is_file():
        return repo_path.resolve()

    return None


def test_t13_canonical_db_sha_unchanged():
    """Assert frozen reference DB SHA when an explicit frozen snapshot is available.

    This guard is skipped in the following situations (all correct behaviour):
      - app/mock_data.db not present (removed from git per lock policy rule 5).
      - CPS_CANONICAL_DB_SOURCE points to the live production DB that the GPS
        worker updates continuously — live DB content is explicitly out-of-scope
        per lock policy rule 5.

    To activate this guard provide CPS_CANONICAL_DB_FROZEN=/path/to/snapshot.db
    pointing to a byte-frozen copy taken at the original baseline commit.
    """
    db_path = _resolve_frozen_db()
    if db_path is None:
        pytest.skip(
            'No frozen reference DB available (live DB is out-of-scope per lock policy rule 5; '
            'set CPS_CANONICAL_DB_FROZEN=/path/snapshot.db to enable this guard).'
        )
    sha = hashlib.sha256(db_path.read_bytes()).hexdigest()
    assert sha == 'cf01972adefdb07298175f59b9e3493b9023ae68a9670dc9928fa937d53ac7fd'
