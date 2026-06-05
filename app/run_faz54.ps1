# ============================================================
# CPS DEV - FAZ 5.4 TIP GUARD - TEK KOMUT RUNNER
# ============================================================
# Kullanim: .\run_faz54.ps1
# 
# Adimlar:
#   1) Patch script'i yerine kopyala (Downloads -> C:\cps_dev)
#   2) Patch'i uygula
#   3) Idempotent test
#   4) Adem'den Flask restart bekle (manuel)
#   5) 18 test senaryosu
# ============================================================

Write-Host ""
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "  CPS DEV - FAZ 5.4 TIP GUARD RUNNER" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host ""

# ============================================================
# 1) Patch script'i yerine koy
# ============================================================
$src = "C:\Users\LENOVO\Downloads\apply_tip_guard.py"
$dst = "C:\cps_dev\apply_tip_guard.py"

Write-Host "--- 1) PATCH DOSYA YERLESTIRME ---" -ForegroundColor Yellow
if (Test-Path $src) {
    Copy-Item $src $dst -Force
    Remove-Item $src -Force
    Write-Host "  [OK] Patch yerlesti: $dst" -ForegroundColor Green
} elseif (Test-Path $dst) {
    Write-Host "  [OK] Patch zaten yerinde: $dst" -ForegroundColor Green
} else {
    Write-Host "  [HATA] Patch dosyasi yok!" -ForegroundColor Red
    Write-Host "         $src bulunamadi" -ForegroundColor Red
    return
}

# ============================================================
# 2) Patch uygula
# ============================================================
Write-Host ""
Write-Host "--- 2) PATCH UYGULAMA ---" -ForegroundColor Yellow
Set-Location C:\cps_dev
python apply_tip_guard.py

# ============================================================
# 3) Idempotent test
# ============================================================
Write-Host ""
Write-Host "--- 3) IDEMPOTENT TEST (tekrar) ---" -ForegroundColor Yellow
python apply_tip_guard.py

# ============================================================
# 4) Flask restart uyarisi
# ============================================================
Write-Host ""
Write-Host "==============================================" -ForegroundColor Yellow
Write-Host "  ! FLASK RESTART GEREKLI !" -ForegroundColor Yellow
Write-Host "==============================================" -ForegroundColor Yellow
Write-Host ""
Write-Host "  Flask'in calistigi terminale gec ve:" -ForegroundColor Gray
Write-Host "    1. Ctrl+C  (durdur)" -ForegroundColor Gray
Write-Host "    2. python app.py  (yeniden baslat)" -ForegroundColor Gray
Write-Host ""
Write-Host "  Restart bittikten sonra herhangi bir tusa bas..." -ForegroundColor Gray
Write-Host ""
Read-Host "  ENTER ile devam et (testleri baslat)"

# ============================================================
# 5) Test fonksiyonu
# ============================================================
Write-Host ""
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "  18 TEST SENARYOSU" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan

function Test-FazGuard {
    param(
        [string]$TestNo,
        [string]$Kadi,
        [string]$Sifre,
        [string]$Url,
        [int]$BeklenenStatus,
        [string]$BeklenenLocation = $null,
        [string]$Aciklama = ""
    )
    
    # Login (eger sifre verilmisse)
    $sess = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    if ($Sifre) {
        Invoke-WebRequest -Uri "http://127.0.0.1:5057/giris" -Method POST `
            -Body "kullanici=$Kadi&sifre=$Sifre" `
            -ContentType "application/x-www-form-urlencoded" `
            -WebSession $sess -UseBasicParsing -MaximumRedirection 0 `
            -ErrorAction SilentlyContinue 2>&1 | Out-Null
    }
    
    # URL'yi cagir (redirect izleme)
    $code = "BAGLANTI"
    $loc = ""
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:5057$Url" `
            -WebSession $sess -UseBasicParsing -TimeoutSec 15 `
            -MaximumRedirection 0 -ErrorAction SilentlyContinue 2>&1
        $code = [int]$r.StatusCode
        if ($r.Headers -and $r.Headers["Location"]) {
            $loc = $r.Headers["Location"]
        }
    } catch {
        $resp = $_.Exception.Response
        if ($resp) {
            $code = [int]$resp.StatusCode
            if ($resp.Headers -and $resp.Headers["Location"]) {
                $loc = $resp.Headers["Location"]
            }
        }
    }
    
    # Karar
    $statusOk = ($code -eq $BeklenenStatus)
    $locOk = $true
    if ($BeklenenLocation) {
        $locOk = ($loc -like "*$BeklenenLocation*")
    }
    $sym = if ($statusOk -and $locOk) { "OK" } else { "FAIL" }
    $color = if ($sym -eq "OK") { "Green" } else { "Red" }
    
    $beklenenLocStr = if ($BeklenenLocation) { " loc='$BeklenenLocation'" } else { "" }
    $aktualLocStr = if ($loc) { " Location='$loc'" } else { "" }
    
    Write-Host ("  [{0,4}] {1}  {2,-15} {3,-30} code={4}{5}{6}  {7}" -f `
        $sym, $TestNo, $Kadi, $Url, $code, $aktualLocStr, "", $Aciklama) -ForegroundColor $color
    
    return ($sym -eq "OK")
}

