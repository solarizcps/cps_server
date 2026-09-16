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
from tools.deploy_preflight import (
    run_preflight,
    print_preflight_report,
    PreflightError,
    normalize_contract_relative_path,
    run_deploy_module_parity,
)
from tools.infra_contract_loader import load_contract
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

_STARTUP_GRACE_SEC = 0.25
_LOG_TAIL_LINES = 20
_HEALTH_PATH = '/giris'
_HEALTH_TOTAL_TIMEOUT_SEC = 60.0
_HEALTH_POLL_INTERVAL_SEC = 2.0
_HEALTH_REQUEST_TIMEOUT_SEC = 5.0


def _build_server_env(
    *,
    db_path: str | None = None,
    port: int = 8080,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    env = os.environ.copy()
    env['FLASK_DEBUG'] = '0'
    env['CPS_PORT'] = str(port)
    if db_path:
        env['CPS_MOCK_DB_PATH'] = db_path
    if extra:
        env.update(extra)
    return env


def _server_log_paths(repo: str) -> tuple[str, str]:
    log_dir = Path(repo) / 'logs' / 'deploy'
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    return (
        str(log_dir / f'cps_server_{ts}.stdout.log'),
        str(log_dir / f'cps_server_{ts}.stderr.log'),
    )


def _tail_log_file(path: str, max_lines: int = _LOG_TAIL_LINES) -> str:
    try:
        with open(path, encoding='utf-8', errors='replace') as fh:
            lines = fh.readlines()
        if not lines:
            return ''
        return ''.join(lines[-max_lines:]).strip()
    except OSError:
        return ''


def _tail_server_logs(stdout_log: str, stderr_log: str) -> str:
    parts: list[str] = []
    out_tail = _tail_log_file(stdout_log)
    err_tail = _tail_log_file(stderr_log)
    if out_tail:
        parts.append(f'stdout:\n{out_tail}')
    if err_tail:
        parts.append(f'stderr:\n{err_tail}')
    return '\n'.join(parts)


def _popen_detached_server(
    cmd: list[str],
    *,
    cwd: str,
    env: dict[str, str],
    stdout_log: str,
    stderr_log: str,
) -> subprocess.Popen:
    """Launch CPS server detached from parent terminal (stdout/stderr → log files)."""
    stdout_f = open(stdout_log, 'w', encoding='utf-8', buffering=1)
    stderr_f = open(stderr_log, 'w', encoding='utf-8', buffering=1)
    popen_kwargs: dict[str, Any] = {
        'cwd': cwd,
        'env': env,
        'stdin': subprocess.DEVNULL,
        'stdout': stdout_f,
        'stderr': stderr_f,
        'close_fds': True,
    }
    if sys.platform == 'win32':
        popen_kwargs['creationflags'] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        )
    else:
        popen_kwargs['start_new_session'] = True
    try:
        proc = subprocess.Popen(cmd, **popen_kwargs)
    finally:
        stdout_f.close()
        stderr_f.close()
    return proc


def _wait_for_immediate_exit(
    proc: subprocess.Popen,
    *,
    stdout_log: str,
    stderr_log: str,
    grace_sec: float,
) -> dict[str, Any] | None:
    deadline = time.monotonic() + grace_sec
    while time.monotonic() < deadline:
        code = proc.poll()
        if code is not None:
            log_tail = _tail_server_logs(stdout_log, stderr_log)
            detail = f'process exited early (code={code})'
            if log_tail:
                detail = f'{detail}\n{log_tail}'
            return {
                'ok': False,
                'pid': '',
                'error': detail,
                'stdout_log': stdout_log,
                'stderr_log': stderr_log,
            }
        time.sleep(0.05)
    return None


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
    db: str | None = None,
    port: int = 8080,
    env: dict[str, str] | None = None,
    _fake_start: Callable | None = None,
    _startup_grace_sec: float = _STARTUP_GRACE_SEC,
) -> dict[str, Any]:
    """Start CPS server detached from deploy terminal. Returns pid + log paths."""
    if _fake_start is not None:
        return _fake_start(repo=repo, env=env, db=db, port=port)
    app_dir = str(Path(repo) / 'app')
    py = sys.executable
    stdout_log, stderr_log = _server_log_paths(repo)
    run_env = _build_server_env(db_path=db, port=port, extra=env)
    try:
        proc = _popen_detached_server(
            [py, 'app.py'],
            cwd=app_dir,
            env=run_env,
            stdout_log=stdout_log,
            stderr_log=stderr_log,
        )
        early = _wait_for_immediate_exit(
            proc,
            stdout_log=stdout_log,
            stderr_log=stderr_log,
            grace_sec=_startup_grace_sec,
        )
        if early is not None:
            return early
        return {
            'ok': True,
            'pid': str(proc.pid),
            'stdout_log': stdout_log,
            'stderr_log': stderr_log,
        }
    except Exception as exc:
        return {'ok': False, 'pid': '', 'error': str(exc)}


