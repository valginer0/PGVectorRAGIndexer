# PGVectorRAGIndexer One-Click Installer
# Fully automatic installation for Windows
# Usage: Double-click install.bat or run: powershell -ExecutionPolicy Bypass -File installer.ps1

param(
    [switch]$Resume,  # Resume after reboot
    [string]$InstallDir = "$env:USERPROFILE\PGVectorRAGIndexer",
    [string]$StateFile = "$env:USERPROFILE\.pgvector-install-state.json"
)

# ============================================================================
# CONFIGURATION
# ============================================================================

$Script:Steps = @(
    @{ Name = "Checking prerequisites"; Time = "~30 seconds" },
    @{ Name = "Installing Python"; Time = "~2 minutes" },
    @{ Name = "Installing Git"; Time = "~1 minute" },
    @{ Name = "Installing Rancher Desktop"; Time = "~3 minutes" },
    @{ Name = "Starting Docker"; Time = "~2-4 minutes" },
    @{ Name = "Setting up application"; Time = "~2 minutes" }
)

$Script:CurrentStep = 0
$Script:TotalSteps = $Steps.Count

# ============================================================================
# UI HELPER FUNCTIONS
# ============================================================================

function Show-Banner {
    Clear-Host
    Write-Host ""
    Write-Host "  ╔═══════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
    Write-Host "  ║                                                               ║" -ForegroundColor Cyan
    Write-Host "  ║           PGVectorRAGIndexer - One-Click Installer            ║" -ForegroundColor Cyan
    Write-Host "  ║                                                               ║" -ForegroundColor Cyan
    Write-Host "  ╚═══════════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
    Write-Host ""
}

function Show-Step {
    param(
        [int]$StepNumber,
        [string]$Message,
        [string]$TimeEstimate = ""
    )
    
    $Script:CurrentStep = $StepNumber
    $percent = [math]::Round(($StepNumber / $TotalSteps) * 100)
    $barLength = 40
    $filled = [math]::Round($barLength * $StepNumber / $TotalSteps)
    $empty = $barLength - $filled
    $bar = ("█" * $filled) + ("░" * $empty)
    
    Write-Host ""
    Write-Host "  Step $StepNumber of $TotalSteps: $Message" -ForegroundColor Yellow
    if ($TimeEstimate) {
        Write-Host "  Estimated time: $TimeEstimate" -ForegroundColor DarkGray
    }
    Write-Host "  [$bar] $percent%" -ForegroundColor Cyan
    Write-Host ""
}

function Show-Spinner {
    param(
        [string]$Message,
        [scriptblock]$Action,
        [int]$TimeoutSeconds = 300
    )
    
    $spinnerChars = @('⠋','⠙','⠹','⠸','⠼','⠴','⠦','⠧','⠇','⠏')
    $job = Start-Job -ScriptBlock $Action
    $elapsed = 0
    $spinIndex = 0
    
    while ($job.State -eq 'Running' -and $elapsed -lt $TimeoutSeconds) {
        $char = $spinnerChars[$spinIndex % $spinnerChars.Count]
        Write-Host "`r  $char $Message ($elapsed seconds)     " -NoNewline -ForegroundColor Gray
        Start-Sleep -Milliseconds 200
        $elapsed += 0.2
        $spinIndex++
    }
    
    Write-Host "`r                                                              " -NoNewline
    Write-Host "`r"
    
    $result = Receive-Job -Job $job
    Remove-Job -Job $job -Force
    return $result
}

function Show-Success {
    param([string]$Message)
    Write-Host "  ✓ $Message" -ForegroundColor Green
}

function Show-Warning {
    param([string]$Message)
    Write-Host "  ⚠ $Message" -ForegroundColor Yellow
}

function Show-Error {
    param([string]$Message)
    Write-Host "  ✗ $Message" -ForegroundColor Red
}

function Show-Info {
    param([string]$Message)
    Write-Host "  ℹ $Message" -ForegroundColor Cyan
}

# ============================================================================
# STATE MANAGEMENT (for resume after reboot)
# ============================================================================

function Save-State {
    param([string]$Stage)
    
    @{
        Stage = $Stage
        InstallDir = $InstallDir
        Timestamp = Get-Date -Format "o"
    } | ConvertTo-Json | Set-Content $StateFile -Force
}

