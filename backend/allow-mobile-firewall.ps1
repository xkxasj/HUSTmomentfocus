$ErrorActionPreference = "Stop"

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run PowerShell as Administrator, then execute this script again."
}

$ruleName = "Mouke Campus API (Local Subnet)"
$existing = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
if ($existing) {
    Enable-NetFirewallRule -DisplayName $ruleName
} else {
    New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8000 -Profile Any -RemoteAddress LocalSubnet | Out-Null
}

Write-Host "Local subnet access to TCP 8000 is enabled." -ForegroundColor Green
