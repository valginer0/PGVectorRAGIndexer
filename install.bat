@echo off
:: PGVectorRAGIndexer One-Click Installer
:: Double-click this file to install!

:: Run PowerShell installer with execution policy bypass
powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0installer.ps1" %*

:: If PowerShell script not found, try downloading it
if errorlevel 1 (
    echo.
    echo Downloading installer...
    powershell -ExecutionPolicy Bypass -NoProfile -Command "irm https://raw.githubusercontent.com/valginer0/PGVectorRAGIndexer/main/installer.ps1 -OutFile '%TEMP%\installer.ps1'; & '%TEMP%\installer.ps1'"
)

pause