def health_url(port: int = 8080, host: str = '127.0.0.1', path: str = _HEALTH_PATH) -> str:
    rel = path if path.startswith('/') else f'/{path}'
    return f'http://{host}:{port}{rel}'


def _process_alive(pid: str) -> bool:
    if not pid or not str(pid).isdigit():
        return False
    if sys.platform == 'win32':
        try:
            proc = subprocess.run(
                ['tasklist', '/FI', f'PID eq {pid}', '/FO', 'CSV', '/NH'],
                capture_output=True, text=True, check=True,
            )
            return pid in proc.stdout
        except Exception:
            return False
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def _port_listening_pids(port: int) -> list[str]:
    pids: list[str] = []
    try:
        proc = subprocess.run(
            ['netstat', '-ano'],
            capture_output=True, text=True,
        )
        for line in proc.stdout.splitlines():
            if f':{port}' in line and 'LISTENING' in line:
                parts = line.split()
                if parts:
                    pids.append(parts[-1])
    except Exception:
        return []
    return list(dict.fromkeys(pids))


def _http_probe_no_redirect(url: str, timeout: float) -> dict[str, Any]:
    import urllib.error
    import urllib.request

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(url, method='GET')
    try:
        with opener.open(req, timeout=timeout) as resp:
            status = resp.status
            ok = status == 200
            return {
                'ok': ok,
                'status': status,
                'error': '' if ok else f'HTTP {status}',
            }
    except urllib.error.HTTPError as exc:
        return {'ok': False, 'status': exc.code, 'error': f'HTTP {exc.code}'}
    except Exception as exc:
        return {'ok': False, 'status': 0, 'error': str(exc)}


