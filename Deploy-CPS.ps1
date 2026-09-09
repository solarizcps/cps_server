# Deploy-CPS.ps1
# Guarded CPS deploy wrapper — V1
# Default: PLAN/DRY-RUN only.
# Execute requires ALL confirmation parameters.
#
# USAGE (plan):
#   .\Deploy-CPS.ps1 -Manifest C:\...\manifest.json -Repo C:\...\repo -Db C:\...\app\mock_data.db -TargetCommit <40-char-hash>
#
# USAGE (execute):
#   .\Deploy-CPS.ps1 -Manifest ... -Repo ... -Db ... -TargetCommit <hash> `
#                    -Execute `
#                    -ConfirmRelease <release_id> `
#                    -ExpectedComputer <HOSTNAME> `
#                    -ExpectedHead <40-char-hash> `
#                    -AllowCanonical

[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [string]$Manifest,

    [Parameter(Mandatory=$true)]
    [string]$Repo,

    [Parameter(Mandatory=$true)]
    [string]$Db,

    [Parameter(Mandatory=$true)]
    [string]$TargetCommit,

    [switch]$Execute,

    [string]$ConfirmRelease = '',
    [string]$ExpectedComputer = '',
    [string]$ExpectedUser = '',
    [string]$ExpectedHead = '',
    [switch]$AllowCanonical,
    [switch]$SkipProcessCheck
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# --- guard: execute requires all confirmation flags ---
if ($Execute) {
    $missing = @()
    if (-not $ConfirmRelease)    { $missing += '--ConfirmRelease' }
    if (-not $ExpectedComputer)  { $missing += '--ExpectedComputer' }
    if (-not $ExpectedHead)      { $missing += '--ExpectedHead' }
    if ($TargetCommit.Length -ne 40) { $missing += '--TargetCommit (must be 40-char full hash)' }

    if ($missing.Count -gt 0) {
        Write-Error "BLOCKED: -Execute requires: $($missing -join ', ')"
        exit 1
    }
}

# --- build python args ---
$pyCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pyCmd) {
    Write-Error 'BLOCKED: python not found in PATH'
    exit 1
}
$py = $pyCmd.Source

$script = Join-Path $PSScriptRoot 'tools\deploy_and_rollback.py'
if (-not (Test-Path $script)) {
    Write-Error "BLOCKED: deploy script not found: $script"
    exit 1
}

$args_list = @(
    $script,
    '--manifest', $Manifest,
    '--repo',     $Repo,
    '--db',       $Db,
    '--target-commit', $TargetCommit
)

if ($Execute)              { $args_list += '--execute' }
if ($ConfirmRelease)       { $args_list += @('--confirm-release', $ConfirmRelease) }
if ($ExpectedComputer)     { $args_list += @('--expected-computer', $ExpectedComputer) }
if ($ExpectedUser)         { $args_list += @('--expected-user', $ExpectedUser) }
if ($ExpectedHead)         { $args_list += @('--expected-head', $ExpectedHead) }
if ($AllowCanonical)       { $args_list += '--allow-canonical' }
if ($SkipProcessCheck)     { $args_list += '--skip-process-check' }

$deployMode = if ($Execute) { 'EXECUTE' } else { 'PLAN' }
Write-Host ('CPS Deploy V1 - MODE=' + $deployMode)
Write-Host ('TARGET_COMMIT=' + $TargetCommit)
Write-Host ''

& $py @args_list
exit $LASTEXITCODE
