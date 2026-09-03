# Install CPS release history git hooks (local repo only).
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "Setting core.hooksPath to .githooks"
git config --local core.hooksPath .githooks

$hooksPath = git config --get core.hooksPath
Write-Host "Verified core.hooksPath = $hooksPath"

if (-not (Test-Path "$Root\.githooks\pre-commit")) {
    throw "Missing .githooks/pre-commit"
}

Write-Host "Pre-commit hook installed via core.hooksPath."
Write-Host "Hook runs: check_release_fragment.py, validate_release_history.py, release_state.py"
