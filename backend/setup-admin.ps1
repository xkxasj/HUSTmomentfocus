$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$studentId = (Read-Host "Admin login ID (recommended: MOUKEADMIN)").Trim().ToUpperInvariant()
$email = (Read-Host "Admin contact email").Trim().ToLowerInvariant()
if ($studentId -notmatch '^[A-Z0-9]{6,20}$') { throw "The login ID must contain 6-20 letters or digits." }
if ($email -notmatch '^[^\s@]+@[^\s@]+\.[^\s@]+$') { throw "Enter a valid email address." }

function Read-PlainPassword([string]$Prompt) {
    $secure = Read-Host $Prompt -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
}

$password = Read-PlainPassword "Admin password (12+ characters, hidden)"
$confirmation = Read-PlainPassword "Enter the admin password again"
if ($password.Length -lt 12) { throw "The admin password must be at least 12 characters." }
if ($password -cne $confirmation) { throw "The passwords do not match." }

$envFile = Join-Path $PSScriptRoot "smtp.local.env"
$lines = if (Test-Path -LiteralPath $envFile) { [Collections.Generic.List[string]](Get-Content -LiteralPath $envFile -Encoding utf8) } else { [Collections.Generic.List[string]]::new() }

function Set-EnvValue([string]$Key, [string]$Value) {
    for ($index = 0; $index -lt $lines.Count; $index++) {
        if ($lines[$index] -match "^$([regex]::Escape($Key))=") {
            $lines[$index] = "$Key=$Value"
            return
        }
    }
    $lines.Add("$Key=$Value")
}

Set-EnvValue "MOUKE_ADMIN_STUDENT_ID" $studentId
Set-EnvValue "MOUKE_ADMIN_EMAIL" $email
Set-EnvValue "MOUKE_ADMIN_PASSWORD" $password
[IO.File]::WriteAllLines($envFile, $lines, [Text.UTF8Encoding]::new($false))

Write-Host "Admin credentials saved to the local secret file. Restart the backend to apply them." -ForegroundColor Green
Write-Host "Admin URL: http://127.0.0.1:5173/#/admin" -ForegroundColor DarkGreen
