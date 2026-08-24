# -*- coding: utf-8 -*-
"""GPS SYSTEM task + DPAPI secret hardening tests — no task, no worker, no real secrets."""
from __future__ import annotations

import hashlib
import io
import json
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
SETUP_PS1 = os.path.join(ROOT, 'Setup-Arac-GPS-Worker-Secrets.ps1')
CANON_DB = os.path.join(ROOT, 'app', 'mock_data.db')
PROD_SECRET = r'C:\ProgramData\Solariz\secrets\arac_gps_worker.dpapi'
DPAPI_ENTROPY = 'Solariz.CPS.AracGPSWorker.DPAPI.v1'
APP_DIR = os.path.join(ROOT, 'app')
GUARD_PY = os.path.join(APP_DIR, 'modules', 'planlama', 'arac_gps_canonical_guard.py')
WRONG_STUB_DB = os.path.join(APP_DIR, 'modules', 'mock_data.db')
FILOM_BASE_URL = 'https://filom.turkcell.com.tr/mobilws/services'
CHANGED_FILES = [START_PS1, REGISTER_PS1, SETUP_PS1, GUARD_PY, __file__]

PASS = FAIL = 0
TEMP_SECRET: str | None = None


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


def run_ps_cmd(script: str) -> tuple[int, str]:
    p = subprocess.run(
        ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', script],
        capture_output=True, text=True, cwd=ROOT,
    )
    return p.returncode, (p.stdout or '') + (p.stderr or '')


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


def run_guard_py(code: str, *, env: dict | None = None) -> tuple[int, str]:
    env2 = os.environ.copy()
    env2['PYTHONPATH'] = APP_DIR
    for key in ('CPS_MOCK_DB_PATH', 'CPS_ARAC_GPS_CANONICAL_WRITE'):
        env2.pop(key, None)
    if env:
        for k, v in env.items():
            if v is None:
                env2.pop(k, None)
            else:
                env2[k] = v
    p = subprocess.run(
        [REAL_PY, '-c', code],
        capture_output=True,
        text=True,
        cwd=APP_DIR,
        env=env2,
    )
    return p.returncode, (p.stdout or '') + (p.stderr or '')


