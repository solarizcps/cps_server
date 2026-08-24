#Requires -Version 5.1
<#
.SYNOPSIS
  Register Solariz CPS Araç GPS Worker as SYSTEM scheduled task (created DISABLED).

.PARAMETER PythonExe
  Exact real python.exe path — WindowsApps alias rejected.

.PARAMETER ValidateOnly
  Build and print task contract without creating task.

.PARAMETER SecretFile
  Override DPAPI secret path (testing only).
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$PythonExe,

    [switch]$ValidateOnly,

    [string]$SecretFile = 'C:\ProgramData\Solariz\secrets\arac_gps_worker.dpapi'
)

$ErrorActionPreference = 'Stop'

$TaskPath = '\Solariz\'
$TaskName = 'Solariz_CPS_Arac_GPS_Worker'
$FullTaskName = "$TaskPath$TaskName"
$Root = 'C:\Solariz_CPS_SERVER'
$Wrapper = Join-Path $Root 'Start-Arac-GPS-Worker.ps1'
$PrincipalUserId = 'SYSTEM'
$Script:ProductionSecretFile = 'C:\ProgramData\Solariz\secrets\arac_gps_worker.dpapi'
$Script:RequiredSystemPaths = @(
    'C:\Solariz_CPS_SERVER',
    'C:\Solariz_CPS_SERVER\app\mock_data.db',
    'C:\Solariz_CPS_SERVER\logs',
    'C:\ProgramData\Solariz\secrets'
)

