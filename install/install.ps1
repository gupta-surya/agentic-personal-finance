# Bootstrap installer for the finance CLI (Windows PowerShell).
# Read this script before running it. It installs uv (if missing), installs the
# finance tool, then starts guided setup. Nothing here contacts your bank; that
# happens inside `finance setup`, which you control.
$ErrorActionPreference = "Stop"

$Repo = if ($env:FINANCE_REPO) { $env:FINANCE_REPO } else {
  "https://github.com/gupta-surya/agentic-personal-finance.git"
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  Write-Host "Installing uv (https://astral.sh/uv) ..."
  Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
}

Write-Host "Installing the finance tool ..."
uv tool install "git+$Repo"

Write-Host "Starting guided setup ..."
finance setup
