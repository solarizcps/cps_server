# -*- coding: utf-8 -*-
"""Migration Runner V1 — contract-scoped, guarded apply/plan."""
from __future__ import annotations

import argparse
import importlib.util
import inspect
import os
import platform
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.infra_contract_loader import load_contract
from tools.schema_parity_check import check_parity, print_report as print_parity_report


def _is_absolute(path: str) -> bool:
    return os.path.isabs(path)


def _git_head(repo: str) -> str:
    proc = subprocess.run(
        ['git', 'rev-parse', 'HEAD'],
        cwd=repo, capture_output=True, text=True, check=True,
    )
    return proc.stdout.strip()


def _tracked_dirty_count(repo: str) -> int:
    proc = subprocess.run(
        ['git', 'status', '--porcelain'],
        cwd=repo, capture_output=True, text=True, check=True,
    )
    count = 0
    for line in proc.stdout.splitlines():
        if line and line[0] in ' MADRCU':
            count += 1
    return count


def _migration_files(migrations_dir: Path) -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    for f in migrations_dir.glob('[0-9]*.py'):
        m = f.name.split('_', 1)[0]
        try:
            ver = int(m)
        except ValueError:
            continue
        out.setdefault(ver, []).append(f.name)
    return out


def _load_migration_module(repo: Path, rel_file: str):
    path = repo / rel_file
    if not path.is_file():
        raise FileNotFoundError(f'Migration file missing: {path}')
    app_dir = str(repo / 'app')
    if app_dir not in sys.path:
        sys.path.insert(0, app_dir)
    spec = importlib.util.spec_from_file_location(
        f'mig_{path.stem}', str(path),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _inspect_run(mod) -> dict[str, Any]:
    run_fn = getattr(mod, 'run', None)
    if not callable(run_fn):
        return {'supported': False, 'reason': 'no run() function'}
    sig = inspect.signature(run_fn)
    params = list(sig.parameters.values())
    has_db = bool(params) and params[0].name in ('db_path', 'path')
    has_allow = any(p.name == 'allow_canonical' for p in params)
    if not has_db:
        return {'supported': False, 'reason': 'run() missing db_path parameter'}
    if not has_allow:
        return {'supported': False, 'reason': 'run() missing allow_canonical (legacy)'}
    return {'supported': True, 'signature': str(sig)}


def _applied_versions(db_path: str) -> set[str]:
    uri = 'file:' + db_path.replace('\\', '/') + '?mode=ro'
    con = sqlite3.connect(uri, uri=True)
    try:
        if not con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        ).fetchone():
            return set()
        rows = con.execute('SELECT version FROM schema_migrations').fetchall()
        return {str(r[0]) for r in rows}
    finally:
        con.close()


def _backup_db(source: str, dest: str) -> None:
    src = sqlite3.connect(f'file:{source.replace(chr(92), "/")}?mode=ro', uri=True)
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)
        dst.commit()
    finally:
        src.close()
        dst.close()


def _canonical_db_path(repo: Path) -> str:
    return os.path.normpath(str(repo / 'app' / 'mock_data.db'))