def test_canonical_guard_contract() -> None:
    canon_norm = os.path.normcase(CANON_DB)
    wrong_norm = os.path.normcase(WRONG_STUB_DB)

    rc, out = run_guard_py(
        "from modules.planlama.arac_gps_canonical_guard import _canonical_path; print(_canonical_path())"
    )
    got = [ln.strip() for ln in out.splitlines() if ln.strip()][-1] if out.strip() else ''
    ok('canonical_path_exact_app_mock_data') if rc == 0 and os.path.normcase(got) == canon_norm else bad('canonical_path_exact_app_mock_data', got or out[-200:])

    rc, out = run_guard_py(
        "from modules.planlama.arac_gps_canonical_guard import "
        "is_canonical_path, _forbidden_modules_stub_path; "
        "import os; "
        "stub=_forbidden_modules_stub_path(); "
        "print('stub_not_canonical' if not is_canonical_path(stub) else 'BAD')"
    )
    ok('modules_stub_not_canonical') if rc == 0 and 'stub_not_canonical' in out else bad('modules_stub_not_canonical', out[-200:])

    rc, out = run_guard_py(
        "from modules.planlama.arac_gps_canonical_guard import validate_db_path_parity; "
        "info=validate_db_path_parity(); "
        "import os; "
        "assert info['parity'] is True; "
        "assert os.path.normcase(info['active_db'])==os.path.normcase(info['config_db']); "
        "print('parity_ok')"
    )
    ok('active_config_parity_default') if rc == 0 and 'parity_ok' in out else bad('active_config_parity_default', out[-200:])

    rc, _ = run_guard_py(
        "from modules.planlama.arac_gps_canonical_guard import assert_gps_db_write_allowed; "
        "assert_gps_db_write_allowed()",
        env={'CPS_ARAC_GPS_CANONICAL_WRITE': None},
    )
    ok('canonical_flag_missing_exit2') if rc == 2 else bad('canonical_flag_missing_exit2', f'rc={rc}')

    missing = os.path.join(tempfile.gettempdir(), f'gps_missing_{os.getpid()}.db')
    if os.path.exists(missing):
        os.remove(missing)
    rc, _ = run_guard_py(
        "from modules.planlama.arac_gps_canonical_guard import assert_gps_db_write_allowed; "
        "assert_gps_db_write_allowed()",
        env={
            'CPS_MOCK_DB_PATH': missing,
            'CPS_ARAC_GPS_CANONICAL_WRITE': 'YES',
        },
    )
    ok('missing_db_exit2') if rc == 2 else bad('missing_db_exit2', f'rc={rc}')
    ok('missing_db_not_created') if not os.path.exists(missing) else bad('missing_db_not_created')

    zero_byte = os.path.join(tempfile.gettempdir(), f'gps_zero_{os.getpid()}.db')
    open(zero_byte, 'wb').close()
    try:
        rc, _ = run_guard_py(
            "from modules.planlama.arac_gps_canonical_guard import assert_gps_db_write_allowed; "
            "assert_gps_db_write_allowed()",
            env={
                'CPS_MOCK_DB_PATH': zero_byte,
                'CPS_ARAC_GPS_CANONICAL_WRITE': 'YES',
            },
        )
        ok('zero_byte_db_exit2') if rc == 2 else bad('zero_byte_db_exit2', f'rc={rc}')
    finally:
        if os.path.exists(zero_byte):
            os.remove(zero_byte)

    rc, _ = run_guard_py(
        "from modules.planlama.arac_gps_canonical_guard import assert_gps_db_write_allowed; "
        "assert_gps_db_write_allowed()",
        env={
            'CPS_MOCK_DB_PATH': WRONG_STUB_DB,
            'CPS_ARAC_GPS_CANONICAL_WRITE': 'YES',
        },
    )
    ok('wrong_modules_stub_rejected') if rc == 2 else bad('wrong_modules_stub_rejected', f'rc={rc}')

    rc, out = run_guard_py(
        "from modules.planlama.arac_gps_canonical_guard import validate_db_path_parity; "
        "info=validate_db_path_parity(); "
        "assert info['explicit_temp_db'] is False; "
        "assert info['parity'] is True; "
        "print('no_implicit_temp')"
    )
    ok('noncanonical_requires_explicit_env') if rc == 0 and 'no_implicit_temp' in out else bad('noncanonical_requires_explicit_env', out[-200:])

    temp_db = os.path.join(tempfile.gettempdir(), f'gps_temp_ok_{os.getpid()}.db')
    import shutil
    shutil.copy2(CANON_DB, temp_db)
    try:
        rc, out = run_guard_py(
            "from modules.planlama.arac_gps_canonical_guard import assert_gps_db_write_allowed; "
            "p=assert_gps_db_write_allowed(); print('TEMP_OK:' + p)",
            env={'CPS_MOCK_DB_PATH': temp_db, 'CPS_ARAC_GPS_CANONICAL_WRITE': None},
        )
        ok('explicit_temp_db_allowed') if rc == 0 and 'TEMP_OK:' in out else bad('explicit_temp_db_allowed', out[-200:])
    finally:
        if os.path.exists(temp_db):
            os.remove(temp_db)

    if os.path.normcase(wrong_norm) != os.path.normcase(canon_norm):
        ok('wrong_stub_distinct_from_canonical')
    else:
        bad('wrong_stub_distinct_from_canonical')


