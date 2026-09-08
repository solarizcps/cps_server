# -*- coding: utf-8 -*-
"""
Deploy and rollback orchestrator — guarded, plan-first.

Default mode: PLAN (no writes, no mutations).
Execute mode: requires --execute + --confirm-release + --expected-computer
              + --expected-head + --target-commit + --allow-canonical.
"""
from __future__ import annotations

import argparse
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.release_manifest import load_manifest, require_valid_manifest
from tools.deploy_preflight import run_preflight, print_preflight_report, PreflightError
from tools.migration_runner import run_migration_runner
from tools.schema_parity_check import check_parity


# ── backup ───────────────────────────────────────────────────────────────────

def backup_db(source: str, backup_dir: str | None = None) -> str:
    """Create a timestamped SQLite backup. Returns backup path."""
    if backup_dir is None:
        backup_dir = tempfile.mkdtemp(prefix='cps_deploy_backup_')
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    dest = os.path.join(backup_dir, f'pre_deploy_{ts}.db')
    src_uri = 'file:' + source.replace('\\', '/') + '?mode=ro'
    src = sqlite3.connect(src_uri, uri=True)
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)
        dst.commit()
    finally:
        src.close()
        dst.close()
    return dest


def verify_backup(source: str, backup: str) -> dict[str, Any]:
    """Verify backup integrity and row/table counts match source."""
    result: dict[str, Any] = {'ok': False}
    for label, path in [('source', source), ('backup', backup)]:
        if not os.path.isfile(path) or os.path.getsize(path) == 0:
            result['error'] = f'{label} missing or empty'
            return result
    src_uri = 'file:' + source.replace('\\', '/') + '?mode=ro'
    bak_uri = 'file:' + backup.replace('\\', '/') + '?mode=ro'
    src = sqlite3.connect(src_uri, uri=True)
    bak = sqlite3.connect(bak_uri, uri=True)
    try:
        bak_ic = bak.execute('PRAGMA integrity_check').fetchone()[0]
        result['backup_integrity'] = bak_ic
        if bak_ic != 'ok':
            result['error'] = f'backup integrity_check={bak_ic}'
            return result

        def _tables(con: sqlite3.Connection) -> list[str]:
            return [
                r[0] for r in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                ).fetchall()
            ]

        src_tables = _tables(src)
        bak_tables = _tables(bak)
        result['source_tables'] = len(src_tables)
        result['backup_tables'] = len(bak_tables)
        if set(src_tables) != set(bak_tables):
            result['error'] = 'table sets differ'
            return result

        for t in src_tables:
            src_count = src.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
            bak_count = bak.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
            if src_count != bak_count:
                result['error'] = f'row count mismatch in {t}: src={src_count} bak={bak_count}'
                return result

        result['ok'] = True
    finally:
        src.close()
        bak.close()
    return result


# ── process helpers ───────────────────────────────────────────────────────────

def stop_process(pid: str, *, _fake_stop: Callable | None = None) -> bool:
    """Stop a process by PID. Returns True on success."""
    if _fake_stop is not None:
        return _fake_stop(pid)
    try:
        subprocess.run(['taskkill', '/F', '/PID', pid], check=True,
                       capture_output=True)
        return True
    except Exception:
        return False


def start_process(
    *,
    repo: str,
    env: dict[str, str] | None = None,
    _fake_start: Callable | None = None,
) -> dict[str, Any]:
    """Start CPS server. Returns {'pid': ..., 'ok': bool}."""
    if _fake_start is not None:
        return _fake_start(repo=repo, env=env)
    app_dir = str(Path(repo) / 'app')
    py = sys.executable
    # Actual start: runs in background via subprocess
    try:
        proc = subprocess.Popen(
            [py, 'app.py'],
            cwd=app_dir,
            env={**os.environ, **(env or {})},
        )
        time.sleep(2)
        if proc.poll() is not None:
            return {'ok': False, 'pid': '', 'error': 'process exited immediately'}
        return {'ok': True, 'pid': str(proc.pid)}
    except Exception as exc:
        return {'ok': False, 'pid': '', 'error': str(exc)}


