# ================================================================
# deploy_preflight_nexgen.ps1
# FAZ-DEPLOY-MIGRATION-KALICI-DUZELTME-1
# Eksik migration varsa exit != 0 → restart YAPILMAMALI
# ================================================================
$ErrorActionPreference = "Stop"

$root   = if ($env:CPS_ROOT) { $env:CPS_ROOT } else { "C:\Solariz_CPS_SERVER" }
$appDir = Join-Path $root "app"
$dbPath = Join-Path $appDir "mock_data.db"
$py     = Join-Path $appDir ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

$ok = $true
function Fail($m) { Write-Host "[HATA] $m" -ForegroundColor Red; $script:ok = $false }
function Pass($m) { Write-Host "[OK]   $m" -ForegroundColor Green }

Write-Host "======================================================"
Write-Host "NEXGEN DEPLOY PREFLIGHT"
Write-Host "Root: $root"
Write-Host "======================================================"

Push-Location $root
try {
  $head = (git rev-parse HEAD 2>$null)
  $origin = (git rev-parse origin/main 2>$null)
  Pass "HEAD=$head"
  if ($origin) {
    if ($head -ne $origin) { Fail "HEAD != origin/main ($origin)" }
    else { Pass "HEAD == origin/main" }
  }
} finally { Pop-Location }

if (-not (Test-Path $dbPath)) { Fail "DB yok: $dbPath" }
else { Pass "DB mevcut" }

$nofocus = Join-Path $appDir "static\js\nexgen_tablet_nofocus.js"
if (-not (Test-Path $nofocus)) { Fail "nofocus.js eksik" } else { Pass "nofocus.js" }

$manifest = Join-Path $appDir "migrations\nexgen_manifest.py"
if (-not (Test-Path $manifest)) { Fail "nexgen_manifest.py eksik" } else { Pass "manifest" }

$runner = Join-Path $appDir "tools\nexgen_schema_upgrade.py"
if (-not (Test-Path $runner)) { Fail "schema_upgrade runner eksik" }
else {
  Write-Host "--- schema --verify ---"
  & $py $runner --db $dbPath --verify
  if ($LASTEXITCODE -ne 0) {
    Fail "DEPLOY BLOKE — MIGRATION REQUIRED"
  } else {
    Pass "schema verify"
  }
}

Write-Host "======================================================"
if ($ok) {
  Write-Host "PREFLIGHT GECTI"
  exit 0
} else {
  Write-Host "PREFLIGHT BASARISIZ — restart YAPMAYIN"
  exit 1
}
