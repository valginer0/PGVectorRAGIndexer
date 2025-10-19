# Running the Desktop App on Windows

The desktop app must be run from **Windows** (not WSL) to access Windows file paths.

## Quick Start

### 1. Install Python on Windows

If you don't have Python installed on Windows:
1. Download from https://www.python.org/downloads/
2. During installation, **check "Add Python to PATH"**
3. Verify: Open PowerShell and run `python --version`

### 2. Run the Desktop App

**From PowerShell (Recommended - works with UNC paths):**

```powershell
cd \\wsl.localhost\Ubuntu\home\valginer0\projects\PGVectorRAGIndexer
.\run_desktop_app.ps1
```

**OR if you have the project on a Windows drive:**

```powershell
cd C:\path\to\PGVectorRAGIndexer
.\run_desktop_app.bat
```

**Note:** The `.ps1` PowerShell script works with UNC paths (`\\wsl.localhost\...`), while the `.bat` file requires a regular Windows path.

This will:
- Create a Windows virtual environment (`venv-windows`)
- Install PySide6 and dependencies
- Launch the desktop app

## How It Works

```
Windows Desktop App (PySide6)
├── Runs on Windows Python
├── Access to Windows file system (C:\, D:\, etc.)
├── Native Windows file picker
└── Communicates with Docker via WSL
    └── Docker containers run in WSL Ubuntu
        ├── PostgreSQL + pgvector
        ├── FastAPI REST API (localhost:8000)
        └── Web UI
```

## Features

- ✅ **Full Windows Path Support** - Select files from C:\, D:\, network drives, etc.
- ✅ **Native File Picker** - Standard Windows file dialog
- ✅ **Docker Management** - Start/stop WSL Docker containers from Windows
- ✅ **Automatic Path Preservation** - Full paths like `C:\Projects\Documents\file.txt` are captured and stored

## Troubleshooting

### "Python is not installed"
- Install Python from https://www.python.org/downloads/
- Make sure to check "Add Python to PATH" during installation

### "Docker is not available"
- Make sure Docker Desktop or Rancher Desktop is running
- Docker containers should be running in WSL Ubuntu
- The app will offer to start them for you
- The app works with both Docker Desktop and Rancher Desktop

### "Can't see Windows files"
- Make sure you're running `run_desktop_app.bat` from Windows, not from WSL
- If you ran `python -m desktop_app.main` from WSL, it will only show WSL files

### File picker shows WSL files instead of Windows
- You're running from WSL. Use `run_desktop_app.bat` from Windows instead

## Manual Installation (Advanced)

If you prefer manual setup:

```powershell
# Create Windows virtual environment
python -m venv venv-windows

# Activate it
.\venv-windows\Scripts\activate

# Install dependencies
pip install -r requirements-desktop.txt

# Run the app
python -m desktop_app.main
```

## Development

The desktop app automatically detects Windows and:
- Uses Windows file paths for file selection
- Calls Docker commands through WSL (`wsl -d Ubuntu -e docker ...`)
- Converts paths between Windows and WSL formats as needed

## Next Steps

After launching the app:
1. Click "Start Containers" if Docker isn't running
2. Wait for API to be ready (green status)
3. Go to Upload tab
4. Click "Select File" - you'll see Windows file picker!
5. Select any file from your Windows drives
6. Upload - the full Windows path is preserved!
