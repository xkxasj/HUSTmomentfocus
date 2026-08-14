$ErrorActionPreference = "Stop"

Set-Location -LiteralPath $PSScriptRoot

$smtpEnvFile = Join-Path $PSScriptRoot "smtp.local.env"
if (Test-Path -LiteralPath $smtpEnvFile) {
    $allowedKeys = @(
        "MOUKE_SMTP_HOST", "MOUKE_SMTP_PORT", "MOUKE_SMTP_USERNAME",
        "MOUKE_SMTP_PASSWORD", "MOUKE_SMTP_FROM", "MOUKE_SMTP_SSL",
        "MOUKE_SMTP_TLS", "MOUKE_DEV_EMAIL_CODES", "MOUKE_CODE_SECRET",
        "MOUKE_VISION_API_URL", "MOUKE_VISION_API_KEY", "MOUKE_VISION_MODEL"
    )
    foreach ($line in Get-Content -LiteralPath $smtpEnvFile -Encoding utf8) {
        if (-not $line -or $line.TrimStart().StartsWith("#") -or -not $line.Contains("=")) { continue }
        $key, $value = $line.Split("=", 2)
        $key = $key.Trim()
        if ($allowedKeys -contains $key) {
            [Environment]::SetEnvironmentVariable($key, $value.Trim(), "Process")
        }
    }
    Write-Host "Loaded local SMTP configuration." -ForegroundColor DarkGreen
} else {
    Write-Host "SMTP is not configured; real registration email is disabled." -ForegroundColor Yellow
}

$pythonExecutable = $null
$systemPython = Get-Command python -ErrorAction SilentlyContinue
$pythonLauncher = Get-Command py -ErrorAction SilentlyContinue
$codexPython = Join-Path ([Environment]::GetFolderPath('UserProfile')) ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if ($systemPython) {
    $pythonExecutable = $systemPython.Source
} elseif ($pythonLauncher) {
    $pythonExecutable = $pythonLauncher.Source
} elseif (Test-Path -LiteralPath $codexPython) {
    $pythonExecutable = $codexPython
} else {
    throw "Python was not found. Install Python 3.11+ and enable Add Python to PATH."
}

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host "Creating the backend virtual environment..." -ForegroundColor Cyan
    & $pythonExecutable -m venv .venv
}

Write-Host "Installing or checking backend dependencies..." -ForegroundColor Cyan
& $venvPython -m pip install -r requirements.txt

Write-Host "Mouke API: http://127.0.0.1:8000" -ForegroundColor Green
Write-Host "API docs: http://127.0.0.1:8000/docs" -ForegroundColor DarkGreen
& $venvPython -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
