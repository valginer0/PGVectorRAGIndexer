# Bootstrap script for PGVectorRAGIndexer Desktop App
# Downloads and sets up the desktop app from GitHub

param(
    [string]$GitHubRepo = "valginer0/PGVectorRAGIndexer",
    [string]$Branch = "main",
    [string]$InstallDir = "$env:USERPROFILE\PGVectorRAGIndexer"
)

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "PGVectorRAGIndexer Desktop App Installer" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# Check Python
try {
    $pythonVersion = python --version 2>&1
    Write-Host "✓ Found: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "✗ ERROR: Python is not installed" -ForegroundColor Red
    Write-Host "  Please install from https://www.python.org/downloads/" -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

# Check Git
try {
    $gitVersion = git --version 2>&1
    Write-Host "✓ Found: $gitVersion" -ForegroundColor Green
} catch {
    Write-Host "✗ ERROR: Git is not installed" -ForegroundColor Red
    Write-Host "  Please install from https://git-scm.com/downloads" -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host ""

# Clone or update repository
if (Test-Path $InstallDir) {
    Write-Host "Updating existing installation at: $InstallDir" -ForegroundColor Yellow
    Set-Location $InstallDir
    git pull origin $Branch
} else {
    Write-Host "Installing to: $InstallDir" -ForegroundColor Yellow
    git clone "https://github.com/$GitHubRepo.git" $InstallDir
}

# Change to install directory (after clone completes)
Set-Location $InstallDir

Write-Host ""

# Create virtual environment if needed
if (-not (Test-Path "venv-windows")) {
    Write-Host "Creating virtual environment..." -ForegroundColor Yellow
    python -m venv venv-windows
}

# Install dependencies (don't need to activate for pip install)
Write-Host "Installing dependencies..." -ForegroundColor Yellow
& ".\venv-windows\Scripts\pip.exe" install -q -r requirements-desktop.txt

Write-Host ""
Write-Host "==========================================" -ForegroundColor Green
Write-Host "Installation Complete!" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green
Write-Host ""
Write-Host "To run the desktop app:" -ForegroundColor Cyan
Write-Host "  cd $InstallDir" -ForegroundColor White
Write-Host "  .\venv-windows\Scripts\Activate.ps1" -ForegroundColor White
Write-Host "  python -m desktop_app.main" -ForegroundColor White
Write-Host ""
Write-Host "Or use the shortcut:" -ForegroundColor Cyan
Write-Host "  cd $InstallDir" -ForegroundColor White
Write-Host "  .\run_desktop_app.ps1" -ForegroundColor White
Write-Host ""

# Ask if user wants to run now
$runNow = Read-Host "Would you like to run the app now? (Y/N)"
if ($runNow -eq "Y" -or $runNow -eq "y") {
    Write-Host ""
    Write-Host "Starting desktop app..." -ForegroundColor Green
    & ".\venv-windows\Scripts\python.exe" -m desktop_app.main
}
