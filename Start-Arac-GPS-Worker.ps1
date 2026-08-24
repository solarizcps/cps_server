#Requires -Version 5.1
<#
.SYNOPSIS
  Start Araç GPS poll worker with DPAPI Filom secrets and bounded log rotation.

.PARAMETER PythonExe
  Exact path to real python.exe (WindowsApps alias rejected).

.PARAMETER ValidateOnly
  Preflight checks only — no worker start, no DB writes.

.PARAMETER SecretFile
  Override DPAPI secret path (testing only).
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$PythonExe,

    [switch]$ValidateOnly,

    [string]$SecretFile = 'C:\ProgramData\Solariz\secrets\arac_gps_worker.dpapi'
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Security

$Root = 'C:\Solariz_CPS_SERVER'
$AppDir = Join-Path $Root 'app'
$Worker = Join-Path $AppDir 'tools\arac_gps_poll_worker.py'
$LogDir = Join-Path $Root 'logs'
$OutLog = Join-Path $LogDir 'arac_gps_worker.out.log'
$ErrLog = Join-Path $LogDir 'arac_gps_worker.err.log'
$MaxLogBytes = 10MB
$MaxLogBackups = 5
$Script:DpapiEntropy = [System.Text.Encoding]::UTF8.GetBytes('Solariz.CPS.AracGPSWorker.DPAPI.v1')
$Script:ProductionSecretFile = 'C:\ProgramData\Solariz\secrets\arac_gps_worker.dpapi'
$Script:FilomFieldNames = @(
    'TURKCELL_FILOM_BASE_URL',
    'TURKCELL_FILOM_USERNAME',
    'TURKCELL_FILOM_PASSWORD'
)

function Test-WindowsAppsPythonAlias {
    param([string]$Path)
    $norm = ($Path -replace '\\', '/').ToLowerInvariant()
    return ($norm -match '/windowsapps/') -or ($norm -match '/microsoft/windowsapps/')
}

function Resolve-RealPythonExe {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) {
        throw 'PythonExe is required — PATH lookup and py launcher are not allowed.'
    }
    if (Test-WindowsAppsPythonAlias -Path $Path) {
        throw "WindowsApps python alias rejected: $Path"
    }
    $resolved = (Resolve-Path -LiteralPath $Path -ErrorAction Stop).Path
    if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) {
        throw "PythonExe is not a file: $resolved"
    }
    if ($resolved -match '\\WindowsApps\\') {
        throw "Resolved PythonExe is WindowsApps alias: $resolved"
    }
    return $resolved
}

