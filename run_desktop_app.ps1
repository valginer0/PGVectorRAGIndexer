# PowerShell launch script for PGVectorRAGIndexer Desktop App
# This works with UNC paths (\\wsl.localhost\...)

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "PGVectorRAGIndexer Desktop App" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Note: Works with Docker Desktop or Rancher Desktop" -ForegroundColor Yellow
Write-Host ""

# Get the script directory (works with UNC paths)
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

# Check if Python is installed
try {
    $pythonVersion = python --version 2>&1
    Write-Host "Found: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "ERROR: Python is not installed on Windows or not in PATH" -ForegroundColor Red
    Write-Host "Please install Python from https://www.python.org/downloads/" -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

# Check if virtual environment exists
if (-not (Test-Path "venv-windows")) {
    Write-Host "Creating Windows virtual environment..." -ForegroundColor Yellow
    python -m venv venv-windows
}

# Check if PySide6 is installed
$pyside6Installed = & ".\venv-windows\Scripts\python.exe" -c "import PySide6" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing desktop app dependencies..." -ForegroundColor Yellow
    & ".\venv-windows\Scripts\pip.exe" install -r requirements-desktop.txt
}

Write-Host ""
Write-Host "Starting desktop application..." -ForegroundColor Green
Write-Host ""

# Run the app (use venv python directly, no activation needed)
& ".\venv-windows\Scripts\python.exe" -m desktop_app.main

# Keep window open if there was an error
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Application exited with error code: $LASTEXITCODE" -ForegroundColor Red
    Read-Host "Press Enter to exit"
}
