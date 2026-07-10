# ================================================================
# deploy_preflight.ps1
# Deploy öncesi güvenlik kontrolleri — mock_data.db ve Git durumu
# Kullanım: .\deploy_preflight.ps1
# Bu script SADECE kontrol yapar, deploy başlatmaz.
# ================================================================
$ErrorActionPreference = "Stop"

$root    = "C:\Solariz_CPS_SERVER"
$appDir  = "$root\app"
$dbPath  = "$appDir\mock_data.db"
$logDir  = "$root\logs"
$logFile = "$logDir\deploy_preflight_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"
$minDB   = 1048576   # 1 MB minimum

New-Item -ItemType Directory -Path $logDir -Force | Out-Null

$ok = $true

function Log($msg) {
    $ts   = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts] $msg"
    Write-Host $line
    Add-Content -Path $logFile -Value $line -Encoding UTF8
}
function Fail($msg) {
    Log "[HATA] $msg"
    $script:ok = $false
}
function PassOK($msg) {
    Log "[OK]   $msg"
}

Log "======================================================"
Log "DEPLOY PREFLIGHT BASLADI"
Log "Hedef DB : $dbPath"
Log "======================================================"

# ------------------------------------------------------------------
# 1. DB fiziksel varlik
# ------------------------------------------------------------------
if (-not (Test-Path $dbPath)) {
    Fail "mock_data.db BULUNAMADI - Deploy durdu. Sunucuya DB kopyalanmali."
} else {
    PassOK "mock_data.db mevcut."
}

if ($ok) {
    # ------------------------------------------------------------------
    # 2. Dosya boyutu
    # ------------------------------------------------------------------
    $boyut = (Get-Item $dbPath).Length
    if ($boyut -lt $minDB) {
        Fail "DB cok kucuk: $boyut bytes (minimum $minDB bekleniyor). Bos/bozuk DB."
    } else {
        PassOK "DB boyutu: $boyut bytes - yeterli."
    }

    # ------------------------------------------------------------------
    # 3-4. integrity_check + tablo kontrolleri (Python script via dosya)
    # ------------------------------------------------------------------
    $pyScript = "$root\_preflight_db_check.py"

    $pyLines = @(
        "import sqlite3, sys",
        "db = sys.argv[1]",
        "tables = sys.argv[2:]",
        "try:",
        "    con = sqlite3.connect(db)",
        "    ic = con.execute('PRAGMA integrity_check').fetchone()[0]",
        "    print('IC:' + ic)",
        "    for t in tables:",
        "        n = con.execute('SELECT COUNT(*) FROM ' + t).fetchone()[0]",
        "        print('TABLE:' + t + ':' + str(n))",
        "    con.close()",
        "except Exception as e:",
        "    print('ERROR:' + str(e))",
        "    sys.exit(1)"
    )
    $pyLines | Out-File -FilePath $pyScript -Encoding UTF8

    $tables  = "nexgen_stok_kart", "nexgen_formul", "nexgen_rf_renk", "nexgen_cari"
    $pyArgs  = @($pyScript, $dbPath) + $tables
    $results = & python @pyArgs 2>&1

    foreach ($line in $results) {
        if ($line -like "IC:*") {
            $ic = $line.Substring(3)
            if ($ic -eq "ok") {
                PassOK "integrity_check = ok"
            } else {
                Fail "integrity_check = $ic - DB bozuk, deploy durdu."
            }
        } elseif ($line -like "TABLE:*") {
            $parts = $line.Split(":")
            if ($parts.Count -ge 3) {
                $tbl = $parts[1]; $cnt = $parts[2]
                PassOK "$tbl : $cnt kayit"
            }
        } elseif ($line -like "ERROR:*") {
            Fail "DB erism hatasi: $line"
        }
    }
    Remove-Item $pyScript -Force -ErrorAction SilentlyContinue

    # ------------------------------------------------------------------
    # 5. DB Git tarafindan takip ediliyor mu?
    # ------------------------------------------------------------------
    Push-Location $root
    $tracked = git ls-files "app/mock_data.db" 2>$null
    Pop-Location
    if ($tracked) {
        Fail "mock_data.db hala Git tarafindan takip ediliyor! Deploy DURDU. 'git rm --cached app/mock_data.db' calistirin."
    } else {
        PassOK "mock_data.db Git tarafindan takip edilmiyor - guvenli."
    }
}

# ------------------------------------------------------------------
# Sonuc
# ------------------------------------------------------------------
Log "======================================================"
if ($ok) {
    Log "PREFLIGHT GECTI - Deploy baslatilabilir."
    Log "======================================================"
    exit 0
} else {
    Log "PREFLIGHT BASARISIZ - Deploy baslatilmamalidir."
    Log "======================================================"
    exit 1
}
