# Start 8080 — debug off, reloader off, test env stripped from child, port guard.
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppDir = Join-Path $Root 'app'
$Py = if ($env:CPS_PYTHON) { $env:CPS_PYTHON } else { 'C:\Users\LENOVO\AppData\Local\Python\pythoncore-3.14-64\python.exe' }
$LogDir = Join-Path $Root 'logs'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$OutLog = Join-Path $LogDir 'cps_8080.out.log'
$ErrLog = Join-Path $LogDir 'cps_8080.err.log'

$saved = @{}
foreach ($key in @('CPS_TEST_DB_GUARD', 'CPS_MOCK_DB_PATH', 'CPS_CANONICAL_DB_SOURCE', 'FLASK_DEBUG')) {
    $saved[$key] = [Environment]::GetEnvironmentVariable($key, 'Process')
}

try {
    & $Py -c "import sys; sys.path.insert(0, r'$AppDir'); from tools.cps_startup_env import ensure_port_free_for_launch; ensure_port_free_for_launch(8080)"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    foreach ($key in @('CPS_TEST_DB_GUARD', 'CPS_MOCK_DB_PATH', 'CPS_CANONICAL_DB_SOURCE')) {
        Remove-Item -Path "Env:$key" -ErrorAction SilentlyContinue
    }
    $env:FLASK_DEBUG = '0'

    $modeLine = & $Py -c "import sys; sys.path.insert(0, r'$AppDir'); from tools.cps_startup_env import startup_db_mode_log_line; print(startup_db_mode_log_line(r'$AppDir'))"
    Write-Host 'Starting 8080 (debug=off, reloader=off, test-env=stripped) ...'
    Write-Host "AppDir: $AppDir"
    Write-Host "Python: $Py"
    Write-Host "OutLog: $OutLog"
    Write-Host $modeLine

    Set-Location $AppDir
    $proc = Start-Process -FilePath $Py -ArgumentList '-u app.py' -WorkingDirectory $AppDir `
        -RedirectStandardOutput $OutLog -RedirectStandardError $ErrLog `
        -NoNewWindow -PassThru
    Write-Host "Started PID: $($proc.Id)"
}
finally {
    foreach ($key in $saved.Keys) {
        if ($null -eq $saved[$key] -or $saved[$key] -eq '') {
            Remove-Item -Path "Env:$key" -ErrorAction SilentlyContinue
        } else {
            Set-Item -Path "Env:$key" -Value $saved[$key]
        }
    }
}