def run_migration_runner(
    *,
    repo: str,
    db: str,
    contract: str,
    expected_commit: str,
    mode: str = 'plan',
    allow_canonical: bool = False,
    computer: str | None = None,
) -> dict[str, Any]:
    apply_mode = mode == 'apply'
    report: dict[str, Any] = {
        'RUNNER_MODE': 'APPLY' if apply_mode else 'PLAN',
        'RUNNER_RESULT': 'BLOCKED',
        'COMPUTER_CHECK': '',
        'REPO_CHECK': '',
        'WORKTREE_CHECK': '',
        'EXPECTED_COMMIT': expected_commit,
        'ACTUAL_COMMIT': '',
        'DB_PATH': db,
        'DB_INTEGRITY': '',
        'BACKUP_PATH': '',
        'REQUIRED_MIGRATIONS': '',
        'ALREADY_APPLIED': '',
        'PENDING_MIGRATIONS': '',
        'MIGRATION_RESULT': '',
        'PARITY_RESULT': '',
        'MIGRATION_CONFLICTS': [],
        'UNSUPPORTED_MIGRATIONS': [],
    }

    # --- guards ---
    if not _is_absolute(repo):
        report['error'] = 'repo path must be absolute'
        return report
    if not _is_absolute(db):
        report['error'] = 'db path must be absolute'
        return report
    if not _is_absolute(contract):
        report['error'] = 'contract path must be absolute'
        return report
    if not os.path.isdir(repo):
        report['error'] = f'repo not found: {repo}'
        return report
    if not os.path.isfile(db):
        report['error'] = f'db not found: {db}'
        return report
    if os.path.getsize(db) == 0:
        report['error'] = 'db is zero bytes'
        return report

    expected_computer = computer or platform.node()
    actual_computer = platform.node()
    if expected_computer.upper() != actual_computer.upper():
        report['COMPUTER_CHECK'] = f'BLOCKED expected={expected_computer} actual={actual_computer}'
        report['error'] = 'computer name mismatch'
        return report
    report['COMPUTER_CHECK'] = 'PASS'

    try:
        actual_commit = _git_head(repo)
        report['ACTUAL_COMMIT'] = actual_commit
        if actual_commit != expected_commit:
            report['error'] = f'commit mismatch: expected {expected_commit}, got {actual_commit}'
            return report
    except subprocess.CalledProcessError as exc:
        report['error'] = f'git head failed: {exc}'
        return report
    report['REPO_CHECK'] = 'PASS'

    dirty = _tracked_dirty_count(repo)
    if dirty > 0:
        report['WORKTREE_CHECK'] = f'BLOCKED dirty_tracked={dirty}'
        report['error'] = f'tracked dirty worktree: {dirty} files'
        return report
    report['WORKTREE_CHECK'] = 'PASS'

    canonical = _canonical_db_path(Path(repo))
    is_canonical = os.path.normpath(os.path.abspath(db)) == os.path.normpath(canonical)
    if is_canonical and apply_mode and not allow_canonical:
        report['error'] = 'canonical DB apply requires --allow-canonical'
        return report

    con_ro = sqlite3.connect(f'file:{db.replace(chr(92), "/")}?mode=ro', uri=True)
    try:
        report['DB_INTEGRITY'] = con_ro.execute('PRAGMA integrity_check').fetchone()[0]
    finally:
        con_ro.close()
    if report['DB_INTEGRITY'] != 'ok':
        report['error'] = f'integrity_check={report["DB_INTEGRITY"]}'
        return report

    contract_data = load_contract(contract)
    required = [str(v) for v in contract_data.get('required_migrations', [])]
    runner_apply = [str(v) for v in contract_data.get('runner_apply', [])]
    report['REQUIRED_MIGRATIONS'] = ','.join(required)

    migrations_dir = Path(repo) / 'app' / 'migrations'
    all_migs = _migration_files(migrations_dir)
    for ver, files in all_migs.items():
        if len(files) > 1:
            report['MIGRATION_CONFLICTS'].append(f'{ver}:{",".join(files)}')

    applied = _applied_versions(db)
    registry_pending = [v for v in required if v not in applied]
    runner_pending = [v for v in runner_apply if v not in applied]
    runner_done = [v for v in runner_apply if v in applied]
    report['ALREADY_APPLIED'] = ','.join(runner_done)
    report['PENDING_MIGRATIONS'] = ','.join(runner_pending)
    report['REGISTRY_PENDING'] = ','.join(registry_pending)

    mig_files = {}
    for entry in (contract_data.get('migrations') or {}).get('files') or []:
        mig_files[str(entry['version'])] = entry['file']

    apply_candidates = []
    for ver in runner_apply:
        rel = mig_files.get(ver)
        if not rel:
            report['UNSUPPORTED_MIGRATIONS'].append(f'{ver}:file_not_in_contract')
            continue
        try:
            mod = _load_migration_module(Path(repo), rel)
            info = _inspect_run(mod)
            if not info['supported']:
                report['UNSUPPORTED_MIGRATIONS'].append(f'{ver}:{info["reason"]}')
                continue
            apply_candidates.append((ver, rel, mod))
        except Exception as exc:
            report['UNSUPPORTED_MIGRATIONS'].append(f'{ver}:{exc}')

    if apply_mode:
        if not apply_candidates:
            if not runner_apply:
                report['MIGRATION_RESULT'] = 'SKIPPED_NO_MIGRATIONS'
            else:
                report['error'] = 'no supported migrations to apply'
                return report

        backup_dir = tempfile.mkdtemp(prefix='mig_runner_backup_')
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = os.path.join(backup_dir, f'pre_apply_{ts}.db')
        _backup_db(db, backup_path)
        report['BACKUP_PATH'] = backup_path

        results = []
        for ver, rel, mod in apply_candidates:
            if ver in applied:
                results.append(f'{ver}=SKIP')
                continue
            try:
                run_result = mod.run(db, allow_canonical=allow_canonical)
                ok = run_result.get('ok', True) if isinstance(run_result, dict) else True
                if not ok:
                    report['MIGRATION_RESULT'] = f'{ver}=FAIL'
                    report['error'] = f'migration {ver} returned ok=False'
                    return report
                results.append(f'{ver}=OK')
                applied.add(ver)
            except Exception as exc:
                report['MIGRATION_RESULT'] = f'{ver}=FAIL:{exc}'
                report['error'] = str(exc)
                parity = check_parity(
                    contract_path=contract,
                    db_path=db,
                    repo_path=repo,
                    expected_commit=expected_commit,
                )
                report['PARITY_RESULT'] = parity['PARITY_RESULT']
                report['parity_detail'] = parity
                return report
        report['MIGRATION_RESULT'] = ','.join(results) if results else 'NONE'

    # --- parity check ---
    parity = check_parity(
        contract_path=contract,
        db_path=db,
        repo_path=repo,
        expected_commit=expected_commit,
    )
    report['PARITY_RESULT'] = parity['PARITY_RESULT']
    report['parity_detail'] = parity

    if parity['PARITY_RESULT'] == 'PASS':
        report['RUNNER_RESULT'] = 'PASS'
    else:
        report['RUNNER_RESULT'] = 'BLOCKED'
        if not report.get('error'):
            report['error'] = 'schema parity blocked'

    return report