def health_check(
    url: str = 'http://127.0.0.1:8080/',
    *,
    _fake_health: Callable | None = None,
) -> dict[str, Any]:
    """HTTP health check. Returns {'ok': bool, 'status': int}."""
    if _fake_health is not None:
        return _fake_health(url)
    try:
        import urllib.request
        with urllib.request.urlopen(url, timeout=10) as resp:
            return {'ok': resp.status < 400, 'status': resp.status}
    except Exception as exc:
        return {'ok': False, 'status': 0, 'error': str(exc)}


def restore_db(backup: str, target: str) -> bool:
    """Restore DB from backup using SQLite Backup API."""
    src = sqlite3.connect(f'file:{backup.replace(chr(92), "/")}?mode=ro', uri=True)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
        dst.commit()
        return True
    except Exception:
        return False
    finally:
        src.close()
        dst.close()


def git_reset_hard(repo: str, commit: str) -> bool:
    try:
        subprocess.run(
            ['git', 'reset', '--hard', commit],
            cwd=repo, check=True, capture_output=True,
        )
        return True
    except Exception:
        return False


# ── main orchestrator ─────────────────────────────────────────────────────────

def run_deploy(
    *,
    manifest_path: str,
    repo: str,
    db: str,
    target_commit: str,
    execute: bool = False,
    confirm_release: str = '',
    expected_computer: str | None = None,
    expected_user: str | None = None,
    expected_head: str | None = None,
    allow_canonical: bool = False,
    cps_port: int = 8080,
    skip_process_check: bool = False,
    # dependency injection for tests
    _fake_pids: list[str] | None = None,
    _fake_stop: Callable | None = None,
    _fake_start: Callable | None = None,
    _fake_health: Callable | None = None,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        'RUNNER_MODE': 'APPLY' if execute else 'PLAN',
        'DEPLOY_RESULT': 'BLOCKED',
        'PREFLIGHT_RESULT': '',
        'OLD_HEAD': '',
        'TARGET_HEAD': target_commit,
        'DEPLOY_FILES': [],
        'DB_PATH': db,
        'DB_INTEGRITY': '',
        'MIGRATION_PLAN': '',
        'PARITY_BEFORE': '',
        'PARITY_AFTER': '',
        'ACTIVE_PID': '',
        'BACKUP_PATH': '',
        'BACKUP_INTEGRITY': '',
        'ROLLBACK_PLAN': '',
        'MIGRATION_RESULT': '',
        'NEW_PID': '',
        'HEALTH_AFTER': '',
        'HEALTH_ROLLBACK': '',
    }

    # ── EXECUTE gate ─────────────────────────────────────────────────────────
    if execute:
        missing: list[str] = []
        if not confirm_release:
            missing.append('--confirm-release')
        if not expected_computer:
            missing.append('--expected-computer')
        if not expected_head:
            missing.append('--expected-head')
        if not target_commit or len(target_commit) != 40:
            missing.append('--target-commit (full 40-char hash)')
        if missing:
            report['error'] = f'EXECUTE requires: {", ".join(missing)}'
            return report

    # ── PREFLIGHT ────────────────────────────────────────────────────────────
    try:
        pf = run_preflight(
            manifest_path=manifest_path,
            repo=repo,
            db=db,
            target_commit=target_commit,
            expected_computer=expected_computer,
            expected_user=expected_user,
            cps_port=cps_port,
            skip_process_check=skip_process_check,
            _fake_pids=_fake_pids,
        )
    except PreflightError as exc:
        report['PREFLIGHT_RESULT'] = f'BLOCKED:{exc.gate}'
        report['error'] = str(exc)
        return report
    except Exception as exc:
        report['PREFLIGHT_RESULT'] = f'BLOCKED:MANIFEST_ERROR'
        report['error'] = str(exc)
        return report

    report['PREFLIGHT_RESULT'] = pf['PREFLIGHT_RESULT']
    report['OLD_HEAD'] = pf['OLD_HEAD']
    report['DEPLOY_FILES'] = pf['DEPLOY_FILES']
    report['DB_INTEGRITY'] = pf['DB_INTEGRITY']
    report['MIGRATION_PLAN'] = pf['MIGRATION_PLAN']
    report['PARITY_BEFORE'] = pf['PARITY_BEFORE']
    report['ACTIVE_PID'] = pf['ACTIVE_PID']

    manifest = load_manifest(manifest_path)
    report['BACKUP_WOULD_CREATE'] = (
        f'pre_deploy_<timestamp>.db in temp dir (SQLite Backup API)'
    )
    rollback_steps = [
        f'1. Stop new process (if started)',
        f'2. restore_db(backup, {db})',
        f'3. git reset --hard {pf["OLD_HEAD"][:12]}',
        f'4. Restart with old env',
        f'5. Health check old version',
    ]
    report['ROLLBACK_PLAN'] = ' | '.join(rollback_steps)
    report['DEPLOY_ALLOWED'] = 'YES' if not execute else 'EXECUTE_PENDING'

    if not execute:
        # PLAN mode ends here — no mutations
        report['DEPLOY_RESULT'] = 'PLAN_PASS'
        return report

    # ── EXECUTE gate: confirm_release must match manifest ────────────────────
    if confirm_release != manifest.get('release_id', ''):
        report['error'] = (
            f'--confirm-release {confirm_release!r} does not match '
            f'manifest.release_id {manifest.get("release_id")!r}'
        )
        return report

    # ── BACKUP ───────────────────────────────────────────────────────────────
    try:
        backup_path = backup_db(db)
    except Exception as exc:
        report['error'] = f'backup failed: {exc}'
        return report
    report['BACKUP_PATH'] = backup_path
    bak_verify = verify_backup(db, backup_path)
    report['BACKUP_INTEGRITY'] = bak_verify.get('backup_integrity', '')
    if not bak_verify['ok']:
        report['error'] = f'backup verify failed: {bak_verify.get("error")}'
        return report

    # ── GIT FAST-FORWARD ─────────────────────────────────────────────────────
    old_head = pf['OLD_HEAD']
    if target_commit != old_head:
        try:
            subprocess.run(
                ['git', 'merge', '--ff-only', target_commit],
                cwd=repo, check=True, capture_output=True,
            )
        except subprocess.CalledProcessError as exc:
            report['error'] = f'git ff-only failed: {exc.stderr}'
            return report

    # ── MIGRATION APPLY ──────────────────────────────────────────────────────
    contract_path_raw = manifest.get('schema_contract', '')
    contract_path = (
        contract_path_raw if os.path.isabs(contract_path_raw)
        else str(Path(repo) / contract_path_raw)
    )
    if os.path.isfile(contract_path):
        mig = run_migration_runner(
            repo=repo, db=db, contract=contract_path,
            expected_commit=target_commit,
            mode='apply', computer=platform.node(),
            allow_canonical=allow_canonical,
        )
        report['MIGRATION_RESULT'] = mig.get('MIGRATION_RESULT', '')
        if mig.get('RUNNER_RESULT') != 'PASS':
            report['error'] = f'migration failed: {mig.get("error")}'
            # rollback DB
            restore_db(backup_path, db)
            if target_commit != old_head:
                git_reset_hard(repo, old_head)
            report['ROLLBACK_APPLIED'] = 'YES'
            return report
    else:
        report['MIGRATION_RESULT'] = 'NO_CONTRACT'

    # ── SCHEMA PARITY AFTER ──────────────────────────────────────────────────
    if os.path.isfile(contract_path):
        parity_after = check_parity(
            contract_path=contract_path,
            db_path=db,
            repo_path=repo,
            expected_commit=target_commit,
        )
        report['PARITY_AFTER'] = parity_after['PARITY_RESULT']
        if parity_after['PARITY_RESULT'] != 'PASS':
            report['error'] = 'post-migration parity BLOCKED'
            restore_db(backup_path, db)
            if target_commit != old_head:
                git_reset_hard(repo, old_head)
            report['ROLLBACK_APPLIED'] = 'YES'
            return report

    # ── STOP OLD PROCESS ─────────────────────────────────────────────────────
    active_pid = pf.get('ACTIVE_PID', '')
    if active_pid and active_pid not in ('NONE', 'SKIPPED'):
        stop_process(active_pid, _fake_stop=_fake_stop)

    # ── START NEW PROCESS ────────────────────────────────────────────────────
    start_result = start_process(repo=repo, _fake_start=_fake_start)
    report['NEW_PID'] = start_result.get('pid', '')
    if not start_result.get('ok'):
        report['error'] = f'process start failed: {start_result.get("error")}'
        # rollback
        restore_db(backup_path, db)
        if target_commit != old_head:
            git_reset_hard(repo, old_head)
        report['ROLLBACK_APPLIED'] = 'YES'
        return report

    # ── HEALTH CHECK ─────────────────────────────────────────────────────────
    health = health_check(_fake_health=_fake_health)
    report['HEALTH_AFTER'] = 'PASS' if health.get('ok') else 'FAIL'
    if not health.get('ok'):
        # rollback
        stop_process(report['NEW_PID'], _fake_stop=_fake_stop)
        restore_db(backup_path, db)
        if target_commit != old_head:
            git_reset_hard(repo, old_head)
        rollback_start = start_process(repo=repo, _fake_start=_fake_start)
        rollback_health = health_check(_fake_health=_fake_health)
        report['HEALTH_ROLLBACK'] = 'PASS' if rollback_health.get('ok') else 'FAIL'
        report['ROLLBACK_APPLIED'] = 'YES'
        report['error'] = 'health check failed after deploy'
        return report

    report['DEPLOY_RESULT'] = 'PASS'
    return report


