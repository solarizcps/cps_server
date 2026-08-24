#Requires -Version 5.1
<#
.SYNOPSIS
  Store Filom credentials for GPS worker using DPAPI LocalMachine.

.DESCRIPTION
  Username/password are interactive only (Read-Host). Never pass on command line.
  Encrypted output: C:\ProgramData\Solariz\secrets\arac_gps_worker.dpapi

.PARAMETER BaseUrl
  Filom API base URL (non-secret, may be supplied as parameter).

.PARAMETER ValidateOnly
  Verify secret file existence, ACL, DPAPI decrypt, and field presence.

.PARAMETER Replace
  Replace existing secret file after explicit YES confirmation.

.PARAMETER SecretFile
  Override secret file path (testing only; default is production path).
#>
[CmdletBinding()]
param(
    [string]$BaseUrl = 'https://filom.turkcell.com.tr/api',

    [switch]$ValidateOnly,

    [switch]$Replace,

    [string]$SecretFile = 'C:\ProgramData\Solariz\secrets\arac_gps_worker.dpapi'
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Security

$Script:SecretDir = Split-Path -Parent $SecretFile
$Script:DpapiEntropy = [System.Text.Encoding]::UTF8.GetBytes('Solariz.CPS.AracGPSWorker.DPAPI.v1')
$Script:ProductionSecretFile = 'C:\ProgramData\Solariz\secrets\arac_gps_worker.dpapi'
$Script:FilomFieldNames = @(
    'TURKCELL_FILOM_BASE_URL',
    'TURKCELL_FILOM_USERNAME',
    'TURKCELL_FILOM_PASSWORD'
)

function Test-Administrator {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-SecretFileAclReport {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return [ordered]@{
            Exists             = $false
            InheritanceDisabled = $false
            SystemFullControl  = $false
            AdminFullControl   = $false
            OtherAccess        = @()
        }
    }
    $acl = Get-Acl -LiteralPath $Path
    $rules = $acl.Access
    $systemOk = $false
    $adminOk = $false
    $disallowed = @()
    $ignoredMeta = @('CREATOR OWNER', 'NT AUTHORITY\CREATOR OWNER')
    foreach ($r in $rules) {
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
    return [ordered]@{
        Exists              = $true
        InheritanceDisabled = $acl.AreAccessRulesProtected
        SystemFullControl   = $systemOk
        AdminFullControl    = $adminOk
        OtherAccess         = $disallowed
    }
}

function Set-SecretFileAcl {
    param([string]$Path)
    $acl = Get-Acl -LiteralPath $Path
    $acl.SetAccessRuleProtection($true, $false)
    $acl.SetOwner([System.Security.Principal.NTAccount]'BUILTIN\Administrators')
    foreach ($r in @($acl.Access)) { $null = $acl.RemoveAccessRule($r) }
    $acl.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule(
        'NT AUTHORITY\SYSTEM', 'FullControl', 'Allow')))
    $acl.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule(
        'BUILTIN\Administrators', 'FullControl', 'Allow')))
    Set-Acl -LiteralPath $Path -AclObject $acl
}

function Protect-FilomPayload {
    param([hashtable]$Payload)
    $json = ($Payload | ConvertTo-Json -Compress)
    $plainBytes = [System.Text.Encoding]::UTF8.GetBytes($json)
    try {
        return [System.Security.Cryptography.ProtectedData]::Protect(
            $plainBytes,
            $Script:DpapiEntropy,
            [System.Security.Cryptography.DataProtectionScope]::LocalMachine
        )
    }
    finally {
        if ($plainBytes) { [Array]::Clear($plainBytes, 0, $plainBytes.Length) }
    }
}

function Unprotect-FilomPayload {
    param([byte[]]$ProtectedBytes)
    $plainBytes = [System.Security.Cryptography.ProtectedData]::Unprotect(
        $ProtectedBytes,
        $Script:DpapiEntropy,
        [System.Security.Cryptography.DataProtectionScope]::LocalMachine
    )
    try {
        $json = [System.Text.Encoding]::UTF8.GetString($plainBytes)
        $obj = $json | ConvertFrom-Json
        return [ordered]@{
            TURKCELL_FILOM_BASE_URL  = [string]$obj.TURKCELL_FILOM_BASE_URL
            TURKCELL_FILOM_USERNAME  = [string]$obj.TURKCELL_FILOM_USERNAME
            TURKCELL_FILOM_PASSWORD  = [string]$obj.TURKCELL_FILOM_PASSWORD
        }
    }
    finally {
        if ($plainBytes) { [Array]::Clear($plainBytes, 0, $plainBytes.Length) }
    }
}