function Get-SavedState {
    if (Test-Path $StateFile) {
        return Get-Content $StateFile | ConvertFrom-Json
    }
    return $null
}

function Clear-State {
    if (Test-Path $StateFile) {
        Remove-Item $StateFile -Force
    }
    # Remove scheduled task if exists
    Unregister-ScheduledTask -TaskName "PGVectorRAGIndexer_Resume" -Confirm:$false -ErrorAction SilentlyContinue
}

function Schedule-Resume {
    # Create a scheduled task to resume installation after reboot
    $scriptPath = $MyInvocation.ScriptName
    if (-not $scriptPath) {
        $scriptPath = "$InstallDir\installer.ps1"
    }
    
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-ExecutionPolicy Bypass -NoProfile -File `"$scriptPath`" -Resume"
    $trigger = New-ScheduledTaskTrigger -AtLogon -User $env:USERNAME
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    
    Register-ScheduledTask -TaskName "PGVectorRAGIndexer_Resume" -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
    Show-Info "Installation will resume automatically after restart"
}

# ============================================================================
# PREREQUISITE CHECKS AND INSTALLATION
# ============================================================================

function Test-Command {
    param([string]$Command)
    try {
        Get-Command $Command -ErrorAction Stop | Out-Null
        return $true
    } catch {
        return $false
    }
}

function Refresh-Path {
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + 
                [System.Environment]::GetEnvironmentVariable("Path", "User")
}

function Test-WingetAvailable {
    return Test-Command "winget"
}

function Install-WithWinget {
    param(
        [string]$PackageId,
        [string]$Name
    )
    
    Write-Host "  Installing $Name..." -ForegroundColor Gray
    
    $result = winget install $PackageId --silent --accept-package-agreements --accept-source-agreements 2>&1
    
    if ($LASTEXITCODE -eq 0 -or $result -match "already installed") {
        Refresh-Path
        Show-Success "$Name installed"
        return $true
    } else {
        Show-Error "Failed to install $Name"
        return $false
    }
}

function Test-Prerequisites {
    $missing = @()
    
    if (-not (Test-Command "python")) { $missing += "Python" }
    if (-not (Test-Command "git")) { $missing += "Git" }
    if (-not (Test-Command "docker")) { $missing += "Docker (Rancher Desktop)" }
    
    return $missing
}

function Install-Python {
    if (Test-Command "python") {
        $version = python --version 2>&1
        Show-Success "Python already installed: $version"
        return $true
    }
    
    return Install-WithWinget "Python.Python.3.11" "Python 3.11"
}

function Install-Git {
    if (Test-Command "git") {
        $version = git --version 2>&1
        Show-Success "Git already installed: $version"
        return $true
    }
    
    return Install-WithWinget "Git.Git" "Git"
}

function Install-RancherDesktop {
    if (Test-Command "docker") {
        Show-Success "Docker already available"
        return $true
    }
    
    # Check if Rancher is installed but not running
    $rdctl = "$env:LOCALAPPDATA\Programs\Rancher Desktop\resources\resources\win32\bin\rdctl.exe"
    if (Test-Path $rdctl) {
        Show-Success "Rancher Desktop already installed"
        return $true
    }
    
    return Install-WithWinget "suse.RancherDesktop" "Rancher Desktop"
}

# ============================================================================
# RANCHER DESKTOP / DOCKER SETUP
# ============================================================================

function Start-RancherDesktop {
    $rdctl = "$env:LOCALAPPDATA\Programs\Rancher Desktop\resources\resources\win32\bin\rdctl.exe"
    
    if (-not (Test-Path $rdctl)) {
        Show-Error "Rancher Desktop not found at expected location"
        return $false
    }
    
    # Start Rancher Desktop with Docker (moby) engine
    Write-Host "  Starting Rancher Desktop (this may take a few minutes)..." -ForegroundColor Gray
    
    try {
        & $rdctl start --container-engine moby 2>&1 | Out-Null
    } catch {
        # Rancher might prompt for reboot if WSL needs setup
        Show-Warning "Rancher Desktop may need a system restart for WSL setup"
        return $false
    }
    
    return $true
}

