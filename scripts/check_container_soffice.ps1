param(
    [string]$ComposeFile = "docker-compose.dev.yml",
    [string]$Service = "app"
)

Write-Host "Checking for LibreOffice (soffice/libreoffice) inside container service '$Service'..." -ForegroundColor Cyan

# Disable TTY to allow scripted exec
$cmdCheck = "command -v soffice || command -v libreoffice"
docker compose -f $ComposeFile exec -T $Service bash -lc $cmdCheck | Tee-Object -Variable BinPath

if ([string]::IsNullOrWhiteSpace($BinPath)) {
    Write-Host "Binary not found in PATH. Searching common locations..." -ForegroundColor Yellow
    $findCmd = "find /usr /opt -maxdepth 4 -type f -name 'soffice'"
    docker compose -f $ComposeFile exec -T $Service bash -lc $findCmd
    Write-Host "Check container logs below for additional context." -ForegroundColor Yellow
} else {
    Write-Host "Found binary at: $BinPath" -ForegroundColor Green
    docker compose -f $ComposeFile exec -T $Service bash -lc "$BinPath --version"
}

Write-Host "\nCapturing recent container logs..." -ForegroundColor Cyan
docker compose -f $ComposeFile logs $Service --tail 100