def print_deploy_report(report: dict[str, Any]) -> None:
    keys = [
        'RUNNER_MODE', 'DEPLOY_RESULT', 'PREFLIGHT_RESULT',
        'OLD_HEAD', 'TARGET_HEAD', 'DB_PATH', 'DB_INTEGRITY',
        'ACTIVE_PID', 'BACKUP_PATH', 'BACKUP_INTEGRITY',
        'MIGRATION_PLAN', 'MIGRATION_RESULT',
        'PARITY_BEFORE', 'PARITY_AFTER',
        'NEW_PID', 'HEALTH_AFTER', 'HEALTH_ROLLBACK',
        'BACKUP_WOULD_CREATE', 'ROLLBACK_PLAN', 'DEPLOY_ALLOWED',
    ]
    for k in keys:
        v = report.get(k, '')
        if isinstance(v, list):
            print(f'{k}={",".join(v)}')
        else:
            print(f'{k}={v}')
    if report.get('error'):
        print(f'ERROR={report["error"]}')


def main() -> int:
    parser = argparse.ArgumentParser(description='CPS Deploy / Rollback V1')
    parser.add_argument('--manifest', required=True, help='Absolute path to release manifest JSON')
    parser.add_argument('--repo', required=True)
    parser.add_argument('--db', required=True)
    parser.add_argument('--target-commit', required=True, help='Full 40-char hash')
    parser.add_argument('--execute', action='store_true', help='Perform actual deploy')
    parser.add_argument('--confirm-release', default='')
    parser.add_argument('--expected-computer', default='')
    parser.add_argument('--expected-user', default='')
    parser.add_argument('--expected-head', default='')
    parser.add_argument('--allow-canonical', action='store_true')
    parser.add_argument('--skip-process-check', action='store_true')
    args = parser.parse_args()

    report = run_deploy(
        manifest_path=args.manifest,
        repo=args.repo,
        db=args.db,
        target_commit=args.target_commit,
        execute=args.execute,
        confirm_release=args.confirm_release,
        expected_computer=args.expected_computer or None,
        expected_user=args.expected_user or None,
        expected_head=args.expected_head or None,
        allow_canonical=args.allow_canonical,
        skip_process_check=args.skip_process_check,
    )
    print_deploy_report(report)
    return 0 if report.get('DEPLOY_RESULT') in ('PASS', 'PLAN_PASS') else 1


if __name__ == '__main__':
    sys.exit(main())