function Test-Administrator {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

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

function Test-SystemPathAccessContract {
    $report = @()
    foreach ($p in $Script:RequiredSystemPaths) {
        if (-not (Test-Path -LiteralPath $p)) {
            if ($p -like '*\secrets') {
                $report += "$p=missing (created by Setup-Arac-GPS-Worker-Secrets.ps1)"
                continue
            }
            throw "Required path missing for SYSTEM access: $p"
        }
        $acl = Get-Acl -LiteralPath $p
        $systemOk = $false
        foreach ($r in $acl.Access) {
            if ($r.IdentityReference.Value -eq 'NT AUTHORITY\SYSTEM' -and $r.AccessControlType -eq 'Allow') {
                $rights = $r.FileSystemRights
                if (($rights -band 'Modify') -eq 'Modify' -or ($rights -band 'FullControl') -eq 'FullControl') {
                    $systemOk = $true
                    break
                }
            }
        }
        $report += "$p=SYSTEM:$systemOk"
        if (-not $systemOk) {
            throw "SYSTEM lacks required access: $p"
        }
    }
    return $report
}

function Test-SecretFileContract {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Secret file missing: $Path"
    }
    $acl = Get-Acl -LiteralPath $Path
    $systemOk = $false
    $adminOk = $false
    $disallowed = @()
    $ignoredMeta = @('CREATOR OWNER', 'NT AUTHORITY\CREATOR OWNER')
    foreach ($r in $acl.Access) {
        if ($r.AccessControlType -ne 'Allow') { continue }
        $id = $r.IdentityReference.Value
        $isFull = ($r.FileSystemRights -band [System.Security.AccessControl.FileSystemRights]::FullControl) -eq `
            [System.Security.AccessControl.FileSystemRights]::FullControl
        if ($id -eq 'NT AUTHORITY\SYSTEM') {
            if ($isFull) { $systemOk = $true }
        }
        elseif ($id -eq 'BUILTIN\Administrators') {
            if ($isFull) { $adminOk = $true }
        }
        elseif ($ignoredMeta -notcontains $id) {
            $disallowed += $id
        }
    }
    if (-not $acl.AreAccessRulesProtected -or -not $systemOk) {
        throw 'Secret file ACL contract not satisfied.'
    }
    $isProduction = ($Path -eq $Script:ProductionSecretFile)
    if ($isProduction) {
        if (-not $adminOk -or $disallowed.Count -gt 0) {
            throw 'Secret file ACL contract not satisfied.'
        }
    }
    return $true
}

function Get-TaskContract {
    param([string]$ResolvedPython)
    $wrapperArg = "-NoProfile -ExecutionPolicy Bypass -File `"$Wrapper`" -PythonExe `"$ResolvedPython`""
    return [ordered]@{
        TaskPath            = $TaskPath
        TaskName            = $TaskName
        Execute             = 'powershell.exe'
        Argument            = $wrapperArg
        WorkingDirectory    = $Root
        Trigger             = 'AtStartup'
        StartWhenAvailable  = $true
        MultipleInstances   = 'IgnoreNew'
        RestartCount        = 3
        RestartIntervalMin  = 1
        InitialState        = 'Disabled'
        PrincipalUserId     = $PrincipalUserId
        LogonType           = 'ServiceAccount'
        RunLevel            = 'Highest'
        SecretSource        = 'DPAPI LocalMachine file (not in task action)'
        SecretFile          = $SecretFile
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
        $diffs += 'Arguments differ'
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
    if (-not $settings.StartWhenAvailable) {
        $diffs += 'StartWhenAvailable: existing=false expected=true'
    }
    $principal = $ExistingTask.Principal
    if ($principal.UserId -ne $Expected.PrincipalUserId) {
        $diffs += "PrincipalUserId: existing=$($principal.UserId) expected=$($Expected.PrincipalUserId)"
    }
    if ($principal.LogonType -ne $Expected.LogonType) {
        $diffs += "LogonType: existing=$($principal.LogonType) expected=$($Expected.LogonType)"
    }
    if ($principal.RunLevel -ne $Expected.RunLevel) {
        $diffs += "RunLevel: existing=$($principal.RunLevel) expected=$($Expected.RunLevel)"
    }
    return $diffs
}

if (-not (Test-Path -LiteralPath $Wrapper -PathType Leaf)) {
    throw "Wrapper script missing: $Wrapper"
}

$resolvedPy = Resolve-RealPythonExe -Path $PythonExe

if (-not $ValidateOnly -and -not (Test-Administrator)) {
    throw 'Administrator privileges required for task registration.'
}

$systemAccess = Test-SystemPathAccessContract
Write-Host ('VALIDATE SystemPathAccess=' + ($systemAccess -join '; '))

if ($ValidateOnly) {
    if (Test-Path -LiteralPath $SecretFile) {
        Test-SecretFileContract -Path $SecretFile | Out-Null
        Write-Host 'VALIDATE SecretFileContract=pass'
    }
    else {
        Write-Host 'VALIDATE SecretFileContract=missing (run Setup-Arac-GPS-Worker-Secrets.ps1 on server)'
    }
}
else {
    Test-SecretFileContract -Path $SecretFile | Out-Null
}

Write-Host 'Running wrapper ValidateOnly...'
$wrapperArgs = @(
    '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $Wrapper,
    '-PythonExe', $resolvedPy, '-ValidateOnly', '-SecretFile', $SecretFile
)
& powershell.exe @wrapperArgs
if ($LASTEXITCODE -ne 0) {
    if ($ValidateOnly -and -not (Test-Path -LiteralPath $SecretFile)) {
        Write-Warning 'Wrapper ValidateOnly skipped — secret file not present yet.'
    }
    else {
        throw "Wrapper ValidateOnly failed with exit code $LASTEXITCODE"
    }
}

$contract = Get-TaskContract -ResolvedPython $resolvedPy

Write-Host '=== TASK CONTRACT ==='
foreach ($pair in $contract.GetEnumerator()) {
    Write-Host ("  {0}={1}" -f $pair.Key, $pair.Value)
}

if ($ValidateOnly) {
    Write-Host 'VALIDATE_ONLY=PASS'
    exit 0
}

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
$Principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest

Register-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName -Action $Action -Trigger $Trigger `
    -Settings $Settings -Principal $Principal `
    -Description 'Solariz CPS Araç GPS Worker — SYSTEM / Filom DPAPI / 60s poll (bounded logs)' | Out-Null
Disable-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName | Out-Null

Write-Host "Task created DISABLED: $FullTaskName"
Get-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName | Select-Object TaskName, State, TaskPath | Format-List
