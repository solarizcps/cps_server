@echo off
REM ================================================================
REM  CPS DEV — Stabil Yedek Al (E_stable_estetik_C2_1)
REM  Estetik C serisi tamamlandiktan sonraki snapshot
REM  Tarih damgasi icin PowerShell kullanilir (bolge bagimsiz)
REM ================================================================

setlocal

for /f "usebackq delims=" %%I in (`powershell -NoProfile -Command "Get-Date -Format 'yyyyMMdd_HHmm'"`) do set STAMP=%%I

set ETIKET=E_stable_estetik_C2_1
set HEDEF=C:\cps_dev\yedekler\backup_%ETIKET%_%STAMP%

echo.
echo ============================================
echo   CPS DEV - Stabil Yedek Aliniyor
echo   Etiket: %ETIKET%
echo   (Estetik C serisi tamamlandi)
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
  echo Bu yedek ESTETIK C SERISI tamamlandiktan sonraki stabil snapshottir.
  echo.
  echo Tamamlanmis isler:
  echo - A asamasi: Ithalat core 8/8
  echo - B asamasi: Manuel satir ekleme 5/5
  echo - IslemTarih bug: Durum Takibi calisiyor
  echo - SAPMA hesabi backend: dogrulandi
  echo - SAPMA UI ^(Patch A + B^): rozet sistemi calisiyor
  echo - Estetik Patch C1 v2 ^(CSS^):
  echo     * KPI bar ferah ^(padding 22/24, font 28px^)
  echo     * SAPMA karti sol 4px renkli accent + 32px bold sayi
  echo     * Tip kart 1.5px border, 10px radius, 120px min-height
  echo     * Rozet pill standardi ^(uppercase, 700^)
  echo     * Sapma rengi Var.B siniflari hazir
  echo - Estetik Patch C2 ^(JS^):
  echo     * Tip kart 3 satirli duzen ^(Plan / Gercek / Sapma^)
  echo     * Hafif dashed ayraclar
  echo     * Sapma yonune gore renkli yuzde ^(yesil/kirmizi^)
  echo - Estetik Patch C2.1A ^(JS^):
  echo     * Kart class kart-pozitif / kart-negatif
  echo - Estetik Patch C2.1B ^(CSS^):
  echo     * Kart border yonune gore renkli ^(yesil tasarruf, kirmizi asim^)
  echo     * BEKLIYOR sari dashed / TAHMINI_YOK mavi dashed korundu
  echo.
  echo Var.B Renk Mantigi:
  echo - Negatif sapma ^(tasarruf^) -^> YESIL
  echo - Pozitif sapma ^(asim^)     -^> KIRMIZI
  echo - Sapma yok                   -^> Gri default
  echo - BEKLIYOR                    -^> Sari dashed
  echo - TAHMINI_YOK                 -^> Mavi dashed
  echo.
  echo Yapilmamis isler ^(estetik C serisi^):
  echo - C3: KPI sag ust ikonlar ^(opsiyonel kozmetik^)
  echo - Sol ic menu / para birimi switch / tablo sort ^(yeni HTML^)
  echo.
  echo Siradaki olasi isler:
  echo - UYGULANDI_BOS keşfi ^(script hazir^)
  echo - Sebs klasorundeki 11 belgeyi uctan uca test
  echo - C asamasi: Google Drive entegrasyonu
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
pause
