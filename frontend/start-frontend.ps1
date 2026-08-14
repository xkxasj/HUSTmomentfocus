$ErrorActionPreference = "Stop"

Set-Location -LiteralPath $PSScriptRoot
$pnpm = Join-Path ([Environment]::GetFolderPath('UserProfile')) ".cache\codex-runtimes\codex-primary-runtime\dependencies\bin\fallback\pnpm.cmd"

if (Get-Command npm -ErrorAction SilentlyContinue) {
    npm install
    npm run dev
} elseif (Test-Path -LiteralPath $pnpm) {
    & $pnpm install
    & $pnpm run dev
} else {
    throw "Node.js/npm was not found. Install the Node.js LTS release first."
}