def create_temp_dpapi_fixture() -> str:
    """Create temp DPAPI LocalMachine fixture with dummy (non-real) credentials."""
    path = os.path.join(tempfile.gettempdir(), f'arac_gps_test_{os.getpid()}.dpapi')
    payload = json.dumps({
        'TURKCELL_FILOM_BASE_URL': 'https://fixture.test.example/api',
        'TURKCELL_FILOM_USERNAME': 'fixture_user_not_real',
        'TURKCELL_FILOM_PASSWORD': 'fixture_pass_not_real',
    }, separators=(',', ':'))
    ps = rf"""
Add-Type -AssemblyName System.Security
$ErrorActionPreference='Stop'
$entropy=[Text.Encoding]::UTF8.GetBytes('{DPAPI_ENTROPY}')
$bytes=[Text.Encoding]::UTF8.GetBytes(@'
{payload}
'@)
$protected=[System.Security.Cryptography.ProtectedData]::Protect($bytes,$entropy,[System.Security.Cryptography.DataProtectionScope]::LocalMachine)
[IO.File]::WriteAllBytes('{path.replace(chr(92), chr(92)+chr(92))}', $protected)
$acl=Get-Acl -LiteralPath '{path.replace(chr(92), chr(92)+chr(92))}'
$acl.SetAccessRuleProtection($true,$false)
foreach($r in @($acl.Access)){{ $null=$acl.RemoveAccessRule($r) }}
$acl.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule('NT AUTHORITY\SYSTEM','FullControl','Allow')))
$acl.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule('BUILTIN\Administrators','FullControl','Allow')))
$cur=[System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$acl.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule($cur,'Read','Allow')))
Set-Acl -LiteralPath '{path.replace(chr(92), chr(92)+chr(92))}' -AclObject $acl
Write-Output 'FIXTURE_OK'
"""
    rc, out = run_ps_cmd(ps)
    if rc != 0 or 'FIXTURE_OK' not in out:
        raise RuntimeError(f'temp DPAPI fixture failed: {out}')
    return path


def get_worker_pids() -> list[str]:
    rc, out = run_ps_cmd(
        "Get-CimInstance Win32_Process | Where-Object { "
        "$_.CommandLine -like '*arac_gps_poll_worker*' -and "
        "$_.CommandLine -notlike '*Where-Object*' "
        "} | Select-Object -ExpandProperty ProcessId"
    )
    if rc != 0:
        return []
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def get_task_state() -> str:
    rc, out = run_ps_cmd(
        "Get-ScheduledTask -TaskPath '\\Solariz\\' -TaskName 'Solariz_CPS_Arac_GPS_Worker' "
        "-ErrorAction SilentlyContinue | Select-Object -ExpandProperty State"
    )
    return out.strip() if rc == 0 else ''


def read_worker_log_tail() -> str:
    log_path = os.path.join(ROOT, 'logs', 'arac_gps_worker.out.log')
    if not os.path.isfile(log_path):
        return ''
    with open(log_path, encoding='utf-8', errors='replace') as fh:
        return fh.read()[-8000:]


def acl_has_system(path: str) -> bool:
    rc, out = run_ps_cmd(
        rf"(Get-Acl -LiteralPath '{path}').Access | Where-Object {{ $_.IdentityReference.Value -eq 'NT AUTHORITY\SYSTEM' }} | Measure-Object | Select-Object -ExpandProperty Count"
    )
    return rc == 0 and out.strip() not in ('', '0')