function Wait-ForDocker {
    param([int]$TimeoutSeconds = 300)
    
    $elapsed = 0
    $spinnerChars = @('⠋','⠙','⠹','⠸','⠼','⠴','⠦','⠧','⠇','⠏')
    $spinIndex = 0
    
    while ($elapsed -lt $TimeoutSeconds) {
        try {
            $result = docker ps 2>&1
            if ($LASTEXITCODE -eq 0) {
                Write-Host ""
                Show-Success "Docker is ready!"
                return $true
            }
        } catch {}
        
        $char = $spinnerChars[$spinIndex % $spinnerChars.Count]
        $remaining = $TimeoutSeconds - $elapsed
        Write-Host "`r  $char Waiting for Docker to be ready... ($elapsed seconds, timeout in $remaining)   " -NoNewline -ForegroundColor Gray
        
        Start-Sleep -Seconds 5
        $elapsed += 5
        $spinIndex++
    }
    
    Write-Host ""
    Show-Error "Docker did not become ready within $TimeoutSeconds seconds"
    return $false
}

# ============================================================================
# REBOOT HANDLING
# ============================================================================

function Request-Reboot {
    param([string]$Reason = "Installation requires a system restart to continue.")
    
    Save-State -Stage "PostReboot"
    Schedule-Resume
    
    $countdown = 60
    
    Write-Host ""
    Write-Host "  ╔═══════════════════════════════════════════════════════════════╗" -ForegroundColor Yellow
    Write-Host "  ║                    SYSTEM RESTART REQUIRED                    ║" -ForegroundColor Yellow
    Write-Host "  ╚═══════════════════════════════════════════════════════════════╝" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  $Reason" -ForegroundColor White
    Write-Host ""
    Write-Host "  Installation will resume automatically after restart." -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Your computer will restart in $countdown seconds." -ForegroundColor White
    Write-Host ""
    Write-Host "  Press [C] to CANCEL restart (you'll need to restart manually)" -ForegroundColor Green
    Write-Host "  Press [R] to restart NOW" -ForegroundColor Green
    Write-Host ""
    
    $timer = $countdown
    while ($timer -gt 0) {
        if ([Console]::KeyAvailable) {
            $key = [Console]::ReadKey($true)
            if ($key.Key -eq 'C') {
                Write-Host ""
                Show-Warning "Restart cancelled. Please restart manually and the installation will resume."
                return
            }
            if ($key.Key -eq 'R') {
                break
            }
        }
        Write-Host "`r  Restarting in $timer seconds... (Press C to cancel, R to restart now)   " -NoNewline -ForegroundColor Cyan
        Start-Sleep -Seconds 1
        $timer--
    }
    
    Write-Host ""
    Write-Host "  Restarting now..." -ForegroundColor Yellow
    Restart-Computer -Force
}

# ============================================================================
# APPLICATION SETUP
# ============================================================================

function Setup-Application {
    # Clone or update repository
    if (Test-Path "$InstallDir\.git") {
        Write-Host "  Updating existing installation..." -ForegroundColor Gray
        Push-Location $InstallDir
        git reset --hard HEAD 2>&1 | Out-Null
        git pull origin main 2>&1
        Pop-Location
    } else {
        Write-Host "  Cloning repository..." -ForegroundColor Gray
        if (Test-Path $InstallDir) {
            Remove-Item -Recurse -Force $InstallDir
        }
        git clone "https://github.com/valginer0/PGVectorRAGIndexer.git" $InstallDir 2>&1
    }
    
    if (-not (Test-Path $InstallDir)) {
        Show-Error "Failed to clone repository"
        return $false
    }
    
    Show-Success "Repository ready"
    
    # Create virtual environment
    Push-Location $InstallDir
    
    if (-not (Test-Path "venv-windows")) {
        Write-Host "  Creating virtual environment..." -ForegroundColor Gray
        python -m venv venv-windows
    }
    Show-Success "Virtual environment ready"
    
    # Install dependencies
    Write-Host "  Installing Python dependencies..." -ForegroundColor Gray
    & ".\venv-windows\Scripts\pip.exe" install -q -r requirements-desktop.txt
    Show-Success "Dependencies installed"
    
    # Pull Docker images
    Write-Host "  Pulling Docker images (this may take a few minutes)..." -ForegroundColor Gray
    & ".\manage.ps1" -Action update -Channel prod 2>&1 | Out-Null
    Show-Success "Docker containers ready"
    
    # Create desktop shortcut
    if (Test-Path "create_desktop_shortcut.ps1") {
        Write-Host "  Creating desktop shortcut..." -ForegroundColor Gray
        & ".\create_desktop_shortcut.ps1"
        Show-Success "Desktop shortcut created"
    }
    
    Pop-Location
    return $true
}

