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

After bootstrap completes, use the unified wrapper:

```powershell
cd %USERPROFILE%\PGVectorRAGIndexer
./manage.ps1 -Action update      # refresh containers (prod by default)
./manage.ps1 -Action run         # launch desktop app anytime
```

Need a development build? `./manage.ps1 -Action update -Channel dev`

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

If you want to run from the WSL directory, `manage.ps1` still works:

```powershell
cd \\wsl.localhost\Ubuntu\home\valginer0\projects\PGVectorRAGIndexer
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
./manage.ps1 -Action update
./manage.ps1 -Action run
```

> ℹ️ UNC paths are slower; prefer the Windows install dir when possible.

---

## See Also (Recommended Reading)

- **Desktop App Data Fields** (where the Document Type comes from): See `README.md` → [Desktop App Data Fields](README.md#desktop-app-data-fields)
- **Troubleshooting UI Not Updating** (refresh steps and checks): See `README.md` → [Troubleshooting UI Not Updating](README.md#troubleshooting-ui-not-updating)

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
   ./manage.sh update dev
   ```
3. **Run the desktop app:**
   ```powershell
   # From Windows
   cd %USERPROFILE%\PGVectorRAGIndexer
   ./manage.ps1 -Action run
   ```

### Daily Use

```powershell
cd %USERPROFILE%\PGVectorRAGIndexer
./manage.ps1 -Action run
```

Or create a desktop shortcut to `run_desktop_app.ps1`!

### Working with SourceOpenManager features

- **Recent Activity tab** – The tab bar now includes `🕓 Recent`, which lists the last files you opened from `Search`, `Documents`, or `Manage`. Each entry shows when it was opened, whether it’s queued, reindexed, or has a last error.
- **Queue and batch reindex** – Use the buttons in the Recent tab (Queue/Unqueue, Reindex, Remove) or the context menus in other tabs to queue items. Press **Reindex Queued** to submit every queued document at once. No pop-ups appear unless a critical error occurs.
- **Context menu actions** – Right-click any `Source URI` entry to access `Open`, `Open with…`, `Show in Folder`, `Copy Path`, `Queue for Reindex`, `Reindex Now`, or `Remove from Recent`. Options stay consistent across tabs thanks to the shared `SourceOpenManager`.

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
