# Update Development Docker Containers
# Pulls the :dev image from GHCR and restarts containers

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  Update Development Docker Containers" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# Check if Docker is running
try {
    docker info 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "✗ ERROR: Docker is not running" -ForegroundColor Red
        Write-Host "  Please start Docker Desktop or Rancher Desktop" -ForegroundColor Yellow
        Read-Host "Press Enter to exit"
        exit 1
    }
} catch {
    Write-Host "✗ ERROR: Docker is not available" -ForegroundColor Red
    Write-Host "  Please install Docker Desktop or Rancher Desktop" -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "✓ Docker is running" -ForegroundColor Green
Write-Host ""

# Pull latest :dev image
Write-Host "Pulling latest :dev image from GHCR..." -ForegroundColor Yellow
docker pull ghcr.io/valginer0/pgvectorragindexer:dev
if ($LASTEXITCODE -ne 0) {
    Write-Host "✗ ERROR: Failed to pull image" -ForegroundColor Red
    Write-Host "  Check your internet connection and Docker login" -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host "✓ Image pulled successfully" -ForegroundColor Green
Write-Host ""

# Stop and remove existing containers
Write-Host "Stopping existing containers..." -ForegroundColor Yellow
docker compose down 2>&1 | Out-Null
Write-Host "✓ Containers stopped" -ForegroundColor Green
Write-Host ""

# Start containers with new image
Write-Host "Starting containers with updated image..." -ForegroundColor Yellow
docker compose up -d
if ($LASTEXITCODE -ne 0) {
    Write-Host "✗ ERROR: Failed to start containers" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host "✓ Containers started" -ForegroundColor Green
Write-Host ""

# Wait for health check
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
        # API not ready yet
    }
    
    if (-not $apiReady) {
        Start-Sleep -Seconds 2
        $attempt++
        Write-Host "." -NoNewline
    }
}

Write-Host ""

if ($apiReady) {
    Write-Host "✓ API is ready!" -ForegroundColor Green
} else {
    Write-Host "⚠ WARNING: API health check timed out" -ForegroundColor Yellow
    Write-Host "  The containers are running but may still be initializing" -ForegroundColor Yellow
    Write-Host "  Check logs with: docker compose logs -f" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "==========================================" -ForegroundColor Green
Write-Host "       ✓ Update Complete!" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green
Write-Host ""
Write-Host "API available at: http://localhost:8000" -ForegroundColor Cyan
Write-Host "Web UI at: http://localhost:8000/static/index.html" -ForegroundColor Cyan
Write-Host ""
