@echo off
REM ================================================================
REM  CPS DEV — Stabil Yedek Al (Estetik Patch C1 ONCESI)
REM  Etiket: D_oncesi_estetik
REM  Tarih damgasi icin PowerShell kullanilir (bolge bagimsiz)
REM ================================================================

setlocal

for /f "usebackq delims=" %%I in (`powershell -NoProfile -Command "Get-Date -Format 'yyyyMMdd_HHmm'"`) do set STAMP=%%I

set ETIKET=D_oncesi_estetik
set HEDEF=C:\cps_dev\yedekler\backup_%ETIKET%_%STAMP%

echo.
echo ============================================
echo   CPS DEV - Stabil Yedek Aliniyor
echo   Etiket: %ETIKET%
echo   (Estetik Patch C1 oncesi snapshot)
echo ============================================
echo Hedef: %HEDEF%
echo.

if not exist "C:\cps_dev\yedekler" mkdir "C:\cps_dev\yedekler"
if not exist "%HEDEF%" mkdir "%HEDEF%"

cd /d C:\cps_dev

echo [1/3] Klasorler kopyalaniyor...
xcopy "modules"   "%HEDEF%\modules\"   /E /I /Y /Q >nul
xcopy "static"    "%HEDEF%\static\"    /E /I /Y /Q >nul
xcopy "templates" "%HEDEF%\templates\" /E /I /Y /Q >nul

echo [2/3] Ana dosyalar kopyalaniyor...
if exist "mock_data.db"   copy /Y "mock_data.db"   "%HEDEF%\" >nul
if exist "app.py"         copy /Y "app.py"         "%HEDEF%\" >nul
if exist "config.py"      copy /Y "config.py"      "%HEDEF%\" >nul
if exist "db.py"          copy /Y "db.py"          "%HEDEF%\" >nul
if exist "cleanup_v2.py"  copy /Y "cleanup_v2.py"  "%HEDEF%\" >nul
if exist "BASLA.bat"      copy /Y "BASLA.bat"      "%HEDEF%\" >nul
if exist "ENTEGRASYON.md" copy /Y "ENTEGRASYON.md" "%HEDEF%\" >nul

echo [3/3] Yedek bilgi dosyasi olusturuluyor...
(
  echo CPS DEV Stabil Yedek
  echo ====================
  echo Tarih : %STAMP%
  echo Etiket: %ETIKET%
  echo.
  echo Bu yedek ESTETIK PATCH C1 oncesi alinmis stabil snapshot'tir.
  echo.
  echo Tamamlanmis isler ^(bu noktaya kadar^):
  echo - A asamasi: Ithalat core 8/8
  echo - B asamasi: Manuel satir ekleme 5/5
  echo - IslemTarih bug: Durum Takibi calisiyor
  echo - SAPMA hesabi backend: 3 parti dogrulandi
  echo - SAPMA UI ^(CSS + JS^): tum senaryolar dogrulandi
  echo.
  echo Sonra uygulanacak isler:
  echo - Patch C1: Estetik CSS ^(tip kart ferahlik, sapma rengi^)
  echo - Patch C2: Tip kart 3 satirli yeni duzen ^(JS^)
  echo - Patch C3: KPI ikonlari ^(JS^)
  echo.
  echo Kapsam disi ^(sonraya^): Sol ic menu, para birimi switch, tablo sort.
  echo.
  echo Geri yukleme:
  echo   xcopy "%HEDEF%\modules\" "C:\cps_dev\modules\" /E /I /Y
  echo   xcopy "%HEDEF%\static\"  "C:\cps_dev\static\"  /E /I /Y
  echo   xcopy "%HEDEF%\templates\" "C:\cps_dev\templates\" /E /I /Y
  echo   copy "%HEDEF%\mock_data.db" "C:\cps_dev\mock_data.db"
) > "%HEDEF%\YEDEK_BILGI.txt"

echo.
echo ============================================
echo   YEDEK TAMAMLANDI
echo ============================================
echo Konum: %HEDEF%
echo.
echo Icerik:
dir /b "%HEDEF%"
echo.
echo Sonra C1 patchini uygulayabilirsin:
echo   python patch_estetik_c1.py
echo.
pause
