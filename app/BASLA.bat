@echo off
REM ============================================================
REM   Solariz CPS DEV - Faz 1 Başlatıcı
REM ============================================================
REM  İlk kez çalıştırıyorsan:
REM    1) python -m pip install -r requirements.txt
REM    2) python init_mock_db.py --sil     (mock DB sıfırdan kur)
REM  Mevcut DB varsa:
REM    python migration_v2.py              (Faz 1 tablolarını ekler)
REM ============================================================

chcp 65001 > nul
cd /d "%~dp0"

REM Prod'da (server) çalıştırmak istersen:
REM set CPS_DB_MODE=prod

echo.
echo ====================================================
echo   Solariz CPS Geliştirme Ortamı
echo ====================================================
echo.
echo   DB_MODE    : %CPS_DB_MODE%
echo   URL        : http://127.0.0.1:5057/
echo   Giriş      : http://127.0.0.1:5057/giris
echo   Yönetim    : http://127.0.0.1:5057/yonetim/
echo   Finans     : http://127.0.0.1:5057/finans/
echo.
echo ====================================================
echo.

python app.py

pause
