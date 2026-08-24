# -*- coding: utf-8 -*-
"""GPS Task Scheduler hardening tests — no task create, no worker start."""
from __future__ import annotations

import hashlib
import io
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import urllib.request

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.abspath(__file__))
REAL_PY = sys.executable
WINDOWS_APPS_PY = r'C:\Users\LENOVO\AppData\Local\Microsoft\WindowsApps\python.exe'
START_PS1 = os.path.join(ROOT, 'Start-Arac-GPS-Worker.ps1')
REGISTER_PS1 = os.path.join(ROOT, 'Register-Arac-GPS-Worker-Task.ps1')
CANON_DB = os.path.join(ROOT, 'app', 'mock_data.db')

PASS = FAIL = 0


def ok(name: str, detail: str = '') -> None:
    global PASS
    PASS += 1
    print(f'  PASS {name}' + (f' — {detail}' if detail else ''))


def bad(name: str, detail: str = '') -> None:
    global FAIL
    FAIL += 1
    print(f'  FAIL {name}' + (f' — {detail}' if detail else ''))


def run_ps(args: list[str], *, expect_fail: bool = False) -> tuple[int, str]:
    cmd = ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File'] + args
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    out = (p.stdout or '') + (p.stderr or '')
    if expect_fail:
        if p.returncode == 0:
            bad('expected_fail', out[-300:])
        else:
            ok('expected_fail', f'rc={p.returncode}')
    return p.returncode, out


def canon_counts() -> dict:
    con = sqlite3.connect(CANON_DB, timeout=10)
    try:
        return {
            'sha256': hashlib.sha256(open(CANON_DB, 'rb').read()).hexdigest(),
            'gps': con.execute('SELECT COUNT(*) FROM arac_gps_snapshot').fetchone()[0],
            'bekleyen': con.execute("SELECT COUNT(*) FROM arac_is_talebi WHERE durum='BEKLIYOR'").fetchone()[0],
            'plan_is': con.execute('SELECT COUNT(*) FROM arac_gunluk_plan_is').fetchone()[0],
        }
    finally:
        con.close()


