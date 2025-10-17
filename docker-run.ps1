# Standalone Docker Deployment Script for Windows
# Run PGVectorRAGIndexer without cloning the repository
# Pulls pre-built image from GitHub Container Registry

# Requires: Docker Desktop for Windows OR Rancher Desktop

$ErrorActionPreference = "Stop"

Write-Host "============================================================" -ForegroundColor Blue
Write-Host "     PGVectorRAGIndexer - Docker-Only Deployment           " -ForegroundColor Blue
Write-Host "                  (Windows Native)                          " -ForegroundColor Blue
Write-Host "============================================================" -ForegroundColor Blue
Write-Host ""

# Check Docker
try {
    docker --version | Out-Null
} catch {
    Write-Host "[ERROR] Docker not found. Please install a container runtime first." -ForegroundColor Red
    Write-Host "  Docker Desktop: https://www.docker.com/products/docker-desktop" -ForegroundColor Yellow
    Write-Host "  Rancher Desktop: https://rancherdesktop.io/ - free, open-source" -ForegroundColor Yellow
    exit 1
}

# Check if Docker is running
try {
    docker ps | Out-Null
} catch {
    Write-Host "[ERROR] Docker is not running. Please start your container runtime:" -ForegroundColor Red
    Write-Host "  - Docker Desktop: Start from Start menu" -ForegroundColor Yellow
    Write-Host "  - Rancher Desktop: Start from Start menu, ensure 'dockerd (moby)' is selected" -ForegroundColor Yellow
    exit 1
}

# Create deployment directory in user's home
$DeployDir = Join-Path $env:USERPROFILE "pgvector-rag"
if (-not (Test-Path $DeployDir)) {
    New-Item -ItemType Directory -Path $DeployDir | Out-Null
}
Set-Location $DeployDir

Write-Host "Deployment directory: $DeployDir" -ForegroundColor Green
Write-Host ""

# Check for existing containers
$existingContainers = docker ps -a --filter "name=vector_rag_" --format "{{.Names}}"
if ($existingContainers) {
    Write-Host "[WARN] Existing containers found" -ForegroundColor Yellow
    $response = Read-Host "Stop and remove existing containers? (y/N)"
    if ($response -ne 'y' -and $response -ne 'Y') {
        Write-Host "[ERROR] Cannot proceed with existing containers. Exiting." -ForegroundColor Red
        exit 1
    }
    
    Write-Host "Stopping and removing existing containers..." -ForegroundColor Green
    
    # Try docker compose down if compose file exists
    $composeFile = Join-Path $DeployDir "docker-compose.yml"
    if (Test-Path $composeFile) {
        Set-Location $DeployDir
        docker compose down *> $null
    }
    
    # Force remove containers by name
    docker rm -f vector_rag_db vector_rag_app *> $null
    Write-Host "[OK] Cleanup complete" -ForegroundColor Green
}
Write-Host ""

# Create .env file if it doesn't exist
$envFile = Join-Path $DeployDir ".env"
if (-not (Test-Path $envFile)) {
    Write-Host "Creating .env file..." -ForegroundColor Green
    @"
# Database Configuration
POSTGRES_USER=rag_user
POSTGRES_PASSWORD=rag_password
POSTGRES_DB=rag_vector_db
DB_HOST=db
DB_PORT=5432

# Embedding Model
EMBEDDING_MODEL_NAME=all-MiniLM-L6-v2
EMBEDDING_DIMENSION=384

# API Configuration
API_HOST=0.0.0.0
API_PORT=8000
"@ | Out-File -FilePath $envFile -Encoding UTF8
    Write-Host "[OK] Created .env file" -ForegroundColor Green
} else {
    Write-Host "[WARN] .env file already exists" -ForegroundColor Yellow
}

# Create docker-compose.yml
Write-Host "Creating docker-compose.yml..." -ForegroundColor Green
$composeFile = Join-Path $DeployDir "docker-compose.yml"
$composeContent = @'
version: '3.8'

services:
  db:
    image: pgvector/pgvector:pg16
    container_name: vector_rag_db
    restart: always
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - rag_network

  app:
    image: ghcr.io/valginer0/pgvectorragindexer:latest
    container_name: vector_rag_app
    restart: always
    environment:
      DB_HOST: db
      DB_PORT: 5432
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
      API_HOST: ${API_HOST}
      API_PORT: ${API_PORT}
    ports:
      - "${API_PORT}:8000"
    volumes:
      - ./documents:/app/documents
      - model_cache:/root/.cache/huggingface
    depends_on:
      db:
        condition: service_healthy
    networks:
      - rag_network

volumes:
  postgres_data:
  model_cache:

networks:
  rag_network:
    driver: bridge
'@
$composeContent | Out-File -FilePath $composeFile -Encoding UTF8

# Download init-db.sql
Write-Host "Downloading database initialization script..." -ForegroundColor Green
$initDbUrl = "https://raw.githubusercontent.com/valginer0/PGVectorRAGIndexer/main/init-db.sql"
$initDbFile = Join-Path $DeployDir "init-db.sql"
Invoke-WebRequest -Uri $initDbUrl -OutFile $initDbFile

# Create documents directory
$documentsDir = Join-Path $DeployDir "documents"
if (-not (Test-Path $documentsDir)) {
    New-Item -ItemType Directory -Path $documentsDir | Out-Null
}

Write-Host "[OK] Configuration complete" -ForegroundColor Green
Write-Host ""

# Pull latest images
Write-Host "Pulling latest Docker images..." -ForegroundColor Green
Set-Location $DeployDir
docker compose pull

# Start services
Write-Host "Starting services..." -ForegroundColor Green
Set-Location $DeployDir
docker compose up -d

# Wait for database to be ready
Write-Host "Waiting for database to initialize..." -ForegroundColor Green
Start-Sleep -Seconds 5

# Initialize database schema
Write-Host "Initializing database schema..." -ForegroundColor Green
Get-Content $initDbFile | docker exec -i vector_rag_db psql -U rag_user -d rag_vector_db *> $null
Write-Host "[OK] Database ready" -ForegroundColor Green

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "              [OK] Deployment Complete!                     " -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Services:" -ForegroundColor Blue
Write-Host "  API:      http://localhost:8000" -ForegroundColor Yellow
Write-Host "  Docs:     http://localhost:8000/docs" -ForegroundColor Yellow
Write-Host "  Database: localhost:5432" -ForegroundColor Yellow
Write-Host ""
Write-Host "Directories:" -ForegroundColor Blue
Write-Host "  Config:    $DeployDir" -ForegroundColor Yellow
Write-Host "  Documents: $documentsDir" -ForegroundColor Yellow
Write-Host ""
Write-Host "Commands:" -ForegroundColor Blue
Write-Host "  View logs:    docker compose logs -f" -ForegroundColor Yellow
Write-Host "  Stop:         docker compose down" -ForegroundColor Yellow
Write-Host "  Restart:      docker compose restart" -ForegroundColor Yellow
Write-Host "  Update image: docker compose pull; docker compose up -d" -ForegroundColor Yellow
Write-Host ""
Write-Host "Upload files from ANY Windows location:" -ForegroundColor Blue
Write-Host "  curl -X POST http://localhost:8000/upload-and-index ``" -ForegroundColor Yellow
Write-Host "    -F ""file=@C:\Users\YourName\Documents\file.pdf""" -ForegroundColor Yellow
Write-Host ""
Write-Host "Or place documents in: $documentsDir" -ForegroundColor Blue
Write-Host ""
