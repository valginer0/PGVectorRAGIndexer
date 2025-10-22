# Desktop App Installation Guide

## One-Line Install (Recommended)

**From Windows PowerShell (as Administrator or with execution policy set):**

```powershell
irm https://raw.githubusercontent.com/valginer0/PGVectorRAGIndexer/main/bootstrap_desktop_app.ps1 | iex
```

This will:
1. ✅ Check for Python and Git
2. ✅ Clone the repository to `%USERPROFILE%\PGVectorRAGIndexer`
3. ✅ Create virtual environment
4. ✅ Install dependencies
5. ✅ Auto-start the desktop app after setup (no interactive prompt)

**If you get "execution policy" error:**
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```
Then run the install command again.

---

## Alternative: Manual Installation

### Option 1: Clone to Windows Directory

```powershell
# Clone to your home directory
cd $env:USERPROFILE
git clone https://github.com/valginer0/PGVectorRAGIndexer.git
cd PGVectorRAGIndexer

# Create virtual environment
python -m venv venv-windows

# Activate and install
.\venv-windows\Scripts\Activate.ps1
pip install -r requirements-desktop.txt

# Run the app
python -m desktop_app.main
```

### Option 2: Use WSL Path (More Complex)

If you want to run from the WSL directory:

```powershell
# Navigate to WSL path
cd \\wsl.localhost\Ubuntu\home\valginer0\projects\PGVectorRAGIndexer

# Set execution policy (one-time)
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

# Run the PowerShell launcher
.\run_desktop_app.ps1
```

**Note:** This requires the execution policy change and works from UNC paths.

---

## Requirements

- **Python 3.10+** - [Download](https://www.python.org/downloads/)
  - ⚠️ During install, check "Add Python to PATH"
- **Git** (for one-line install) - [Download](https://git-scm.com/downloads)
- **Docker Desktop or Rancher Desktop** - For the backend

---

## Quick Start After Installation

### First Time Setup

1. **Start Docker/Rancher Desktop**
2. **Start the backend containers:**
   ```bash
   # From WSL
   cd /home/valginer0/projects/PGVectorRAGIndexer
   docker compose up -d
   ```
3. **Run the desktop app:**
   ```powershell
   # From Windows
   cd %USERPROFILE%\PGVectorRAGIndexer
   .\run_desktop_app.ps1
   ```

### Daily Use

```powershell
cd %USERPROFILE%\PGVectorRAGIndexer
.\run_desktop_app.ps1
```

Or create a desktop shortcut to `run_desktop_app.ps1`!

---

## Troubleshooting

### "Python is not installed"
- Install Python from https://www.python.org/downloads/
- Make sure to check "Add Python to PATH" during installation
- Restart PowerShell after installing

### "Git is not installed"
- Install Git from https://git-scm.com/downloads/
- Restart PowerShell after installing

### "Scripts disabled" / Execution Policy Error
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### "Docker is not available"
- Start Docker Desktop or Rancher Desktop
- Run `docker ps` to verify it's working
- The desktop app can start containers for you

### "Can't see Windows files"
- Make sure you're running from Windows PowerShell, not WSL
- The file picker should show C:\, D:\, etc.

---

## Uninstall

```powershell
# Remove the installation directory
Remove-Item -Recurse -Force "$env:USERPROFILE\PGVectorRAGIndexer"
```

---

## What Gets Installed

```
%USERPROFILE%\PGVectorRAGIndexer\
├── desktop_app/           # Desktop application code
├── venv-windows/          # Python virtual environment
├── requirements-desktop.txt
├── run_desktop_app.ps1    # Launcher script
└── ... (other project files)
```

**Size:** ~300 MB (includes PySide6 and dependencies)

---

## Next Steps

After installation, see [TESTING_DESKTOP_APP.md](TESTING_DESKTOP_APP.md) for testing guide.
