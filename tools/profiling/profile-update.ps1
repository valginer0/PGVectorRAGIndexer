param(
    [ValidateSet("prod", "dev")]
    [string]$Channel = "prod",

    [switch]$SkipHealthCheck
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Section {
    param(
        [string]$Message
    )
    Write-Host "`n=== $Message ===" -ForegroundColor Cyan
}

function Measure-Step {
    param(
        [string]$Name,
        [scriptblock]$Action
    )

    Write-Host ("{0,-25}" -f $Name) -NoNewline
    $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        & $Action
        $stopwatch.Stop()
        Write-Host (" {0,6:N2}s" -f $stopwatch.Elapsed.TotalSeconds) -ForegroundColor Green
    }
    catch {
        $stopwatch.Stop()
        Write-Host (" {0,6:N2}s (FAILED)" -f $stopwatch.Elapsed.TotalSeconds) -ForegroundColor Red
        throw
    }
    return $stopwatch.Elapsed
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptRoot ".." "..")
Set-Location $repoRoot

Write-Host "Profiling update workflow (channel: $Channel)" -ForegroundColor Yellow

# Validate tooling
Measure-Step "docker info" { docker info | Out-Null } | Out-Null

$totalStopwatch = [System.Diagnostics.Stopwatch]::StartNew()

$envFile = Join-Path $repoRoot ".env.manage.profile.tmp"

try {
    if ($Channel -eq "dev") {
        Write-Section "Development channel"
        Measure-Step "docker compose down" { docker compose -f docker-compose.dev.yml down }
        Measure-Step "docker compose up" { docker compose -f docker-compose.dev.yml up -d --build }
    }
    else {
        Write-Section "Production channel"
        "APP_IMAGE=ghcr.io/valginer0/pgvectorragindexer:latest" | Set-Content -Path $envFile -Encoding UTF8
        Measure-Step "compose pull" { docker compose --file docker-compose.yml --env-file $envFile pull }
        Measure-Step "compose down" { docker compose --file docker-compose.yml --env-file $envFile down }
        Measure-Step "compose up" { docker compose --file docker-compose.yml --env-file $envFile up -d }
    }

    if (-not $SkipHealthCheck) {
        Write-Section "API health check"
        $maxAttempts = 30
        $attempt = 0
        $apiReady = $false
        $elapsedHealth = Measure-Step "wait for /health" {
            while ($attempt -lt $maxAttempts -and -not $apiReady) {
                try {
                    $response = Invoke-WebRequest -Uri "http://localhost:8000/health" -TimeoutSec 2 -ErrorAction Stop
                    if ($response.StatusCode -eq 200) {
                        $apiReady = $true
                        break
                    }
                }
                catch {
                    Start-Sleep -Seconds 2
                    $attempt++
                }
            }
            if (-not $apiReady) {
                throw "Health check timed out after $maxAttempts attempts"
            }
        }
        Write-Host ("API ready in {0:N2}s" -f $elapsedHealth.TotalSeconds) -ForegroundColor Green
    }
    else {
        Write-Host "Skipping health check" -ForegroundColor Yellow
    }
}
finally {
    if (Test-Path $envFile) {
        Remove-Item $envFile -Force
    }
}

$totalStopwatch.Stop()
Write-Section "Summary"
Write-Host ("Total elapsed: {0:N2}s" -f $totalStopwatch.Elapsed.TotalSeconds) -ForegroundColor Magenta
