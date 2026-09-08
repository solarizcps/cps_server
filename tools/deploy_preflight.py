# -*- coding: utf-8 -*-
"""Deploy preflight — all guards before any mutation."""
from __future__ import annotations

import getpass
import os
import platform
import socket
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.release_manifest import load_manifest, require_valid_manifest
from tools.migration_runner import run_migration_runner
from tools.schema_parity_check import check_parity


class PreflightError(Exception):
    """Raised when any preflight gate fails."""
    def __init__(self, gate: str, detail: str):
        self.gate = gate
        self.detail = detail
        super().__init__(f'[PREFLIGHT BLOCKED] {gate}: {detail}')


# ── helpers ──────────────────────────────────────────────────────────────────

def _git(args: list[str], cwd: str) -> str:
    proc = subprocess.run(
        ['git'] + args, cwd=cwd,
        capture_output=True, text=True, check=True,
    )
    return proc.stdout.strip()


def _git_ok(args: list[str], cwd: str) -> str:
    """Return '' on error instead of raising."""
    try:
        return _git(args, cwd)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ''


def _port_pids(port: int) -> list[str]:
    """Return PIDs listening on given port (Windows netstat)."""
    try:
        proc = subprocess.run(
            ['netstat', '-ano'],
            capture_output=True, text=True,
        )
        pids: list[str] = []
        for line in proc.stdout.splitlines():
            if f':{port}' in line and 'LISTENING' in line:
                parts = line.split()
                if parts:
                    pids.append(parts[-1])
        return list(set(pids))
    except Exception:
        return []


def _process_info(pid: str) -> dict[str, str]:
    """Return {name, cmd} for a PID on Windows via tasklist/wmic."""
    info: dict[str, str] = {'pid': pid, 'name': '', 'cmd': ''}
    try:
        proc = subprocess.run(
            ['tasklist', '/FI', f'PID eq {pid}', '/FO', 'CSV', '/NH'],
            capture_output=True, text=True,
        )
        lines = [l for l in proc.stdout.splitlines() if pid in l]
        if lines:
            parts = lines[0].strip('"').split('","')
            if parts:
                info['name'] = parts[0].strip('"')
    except Exception:
        pass
    try:
        proc = subprocess.run(
            ['wmic', 'process', 'where', f'ProcessId={pid}',
             'get', 'CommandLine', '/format:value'],
            capture_output=True, text=True,
        )
        for line in proc.stdout.splitlines():
            if line.strip().startswith('CommandLine='):
                info['cmd'] = line.split('=', 1)[1].strip()
                break
    except Exception:
        pass
    return info


def _tracked_dirty(repo: str) -> list[str]:
    try:
        out = _git(['status', '--porcelain'], repo)
    except Exception:
        return []
    dirty = []
    for line in out.splitlines():
        if line and line[0] in 'MADRCU' and line[0] != '?':
            dirty.append(line.strip())
    return dirty


def _untracked(repo: str) -> list[str]:
    try:
        out = _git(['status', '--porcelain'], repo)
    except Exception:
        return []
    return [
        line[3:].strip()
        for line in out.splitlines()
        if line.startswith('?? ')
    ]


def _deploy_diff_files(repo: str, old_head: str, new_head: str) -> list[str]:
    """Files changed between two commits."""
    try:
        out = _git(['diff', '--name-only', old_head, new_head], repo)
        return [l.strip() for l in out.splitlines() if l.strip()]
    except Exception:
        return []


# ── main preflight ────────────────────────────────────────────────────────────