function Test-FilomPayloadComplete {
    param($Payload)
    $missing = @()
    foreach ($n in $Script:FilomFieldNames) {
        if (-not $Payload.$n -or [string]::IsNullOrWhiteSpace([string]$Payload.$n)) {
            $missing += $n
        }
    }
    return $missing
}

function ConvertTo-PlainSecureString {
    param([System.Security.SecureString]$Secure)
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
}

function Invoke-SecretValidateOnly {
    param([string]$Path)
    $aclReport = Get-SecretFileAclReport -Path $Path
    Write-Host ("VALIDATE SecretFile={0}" -f $Path)
    Write-Host ("VALIDATE SecretFileExists={0}" -f $aclReport.Exists)
    if (-not $aclReport.Exists) {
        throw 'Secret file missing.'
    }
    Write-Host ("VALIDATE AclInheritanceDisabled={0}" -f $aclReport.InheritanceDisabled)
    Write-Host ("VALIDATE AclSystemFullControl={0}" -f $aclReport.SystemFullControl)
    Write-Host ("VALIDATE AclAdminFullControl={0}" -f $aclReport.AdminFullControl)
    Write-Host ("VALIDATE AclOtherAccessCount={0}" -f $aclReport.OtherAccess.Count)
    if (-not $aclReport.InheritanceDisabled -or -not $aclReport.SystemFullControl) {
        throw 'Secret file ACL contract not satisfied.'
    }
    $isProduction = ($Path -eq $Script:ProductionSecretFile)
    if ($isProduction) {
        if (-not $aclReport.AdminFullControl) {
            throw 'Secret file ACL contract not satisfied.'
        }
        if ($aclReport.OtherAccess.Count -gt 0) {
            throw 'Unexpected ACL entries on secret file.'
        }
    }
    $protected = [System.IO.File]::ReadAllBytes($Path)
    $payload = Unprotect-FilomPayload -ProtectedBytes $protected
    $missing = Test-FilomPayloadComplete -Payload $payload
    foreach ($n in $Script:FilomFieldNames) {
        $present = ($missing -notcontains $n)
        Write-Host ("VALIDATE FieldPresent {0}={1}" -f $n, $(if ($present) { 'yes' } else { 'no' }))
    }
    if ($missing.Count -gt 0) {
        throw ("Secret payload incomplete: {0}" -f ($missing -join ', '))
    }
    Write-Host 'VALIDATE DpapiScope=LocalMachine'
    Write-Host 'VALIDATE DpapiEntropy=Solariz.CPS.AracGPSWorker.DPAPI.v1'
    Write-Host 'VALIDATE_ONLY=PASS'
}

# --- Main ---
if ($ValidateOnly) {
    Invoke-SecretValidateOnly -Path $SecretFile
    exit 0
}

if (-not (Test-Administrator)) {
    throw 'Administrator privileges required for Setup/Replace.'
}

if (Test-Path -LiteralPath $SecretFile) {
    if (-not $Replace) {
        throw 'Secret file already exists. Use -Replace with interactive YES confirmation to rotate.'
    }
    $confirm = Read-Host 'Existing secret file will be replaced. Type YES to confirm'
    if ($confirm -ne 'YES') {
        throw 'Replace aborted.'
    }
}

if ([string]::IsNullOrWhiteSpace($BaseUrl)) {
    $BaseUrl = Read-Host 'Filom Base URL'
}
$username = Read-Host 'Filom Username'
$securePassword = Read-Host 'Filom Password' -AsSecureString
if ([string]::IsNullOrWhiteSpace($username)) {
    throw 'Username cannot be empty.'
}
if (-not $securePassword -or $securePassword.Length -eq 0) {
    throw 'Password cannot be empty.'
}

$plainPassword = ConvertTo-PlainSecureString -Secure $securePassword
$securePassword.Dispose()
try {
    $payload = [ordered]@{
        TURKCELL_FILOM_BASE_URL = $BaseUrl.Trim()
        TURKCELL_FILOM_USERNAME = $username.Trim()
        TURKCELL_FILOM_PASSWORD = $plainPassword
    }
    $protectedBytes = Protect-FilomPayload -Payload $payload
}
finally {
    if ($plainPassword) { $plainPassword = $null }
}

New-Item -ItemType Directory -Force -Path $Script:SecretDir | Out-Null
[System.IO.File]::WriteAllBytes($SecretFile, $protectedBytes)
Set-SecretFileAcl -Path $SecretFile

Write-Host 'SETUP SecretFile=created'
Write-Host ("VALIDATE SecretFile={0}" -f $SecretFile)
foreach ($n in $Script:FilomFieldNames) {
    Write-Host ("VALIDATE FieldPresent {0}=yes" -f $n)
}
Write-Host 'SETUP_ONLY=PASS'
