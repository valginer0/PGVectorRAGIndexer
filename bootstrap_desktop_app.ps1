# Bootstrap script for PGVectorRAGIndexer Desktop App
# Downloads and sets up the desktop app from GitHub

param(
    [string]$GitHubRepo = "valginer0/PGVectorRAGIndexer",
    [string]$Branch = "main",
    [string]$InstallDir = "$env:USERPROFILE\PGVectorRAGIndexer",
    [ValidateSet("prod", "dev")]
    [string]$Channel = "prod",
    [string]$RemoteBackend = ""
)

function Get-EffectiveOverride {
    param(
        [string]$Name,
        [string]$DefaultValue
    )

    $value = [Environment]::GetEnvironmentVariable($Name, "Process")
    if (-not [string]::IsNullOrWhiteSpace($value)) {
        return $value
    }

    $value = [Environment]::GetEnvironmentVariable($Name, "User")
    if (-not [string]::IsNullOrWhiteSpace($value)) {
        return $value
    }

    return $DefaultValue
}

$RepoRef = Get-EffectiveOverride -Name "PGVECTOR_REPO_REF" -DefaultValue $Branch

function Update-RepoRef {
    param(
        [string]$Ref
    )

    Write-Host "Backend source ref: $Ref" -ForegroundColor Cyan
    git fetch origin
    if ($LASTEXITCODE -ne 0) {
        return $false
    }

    git checkout $Ref
    if ($LASTEXITCODE -ne 0) {
        return $false
    }

    git show-ref --verify --quiet "refs/remotes/origin/$Ref"
    if ($LASTEXITCODE -eq 0) {
        git pull origin $Ref
        return ($LASTEXITCODE -eq 0)
    }

    Write-Host "Using detached/tag/SHA ref without pull: $Ref" -ForegroundColor Cyan
    return $true
}

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
    # Check if it's a valid git repository
    if (Test-Path "$InstallDir\.git") {
        Write-Host "Updating existing installation at: $InstallDir" -ForegroundColor Yellow
        Set-Location $InstallDir
        
        # Reset any local changes and pull
        git reset --hard HEAD 2>&1 | Out-Null
        if (-not (Update-RepoRef -Ref $RepoRef)) {
            Write-Host "✗ ERROR: Failed to update repository" -ForegroundColor Red
            Write-Host "  Removing corrupted installation and retrying..." -ForegroundColor Yellow
            Set-Location ..
            Remove-Item -Recurse -Force $InstallDir
            git clone "https://github.com/$GitHubRepo.git" $InstallDir
            if ($LASTEXITCODE -ne 0) {
                Write-Host "✗ ERROR: Failed to clone repository" -ForegroundColor Red
                Read-Host "Press Enter to exit"
                exit 1
            }
            Set-Location $InstallDir
            if (-not (Update-RepoRef -Ref $RepoRef)) {
                Write-Host "✗ ERROR: Failed to prepare repository ref: $RepoRef" -ForegroundColor Red
                Read-Host "Press Enter to exit"
                exit 1
            }
        }
    } else {
        # Directory exists but is not a git repo - remove and clone fresh
        Write-Host "Removing incomplete installation at: $InstallDir" -ForegroundColor Yellow
        Remove-Item -Recurse -Force $InstallDir
        Write-Host "Installing to: $InstallDir" -ForegroundColor Yellow
        git clone "https://github.com/$GitHubRepo.git" $InstallDir
        if ($LASTEXITCODE -ne 0) {
            Write-Host "✗ ERROR: Failed to clone repository" -ForegroundColor Red
            Read-Host "Press Enter to exit"
            exit 1
        }
        Set-Location $InstallDir
        if (-not (Update-RepoRef -Ref $RepoRef)) {
            Write-Host "✗ ERROR: Failed to prepare repository ref: $RepoRef" -ForegroundColor Red
            Read-Host "Press Enter to exit"
            exit 1
        }
    }
} else {
    Write-Host "Installing to: $InstallDir" -ForegroundColor Yellow
    git clone "https://github.com/$GitHubRepo.git" $InstallDir
    if ($LASTEXITCODE -ne 0) {
        Write-Host "✗ ERROR: Failed to clone repository" -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
    Set-Location $InstallDir
    if (-not (Update-RepoRef -Ref $RepoRef)) {
        Write-Host "✗ ERROR: Failed to prepare repository ref: $RepoRef" -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
}

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

# Update Docker containers if manage.ps1 exists (skip in remote mode)
if (-not $RemoteBackend) {
    $manageScript = ".\manage.ps1"
    if (Test-Path $manageScript) {
        Write-Host "Updating Docker containers (channel: $Channel)..." -ForegroundColor Yellow
        & $manageScript -Action update -Channel $Channel
        Write-Host ""
    }
}

# Pre-seed remote backend configuration if -RemoteBackend was provided
if ($RemoteBackend) {
    Write-Host "Configuring remote backend: $RemoteBackend" -ForegroundColor Yellow
    & ".\venv-windows\Scripts\python.exe" -c @"
import sys; sys.path.insert(0, '.')
from desktop_app.utils import app_config
app_config.set_backend_mode(app_config.BACKEND_MODE_REMOTE)
app_config.set_backend_url('$RemoteBackend')
print('  Remote backend configured')
print('  Note: Enter your API key in the Settings tab')
"@
    Write-Host ""
}

# Create desktop shortcut
if (Test-Path "create_desktop_shortcut.ps1") {
    Write-Host "Creating Desktop Shortcut..." -ForegroundColor Yellow
    & ".\create_desktop_shortcut.ps1"
}

Write-Host "=========================================" -ForegroundColor Green
Write-Host "Installation Complete!" -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Green
Write-Host ""
if ($RemoteBackend) {
    Write-Host "Remote backend: $RemoteBackend" -ForegroundColor Cyan
    Write-Host "Open Settings tab to enter your API key." -ForegroundColor Cyan
    Write-Host ""
}
Write-Host "To run the desktop app:" -ForegroundColor Cyan
Write-Host "  cd $InstallDir" -ForegroundColor White
Write-Host "  .\venv-windows\Scripts\Activate.ps1" -ForegroundColor White
Write-Host "  python -m desktop_app.main" -ForegroundColor White
Write-Host ""
Write-Host "Or use the shortcut:" -ForegroundColor Cyan
Write-Host "  cd $InstallDir" -ForegroundColor White
Write-Host "  .\run_desktop_app.ps1" -ForegroundColor White
Write-Host ""

# Auto-start the desktop app
Write-Host "Starting desktop app..." -ForegroundColor Green
& ".\venv-windows\Scripts\python.exe" -m desktop_app.main