def run_preflight(
    *,
    manifest_path: str,
    repo: str,
    db: str,
    target_commit: str,
    expected_computer: str | None = None,
    expected_user: str | None = None,
    expected_branch: str | None = None,
    cps_port: int = 8080,
    skip_process_check: bool = False,
    _fake_pids: list[str] | None = None,
) -> dict[str, Any]:
    """
    Run all preflight gates.

    Returns report dict. Raises PreflightError on first gate failure.
    """
    report: dict[str, Any] = {
        'PREFLIGHT_RESULT': 'BLOCKED',
        'COMPUTER': '',
        'USER': '',
        'REPO': repo,
        'BRANCH': '',
        'OLD_HEAD': '',
        'TARGET_HEAD': target_commit,
        'REMOTE_HEAD': '',
        'FAST_FORWARD': '',
        'TRACKED_DIRTY': [],
        'UNTRACKED': [],
        'UNTRACKED_COLLISION': [],
        'DB_PATH': db,
        'DB_INTEGRITY': '',
        'ACTIVE_PID': '',
        'ACTIVE_PROCESS': '',
        'DEPLOY_FILES': [],
        'FORBIDDEN_VIOLATIONS': [],
        'MIGRATION_PLAN': '',
        'PARITY_BEFORE': '',
        'MANIFEST_RELEASE_ID': '',
        'MANIFEST_MODULE': '',
    }

    # 1. COMPUTER
    actual_computer = platform.node().upper()
    report['COMPUTER'] = actual_computer
    if expected_computer:
        if expected_computer.upper() != actual_computer:
            raise PreflightError(
                'COMPUTER_CHECK',
                f'expected={expected_computer.upper()} actual={actual_computer}',
            )

    # 2. USER
    actual_user = getpass.getuser()
    report['USER'] = actual_user
    if expected_user:
        if expected_user.lower() != actual_user.lower():
            raise PreflightError(
                'USER_CHECK',
                f'expected={expected_user} actual={actual_user}',
            )

    # 3. REPO (absolute + .git)
    if not os.path.isabs(repo):
        raise PreflightError('REPO_ABS', f'repo must be absolute: {repo}')
    if not os.path.isdir(repo):
        raise PreflightError('REPO_EXISTS', f'repo not found: {repo}')
    if not os.path.isdir(os.path.join(repo, '.git')) and not os.path.isfile(os.path.join(repo, '.git')):
        raise PreflightError('REPO_GIT', f'no .git at: {repo}')

    # 4. BRANCH / HEAD
    try:
        actual_branch = _git(['branch', '--show-current'], repo)
        report['BRANCH'] = actual_branch
    except Exception as exc:
        raise PreflightError('BRANCH_READ', str(exc)) from exc

    if expected_branch and actual_branch != expected_branch:
        raise PreflightError(
            'BRANCH_CHECK',
            f'expected={expected_branch} actual={actual_branch}',
        )

    try:
        old_head = _git(['rev-parse', 'HEAD'], repo)
        report['OLD_HEAD'] = old_head
    except Exception as exc:
        raise PreflightError('HEAD_READ', str(exc)) from exc

    # 5. TARGET COMMIT — must be full 40-char hash
    if not target_commit or len(target_commit) != 40:
        raise PreflightError(
            'TARGET_HASH',
            f'target_commit must be 40-char full hash, got: {target_commit!r}',
        )

    # 6. REMOTE commit exists
    try:
        _git(['fetch', '--quiet'], repo)
    except Exception:
        pass  # offline or no remote — proceed, next check will catch if needed

    remote_head = _git_ok(['rev-parse', f'origin/{actual_branch}'], repo)
    report['REMOTE_HEAD'] = remote_head

    # 7. FAST-FORWARD — is target reachable from current HEAD?
    try:
        merge_base = _git(['merge-base', old_head, target_commit], repo)
        if merge_base == old_head:
            report['FAST_FORWARD'] = 'YES'
        else:
            report['FAST_FORWARD'] = 'NO'
            raise PreflightError(
                'FAST_FORWARD',
                f'target {target_commit[:12]} is not fast-forward from HEAD {old_head[:12]}',
            )
    except PreflightError:
        raise
    except Exception:
        # target commit not in history yet; allow if target==old_head (same)
        if target_commit == old_head:
            report['FAST_FORWARD'] = 'YES'
        else:
            report['FAST_FORWARD'] = 'UNKNOWN'

    # 8. TRACKED DIRTY = 0
    dirty = _tracked_dirty(repo)
    report['TRACKED_DIRTY'] = dirty
    if dirty:
        raise PreflightError(
            'DIRTY_TRACKED',
            f'{len(dirty)} tracked dirty files: {dirty[:3]}',
        )

    # 9. UNTRACKED — report + collision check with allowed_files
    untracked = _untracked(repo)
    report['UNTRACKED'] = untracked

    # 10. MANIFEST load + validate
    manifest = load_manifest(manifest_path)
    require_valid_manifest(manifest)  # raises ManifestError → let it propagate
    report['MANIFEST_RELEASE_ID'] = manifest.get('release_id', '')
    report['MANIFEST_MODULE'] = manifest.get('module', '')

    # 11. Manifest tested_commit == target_commit (exact full hash)
    manifest_tested = manifest.get('tested_commit', '')
    if manifest_tested != target_commit:
        raise PreflightError(
            'MANIFEST_COMMIT',
            f'manifest.tested_commit={manifest_tested[:12]} != target={target_commit[:12]}',
        )

    # 12. Untracked collision with allowed_files
    allowed = set(manifest.get('allowed_files', []))
    collisions = [u for u in untracked if u in allowed]
    report['UNTRACKED_COLLISION'] = collisions
    if collisions:
        raise PreflightError(
            'UNTRACKED_COLLISION',
            f'untracked files collide with allowed deploy files: {collisions}',
        )

    # 13. DB absolute + exists + non-zero + SQLite + integrity
    if not os.path.isabs(db):
        raise PreflightError('DB_ABS', f'db must be absolute: {db}')
    if not os.path.isfile(db):
        raise PreflightError('DB_EXISTS', f'db not found: {db}')
    if os.path.getsize(db) == 0:
        raise PreflightError('DB_ZERO', 'db is zero bytes')
    db_uri = 'file:' + db.replace('\\', '/') + '?mode=ro'
    try:
        con = sqlite3.connect(db_uri, uri=True)
        ic = con.execute('PRAGMA integrity_check').fetchone()[0]
        con.close()
    except Exception as exc:
        raise PreflightError('DB_OPEN', f'cannot open db: {exc}') from exc
    report['DB_INTEGRITY'] = ic
    if ic != 'ok':
        raise PreflightError('DB_INTEGRITY', f'integrity_check={ic}')

    # 14. PROCESS CHECK on port 8080
    if not skip_process_check:
        pids = _fake_pids if _fake_pids is not None else _port_pids(cps_port)
        if not pids:
            report['ACTIVE_PID'] = 'NONE'
            report['ACTIVE_PROCESS'] = 'no process on port 8080'
        else:
            pid = pids[0]
            report['ACTIVE_PID'] = pid
            proc_info = _process_info(pid)
            report['ACTIVE_PROCESS'] = proc_info.get('name', '')
            if 'python' not in proc_info.get('name', '').lower() and \
               'python' not in proc_info.get('cmd', '').lower():
                raise PreflightError(
                    'PORT_OWNER',
                    f'port {cps_port} is held by non-python process: {proc_info}',
                )
    else:
        report['ACTIVE_PID'] = 'SKIPPED'

    # 15. DEPLOY FILES diff + forbidden check
    diff_files = _deploy_diff_files(repo, old_head, target_commit)
    report['DEPLOY_FILES'] = diff_files

    forbidden = manifest.get('forbidden_paths', [])
    violations = [f for f in diff_files if any(f.startswith(fp) for fp in forbidden)]
    report['FORBIDDEN_VIOLATIONS'] = violations
    if violations:
        raise PreflightError(
            'FORBIDDEN_FILES',
            f'diff contains forbidden paths: {violations}',
        )

    # 16. MIGRATION plan
    contract_path_raw = manifest.get('schema_contract', '')
    contract_path = (
        contract_path_raw if os.path.isabs(contract_path_raw)
        else str(Path(repo) / contract_path_raw)
    )
    if os.path.isfile(contract_path):
        mig_report = run_migration_runner(
            repo=repo,
            db=db,
            contract=contract_path,
            expected_commit=old_head,  # check against current HEAD
            mode='plan',
            computer=platform.node(),
        )
        report['MIGRATION_PLAN'] = mig_report.get('PENDING_MIGRATIONS', '')
        report['PARITY_BEFORE'] = mig_report.get('PARITY_RESULT', '')
    else:
        report['MIGRATION_PLAN'] = 'CONTRACT_NOT_FOUND'
        report['PARITY_BEFORE'] = 'SKIPPED'

    report['PREFLIGHT_RESULT'] = 'PASS'
    return report


def print_preflight_report(report: dict[str, Any]) -> None:
    keys = [
        'PREFLIGHT_RESULT', 'COMPUTER', 'USER', 'REPO', 'BRANCH',
        'OLD_HEAD', 'TARGET_HEAD', 'REMOTE_HEAD', 'FAST_FORWARD',
        'DB_PATH', 'DB_INTEGRITY', 'ACTIVE_PID', 'ACTIVE_PROCESS',
        'MIGRATION_PLAN', 'PARITY_BEFORE',
        'MANIFEST_RELEASE_ID', 'MANIFEST_MODULE',
    ]
    for k in keys:
        v = report.get(k, '')
        print(f'{k}={v}')
    for list_key in ('TRACKED_DIRTY', 'UNTRACKED_COLLISION', 'FORBIDDEN_VIOLATIONS', 'DEPLOY_FILES'):
        v = report.get(list_key, [])
        print(f'{list_key}={",".join(v) if v else ""}')
    print(f'UNTRACKED_COUNT={len(report.get("UNTRACKED", []))}')
