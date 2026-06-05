@echo off
cd /d C:\Solariz_CPS_SERVER\app

:START
python app.py

echo CPS kapandi. 120 saniye sonra yeniden baslatiliyor...
timeout /t 120

goto START