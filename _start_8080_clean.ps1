# Start 8080 — debug off, reloader off, test env stripped from child, port guard.
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppDir = Join-Path $Root 'app'
$LogDir = Join-Path $Root 'logs'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$OutLog = Join-Path $LogDir 'cps_8080.out.log'
$ErrLog = Join-Path $LogDir 'cps_8080.err.log'

function Resolve-CpsPython314 {
    $candidate = $null

    if ($env:CPS_PYTHON_EXE) {
        $candidate = $env:CPS_PYTHON_EXE.Trim()
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            Write-Host "CPS_PYTHON_EXE not found, falling back to py -3.14: $candidate"
            $candidate = $null
        }
    }

    if (-not $candidate) {
        $raw = & py -3.14 -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($raw)) {
            Write-Error 'Could not resolve Python 3.14. Set CPS_PYTHON_EXE to a valid python.exe or install Python 3.14 with the py launcher.'
            exit 1
        }
        $candidate = ($raw -replace "`r", '').Trim()
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            Write-Error "py -3.14 resolved path does not exist: $candidate"
            exit 1
        }
    }

    $verOut = & $candidate -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
    if ($LASTEXITCODE -ne 0 -or ($verOut.Trim() -ne '3.14')) {
        Write-Error "Python executable is not 3.14: $candidate (reported $($verOut.Trim()))"
        exit 1
    }

    return $candidate
}

$Py = Resolve-CpsPython314

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
