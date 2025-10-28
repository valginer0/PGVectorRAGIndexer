param(
    [ValidateSet("bootstrap", "update", "run", "help")]
    [string]$Action = "help",

    [ValidateSet("prod", "dev")]
    [string]$Channel = "prod",

    [switch]$DryRun,

    [string]$InstallDir
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptRoot

function Show-Usage {
    Write-Host "Usage:" -ForegroundColor Cyan
    Write-Host "  .\\manage.ps1 -Action bootstrap [-Channel prod|dev] [-InstallDir <path>]" -ForegroundColor Yellow
    Write-Host "  .\\manage.ps1 -Action update [-Channel prod|dev] [-DryRun]" -ForegroundColor Yellow
    Write-Host "  .\\manage.ps1 -Action run [-DryRun]" -ForegroundColor Yellow
    Write-Host "" 
    Write-Host "Actions:" -ForegroundColor Cyan
    Write-Host "  bootstrap  Clone or refresh the repository and prepare the desktop app" -ForegroundColor White
    Write-Host "  update     Pull the selected Docker image and restart containers" -ForegroundColor White
    Write-Host "  run        Launch the desktop application" -ForegroundColor White
    Write-Host "  help       Show this message" -ForegroundColor White
}

function Assert-DockerAvailable {
    param(
        [switch]$Skip
    )

    if ($Skip) {
        return
    }

    try {
        docker info 2>&1 | Out-Null
    } catch {
        throw "Docker is not available. Install or start Docker Desktop/Rancher Desktop first."
    }
}

function Invoke-ComposeUpdate {
    param(
        [string]$SelectedChannel,
        [switch]$Preview
    )

    $image = if ($SelectedChannel -eq "dev") { "ghcr.io/valginer0/pgvectorragindexer:dev" } else { "ghcr.io/valginer0/pgvectorragindexer:latest" }
    $envFile = Join-Path $ScriptRoot ".env.manage.tmp"
    $envContent = @("APP_IMAGE=$image")

    Write-Host "Preparing update for channel '$SelectedChannel' (image: $image)" -ForegroundColor Cyan

    if ($Preview) {
        Write-Host "[DRY RUN] docker compose --file docker-compose.yml --env-file $envFile pull" -ForegroundColor Yellow
        Write-Host "[DRY RUN] docker compose --file docker-compose.yml --env-file $envFile down" -ForegroundColor Yellow
        Write-Host "[DRY RUN] docker compose --file docker-compose.yml --env-file $envFile up -d" -ForegroundColor Yellow
        return
    }

    try {
        $envContent | Set-Content -Path $envFile -Encoding UTF8
        docker compose --file "docker-compose.yml" --env-file $envFile pull
        docker compose --file "docker-compose.yml" --env-file $envFile down
        docker compose --file "docker-compose.yml" --env-file $envFile up -d
    }
    finally {
        Remove-Item -Path $envFile -ErrorAction SilentlyContinue
    }

    Write-Host "Waiting for API to be ready..." -ForegroundColor Yellow
    $maxAttempts = 30
    $attempt = 0
    $apiReady = $false

    while ($attempt -lt $maxAttempts -and -not $apiReady) {
        try {
            $response = Invoke-WebRequest -Uri "http://localhost:8000/health" -TimeoutSec 2 -ErrorAction SilentlyContinue
            if ($response.StatusCode -eq 200) {
                $apiReady = $true
            }
        }
        catch {
            # ignore and retry
        }

        if (-not $apiReady) {
            Start-Sleep -Seconds 2
            $attempt++
            Write-Host "." -NoNewline
        }
    }

    Write-Host ""

    if ($apiReady) {
        Write-Host "[OK] API is ready!" -ForegroundColor Green
    } else {
        Write-Host "[WARNING] API health check timed out. Containers may still be initializing." -ForegroundColor Yellow
        Write-Host "  Tip: docker compose logs -f" -ForegroundColor Yellow
    }
}

function Invoke-Bootstrap {
    param(
        [string]$SelectedChannel,
        [string]$TargetDir,
        [switch]$Preview
    )

    $bootstrapScript = Join-Path $ScriptRoot "bootstrap_desktop_app.ps1"
    if (-not (Test-Path $bootstrapScript)) {
        throw "bootstrap_desktop_app.ps1 not found at $bootstrapScript"
    }

    $args = @()
    if ($TargetDir) {
        $args += "-InstallDir", $TargetDir
    }
    $args += "-Channel", $SelectedChannel
    if ($Preview) {
        Write-Host "[DRY RUN] \"$bootstrapScript\" $($args -join ' ')" -ForegroundColor Yellow
    } else {
        & $bootstrapScript @args
    }
}

function Invoke-RunDesktopApp {
    param(
        [switch]$Preview
    )

    $runScript = Join-Path $ScriptRoot "run_desktop_app.ps1"
    if (-not (Test-Path $runScript)) {
        throw "run_desktop_app.ps1 not found at $runScript"
    }

    if ($Preview) {
        Write-Host "[DRY RUN] \"$runScript\"" -ForegroundColor Yellow
    } else {
        & $runScript
    }
}

switch ($Action.ToLowerInvariant()) {
    "bootstrap" {
        Invoke-Bootstrap -SelectedChannel $Channel -TargetDir $InstallDir -Preview:$DryRun
    }
    "update" {
        Assert-DockerAvailable -Skip:$DryRun
        Invoke-ComposeUpdate -SelectedChannel $Channel -Preview:$DryRun
    }
    "run" {
        Invoke-RunDesktopApp -Preview:$DryRun
    }
    default {
        Show-Usage
    }
}
