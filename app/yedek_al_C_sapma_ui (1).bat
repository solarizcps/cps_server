@echo off
REM ================================================================
REM  CPS DEV — Stabil Yedek Al (C_stable_sapma_ui)
REM  Tarih damgasi icin PowerShell kullanilir (bolge bagimsiz)
REM ================================================================

setlocal

for /f "usebackq delims=" %%I in (`powershell -NoProfile -Command "Get-Date -Format 'yyyyMMdd_HHmm'"`) do set STAMP=%%I

set ETIKET=C_stable_sapma_ui
set HEDEF=C:\cps_dev\yedekler\backup_%ETIKET%_%STAMP%

echo.
echo ============================================
echo   CPS DEV - Stabil Yedek Aliniyor
echo   Etiket: %ETIKET%
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
if exist "cleanup_v2.py"  copy /Y "cleanup_v2.py"  "%HEDEF%\" >nul
REM Yardimci dosyalar (varsa)
if exist "config.py"      copy /Y "config.py"      "%HEDEF%\" >nul
if exist "db.py"          copy /Y "db.py"          "%HEDEF%\" >nul
if exist "BASLA.bat"      copy /Y "BASLA.bat"      "%HEDEF%\" >nul

echo [3/3] Yedek bilgi dosyasi olusturuluyor...
(
  echo CPS DEV Stabil Yedek
  echo ====================
  echo Tarih : %STAMP%
  echo Etiket: %ETIKET%
  echo.
  echo Bu yedek SAPMA UI fix'in tamamlanmasindan sonraki stabil noktadir.
  echo.
  echo Kapsanan tamamlanan isler:
  echo - A asamasi: Ithalat core 8/8
  echo - B asamasi: Manuel satir ekleme 5/5
  echo - IslemTarih bug: Durum Takibi calisiyor
  echo - SAPMA hesabi backend: 3 parti dogrulandi
  echo - SAPMA UI (CSS + JS):
  echo     * sapma guvenilir=false uyari ikonu
  echo     * Karisik para birimi turuncu alt metin
  echo     * sapma_yuzde null "Karsilastirilabilir tip yok"
  echo     * BEKLIYOR / TAHMINI_YOK rozetleri
  echo     * TAHMINI_YOK mavi dashed kart
  echo.
  echo Siradaki is: UYGULANDI_BOS temizlik (14 eski kayit).
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
pause
