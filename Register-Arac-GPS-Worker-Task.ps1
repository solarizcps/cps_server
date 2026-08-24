# GPS P3 Task Scheduler — create DISABLED task
$ErrorActionPreference = 'Stop'
$TaskName = '\Solariz\Solariz_CPS_Arac_GPS_Worker'
$Root = 'C:\Solariz_CPS_SERVER'
$AppDir = Join-Path $Root 'app'
$Py = (Get-Command python).Source
$Worker = Join-Path $AppDir 'tools\arac_gps_poll_worker.py'
$LogDir = Join-Path $Root 'logs'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$OutLog = Join-Path $LogDir 'arac_gps_worker.out.log'
$ErrLog = Join-Path $LogDir 'arac_gps_worker.err.log'

$Action = New-ScheduledTaskAction -Execute $Py -Argument "-u `"$Worker`"" -WorkingDirectory $AppDir
$Trigger = New-ScheduledTaskTrigger -AtStartup
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

# Environment via wrapper script (Task Scheduler env vars limited on some Windows versions)
$Wrapper = Join-Path $Root 'Start-Arac-GPS-Worker.ps1'
@"
`$env:CPS_ARAC_GPS_CANONICAL_WRITE='YES'
`$env:ARAC_GPS_POLL_INTERVAL_SEC='60'
Set-Location '$AppDir'
& '$Py' -u '$Worker' *>> '$OutLog' 2>> '$ErrLog'
"@ | Set-Content -Path $Wrapper -Encoding UTF8

$Action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Wrapper`"" -WorkingDirectory $Root

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Description 'Solariz CPS Araç GPS Worker — Filom /mobiles poll 60s' -Force | Out-Null
Disable-ScheduledTask -TaskName $TaskName | Out-Null

Write-Host "Task created DISABLED: $TaskName"
Write-Host "Wrapper: $Wrapper"
Write-Host "Python: $Py"
Write-Host "Worker: $Worker"
Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State | Format-List