def print_runner_report(report: dict[str, Any]) -> None:
    keys = [
        'RUNNER_MODE', 'COMPUTER_CHECK', 'REPO_CHECK', 'WORKTREE_CHECK',
        'EXPECTED_COMMIT', 'ACTUAL_COMMIT', 'DB_PATH', 'DB_INTEGRITY',
        'BACKUP_PATH', 'REQUIRED_MIGRATIONS', 'ALREADY_APPLIED',
        'PENDING_MIGRATIONS', 'REGISTRY_PENDING', 'MIGRATION_RESULT', 'PARITY_RESULT', 'RUNNER_RESULT',
    ]
    for key in keys:
        val = report.get(key, '')
        print(f'{key}={val}')
    conflicts = report.get('MIGRATION_CONFLICTS') or []
    print(f'MIGRATION_CONFLICTS_REPORTED={",".join(conflicts) if conflicts else ""}')
    unsupported = report.get('UNSUPPORTED_MIGRATIONS') or []
    print(f'UNSUPPORTED_MIGRATIONS={",".join(unsupported) if unsupported else ""}')
    if report.get('error'):
        print(f'ERROR={report["error"]}')
    pd = report.get('parity_detail')
    if pd and report.get('PARITY_RESULT') != 'PASS':
        print_parity_report(pd)


def main() -> int:
    parser = argparse.ArgumentParser(description='Migration Runner V1')
    parser.add_argument('--repo', required=True, help='Absolute repo path')
    parser.add_argument('--db', required=True, help='Absolute DB path')
    parser.add_argument('--contract', required=True, help='Absolute contract TOML path')
    parser.add_argument('--expected-commit', required=True, help='Full commit hash')
    parser.add_argument('--plan', action='store_true', default=True, help='Plan mode (default)')
    parser.add_argument('--apply', action='store_true', help='Apply pending migrations')
    parser.add_argument('--allow-canonical', action='store_true')
    parser.add_argument('--computer', default='', help='Expected computer name')
    args = parser.parse_args()

    mode = 'apply' if args.apply else 'plan'
    report = run_migration_runner(
        repo=args.repo,
        db=args.db,
        contract=args.contract,
        expected_commit=args.expected_commit,
        mode=mode,
        allow_canonical=args.allow_canonical,
        computer=args.computer or None,
    )
    print_runner_report(report)
    return 0 if report.get('RUNNER_RESULT') == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