$results = @()

# ============================================================
# SISTEM TESTLERI
# ============================================================
Write-Host ""
Write-Host "--- SISTEM (admin) ---" -ForegroundColor Cyan
$results += Test-FazGuard -TestNo "T1"  -Kadi "admin" -Sifre "admin123" -Url "/finans/" -BeklenenStatus 200 -Aciklama "(mevcut korundu)"
$results += Test-FazGuard -TestNo "T2"  -Kadi "admin" -Sifre "admin123" -Url "/hedef/" -BeklenenStatus 200 -Aciklama "(mevcut)"
$results += Test-FazGuard -TestNo "T3"  -Kadi "admin" -Sifre "admin123" -Url "/uretim/" -BeklenenStatus 200 -Aciklama "(mevcut)"

# ============================================================
# PERSONEL TESTLERI
# ============================================================
Write-Host ""
Write-Host "--- PERSONEL (test_personel) ---" -ForegroundColor Cyan
$results += Test-FazGuard -TestNo "T4"  -Kadi "test_personel" -Sifre "test123" -Url "/giris" -BeklenenStatus 302 -BeklenenLocation "/uretim/" -Aciklama "(login redirect FAZ 5.1)"
$results += Test-FazGuard -TestNo "T5"  -Kadi "test_personel" -Sifre "test123" -Url "/uretim/" -BeklenenStatus 200 -Aciklama "(personel ana sayfa)"
$results += Test-FazGuard -TestNo "T6"  -Kadi "test_personel" -Sifre "test123" -Url "/hedef/" -BeklenenStatus 302 -BeklenenLocation "/uretim/" -Aciklama "(YENI - guard redirect)"
$results += Test-FazGuard -TestNo "T7"  -Kadi "test_personel" -Sifre "test123" -Url "/finans/" -BeklenenStatus 302 -BeklenenLocation "/uretim/" -Aciklama "(YENI - guard redirect)"
$results += Test-FazGuard -TestNo "T8"  -Kadi "test_personel" -Sifre "test123" -Url "/tasks" -BeklenenStatus 302 -BeklenenLocation "/uretim/" -Aciklama "(YENI - guard redirect)"
$results += Test-FazGuard -TestNo "T9"  -Kadi "test_personel" -Sifre "test123" -Url "/static/css/global_overlay.css" -BeklenenStatus 200 -Aciklama "(BYPASS - css yuklenmeli)"

