# ================================================================
# deploy_preflight_nexgen.ps1
# FAZ-DEPLOY-MIGRATION-KALICI-DUZELTME-1 + PARITE-1 master/UI
# Eksik migration veya master data varsa exit != 0
# ================================================================
$ErrorActionPreference = "Stop"

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
try { chcp 65001 | Out-Null } catch { }

$scriptRoot = Split-Path -Parent $PSScriptRoot
$root   = if ($env:CPS_ROOT) { $env:CPS_ROOT } else { $scriptRoot }
$appDir = Join-Path $root "app"
$dbPath = Join-Path $appDir "mock_data.db"
$pyCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pyCmd) {
  Write-Host "[HATA] PATH icinde aktif python komutu bulunamadi (Get-Command python)" -ForegroundColor Red
  exit 1
}
$py = $pyCmd.Source

$ok = $true
function Fail($m) { Write-Host "[HATA] $m" -ForegroundColor Red; $script:ok = $false }
function Pass($m) { Write-Host "[OK]   $m" -ForegroundColor Green }
function Warn($m) { Write-Host "[UYARI] $m" -ForegroundColor Yellow }

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

# --- Master data verify ---
$masterSync = Join-Path $appDir "tools\nexgen_master_data_sync.py"
if (-not (Test-Path $masterSync)) {
  Fail "nexgen_master_data_sync.py eksik"
} else {
  Write-Host "--- master data --verify ---"
  & $py $masterSync --target-db $dbPath --verify
  if ($LASTEXITCODE -ne 0) {
    Fail "DEPLOY BLOKE — MASTER DATA REQUIRED"
  } else {
    Pass "master data verify (9 cekirdek + recete kalemleri)"
  }
}

# --- UI parity markers ---
$tui = Join-Path $appDir "templates\nexgen\tablet_uretim_islem.html"
if (-not (Test-Path $tui)) {
  Fail "DEPLOY BLOKE — UI PARITY REQUIRED (tablet_uretim_islem.html yok)"
} else {
  $body = Get-Content -Path $tui -Raw -Encoding UTF8
  $uiOk = $true
  if ($body -notmatch 'sol-kimlik') {
    Fail "DEPLOY BLOKE — UI PARITY REQUIRED (sol-kimlik yok)"
    $uiOk = $false
  }
  if ($body -notmatch 'rm-page-hdr') {
    Fail "DEPLOY BLOKE — UI PARITY REQUIRED (rm-page-hdr yok)"
    $uiOk = $false
  }
  if ($body -match '(?i)DEPO\s+HAZIRLIK') {
    Warn "DEPO HAZIRLIK blogu template icinde gorunuyor (opsiyonel warn)"
  }
  if ($uiOk) { Pass "UI parity markers (sol-kimlik, rm-page-hdr)" }
}

# --- Core formul inline double-check ---
$coreCodes = @(
  '1BA-FL01','1BA-FS01','1BA-FL02','1BA-FS02','1BA-FL03','1BA-FS03',
  '2BA-FL01','2BA-FS01','3BA-FM01'
)
$corePy = @"
import sqlite3, sys
codes = $($coreCodes | ConvertTo-Json -Compress)
con = sqlite3.connect(r'$dbPath')
missing = [k for k in codes if not con.execute('SELECT 1 FROM nexgen_formul WHERE kod=? AND aktif=1', (k,)).fetchone()]
empty = []
for k in codes:
    f = con.execute('SELECT id FROM nexgen_formul WHERE kod=? AND aktif=1', (k,)).fetchone()
    if not f: continue
    c = con.execute('''SELECT COUNT(*) FROM nexgen_recete_kalem rk
        JOIN nexgen_uretim_varyant uv ON uv.id=rk.uretim_varyant_id
        JOIN nexgen_renk_varyant rv ON rv.id=uv.renk_varyant_id
        WHERE rv.formul_id=? AND rk.aktif=1''', (f[0],)).fetchone()[0]
    if c <= 0: empty.append(k)
if missing or empty:
    print('MISSING', missing, 'EMPTY', empty)
    sys.exit(1)
print('CORE_OK', len(codes))
"@
$corePy | & $py -
if ($LASTEXITCODE -ne 0) {
  Fail "DEPLOY BLOKE — MASTER DATA REQUIRED (cekirdek/recete)"
} else {
  Pass "9 cekirdek formul + recete kalem inline"
}

Write-Host "======================================================"
if ($ok) {
  Write-Host "PREFLIGHT GECTI"
  exit 0
} else {
  Write-Host "PREFLIGHT BASARISIZ — restart YAPMAYIN"
  exit 1
}
