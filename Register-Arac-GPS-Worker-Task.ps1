#Requires -Version 5.1
<#
.SYNOPSIS
  Register Solariz CPS Araç GPS Worker scheduled task (created DISABLED).

.PARAMETER PythonExe
  Exact real python.exe path — WindowsApps alias rejected.

.PARAMETER RunAsUser
  Task principal account (default: current user).

.PARAMETER ValidateOnly
  Build and print task contract without creating task.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$PythonExe,

    [string]$RunAsUser = $env:USERNAME,

    [switch]$ValidateOnly
)

$ErrorActionPreference = 'Stop'

$TaskPath = '\Solariz\'
$TaskName = 'Solariz_CPS_Arac_GPS_Worker'
$FullTaskName = "$TaskPath$TaskName"
$Root = 'C:\Solariz_CPS_SERVER'
$Wrapper = Join-Path $Root 'Start-Arac-GPS-Worker.ps1'

function Test-WindowsAppsPythonAlias {
    param([string]$Path)
    $norm = ($Path -replace '\\', '/').ToLowerInvariant()
    return ($norm -match '/windowsapps/') -or ($norm -match '/microsoft/windowsapps/')
}

function Resolve-RealPythonExe {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) {
        throw 'PythonExe is required — PATH lookup and py launcher are not allowed.'
    }
    if (Test-WindowsAppsPythonAlias -Path $Path) {
        throw "WindowsApps python alias rejected: $Path"
    }
    $resolved = (Resolve-Path -LiteralPath $Path -ErrorAction Stop).Path
    if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) {
        throw "PythonExe is not a file: $resolved"
    }
    if ($resolved -match '\\WindowsApps\\') {
        throw "Resolved PythonExe is WindowsApps alias: $resolved"
    }
    return $resolved
}

function Get-TaskContract {
    param(
        [string]$ResolvedPython,
        [string]$PrincipalUser
    )
    $wrapperArg = "-NoProfile -ExecutionPolicy Bypass -File `"$Wrapper`" -PythonExe `"$ResolvedPython`""
    return [ordered]@{
        TaskPath            = $TaskPath
        TaskName            = $TaskName
        Execute             = 'powershell.exe'
        Argument            = $wrapperArg
        WorkingDirectory    = $Root
        Trigger             = 'AtStartup'
        MultipleInstances   = 'IgnoreNew'
        RestartCount        = 3
        RestartIntervalMin  = 1
        InitialState        = 'Disabled'
        PrincipalUserId     = $PrincipalUser
        LogonType           = 'Interactive'
        RunLevel            = 'Limited'
        WrapperScript       = $Wrapper
        PythonExe           = $ResolvedPython
    }
}

function Compare-TaskContract {
    param($ExistingTask, $Expected)
    $diffs = @()
    if (-not $ExistingTask) { return @('task_missing') }
    $action = $ExistingTask.Actions | Select-Object -First 1
    if ($action.Execute -ne $Expected.Execute) {
        $diffs += "Execute: existing=$($action.Execute) expected=$($Expected.Execute)"
    }
    if ($action.Arguments -ne $Expected.Argument) {
        $diffs += "Arguments differ"
        $diffs += "  existing=$($action.Arguments)"
        $diffs += "  expected=$($Expected.Argument)"
    }
    if ($action.WorkingDirectory -ne $Expected.WorkingDirectory) {
        $diffs += "WorkingDirectory: existing=$($action.WorkingDirectory) expected=$($Expected.WorkingDirectory)"
    }
    $settings = $ExistingTask.Settings
    if ($settings.MultipleInstances -ne $Expected.MultipleInstances) {
        $diffs += "MultipleInstances: existing=$($settings.MultipleInstances) expected=$($Expected.MultipleInstances)"
    }
    if ($settings.RestartCount -ne $Expected.RestartCount) {
        $diffs += "RestartCount: existing=$($settings.RestartCount) expected=$($Expected.RestartCount)"
    }
    $principal = $ExistingTask.Principal
    if ($principal.UserId -ne $Expected.PrincipalUserId) {
        $diffs += "PrincipalUserId: existing=$($principal.UserId) expected=$($Expected.PrincipalUserId)"
    }
    if ($principal.LogonType -ne $Expected.LogonType) {
        $diffs += "LogonType: existing=$($principal.LogonType) expected=$($Expected.LogonType)"
    }
    return $diffs
}

# --- Validate wrapper exists ---
if (-not (Test-Path -LiteralPath $Wrapper -PathType Leaf)) {
    throw "Wrapper script missing: $Wrapper"
}

$resolvedPy = Resolve-RealPythonExe -Path $PythonExe
if ([string]::IsNullOrWhiteSpace($RunAsUser)) {
    throw 'RunAsUser cannot be empty.'
}

# Run wrapper ValidateOnly first
Write-Host "Running wrapper ValidateOnly..."
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Wrapper -PythonExe $resolvedPy -ValidateOnly
if ($LASTEXITCODE -ne 0) {
    throw "Wrapper ValidateOnly failed with exit code $LASTEXITCODE"
}

$contract = Get-TaskContract -ResolvedPython $resolvedPy -PrincipalUser $RunAsUser

Write-Host '=== TASK CONTRACT ==='
foreach ($pair in $contract.GetEnumerator()) {
    Write-Host ("  {0}={1}" -f $pair.Key, $pair.Value)
}

# Filom env source report (names/scopes only)
$filomNames = @('TURKCELL_FILOM_BASE_URL', 'TURKCELL_FILOM_USERNAME', 'TURKCELL_FILOM_PASSWORD')
$filomReport = @()
foreach ($n in $filomNames) {
    foreach ($scope in @('User', 'Machine')) {
        $val = [Environment]::GetEnvironmentVariable($n, $scope)
        if ($val) { $filomReport += "$scope`:$n=SET" } else { $filomReport += "$scope`:$n=unset" }
    }
}
Write-Host ('  FilomEnv=' + ($filomReport -join '; '))

if ($ValidateOnly) {
    Write-Host 'VALIDATE_ONLY=PASS'
    exit 0
}

# Check existing task — refuse silent overwrite if config differs
$existing = Get-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    $diffs = Compare-TaskContract -ExistingTask $existing -Expected $contract
    if ($diffs.Count -gt 0) {
        Write-Host 'EXISTING TASK CONFIG DIFFERS — refusing silent overwrite:'
        $diffs | ForEach-Object { Write-Host "  $_" }
        throw 'Existing task configuration differs. Remove or reconcile manually before register.'
    }
    Write-Host 'Existing task config matches — no re-register needed.'
    exit 0
}

$Action = New-ScheduledTaskAction -Execute $contract.Execute -Argument $contract.Argument -WorkingDirectory $contract.WorkingDirectory
$Trigger = New-ScheduledTaskTrigger -AtStartup
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -RestartCount $contract.RestartCount `
    -RestartInterval (New-TimeSpan -Minutes $contract.RestartIntervalMin)
$Principal = New-ScheduledTaskPrincipal -UserId $contract.PrincipalUserId -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName -Action $Action -Trigger $Trigger `
    -Settings $Settings -Principal $Principal `
    -Description 'Solariz CPS Araç GPS Worker — Filom /mobiles poll 60s (bounded logs)' | Out-Null
Disable-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName | Out-Null

Write-Host "Task created DISABLED: $FullTaskName"
Get-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName | Select-Object TaskName, State, TaskPath | Format-List
