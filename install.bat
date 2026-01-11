@echo off
title PGVectorRAGIndexer Installer
echo.
echo ============================================
echo   PGVectorRAGIndexer One-Click Installer
echo ============================================
echo.
echo Downloading installer script...
echo.

:: Download and run the PowerShell installer
powershell -ExecutionPolicy Bypass -NoProfile -Command ^
    "try { " ^
    "  $ProgressPreference = 'SilentlyContinue'; " ^
    "  Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/valginer0/PGVectorRAGIndexer/main/installer.ps1' -OutFile '%TEMP%\installer.ps1' -UseBasicParsing; " ^
    "  Write-Host 'Starting installation...' -ForegroundColor Green; " ^
    "  & '%TEMP%\installer.ps1' " ^
    "} catch { " ^
    "  Write-Host 'Error downloading installer: ' $_.Exception.Message -ForegroundColor Red; " ^
    "  Read-Host 'Press Enter to exit' " ^
    "}"

:: If we get here, something went wrong
if errorlevel 1 (
    echo.
    echo Installation encountered an error.
    pause
)