function Get-SecretFileAclReport {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return [ordered]@{
            Exists              = $false
            InheritanceDisabled = $false
            SystemFullControl   = $false
            AdminFullControl    = $false
            OtherAccess         = @()
        }
    }
    $acl = Get-Acl -LiteralPath $Path
    $systemOk = $false
    $adminOk = $false
    $disallowed = @()
    $ignoredMeta = @('CREATOR OWNER', 'NT AUTHORITY\CREATOR OWNER')
    foreach ($r in $acl.Access) {
        if ($r.AccessControlType -ne 'Allow') { continue }
        $id = $r.IdentityReference.Value
        $isFull = ($r.FileSystemRights -band [System.Security.AccessControl.FileSystemRights]::FullControl) -eq `
            [System.Security.AccessControl.FileSystemRights]::FullControl
        if ($id -eq 'NT AUTHORITY\SYSTEM') {
            if ($isFull) { $systemOk = $true }
        }
        elseif ($id -eq 'BUILTIN\Administrators') {
            if ($isFull) { $adminOk = $true }
        }
        elseif ($ignoredMeta -notcontains $id) {
            $disallowed += $id
        }
    }
    return [ordered]@{
        Exists              = $true
        InheritanceDisabled = $acl.AreAccessRulesProtected
        SystemFullControl   = $systemOk
        AdminFullControl    = $adminOk
        OtherAccess         = $disallowed
    }
}

function Test-SecretFileAclContract {
    param(
        [hashtable]$Report,
        [string]$Path
    )
    if (-not $Report.InheritanceDisabled) {
        throw 'Secret file ACL: inheritance must be disabled.'
    }
    if (-not $Report.SystemFullControl) {
        throw 'Secret file ACL: SYSTEM FullControl required.'
    }
    $isProduction = ($Path -eq $Script:ProductionSecretFile)
    if ($isProduction) {
        if (-not $Report.AdminFullControl) {
            throw 'Secret file ACL: Administrators FullControl required.'
        }
        if ($Report.OtherAccess.Count -gt 0) {
            throw ('Unexpected ACL identities on secret file: {0}' -f ($Report.OtherAccess -join ', '))
        }
    }
    elseif ($Report.OtherAccess.Count -gt 0) {
        Write-Verbose ('Non-production secret path allows extra ACL identities: {0}' -f ($Report.OtherAccess -join ', '))
    }
}

function Unprotect-FilomSecrets {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Secret file missing: $Path"
    }
    $acl = Get-SecretFileAclReport -Path $Path
    Test-SecretFileAclContract -Report $acl -Path $Path
    $protected = [System.IO.File]::ReadAllBytes($Path)
    $plainBytes = [System.Security.Cryptography.ProtectedData]::Unprotect(
        $protected,
        $Script:DpapiEntropy,
        [System.Security.Cryptography.DataProtectionScope]::LocalMachine
    )
    try {
        $json = [System.Text.Encoding]::UTF8.GetString($plainBytes)
        $obj = $json | ConvertFrom-Json
        return [ordered]@{
            TURKCELL_FILOM_BASE_URL = [string]$obj.TURKCELL_FILOM_BASE_URL
            TURKCELL_FILOM_USERNAME = [string]$obj.TURKCELL_FILOM_USERNAME
            TURKCELL_FILOM_PASSWORD = [string]$obj.TURKCELL_FILOM_PASSWORD
        }
    }
    finally {
        if ($plainBytes) { [Array]::Clear($plainBytes, 0, $plainBytes.Length) }
    }
}

function Test-FilomSecretsReady {
    param([string]$Path)
    $secrets = Unprotect-FilomSecrets -Path $Path
    $missing = @()
    foreach ($n in $Script:FilomFieldNames) {
        if (-not $secrets.$n -or [string]::IsNullOrWhiteSpace([string]$secrets.$n)) {
            $missing += $n
        }
    }
    if ($missing.Count -gt 0) {
        throw ("Secret payload incomplete: {0}" -f ($missing -join ', '))
    }
    return $secrets
}

function Set-FilomProcessEnv {
    param($Secrets)
    $env:TURKCELL_FILOM_BASE_URL = [string]$Secrets.TURKCELL_FILOM_BASE_URL
    $env:TURKCELL_FILOM_USERNAME = [string]$Secrets.TURKCELL_FILOM_USERNAME
    $env:TURKCELL_FILOM_PASSWORD = [string]$Secrets.TURKCELL_FILOM_PASSWORD
}

function Clear-FilomProcessEnv {
    Remove-Item -Path Env:TURKCELL_FILOM_BASE_URL -ErrorAction SilentlyContinue
    Remove-Item -Path Env:TURKCELL_FILOM_USERNAME -ErrorAction SilentlyContinue
    Remove-Item -Path Env:TURKCELL_FILOM_PASSWORD -ErrorAction SilentlyContinue
}

function Test-PythonExeContract {
    param([string]$ResolvedPython)
    $probe = @"
import sys, os
sys.path.insert(0, r'$AppDir')
os.chdir(r'$AppDir')
expected = os.path.normcase(r'$ResolvedPython')
actual = os.path.normcase(sys.executable)
if expected != actual:
    raise SystemExit('sys.executable mismatch: ' + actual)
import modules.planlama.arac_gps_canonical_guard  # noqa: F401
import modules.planlama.arac_gps_poll_service  # noqa: F401
print('IMPORT_OK')
"@
    $tmp = Join-Path $env:TEMP ("arac_gps_py_probe_{0}.py" -f $PID)
    Set-Content -LiteralPath $tmp -Value $probe -Encoding UTF8
    try {
        $out = & $ResolvedPython $tmp 2>&1
        if ($LASTEXITCODE -ne 0 -or ($out -notmatch 'IMPORT_OK')) {
            throw "Python import smoke failed: $out"
        }
    }
    finally {
        Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
    }
}

function Test-DbPathParity {
    param([string]$ResolvedPython)
    $canonicalDb = Join-Path $AppDir 'mock_data.db'
    $probe = @"
import json, os, sys
sys.path.insert(0, r'$AppDir')
os.chdir(r'$AppDir')
os.environ.pop('CPS_MOCK_DB_PATH', None)
os.environ['CPS_ARAC_GPS_CANONICAL_WRITE'] = 'YES'
from modules.planlama.arac_gps_canonical_guard import (
    validate_db_path_parity,
    assert_gps_db_write_allowed,
    _forbidden_modules_stub_path,
    _canonical_path,
)
info = validate_db_path_parity()
forbidden = _forbidden_modules_stub_path()
expected = _canonical_path()
if info['parity'] != True:
    raise SystemExit('db_path_parity=false')
if os.path.normcase(info['expected_canonical']) != os.path.normcase(r'$canonicalDb'):
    raise SystemExit('expected_canonical_mismatch')
if os.path.normcase(info['active_db']) != os.path.normcase(info['config_db']):
    raise SystemExit('active_config_mismatch')
if os.path.normcase(forbidden) == os.path.normcase(info['expected_canonical']):
    raise SystemExit('forbidden_equals_canonical')
assert_gps_db_write_allowed()
print('ExpectedCanonicalDb=' + info['expected_canonical'])
print('ActiveDb=' + info['active_db'])
print('ConfigDb=' + info['config_db'])
print('DbPathParity=True')
print('DB_PARITY_OK')
"@
    $tmp = Join-Path $env:TEMP ("arac_gps_db_parity_probe_{0}.py" -f $PID)
    Set-Content -LiteralPath $tmp -Value $probe -Encoding UTF8
    try {
        $out = & $ResolvedPython $tmp 2>&1 | Out-String
        if ($LASTEXITCODE -ne 0 -or ($out -notmatch 'DB_PARITY_OK')) {
            throw "DB path parity check failed: $out"
        }
        return $out
    }
    finally {
        Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
    }
}

function Test-LogDirectoryWritable {
    if (-not (Test-Path -LiteralPath $LogDir)) {
        New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
    }
    $probe = Join-Path $LogDir ('._write_probe_{0}' -f $PID)
    try {
        Set-Content -LiteralPath $probe -Value 'ok' -Encoding ASCII
        Remove-Item -LiteralPath $probe -Force
    }
    catch {
        throw "Log directory not writable: $LogDir"
    }
}

function New-LogSupervisorScript {
    param(
        [string]$ResolvedPython,
        [string]$WorkerPath,
        [string]$OutPath,
        [string]$ErrPath,
        [int]$MaxBytes,
        [int]$BackupCount
    )
    $supervisor = @"
# -*- coding: utf-8 -*-
"""Runtime GPS worker log supervisor — generated by Start-Arac-GPS-Worker.ps1"""
from __future__ import annotations

import logging
import logging.handlers
import os
import subprocess
import threading

WORKER = r'$WorkerPath'
PYTHON = r'$ResolvedPython'
OUT_LOG = r'$OutPath'
ERR_LOG = r'$ErrPath'
APP_DIR = r'$AppDir'
MAX_BYTES = $MaxBytes
BACKUP_COUNT = $BackupCount
FILOM_KEYS = (
    'TURKCELL_FILOM_BASE_URL',
    'TURKCELL_FILOM_USERNAME',
    'TURKCELL_FILOM_PASSWORD',
)


def _handler(path: str) -> logging.Handler:
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    h = logging.handlers.RotatingFileHandler(
        path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding='utf-8',
    )
    h.setFormatter(logging.Formatter('%(message)s'))
    return h


def _pump(stream, logger: logging.Logger) -> None:
    for line in iter(stream.readline, ''):
        if not line:
            break
        logger.info(line.rstrip('\r\n'))
    stream.close()


def main() -> int:
    env = os.environ.copy()
    env['CPS_ARAC_GPS_CANONICAL_WRITE'] = 'YES'
    env['ARAC_GPS_POLL_INTERVAL_SEC'] = '60'
    env.pop('CPS_MOCK_DB_PATH', None)
    for key in FILOM_KEYS:
        if key not in env or not env[key]:
            raise SystemExit('missing_filom_env=' + key)
    out_logger = logging.getLogger('gps_out')
    out_logger.setLevel(logging.INFO)
    out_logger.handlers.clear()
    out_logger.addHandler(_handler(OUT_LOG))
    err_logger = logging.getLogger('gps_err')
    err_logger.setLevel(logging.INFO)
    err_logger.handlers.clear()
    err_logger.addHandler(_handler(ERR_LOG))
    proc = subprocess.Popen(
        [PYTHON, '-u', WORKER],
        cwd=APP_DIR,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    t_out = threading.Thread(target=_pump, args=(proc.stdout, out_logger), daemon=True)
    t_err = threading.Thread(target=_pump, args=(proc.stderr, err_logger), daemon=True)
    t_out.start()
    t_err.start()
    return proc.wait()


if __name__ == '__main__':
    raise SystemExit(main())
"@
    $path = Join-Path $env:TEMP ("arac_gps_log_supervisor_{0}.py" -f $PID)
    Set-Content -LiteralPath $path -Value $supervisor -Encoding UTF8
    return $path
}

# --- Main ---
$resolvedPy = Resolve-RealPythonExe -Path $PythonExe

if (-not (Test-Path -LiteralPath $AppDir -PathType Container)) {
    throw "AppDir missing: $AppDir"
}
if (-not (Test-Path -LiteralPath $Worker -PathType Leaf)) {
    throw "Worker missing: $Worker"
}

Test-PythonExeContract -ResolvedPython $resolvedPy
$dbParityOut = Test-DbPathParity -ResolvedPython $resolvedPy
Test-LogDirectoryWritable

$aclReport = Get-SecretFileAclReport -Path $SecretFile
$secrets = Test-FilomSecretsReady -Path $SecretFile

$fieldStatus = @()
foreach ($n in $Script:FilomFieldNames) {
    $fieldStatus += ("{0}=present" -f $n)
}

$expectedCanonicalDb = ($dbParityOut -split "`n" | Where-Object { $_ -match '^ExpectedCanonicalDb=' } | Select-Object -First 1) -replace '^ExpectedCanonicalDb=', ''
$activeDb = ($dbParityOut -split "`n" | Where-Object { $_ -match '^ActiveDb=' } | Select-Object -First 1) -replace '^ActiveDb=', ''
$configDb = ($dbParityOut -split "`n" | Where-Object { $_ -match '^ConfigDb=' } | Select-Object -First 1) -replace '^ConfigDb=', ''
$dbPathParity = ($dbParityOut -match 'DbPathParity=True')

$report = [ordered]@{
    PythonExe           = $resolvedPy
    AppDir              = $AppDir
    Worker              = $Worker
    ExpectedCanonicalDb = $expectedCanonicalDb
    ActiveDb            = $activeDb
    ConfigDb            = $configDb
    DbPathParity        = $dbPathParity
    SecretFile          = $SecretFile
    SecretFileExists    = $aclReport.Exists
    SecretAclOk         = ($aclReport.InheritanceDisabled -and $aclReport.SystemFullControl -and (
        ($SecretFile -eq $Script:ProductionSecretFile -and $aclReport.AdminFullControl -and $aclReport.OtherAccess.Count -eq 0) -or
        ($SecretFile -ne $Script:ProductionSecretFile)
    ))
    FilomSecretSource   = 'DPAPI LocalMachine'
    FilomFields         = ($fieldStatus -join ', ')
    OutLog              = $OutLog
    ErrLog              = $ErrLog
    MaxLogBytes         = $MaxLogBytes
    MaxLogBackups       = $MaxLogBackups
    CanonicalWrite      = 'YES (process scope via supervisor env)'
    PollIntervalSec     = 60
    MockDbPath          = 'unset'
    MachineEnvPersist   = 'none'
    WorkerSingleLock    = 'arac_gps_poll_worker.lock (worker process)'
}

foreach ($pair in $report.GetEnumerator()) {
    Write-Host ("VALIDATE {0}={1}" -f $pair.Key, $pair.Value)
}

if ($ValidateOnly) {
    if (-not $dbPathParity) {
        throw 'ValidateOnly failed: DbPathParity=False'
    }
    Write-Host 'VALIDATE_ONLY=PASS'
    exit 0
}

$supervisorPy = New-LogSupervisorScript -ResolvedPython $resolvedPy -WorkerPath $Worker `
    -OutPath $OutLog -ErrPath $ErrLog -MaxBytes $MaxLogBytes -BackupCount $MaxLogBackups

Set-FilomProcessEnv -Secrets $secrets
$secrets = $null
try {
    Write-Host "Starting GPS worker supervisor via $resolvedPy"
    Write-Host "Supervisor: $supervisorPy"
    & $resolvedPy $supervisorPy
    exit $LASTEXITCODE
}
finally {
    Clear-FilomProcessEnv
}
