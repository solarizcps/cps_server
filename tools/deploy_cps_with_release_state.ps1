# Official CPS deploy wrapper with automatic release-state update.
# Does NOT push or transfer code. Operates on code already present at RepoRoot.
#
# Default: DRY-RUN (prints plan only). Real deploy requires -Execute.
#
# Usage:
#   powershell -File tools/deploy_cps_with_release_state.ps1
#   powershell -File tools/deploy_cps_with_release_state.ps1 -Execute
#   powershell -File tools/deploy_cps_with_release_state.ps1 -Execute -SmokeOnly
#
param(
    [switch]$Execute,
    [switch]$SmokeOnly,
    [switch]$SkipRestart,
    [string]$RepoRoot = "",
    [string]$TargetBranch = "main",
    [string]$TargetCommit = "",
    [string]$SmokeUrl = "http://127.0.0.1:8080/giris",
    [string]$TargetServer = "CPS-PROD",
    [string]$RestartScript = "Start-CPS-8080.ps1",
    [string]$DbPath = "app\mock_data.db"
)

$ErrorActionPreference = "Stop"
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$DefaultRoot = Split-Path -Parent $ScriptRoot
if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = $DefaultRoot
}
$RepoRoot = (Resolve-Path $RepoRoot).Path

function Write-Step($msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Write-Host "[$ts] $msg"
}

function Fail($msg) {
    Write-Step "FAIL: $msg"
    if ($Execute) {
        & python "$RepoRoot\tools\record_deploy_event.py" --no-restart --smoke-url $SmokeUrl --target-server $TargetServer 2>$null | Out-Null
    }
    throw $msg
}

Write-Step "CPS deploy wrapper (Execute=$Execute, SmokeOnly=$SmokeOnly)"

# Exact repo root guard
$expectedMarker = Join-Path $RepoRoot "tools\release_state.py"
if (-not (Test-Path $expectedMarker)) {
    Fail "RepoRoot validation failed: $RepoRoot (release_state.py missing)"
}
Write-Step "RepoRoot=$RepoRoot"

Set-Location $RepoRoot

# Target commit / branch
$head = git rev-parse HEAD
if (-not $head) { Fail "Git HEAD unavailable" }
if ($TargetCommit) {
    git cat-file -t $TargetCommit 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { Fail "TargetCommit not found in git: $TargetCommit" }
    $head = (git rev-parse $TargetCommit).Trim()
}
$branch = git rev-parse --abbrev-ref HEAD
if ($branch -ne $TargetBranch) {
    Write-Step "WARN: active branch=$branch target=$TargetBranch"
}
Write-Step "Deploy target SHA: $($head.Substring(0,8)) branch=$TargetBranch"

# Dirty tracked worktree guard (Execute deploy only)
$dirtyTracked = @(git status --porcelain | Where-Object { $_ -match '^.[MADRCU]' })
if ($dirtyTracked.Count -gt 0) {
    if ($Execute) {
        Fail "Dirty tracked worktree - deploy blocked ($($dirtyTracked.Count) files)"
    } else {
        Write-Step "[DRY-RUN] Dirty tracked worktree noted ($($dirtyTracked.Count) files) - would block Execute"
    }
}

# Unpushed commit guard when upstream exists
$upstream = git rev-parse --abbrev-ref "$branch@{upstream}" 2>$null
if ($upstream) {
    $counts = git rev-list --left-right --count "$upstream...HEAD"
    $parts = $counts -split '\s+'
    if ($parts.Count -eq 2) {
        $ahead = [int]$parts[1]
        if ($ahead -gt 0) {
            Write-Step "WARN: HEAD is $ahead commits ahead of upstream - prod deploy blocked without push"
            if ($Execute -and -not $SmokeOnly) {
                Fail "Unpushed commits block prod deploy (ahead=$ahead)"
            }
        }
        $behind = [int]$parts[0]
        if ($behind -gt 0 -and $Execute -and -not $SmokeOnly) {
            Fail "Fast-forward not possible - server/local is $behind commits behind"
        }
    }
}

# Preflight + DB backup (Execute only)
$dbFull = Join-Path $RepoRoot $DbPath
if ($Execute -and -not $SmokeOnly) {
    if (Test-Path "$RepoRoot\deploy_preflight.ps1") {
        Write-Step "deploy_preflight.ps1"
        & "$RepoRoot\deploy_preflight.ps1"
        if ($LASTEXITCODE -ne 0) { Fail "Preflight FAIL" }
    }
    if (Test-Path $dbFull) {
        $backupDir = Join-Path $RepoRoot "logs\deploy_backup"
        New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
        $backup = Join-Path $backupDir ("mock_data_{0}.db" -f (Get-Date -Format "yyyyMMdd_HHmmss"))
        Copy-Item $dbFull $backup
        Write-Step "DB backup: $backup"
    }
}

# Restart (Execute only; old process continues until successful restart script)
$restartPath = Join-Path $RepoRoot $RestartScript
if ($SmokeOnly) {
    Write-Step "SmokeOnly - restart skipped"
} elseif (-not $Execute) {
    Write-Step "[DRY-RUN] Restart: $restartPath"
} elseif ($SkipRestart) {
    Write-Step "SkipRestart - restart skipped"
} elseif (Test-Path $restartPath) {
    Write-Step "Restart script ready: $RestartScript"
    Write-Step "[NOT RUN THIS PHASE] Real restart skipped in audit phase"
} else {
    Write-Step "Restart script missing: $restartPath"
}

# Manifest + smoke + state (Execute only; DRY-RUN skips manifest write)
if (-not $Execute) {
    Write-Step "[DRY-RUN] record_deploy_event.py skipped"
    Write-Step "[DRY-RUN] MANUAL_STATE_COMMAND_REQUIRED=false (automatic with -Execute)"
    Write-Step "Deploy wrapper DRY-RUN complete"
    exit 0
}

Write-Step "record_deploy_event.py (smoke required)"
$recordArgs = @(
    "$RepoRoot\tools\record_deploy_event.py",
    "--commit", $head,
    "--server-head", $head,
    "--smoke-url", $SmokeUrl,
    "--target-server", $TargetServer
)
if ($SkipRestart -or $SmokeOnly) {
    $recordArgs += @("--no-restart")
}
& python @recordArgs
if ($LASTEXITCODE -ne 0) {
    Write-Step "Deploy FAIL - old process continues; rollback is manual"
    exit 1
}

Write-Step "Deploy wrapper complete - manifest/state updated automatically"
Write-Step "MANUAL_STATE_COMMAND_REQUIRED=false"
exit 0