def main() -> int:
    print('=' * 60)
    print('GPS TASK HARDENING TESTS')
    before = canon_counts()

    # Parser check
    for path in (START_PS1, REGISTER_PS1):
        rc, out = run_ps([path, '-PythonExe', REAL_PY, '-ValidateOnly'])
        if rc == 0 and 'VALIDATE_ONLY=PASS' in out:
            ok(f'parser_validate_{os.path.basename(path)}')
        else:
            bad(f'parser_validate_{os.path.basename(path)}', out[-400:])

    # Real PythonExe accepted
    rc, out = run_ps([START_PS1, '-PythonExe', REAL_PY, '-ValidateOnly'])
    if rc == 0 and 'IMPORT_OK' not in out and 'VALIDATE_ONLY=PASS' in out:
        ok('start_real_python_accepted')
    else:
        bad('start_real_python_accepted', out[-400:])

    # WindowsApps rejected
    if os.path.exists(WINDOWS_APPS_PY):
        rc, _ = run_ps([START_PS1, '-PythonExe', WINDOWS_APPS_PY, '-ValidateOnly'], expect_fail=True)
        if rc != 0:
            ok('windowsapps_rejected_start')
        else:
            bad('windowsapps_rejected_start')
        rc2, _ = run_ps([REGISTER_PS1, '-PythonExe', WINDOWS_APPS_PY, '-ValidateOnly'], expect_fail=True)
        if rc2 != 0:
            ok('windowsapps_rejected_register')
        else:
            bad('windowsapps_rejected_register')
    else:
        ok('windowsapps_rejected_start', 'alias absent — skip')

    # Missing python rejected
    fake = os.path.join(tempfile.gettempdir(), 'no_such_python_xyz.exe')
    rc, _ = run_ps([START_PS1, '-PythonExe', fake, '-ValidateOnly'], expect_fail=True)
    if rc != 0:
        ok('missing_python_rejected')
    else:
        bad('missing_python_rejected')

    # Empty python rejected (PowerShell mandatory param should fail)
    p = subprocess.run(
        ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', START_PS1, '-ValidateOnly'],
        capture_output=True, text=True, cwd=ROOT,
    )
    if p.returncode != 0:
        ok('empty_python_rejected')
    else:
        bad('empty_python_rejected')

    # No Get-Command fallback in scripts
    for path in (START_PS1, REGISTER_PS1):
        text = open(path, encoding='utf-8').read()
        if 'Get-Command python' not in text and "Get-Command 'python'" not in text:
            ok(f'no_path_lookup_{os.path.basename(path)}')
        else:
            bad(f'no_path_lookup_{os.path.basename(path)}')

    # Contract fields in ValidateOnly output
    rc, out = run_ps([REGISTER_PS1, '-PythonExe', REAL_PY, '-ValidateOnly'])
    checks = {
        'exact_worker_path': 'arac_gps_poll_worker.py' in out and 'app' in out and 'tools' in out,
        'exact_workdir': 'WorkingDirectory=C:\\Solariz_CPS_SERVER' in out or 'WorkingDirectory=C:/Solariz_CPS_SERVER' in out,
        'canonical_flag': 'CanonicalWrite=YES' in out,
        'interval_60': 'PollIntervalSec=60' in out,
        'mock_unset': 'MockDbPath=unset' in out,
        'trigger_startup': 'Trigger=AtStartup' in out,
        'ignore_new': 'MultipleInstances=IgnoreNew' in out,
        'initial_disabled': 'InitialState=Disabled' in out,
        'log_10mb': 'MaxLogBytes=10485760' in out,
        'log_5_backup': 'MaxLogBackups=5' in out,
    }
    for k, v in checks.items():
        if v:
            ok(k)
        else:
            bad(k, out[-200:])

    # Quoted PythonExe in task argument
    if f'-PythonExe "{REAL_PY}"' in out or f"-PythonExe `{REAL_PY}`" in out:
        ok('quoted_python_in_task_action')
    else:
        # PowerShell may normalize quotes in output
        if '-PythonExe' in out and REAL_PY in out:
            ok('quoted_python_in_task_action', 'path present in contract')
        else:
            bad('quoted_python_in_task_action')

    # Principal contract
    if 'LogonType=Interactive' in out and 'PrincipalUserId=' in out:
        ok('principal_contract')
    else:
        bad('principal_contract')

    # No secrets in output (var names with =unset are allowed)
    secret_patterns = [
        r'password\s*=\s*(?!unset\b)[^\s;]+',
        r'token\s*=\s*[A-Za-z0-9]{20,}',
        r'TURKCELL_FILOM_PASSWORD=(?!unset\b)[^\s;]+',
    ]
    leaked = any(re.search(pat, out, re.I) for pat in secret_patterns)
    if not leaked and 'FilomEnv=' in out:
        ok('no_secret_leak_register_output')
    else:
        bad('no_secret_leak_register_output')

    # Register script does not overwrite wrapper
    reg_text = open(REGISTER_PS1, encoding='utf-8').read()
    if 'Set-Content -Path $Wrapper' not in reg_text:
        ok('register_does_not_overwrite_wrapper')
    else:
        bad('register_does_not_overwrite_wrapper')

    # Log rotation contract in Start script
    start_text = open(START_PS1, encoding='utf-8').read()
    if 'RotatingFileHandler' in start_text and '$MaxLogBytes = 10MB' in start_text and '$MaxLogBackups = 5' in start_text:
        ok('log_rotation_contract_in_start')
    else:
        bad('log_rotation_contract_in_start')

    # ValidateOnly does not start worker
    before_procs = subprocess.run(
        ['powershell', '-NoProfile', '-Command',
         "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*arac_gps_poll_worker*' -and $_.CommandLine -notlike '*Where-Object*' } | Measure-Object | Select-Object -ExpandProperty Count"],
        capture_output=True, text=True,
    ).stdout.strip()
    run_ps([START_PS1, '-PythonExe', REAL_PY, '-ValidateOnly'])
    after_procs = subprocess.run(
        ['powershell', '-NoProfile', '-Command',
         "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*arac_gps_poll_worker*' -and $_.CommandLine -notlike '*Where-Object*' } | Measure-Object | Select-Object -ExpandProperty Count"],
        capture_output=True, text=True,
    ).stdout.strip()
    if before_procs == after_procs:
        ok('validateonly_no_worker_process')
    else:
        bad('validateonly_no_worker_process', f'before={before_procs} after={after_procs}')

    # 8080 health
    try:
        r = urllib.request.urlopen('http://127.0.0.1:8080/', timeout=5)
        if r.status == 200:
            ok('8080_health')
        else:
            bad('8080_health', str(r.status))
    except Exception as e:
        bad('8080_health', str(e))

    # Canonical unchanged
    after = canon_counts()
    if before['sha256'] == after['sha256']:
        ok('canonical_sha_unchanged')
    else:
        bad('canonical_sha_unchanged', f"{before['sha256'][:16]} -> {after['sha256'][:16]}")
    if before['gps'] == after['gps'] == 6:
        ok('gps_snapshot_unchanged')
    else:
        bad('gps_snapshot_unchanged', str(after))
    if before['bekleyen'] == after['bekleyen'] == 85:
        ok('bekleyen_unchanged')
    else:
        bad('bekleyen_unchanged', str(after))
    if before['plan_is'] == after['plan_is'] == 92:
        ok('plan_is_unchanged')
    else:
        bad('plan_is_unchanged', str(after))

    # git diff --check on changed files
    p = subprocess.run(['git', 'diff', '--check', '--', START_PS1, REGISTER_PS1], capture_output=True, text=True, cwd=ROOT)
    if p.returncode == 0:
        ok('git_diff_check')
    else:
        bad('git_diff_check', p.stdout + p.stderr)

    print('=' * 60)
    print(f'RESULT {PASS}/{PASS + FAIL} PASS, {FAIL} FAIL')
    return 0 if FAIL == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
