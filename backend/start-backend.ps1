$ErrorActionPreference = "Stop"

Set-Location -LiteralPath $PSScriptRoot

$smtpEnvFile = Join-Path $PSScriptRoot "smtp.local.env"
if (Test-Path -LiteralPath $smtpEnvFile) {
    $allowedKeys = @(
        "MOUKE_SMTP_HOST", "MOUKE_SMTP_PORT", "MOUKE_SMTP_USERNAME",
        "MOUKE_SMTP_PASSWORD", "MOUKE_SMTP_FROM", "MOUKE_SMTP_SSL",
        "MOUKE_SMTP_TLS", "MOUKE_DEV_EMAIL_CODES", "MOUKE_CODE_SECRET",
        "MOUKE_VISION_API_URL", "MOUKE_VISION_API_KEY", "MOUKE_VISION_MODEL",
        "MOUKE_ADMIN_STUDENT_ID", "MOUKE_ADMIN_EMAIL", "MOUKE_ADMIN_PASSWORD",
        "DEEPSEEK_API_KEY", "DEEPSEEK_API_URL", "DEEPSEEK_MODEL",
        "SILICONFLOW_API_KEY", "SILICONFLOW_API_URL", "SILICONFLOW_VISION_MODEL",
        "MOUKE_AI_STRICT"
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

$systemPython = Get-Command python -ErrorAction SilentlyContinue
$pythonLauncher = Get-Command py -ErrorAction SilentlyContinue
$codexPython = Join-Path ([Environment]::GetFolderPath('UserProfile')) ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$pythonCandidates = @()

if ($systemPython) {
    $pythonCandidates += $systemPython.Source
}
if (Test-Path -LiteralPath $codexPython) {
    $pythonCandidates += $codexPython
}
if ($pythonLauncher) {
    $pythonCandidates += $pythonLauncher.Source
}

$pythonExecutable = $null
foreach ($candidate in $pythonCandidates) {
    $savedErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $candidate --version *> $null
        if ($LASTEXITCODE -eq 0) {
            $pythonExecutable = $candidate
            break
        }
    } finally {
        $ErrorActionPreference = $savedErrorActionPreference
    }
}

if (-not $pythonExecutable) {
    throw "Python was not found. Install Python 3.11+ and enable Add Python to PATH."
}

$runtimeDirectory = Join-Path $PSScriptRoot ".venv-runtime"
$venvPython = Join-Path $runtimeDirectory "Scripts\python.exe"
$repairDependencies = $false
if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host "Creating the backend virtual environment..." -ForegroundColor Cyan
    & $pythonExecutable -m venv $runtimeDirectory
} else {
    # A failed native command becomes a terminating PowerShell error while
    # ErrorActionPreference is "Stop". Temporarily allow the import probe to
    # fail so its exit code can trigger the repair branch below.
    $savedErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $venvPython -c "import fastapi, pydantic_core, sqlalchemy, uvicorn" 2>$null
        $dependencyCheckExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $savedErrorActionPreference
    }

    if ($dependencyCheckExitCode -ne 0) {
        Write-Host "Repairing backend dependencies..." -ForegroundColor Yellow
        $repairDependencies = $true
    }
}

Write-Host "Installing or checking backend dependencies..." -ForegroundColor Cyan
if ($repairDependencies) {
    & $venvPython -m pip install --upgrade --force-reinstall --ignore-installed -r requirements.txt
} else {
    & $venvPython -m pip install -r requirements.txt
}

# Fail here with a useful traceback instead of printing a URL for a server that
# cannot start.
& $venvPython -c "import fastapi, pydantic_core, sqlalchemy, uvicorn; from click import Choice; import app.main"

Write-Host "Mouke API: http://127.0.0.1:8000" -ForegroundColor Green
Write-Host "API docs: http://127.0.0.1:8000/docs" -ForegroundColor DarkGreen
& $venvPython -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