# ============================================================
# USTA TESTLERI
# ============================================================
Write-Host ""
Write-Host "--- USTA (test_usta) ---" -ForegroundColor Cyan
$results += Test-FazGuard -TestNo "T10" -Kadi "test_usta" -Sifre "test123" -Url "/giris" -BeklenenStatus 302 -BeklenenLocation "/hedef/" -Aciklama "(login redirect)"
$results += Test-FazGuard -TestNo "T11" -Kadi "test_usta" -Sifre "test123" -Url "/hedef/" -BeklenenStatus 200 -Aciklama "(FAZ 5.3 ile usta acti)"
$results += Test-FazGuard -TestNo "T12" -Kadi "test_usta" -Sifre "test123" -Url "/uretim/" -BeklenenStatus 200 -Aciklama "(usta uretimi de gorebilir)"
$results += Test-FazGuard -TestNo "T13" -Kadi "test_usta" -Sifre "test123" -Url "/finans/" -BeklenenStatus 302 -BeklenenLocation "/hedef/" -Aciklama "(YENI - guard redirect)"
$results += Test-FazGuard -TestNo "T14" -Kadi "test_usta" -Sifre "test123" -Url "/yonetim/" -BeklenenStatus 302 -BeklenenLocation "/hedef/" -Aciklama "(YENI - guard redirect)"
$results += Test-FazGuard -TestNo "T15" -Kadi "test_usta" -Sifre "test123" -Url "/static/css/global_overlay.css" -BeklenenStatus 200 -Aciklama "(BYPASS)"

# ============================================================
# GENEL BYPASS TESTLERI (login YOK)
# ============================================================
Write-Host ""
Write-Host "--- BYPASS TESTLERI (oturum yok / herkes) ---" -ForegroundColor Cyan
$results += Test-FazGuard -TestNo "T16" -Kadi "" -Sifre "" -Url "/giris" -BeklenenStatus 200 -Aciklama "(login sayfasi)"

# T17: cikis - admin login sonrasi cikis 302 -> /giris
$sess17 = New-Object Microsoft.PowerShell.Commands.WebRequestSession
Invoke-WebRequest -Uri "http://127.0.0.1:5057/giris" -Method POST `
    -Body "kullanici=admin&sifre=admin123" -ContentType "application/x-www-form-urlencoded" `
    -WebSession $sess17 -UseBasicParsing -MaximumRedirection 0 -ErrorAction SilentlyContinue 2>&1 | Out-Null
$cikisCode = "BAGLANTI"; $cikisLoc = ""
try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:5057/cikis" -WebSession $sess17 -UseBasicParsing -MaximumRedirection 0 -ErrorAction SilentlyContinue 2>&1
    $cikisCode = [int]$r.StatusCode
    if ($r.Headers["Location"]) { $cikisLoc = $r.Headers["Location"] }
} catch {
    $resp = $_.Exception.Response
    if ($resp) { $cikisCode = [int]$resp.StatusCode; if ($resp.Headers["Location"]) { $cikisLoc = $resp.Headers["Location"] } }
}
$cikisOk = ($cikisCode -eq 302) -and ($cikisLoc -like "*giris*" -or $cikisLoc -like "*/")
$cikisSym = if ($cikisOk) { "OK" } else { "FAIL" }
$cikisColor = if ($cikisOk) { "Green" } else { "Red" }
Write-Host ("  [{0,4}] T17  {1,-15} {2,-30} code={3} Location='{4}'  (cikis redirect)" -f `
    $cikisSym, "admin->cikis", "/cikis", $cikisCode, $cikisLoc) -ForegroundColor $cikisColor
$results += $cikisOk

$results += Test-FazGuard -TestNo "T18" -Kadi "admin" -Sifre "admin123" -Url "/sifre-degistir" -BeklenenStatus 200 -Aciklama "(BYPASS - sifre sayfasi)"

# ============================================================
# OZET
# ============================================================
$pass = ($results | Where-Object { $_ -eq $true }).Count
$fail = ($results | Where-Object { $_ -eq $false }).Count
$total = $results.Count

Write-Host ""
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "  TEST OZETI" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan
$ozetColor = if ($fail -eq 0) { "Green" } else { "Yellow" }
Write-Host ""
Write-Host "  TOPLAM: $pass PASS / $fail FAIL  (toplam $total)" -ForegroundColor $ozetColor
Write-Host ""
if ($fail -eq 0) {
    Write-Host "  [OK] Tum testler PASS!" -ForegroundColor Green
    Write-Host "  FAZ 5.4 TIP GUARD basariyla calisiyor." -ForegroundColor Green
} else {
    Write-Host "  [UYARI] Bazi testler FAIL - detaylar yukarida." -ForegroundColor Yellow
}
Write-Host ""
