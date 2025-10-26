param(
    [string]$ComposeFile = "docker-compose.dev.yml",
    [string]$Service = "app"
)

Write-Host "Checking for LibreOffice (soffice) inside container service '$Service'..." -ForegroundColor Cyan

docker compose -f $ComposeFile exec $Service where.exe soffice
if ($LASTEXITCODE -ne 0) {
    Write-Host "soffice not found via PATH. Inspecting filesystem..." -ForegroundColor Yellow
    docker compose -f $ComposeFile exec $Service powershell -Command "Get-ChildItem -Path C:/ -Recurse -Filter soffice.exe -ErrorAction SilentlyContinue | Select-Object -First 5"
    exit 1
}

Write-Host "Found soffice in PATH. Printing version..." -ForegroundColor Green
docker compose -f $ComposeFile exec $Service soffice --version

Write-Host "Capturing recent container logs..." -ForegroundColor Cyan
docker compose -f $ComposeFile logs $Service --tail 100