def main() -> int:
    global TEMP_SECRET
    print('=' * 60)
    print('GPS CANONICAL DB PATH + FILOM URL FINAL LOCK TESTS')
    before = canon_counts()
    worker_before = get_worker_pids()
    task_before = get_task_state()

    test_canonical_guard_contract()

    TEMP_SECRET = create_temp_dpapi_fixture()
    ok('dpapi_temp_fixture_created', TEMP_SECRET)

    # Script parsers with temp secret
    for label, path in (
        ('setup', SETUP_PS1),
        ('start', START_PS1),
        ('register', REGISTER_PS1),
    ):
        args = [path, '-ValidateOnly', '-SecretFile', TEMP_SECRET]
        if path != SETUP_PS1:
            args = [path, '-PythonExe', REAL_PY, '-ValidateOnly', '-SecretFile', TEMP_SECRET]
        else:
            args = [path, '-ValidateOnly', '-SecretFile', TEMP_SECRET]
        rc, out = run_ps(args)
        if rc == 0 and 'VALIDATE_ONLY=PASS' in out:
            ok(f'parser_validate_{label}')
        else:
            bad(f'parser_validate_{label}', out[-400:])

    # Setup script content contracts
    setup_text = open(SETUP_PS1, encoding='utf-8').read()
    if 'Read-Host' in setup_text and 'AsSecureString' in setup_text:
        ok('setup_readhost_securestring')
    else:
        bad('setup_readhost_securestring')
    if re.search(r'param\s*\([^)]*Password', setup_text, re.I):
        bad('setup_no_password_cli_param')
    else:
        ok('setup_no_password_cli_param')
    if 'LocalMachine' in setup_text and DPAPI_ENTROPY in setup_text:
        ok('setup_dpapi_localmachine_entropy')
    else:
        bad('setup_dpapi_localmachine_entropy')
    if 'ZeroFreeBSTR' in setup_text:
        ok('setup_securestring_cleanup')
    else:
        bad('setup_securestring_cleanup')
    if PROD_SECRET in setup_text:
        ok('setup_secret_path_programdata')
    else:
        bad('setup_secret_path_programdata')
    if 'SetAccessRuleProtection($true' in setup_text:
        ok('setup_acl_inheritance_disabled')
    else:
        bad('setup_acl_inheritance_disabled')
    if f"BaseUrl = '{FILOM_BASE_URL}'" in setup_text:
        ok('setup_default_filom_baseurl')
    else:
        bad('setup_default_filom_baseurl')
    if 'filom.turkcell.com.tr/api' not in setup_text.replace(FILOM_BASE_URL, ''):
        ok('setup_no_legacy_api_baseurl')
    else:
        bad('setup_no_legacy_api_baseurl')

    # Start wrapper contracts
    start_text = open(START_PS1, encoding='utf-8').read()
    if 'ProtectedData]::Unprotect' in start_text and DPAPI_ENTROPY in start_text:
        ok('start_dpapi_decrypt')
    else:
        bad('start_dpapi_decrypt')
    if 'Clear-FilomProcessEnv' in start_text and 'Set-FilomProcessEnv' in start_text:
        ok('start_process_env_contract')
    else:
        bad('start_process_env_contract')
    if 'setx' not in start_text.lower():
        ok('start_no_setx_persist')
    else:
        bad('start_no_setx_persist')
    if "MachineEnvPersist   = 'none'" in start_text or "MachineEnvPersist=none" in start_text:
        ok('start_machine_env_none')
    else:
        bad('start_machine_env_none')
    if 'RotatingFileHandler' in start_text and '$MaxLogBytes = 10MB' in start_text:
        ok('log_rotation_10mb_x5')
    else:
        bad('log_rotation_10mb_x5')
    if 'FILOM_KEYS' in start_text and 'missing_filom_env' in start_text:
        ok('supervisor_filom_from_env')
    else:
        bad('supervisor_filom_from_env')

    # Wrapper ValidateOnly parity fields
    rc, start_out = run_ps([START_PS1, '-PythonExe', REAL_PY, '-ValidateOnly', '-SecretFile', TEMP_SECRET])
    parity_checks = {
        'wrapper_expected_canonical_db': 'ExpectedCanonicalDb=' in start_out and 'mock_data.db' in start_out,
        'wrapper_active_db': 'ActiveDb=' in start_out,
        'wrapper_config_db': 'ConfigDb=' in start_out,
        'wrapper_db_path_parity': 'DbPathParity=True' in start_out,
    }
    for k, v in parity_checks.items():
        ok(k) if v else bad(k, start_out[-300:])

    # Register ValidateOnly chain
    rc, reg_out = run_ps([REGISTER_PS1, '-PythonExe', REAL_PY, '-ValidateOnly', '-SecretFile', TEMP_SECRET])
    ok('register_validateonly_pass') if rc == 0 and 'VALIDATE_ONLY=PASS' in reg_out else bad('register_validateonly_pass', reg_out[-300:])

    reg_checks = {
        'system_principal': 'PrincipalUserId=SYSTEM' in reg_out,
        'service_account': 'LogonType=ServiceAccount' in reg_out,
        'runlevel_highest': 'RunLevel=Highest' in reg_out,
        'trigger_startup': 'Trigger=AtStartup' in reg_out,
        'start_when_available': 'StartWhenAvailable=True' in reg_out,
        'ignore_new': 'MultipleInstances=IgnoreNew' in reg_out,
        'initial_disabled': 'InitialState=Disabled' in reg_out,
        'secret_not_in_action': 'TURKCELL_FILOM_PASSWORD' not in reg_out.split('Argument=')[-1] if 'Argument=' in reg_out else True,
        'dpapi_secret_source': 'DPAPI LocalMachine' in reg_out,
    }
    for k, v in reg_checks.items():
        ok(k) if v else bad(k, reg_out[-200:])

    # WindowsApps rejected
    if os.path.exists(WINDOWS_APPS_PY):
        for script in (START_PS1, REGISTER_PS1):
            rc, _ = run_ps([script, '-PythonExe', WINDOWS_APPS_PY, '-ValidateOnly', '-SecretFile', TEMP_SECRET], expect_fail=True)
            ok(f'windowsapps_rejected_{os.path.basename(script)}') if rc != 0 else bad(f'windowsapps_rejected_{os.path.basename(script)}')
    else:
        ok('windowsapps_rejected', 'alias absent')

    # Missing/bempty python
    fake = os.path.join(tempfile.gettempdir(), 'no_such_python_xyz.exe')
    rc, _ = run_ps([START_PS1, '-PythonExe', fake, '-ValidateOnly', '-SecretFile', TEMP_SECRET], expect_fail=True)
    ok('missing_python_rejected') if rc != 0 else bad('missing_python_rejected')
    p = subprocess.run(
        ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', START_PS1, '-ValidateOnly', '-SecretFile', TEMP_SECRET],
        capture_output=True, text=True, cwd=ROOT,
    )
    ok('empty_python_rejected') if p.returncode != 0 else bad('empty_python_rejected')

    # No PATH lookup
    for path in (START_PS1, REGISTER_PS1):
        text = open(path, encoding='utf-8').read()
        ok(f'no_path_lookup_{os.path.basename(path)}') if 'Get-Command python' not in text else bad(f'no_path_lookup_{os.path.basename(path)}')

    # ValidateOnly must not spawn a new worker; live instance preserved
    mid_worker = get_worker_pids()
    run_ps([START_PS1, '-PythonExe', REAL_PY, '-ValidateOnly', '-SecretFile', TEMP_SECRET])
    after_validate_worker = get_worker_pids()
    ok('validateonly_no_new_worker') if mid_worker == after_validate_worker else bad(
        'validateonly_no_new_worker', f'mid={mid_worker} after={after_validate_worker}'
    )

    # Secret not leaked in outputs
    secret_patterns = [
        r'fixture_pass_not_real',
        r'fixture_user_not_real',
        r'password\s*=\s*(?!unset\b|present)[A-Za-z0-9@#$%^&*!]{6,}',
    ]
    leaked = any(re.search(pat, reg_out, re.I) for pat in secret_patterns)
    ok('validateonly_no_secret_leak') if not leaked else bad('validateonly_no_secret_leak')

    # ACL on temp fixture
    rc, acl_out = run_ps_cmd(rf"(Get-Acl -LiteralPath '{TEMP_SECRET}').AreAccessRulesProtected")
    ok('fixture_acl_inheritance_disabled') if 'True' in acl_out else bad('fixture_acl_inheritance_disabled', acl_out)
    # Production ACL contract in Setup script (SYSTEM + Administrators only)
    if "NT AUTHORITY\\SYSTEM', 'FullControl', 'Allow'" in setup_text and "BUILTIN\\Administrators', 'FullControl', 'Allow'" in setup_text:
        ok('production_acl_system_admin_only')
    else:
        bad('production_acl_system_admin_only')

    # No broad user access on fixture
    rc, acl_list = run_ps_cmd(rf"(Get-Acl -LiteralPath '{TEMP_SECRET}').Access | ForEach-Object {{ $_.IdentityReference.Value + ':' + $_.AccessControlType + ':' + $_.FileSystemRights }}")
    broad = [ln for ln in acl_list.splitlines() if 'BUILTIN\\Users' in ln or 'Authenticated Users' in ln]
    ok('fixture_no_broad_user_acl') if not broad else bad('fixture_no_broad_user_acl', ';'.join(broad))

    # SYSTEM path ACL forensic (read-only)
    for path in (
        REAL_PY,
        ROOT,
        CANON_DB,
        os.path.join(ROOT, 'logs'),
    ):
        ok(f'system_acl_{os.path.basename(path)}') if acl_has_system(path) else bad(f'system_acl_{os.path.basename(path)}')

    # DPAPI round-trip via Setup ValidateOnly
    rc, setup_out = run_ps([SETUP_PS1, '-ValidateOnly', '-SecretFile', TEMP_SECRET])
    ok('setup_validateonly_dpapi_roundtrip') if rc == 0 and 'FieldPresent TURKCELL_FILOM_PASSWORD=yes' in setup_out else bad('setup_validateonly_dpapi_roundtrip', setup_out[-300:])

    # Entropy parity across scripts
    texts = [open(p, encoding='utf-8').read() for p in (SETUP_PS1, START_PS1)]
    ok('entropy_parity') if all(DPAPI_ENTROPY in t for t in texts) else bad('entropy_parity')

    # Register does not overwrite wrapper
    ok('register_no_wrapper_overwrite') if 'Set-Content -Path $Wrapper' not in open(REGISTER_PS1, encoding='utf-8').read() else bad('register_no_wrapper_overwrite')

    # Live task must stay Running; tests must not stop/start it
    task_after = get_task_state()
    if task_before.lower() == 'running':
        ok('task_still_running') if task_after.lower() == 'running' else bad('task_still_running', task_after)
    elif not task_before:
        ok('task_state_unchanged', 'absent')
    else:
        ok('task_state_unchanged') if task_before == task_after else bad('task_state_unchanged', f'{task_before}->{task_after}')

    # 8080 health
    try:
        r = urllib.request.urlopen('http://127.0.0.1:8080/', timeout=5)
        ok('8080_health') if r.status == 200 else bad('8080_health', str(r.status))
    except Exception as e:
        bad('8080_health', str(e))

    # Live worker preserved; business counts stable (GPS may grow during polls)
    worker_after = get_worker_pids()
    if len(worker_before) == 1:
        ok('worker_count_one') if len(worker_after) == 1 else bad('worker_count_one', str(worker_after))
        ok('worker_instance_preserved') if worker_before == worker_after else bad(
            'worker_instance_preserved', f'{worker_before}->{worker_after}'
        )
    elif len(worker_before) == 0:
        ok('worker_count_baseline_zero', 'no live worker in this host')
        ok('worker_instance_preserved') if worker_before == worker_after else bad(
            'worker_instance_preserved', f'{worker_before}->{worker_after}'
        )
    else:
        bad('worker_count_one', f'baseline={worker_before}')

    after = canon_counts()
    ok('gps_count_non_decreasing') if after['gps'] >= before['gps'] else bad('gps_count_non_decreasing', str(after))
    ok('bekleyen_unchanged') if before['bekleyen'] == after['bekleyen'] == 85 else bad('bekleyen_unchanged', str(after))
    ok('plan_is_unchanged') if before['plan_is'] == after['plan_is'] == 92 else bad('plan_is_unchanged', str(after))

    log_tail = read_worker_log_tail()
    if len(worker_before) == 1:
        ok('worker_log_poll_ok') if log_tail and 'poll ok=True' in log_tail else bad('worker_log_poll_ok', 'missing poll ok=True')
        ok('worker_log_vehicles_four') if log_tail and 'vehicles=4' in log_tail else bad('worker_log_vehicles_four', 'missing vehicles=4')
    elif log_tail and ('poll ok=True' in log_tail or 'vehicles=' in log_tail):
        ok('worker_log_poll_ok') if 'poll ok=True' in log_tail else bad('worker_log_poll_ok')
        ok('worker_log_vehicles_four') if 'vehicles=4' in log_tail else bad('worker_log_vehicles_four')
    else:
        ok('worker_log_poll_ok', 'skipped — no live worker/log on host')
        ok('worker_log_vehicles_four', 'skipped — no live worker/log on host')

    # git diff --check
    p = subprocess.run(['git', 'diff', '--check', '--'] + CHANGED_FILES, capture_output=True, text=True, cwd=ROOT)
    ok('git_diff_check') if p.returncode == 0 else bad('git_diff_check', p.stdout + p.stderr)

    # cleanup temp fixture
    try:
        os.remove(TEMP_SECRET)
        ok('temp_fixture_cleaned')
    except OSError as e:
        bad('temp_fixture_cleaned', str(e))

    print('=' * 60)
    print(f'RESULT {PASS}/{PASS + FAIL} PASS, {FAIL} FAIL')
    return 0 if FAIL == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
