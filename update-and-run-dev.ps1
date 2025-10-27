param(
    [switch]$SkipUpdate
)

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host " Update Dev Containers & Launch Desktop App" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

if (-not $SkipUpdate) {
    Write-Host "[Step 1/2] Pulling :dev image and restarting containers..." -ForegroundColor Yellow
    & "$ScriptDir\update-dev.ps1"
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        Write-Host "✗ Update script failed (exit code: $exitCode). Aborting." -ForegroundColor Red
        exit $exitCode
    }
    Write-Host "[OK] Containers refreshed" -ForegroundColor Green
    Write-Host ""
} else {
    Write-Host "[!] SkipUpdate flag detected - skipping container refresh." -ForegroundColor Yellow
    Write-Host ""
}

Write-Host "[Step 2/2] Launching desktop application..." -ForegroundColor Yellow
& "$ScriptDir\run_desktop_app.ps1"
$appExitCode = $LASTEXITCODE

if ($appExitCode -eq 0) {
    Write-Host ""
    Write-Host "[OK] Desktop app exited cleanly" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "[WARNING] Desktop app exited with code $appExitCode" -ForegroundColor Yellow
}

exit $appExitCode
