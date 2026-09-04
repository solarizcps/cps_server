#Requires -Version 5.1
<#
.SYNOPSIS
  Stop Araç GPS poll worker supervisor + child chain only.

.DESCRIPTION
  Companion to Start-Arac-GPS-Worker.ps1. Targets processes whose command line
  references arac_gps_poll_worker.py or arac_gps_log_supervisor, plus PIDs
  recorded in arac_gps_poll_worker.lock. Does not stop unrelated python.exe.
#>
[CmdletBinding()]
param(
    [switch]$WhatIf
)

$ErrorActionPreference = 'Stop'

function Get-GpsLockPids {
    $pids = @()
    foreach ($dir in @($env:TEMP, 'C:\Windows\TEMP')) {
        if (-not $dir) { continue }
        $lock = Join-Path $dir 'arac_gps_poll_worker.lock'
        try {
            if (Test-Path -LiteralPath $lock) {
                $raw = (Get-Content -LiteralPath $lock -Raw -ErrorAction Stop).Trim()
                if ($raw -match '^\d+$') {
                    $pids += [int]$raw
                }
            }
        }
        catch {
            Write-Warning "Lock read skipped: $lock ($($_.Exception.Message))"
        }
    }
    return @($pids | Select-Object -Unique)
}

function Get-GpsCommandLineMatches {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -and $_.CommandLine -notlike '*Get-CimInstance*' -and (
            $_.CommandLine -match 'arac_gps_poll_worker\.py' -or
            $_.CommandLine -match 'arac_gps_log_supervisor'
        )
    }
}

function Get-GpsFallbackChain {
    $targets = @()
    $pythonProcs = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue)
    foreach ($child in $pythonProcs) {
        if ($child.CommandLine -and ($child.CommandLine -match 'pytest|test_release_history')) { continue }
        $supervisor = Get-CimInstance Win32_Process -Filter "ProcessId=$($child.ParentProcessId)" -ErrorAction SilentlyContinue
        if (-not $supervisor -or $supervisor.Name -ne 'python.exe') { continue }
        if ($supervisor.CommandLine -and ($supervisor.CommandLine -match 'pytest|test_release_history')) { continue }
        $launcher = Get-CimInstance Win32_Process -Filter "ProcessId=$($supervisor.ParentProcessId)" -ErrorAction SilentlyContinue
        if (-not $launcher -or $launcher.Name -ne 'powershell.exe') { continue }
        $childEmpty = [string]::IsNullOrWhiteSpace($child.CommandLine)
        $superEmpty = [string]::IsNullOrWhiteSpace($supervisor.CommandLine)
        if (-not ($childEmpty -and $superEmpty)) { continue }
        $targets += $child
        $targets += $supervisor
    }
    return @($targets | Sort-Object ProcessId -Unique)
}

function Get-GpsTargetPids {
    $targets = @{}
    foreach ($proc in Get-GpsCommandLineMatches) {
        $targets[[int]$proc.ProcessId] = $proc
    }
    foreach ($lockPid in Get-GpsLockPids) {
        if (-not $targets.ContainsKey($lockPid)) {
            $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$lockPid" -ErrorAction SilentlyContinue
            if ($proc) {
                $targets[$lockPid] = $proc
            }
        }
        $parent = Get-CimInstance Win32_Process -Filter "ProcessId=$lockPid" -ErrorAction SilentlyContinue
        if ($parent) {
            $ppid = [int]$parent.ParentProcessId
            if ($ppid -gt 0) {
                $parentProc = Get-CimInstance Win32_Process -Filter "ProcessId=$ppid" -ErrorAction SilentlyContinue
                if ($parentProc -and $parentProc.Name -match 'python') {
                    $targets[$ppid] = $parentProc
                }
            }
        }
    }
    foreach ($proc in Get-GpsFallbackChain) {
        $targets[[int]$proc.ProcessId] = $proc
    }
    return $targets.Values | Sort-Object ProcessId
}

function Stop-ProcessTreeSafe {
    param([int[]]$Pids)
    $ordered = @()
    foreach ($procId in ($Pids | Sort-Object -Descending)) {
        if ($procId -le 4) { continue }
        if ($ordered -notcontains $procId) {
            $ordered += $procId
        }
    }
    foreach ($procId in $ordered) {
        $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
        if (-not $proc) { continue }
        Write-Host "Stopping PID=$procId Name=$($proc.ProcessName)"
        if ($WhatIf) { continue }
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
    }
}

$targets = @(Get-GpsTargetPids)
if (-not $targets) {
    Write-Host 'GPS_WORKER_COUNT=0 (nothing to stop)'
    exit 0
}

Write-Host 'GPS targets:'
foreach ($t in $targets) {
    $cmd = $t.CommandLine
    if ($cmd -and $cmd.Length -gt 120) { $cmd = $cmd.Substring(0, 120) + '...' }
    Write-Host "  PID=$($t.ProcessId) PPID=$($t.ParentProcessId) Name=$($t.Name) Cmd=$cmd"
}

$workerPids = @($targets | Where-Object { $_.CommandLine -match 'arac_gps_poll_worker\.py' -or (Get-GpsLockPids -contains $_.ProcessId) } | ForEach-Object { [int]$_.ProcessId })
$supervisorPids = @($targets | Where-Object { $_.CommandLine -match 'arac_gps_log_supervisor' -or ($workerPids -contains $_.ProcessId) } | ForEach-Object { [int]$_.ProcessId })

# Workers/lock PIDs first, then supervisors/parents
$allPids = @($workerPids + $supervisorPids + @($targets | ForEach-Object { [int]$_.ProcessId }) | Select-Object -Unique)
Stop-ProcessTreeSafe -Pids $allPids

Start-Sleep -Seconds 2
$remaining = @(Get-GpsTargetPids)
Write-Host "GPS_WORKER_COUNT_AFTER=$($remaining.Count)"
if ($remaining.Count -gt 0) {
    foreach ($r in $remaining) {
        Write-Host "  STILL RUNNING PID=$($r.ProcessId)"
    }
    exit 1
}
Write-Host 'GPS worker chain stopped.'
exit 0
