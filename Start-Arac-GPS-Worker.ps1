$env:CPS_ARAC_GPS_CANONICAL_WRITE='YES'
$env:ARAC_GPS_POLL_INTERVAL_SEC='60'
Set-Location 'C:\Solariz_CPS_SERVER\app'
& 'C:\Users\LENOVO\AppData\Local\Microsoft\WindowsApps\python.exe' -u 'C:\Solariz_CPS_SERVER\app\tools\arac_gps_poll_worker.py' *>> 'C:\Solariz_CPS_SERVER\logs\arac_gps_worker.out.log' 2>> 'C:\Solariz_CPS_SERVER\logs\arac_gps_worker.err.log'