function Start-Application {
    Push-Location $InstallDir
    
    Write-Host ""
    Write-Host "  ╔═══════════════════════════════════════════════════════════════╗" -ForegroundColor Green
    Write-Host "  ║                   INSTALLATION COMPLETE!                      ║" -ForegroundColor Green
    Write-Host "  ╚═══════════════════════════════════════════════════════════════╝" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Starting PGVectorRAGIndexer..." -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  To run again later, use the Desktop shortcut or run:" -ForegroundColor Gray
    Write-Host "  cd $InstallDir" -ForegroundColor White
    Write-Host "  .\manage.ps1 -Action run" -ForegroundColor White
    Write-Host ""
    
    & ".\venv-windows\Scripts\python.exe" -m desktop_app.main
    
    Pop-Location
}

# ============================================================================
# MAIN INSTALLATION FLOW
# ============================================================================

function Main {
    Show-Banner
    
    # Check if resuming after reboot
    if ($Resume) {
        $state = Get-SavedState
        if ($state -and $state.Stage -eq "PostReboot") {
            Show-Info "Resuming installation after restart..."
            Clear-State
            # Skip to Docker wait and app setup
            Show-Step 5 "Starting Docker" "~2-4 minutes"
            if (-not (Wait-ForDocker -TimeoutSeconds 300)) {
                Show-Error "Docker failed to start. Please check Rancher Desktop."
                Read-Host "Press Enter to exit"
                return
            }
            Show-Step 6 "Setting up application" "~2 minutes"
            if (Setup-Application) {
                Start-Application
            }
            return
        }
    }
    
    # Check for winget
    if (-not (Test-WingetAvailable)) {
        Show-Error "Windows Package Manager (winget) is required but not found."
        Show-Info "Please update Windows or install App Installer from the Microsoft Store."
        Read-Host "Press Enter to exit"
        return
    }
    
    # Phase 1: Check prerequisites
    Show-Step 1 "Checking prerequisites" "~30 seconds"
    $missing = Test-Prerequisites
    if ($missing.Count -gt 0) {
        Show-Info "Missing: $($missing -join ', ')"
        Show-Info "Will install automatically..."
    } else {
        Show-Success "All prerequisites found!"
    }
    
    # Phase 2: Install Python
    Show-Step 2 "Installing Python" "~2 minutes"
    if (-not (Install-Python)) {
        Show-Error "Python installation failed"
        Read-Host "Press Enter to exit"
        return
    }
    
    # Phase 3: Install Git
    Show-Step 3 "Installing Git" "~1 minute"
    if (-not (Install-Git)) {
        Show-Error "Git installation failed"
        Read-Host "Press Enter to exit"
        return
    }
    
    # Phase 4: Install Rancher Desktop
    Show-Step 4 "Installing Rancher Desktop" "~3 minutes"
    if (-not (Install-RancherDesktop)) {
        Show-Error "Rancher Desktop installation failed"
        Read-Host "Press Enter to exit"
        return
    }
    
    # Phase 5: Start Docker
    Show-Step 5 "Starting Docker" "~2-4 minutes"
    
    $dockerStarted = Start-RancherDesktop
    
    if (-not $dockerStarted) {
        # May need reboot for WSL
        Request-Reboot -Reason "Rancher Desktop needs to set up WSL2 (Windows Subsystem for Linux)."
        return
    }
    
    if (-not (Wait-ForDocker -TimeoutSeconds 300)) {
        Show-Warning "Docker is taking longer than expected to start."
        Show-Info "Rancher Desktop may still be initializing. Please wait and try again."
        Read-Host "Press Enter to exit"
        return
    }
    
    # Phase 6: Setup application
    Show-Step 6 "Setting up application" "~2 minutes"
    if (-not (Setup-Application)) {
        Show-Error "Application setup failed"
        Read-Host "Press Enter to exit"
        return
    }
    
    # Clear any saved state
    Clear-State
    
    # Launch the application
    Start-Application
}

# Run main
Main