def health_check(
    url: str | None = None,
    *,
    port: int = 8080,
    expected_pid: str | None = None,
    stdout_log: str = '',
    stderr_log: str = '',
    _fake_health: Callable | None = None,
    _total_timeout_sec: float = _HEALTH_TOTAL_TIMEOUT_SEC,
    _poll_interval_sec: float = _HEALTH_POLL_INTERVAL_SEC,
) -> dict[str, Any]:
    """
    Readiness probe: only HTTP 200 on /giris is PASS (no redirect follow).
    Retries transient connection errors for up to 60s by default.
    """
    probe_url = url or health_url(port)
    if _fake_health is not None:
        return _fake_health(probe_url)

    deadline = time.monotonic() + _total_timeout_sec
    attempts = 0
    last: dict[str, Any] = {
        'ok': False,
        'status': 0,
        'error': 'health timeout',
        'url': probe_url,
        'attempts': 0,
    }

    while time.monotonic() < deadline:
        attempts += 1

        if expected_pid and not _process_alive(expected_pid):
            tail = _tail_server_logs(stdout_log, stderr_log)
            err = f'process {expected_pid} exited before health passed'
            if tail:
                err = f'{err}\n{tail}'
            return {
                'ok': False,
                'status': 0,
                'error': err,
                'url': probe_url,
                'attempts': attempts,
            }

        if expected_pid:
            owners = _port_listening_pids(port)
            if owners and expected_pid not in owners:
                return {
                    'ok': False,
                    'status': 0,
                    'error': (
                        f'port {port} owned by {owners}, expected pid {expected_pid}'
                    ),
                    'url': probe_url,
                    'attempts': attempts,
                }

        result = _http_probe_no_redirect(probe_url, _HEALTH_REQUEST_TIMEOUT_SEC)
        last = {
            **result,
            'url': probe_url,
            'attempts': attempts,
        }
        if result.get('ok'):
            return last

        status = int(result.get('status') or 0)
        if status in (302, 404, 500, 502, 503):
            return last

        time.sleep(_poll_interval_sec)

    last['attempts'] = attempts
    if not last.get('error'):
        last['error'] = f'health timeout after {_total_timeout_sec}s'
    return last


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
        report['DEPLOY_ALLOWED'] = 'NO'
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

    if pf.get('PARITY_BEFORE') != 'PASS':
        report['DEPLOY_ALLOWED'] = 'NO'
        report['DEPLOY_RESULT'] = 'BLOCKED'
        report['error'] = f'parity before blocked: {pf.get("PARITY_BEFORE")}'
        return report

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
    try:
        rel_contract = normalize_contract_relative_path(repo, contract_path_raw)
    except PreflightError as exc:
        report['error'] = str(exc)
        restore_db(backup_path, db)
        if target_commit != old_head:
            git_reset_hard(repo, old_head)
        report['ROLLBACK_APPLIED'] = 'YES'
        return report

    contract_path = str(Path(repo) / rel_contract)
    if not os.path.isfile(contract_path):
        report['error'] = f'contract not found after checkout: {contract_path}'
        restore_db(backup_path, db)
        if target_commit != old_head:
            git_reset_hard(repo, old_head)
        report['ROLLBACK_APPLIED'] = 'YES'
        return report

    contract_data = load_contract(contract_path)
    required = contract_data.get('required_migrations') or []

    if not required:
        report['MIGRATION_RESULT'] = 'SKIPPED_NO_MIGRATIONS'
    else:
        mig = run_migration_runner(
            repo=repo, db=db, contract=contract_path,
            expected_commit=target_commit,
            mode='apply', computer=platform.node(),
            allow_canonical=allow_canonical,
        )
        report['MIGRATION_RESULT'] = mig.get('MIGRATION_RESULT', '')
        if mig.get('RUNNER_RESULT') != 'PASS':
            report['error'] = f'migration failed: {mig.get("error")}'
            restore_db(backup_path, db)
            if target_commit != old_head:
                git_reset_hard(repo, old_head)
            report['ROLLBACK_APPLIED'] = 'YES'
            return report

    # ── SCHEMA PARITY AFTER ──────────────────────────────────────────────────
    manifest_module = manifest.get('module', '')
    if not required:
        parity_after = run_deploy_module_parity(
            contract_path=contract_path,
            db_path=db,
            manifest_module=manifest_module,
        )
    else:
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
    start_result = start_process(
        repo=repo, db=db, port=cps_port, _fake_start=_fake_start,
    )
    report['NEW_PID'] = start_result.get('pid', '')
    report['SERVER_STDOUT_LOG'] = start_result.get('stdout_log', '')
    report['SERVER_STDERR_LOG'] = start_result.get('stderr_log', '')
    if not start_result.get('ok'):
        report['error'] = f'process start failed: {start_result.get("error")}'
        # rollback
        restore_db(backup_path, db)
        if target_commit != old_head:
            git_reset_hard(repo, old_head)
        report['ROLLBACK_APPLIED'] = 'YES'
        return report

    # ── HEALTH CHECK ─────────────────────────────────────────────────────────
    health = health_check(
        port=cps_port,
        expected_pid=report['NEW_PID'],
        stdout_log=report.get('SERVER_STDOUT_LOG', ''),
        stderr_log=report.get('SERVER_STDERR_LOG', ''),
        _fake_health=_fake_health,
    )
    report['HEALTH_URL'] = health.get('url', health_url(cps_port))
    report['HEALTH_ATTEMPTS'] = health.get('attempts', 0)
    report['HEALTH_AFTER'] = 'PASS' if health.get('ok') else 'FAIL'
    if not health.get('ok'):
        # rollback
        stop_process(report['NEW_PID'], _fake_stop=_fake_stop)
        restore_db(backup_path, db)
        if target_commit != old_head:
            git_reset_hard(repo, old_head)
        rollback_start = start_process(
            repo=repo, db=db, port=cps_port, _fake_start=_fake_start,
        )
        rollback_health = health_check(
            port=cps_port,
            expected_pid=rollback_start.get('pid', ''),
            stdout_log=rollback_start.get('stdout_log', ''),
            stderr_log=rollback_start.get('stderr_log', ''),
            _fake_health=_fake_health,
        )
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
        'NEW_PID', 'HEALTH_URL', 'HEALTH_ATTEMPTS', 'HEALTH_AFTER', 'HEALTH_ROLLBACK',
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
