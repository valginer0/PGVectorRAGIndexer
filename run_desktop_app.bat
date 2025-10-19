@echo off
REM Launch script for PGVectorRAGIndexer Desktop App on Windows

echo ==========================================
echo PGVectorRAGIndexer Desktop App
echo ==========================================
echo.
echo Note: Works with Docker Desktop or Rancher Desktop
echo.

REM Check if Python is installed on Windows
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed on Windows or not in PATH
    echo Please install Python from https://www.python.org/downloads/
    pause
    exit /b 1
)

REM Check if virtual environment exists
if not exist "venv-windows" (
    echo Creating Windows virtual environment...
    python -m venv venv-windows
)

REM Activate virtual environment
call venv-windows\Scripts\activate.bat

REM Check if PySide6 is installed
python -c "import PySide6" 2>nul
if errorlevel 1 (
    echo Installing desktop app dependencies...
    pip install -r requirements-desktop.txt
)

echo Starting desktop application...
python -m desktop_app.main

pause
