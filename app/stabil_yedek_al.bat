@echo off
REM ================================================================
REM  CPS DEV — Stabil Yedek Al (B asamasi sonrasi)
REM  Hedef: C:\cps_dev\yedekler\backup_B_stable_<tarih>_<saat>\
REM  Icerik: modules, static, templates, mock_data.db, app.py,
REM          config.py, db.py, cleanup_v2.py, BASLA.bat
REM ================================================================

setlocal enabledelayedexpansion

REM Tarih-saat damgasi (bolge bagimsiz)
for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value ^| find "="') do set dt=%%I
set YYYY=!dt:~0,4!
set MM=!dt:~4,2!
set DD=!dt:~6,2!
set HH=!dt:~8,2!
set NN=!dt:~10,2!

set ETIKET=B_stable
set HEDEF=C:\cps_dev\yedekler\backup_!ETIKET!_!YYYY!_!MM!_!DD!_!HH!!NN!

echo.
echo ============================================
echo   CPS DEV — Stabil Yedek Aliniyor
echo ============================================
echo Hedef: !HEDEF!
echo.

if not exist "C:\cps_dev\yedekler" mkdir "C:\cps_dev\yedekler"
if exist "!HEDEF!" (
  echo UYARI: Hedef klasor zaten var, icine yazilacak.
) else (
  mkdir "!HEDEF!"
)

cd /d C:\cps_dev

REM --- Klasorler ---
echo [1/3] Klasorler kopyalaniyor...
xcopy "modules"   "!HEDEF!\modules\"   /E /I /Y /Q >nul
xcopy "static"    "!HEDEF!\static\"    /E /I /Y /Q >nul
xcopy "templates" "!HEDEF!\templates\" /E /I /Y /Q >nul

REM --- Ana dosyalar ---
echo [2/3] Ana dosyalar kopyalaniyor...
if exist "mock_data.db"  copy /Y "mock_data.db"  "!HEDEF!\" >nul
if exist "app.py"        copy /Y "app.py"        "!HEDEF!\" >nul
if exist "config.py"     copy /Y "config.py"     "!HEDEF!\" >nul
if exist "db.py"         copy /Y "db.py"         "!HEDEF!\" >nul
if exist "cleanup_v2.py" copy /Y "cleanup_v2.py" "!HEDEF!\" >nul
if exist "BASLA.bat"     copy /Y "BASLA.bat"     "!HEDEF!\" >nul
if exist "ENTEGRASYON.md" copy /Y "ENTEGRASYON.md" "!HEDEF!\" >nul

REM --- Bilgi dosyasi ---
echo [3/3] Yedek bilgi dosyasi olusturuluyor...
(
  echo CPS DEV Stabil Yedek
  echo ====================
  echo Tarih  : !YYYY!-!MM!-!DD! !HH!:!NN!
  echo Etiket : !ETIKET!
  echo.
  echo B Asamasi Sonrasi — Manuel Satir Ekleme Ozelligi Calisir Durumda
  echo - Bilir / tanimayan faturalar ONERI BEKLIYOR modunda acilir
  echo - "+ Manuel Satir Ekle" butonu ile kalem eklenebilir
  echo - Validation: aciklama bos olamaz / tutar 0'dan buyuk olmali
  echo - Sil ^(X^) butonu calisir
  echo - Guvenlik filtresi ^(10M+ TRY / 1M+ USD^) regresyon testleri gecti
  echo.
  echo A Asamasi 8/8 + B Asamasi 5/5 test gecti.
) > "!HEDEF!\YEDEK_BILGI.txt"

echo.
echo ============================================
echo   YEDEK TAMAMLANDI
echo ============================================
echo Konum: !HEDEF!
echo.
dir /b "!HEDEF!"
echo.
pause
