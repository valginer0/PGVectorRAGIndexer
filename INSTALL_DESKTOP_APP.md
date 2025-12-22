# Desktop App Installation Guide

## Windows Installation

### One-Line Install (Recommended)

**From Windows PowerShell (as Administrator or with execution policy set):**

```powershell
irm https://raw.githubusercontent.com/valginer0/PGVectorRAGIndexer/main/bootstrap_desktop_app.ps1 | iex
```

This will:
1. ✅ Check for Python and Git
2. ✅ Clone the repository to `%USERPROFILE%\PGVectorRAGIndexer`
3. ✅ Create virtual environment
4. ✅ Install dependencies
5. ✅ Create a Desktop Shortcut for easy access
6. ✅ Auto-start the desktop app after setup (no interactive prompt)

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

### Create a Desktop Shortcut
You can automatically create a "One-Click" desktop shortcut at any time:

```powershell
./manage.ps1 -Action shortcut
```

This will create a `PGVectorRAGIndexer` shortcut on your desktop. Double-click it to start the app!



---

### Daily Usage (Windows)
To run the app later, you can use:
1.  **The Desktop Shortcut** (Recommended)
2.  Or Run via PowerShell:
    ```powershell
    cd %USERPROFILE%\PGVectorRAGIndexer
    ./manage.ps1 -Action run
    ```

---


## macOS & Linux Installation

**Prerequisites:**
- **Python 3.10+**:
  - **Option 1 (Recommended)**: Download from [Python.org](https://www.python.org/downloads/macos/) (macOS installer package) - *Fastest method*
  - **Option 2 (Homebrew)**: `brew install python` (requires [Homebrew](https://brew.sh/))
- **Docker-compatible runtime**: [Docker Desktop](https://www.docker.com/products/docker-desktop/), [Rancher Desktop](https://rancherdesktop.io/), [Podman Desktop](https://podman-desktop.io/), or Docker Engine (Linux)

### 1. Clone the Repository
Open Terminal:
```bash
cd ~/Projects  # or wherever you keep code
git clone https://github.com/valginer0/PGVectorRAGIndexer.git
cd PGVectorRAGIndexer
```

### 2. Setup & Install
```bash
# Create virtual environment
python3 -m venv venv

# Activate and install dependencies
source venv/bin/activate
pip install -r requirements-desktop.txt
```

### 3. Run the App
```bash
# Make the helper script executable
chmod +x manage.sh

# Start backend containers (requires Docker running)
./manage.sh update dev

# Run the desktop app
./manage.sh run
```

---

## macOS Catalina (10.15) Setup

If you are running macOS Catalina, you must use specific versions of Docker and the desktop app dependencies.

### 1. Docker Desktop Requirement
You must use **Docker Desktop 4.15.0**. Newer versions require macOS 11+.
- **Download**: [Docker Desktop 4.15.0 for Mac (Intel)](https://desktop.docker.com/mac/main/amd64/93002/Docker.dmg)
- do **not** update Docker Desktop if prompted, as newer versions will fail to start on Catalina.

### 2. Python Requirement (Critical)
**You must use Python 3.10 or 3.11.**
By default, Homebrew installs the *latest* Python (often 3.12+ or 3.13), which is **incompatible** with the PySide6 version available for Catalina.

**Recommended Solution:**
1.  Uninstall any existing python from brew if it's too new (`brew uninstall python`).
2.  **Download & Install Python 3.11.9**:
    *   [Python 3.11.9 macOS Universal Installer](https://www.python.org/ftp/python/3.11.9/python-3.11.9-macos11.pkg)
3.  Run the installer and check "Install Certificates".

### 3. Installation
Follow the standard [macOS & Linux Installation](#macos--linux-installation) steps, but in **Step 2**, use the Catalina-specific requirements file:

```bash
# Create virtual environment (make sure to use the specific python version)
/usr/local/bin/python3.11 -m venv venv

# Activate (standard step)
source venv/bin/activate

# INSTALL SPECIAL DEPENDENCIES (Critical for Catalina)
pip install -r requirements-desktop-catalina.txt
```

Then proceed to [Run the App](#3-run-the-app).

---



## See Also (Recommended Reading)

- **Desktop App Data Fields** (where the Document Type comes from): See `README.md` → [Desktop App Data Fields](README.md#desktop-app-data-fields)
- **Troubleshooting UI Not Updating** (refresh steps and checks): See `README.md` → [Troubleshooting UI Not Updating](README.md#troubleshooting-ui-not-updating)

---

## Requirements

- **Python 3.10+** - [Download](https://www.python.org/downloads/)
  - ⚠️ During install, check "Add Python to PATH"
- **Git** (for one-line install) - [Download](https://git-scm.com/downloads)
- **Docker-compatible runtime** - Docker Desktop, Rancher Desktop, Podman, or similar

---

## Software User Interface Guide

The desktop app has six tabs, ordered by typical workflow:

1. **Upload** – Add documents to the system. Upload individual files or entire folders. Full file paths are preserved.
   - **OCR Mode**: Choose how scanned documents are handled:
     - `Auto` (default): Uses OCR only when native text extraction fails
     - `Skip`: Faster, never uses OCR (good for native text documents)
     - `Only`: Process only files that require OCR (useful for image-only batches)
   - **Incremental Indexing**: Files with unchanged content are automatically skipped (hash-based detection)
   - **Encrypted PDFs**: Password-protected PDFs are detected and listed for review
     - A **"🔒 Encrypted PDFs (N)"** button appears after upload if any were found
     - Click to see the full list with filter, copy path, and open folder options
     - Decrypt the files externally, then re-upload them
2. **Search** – Find information across your indexed documents. Click on file paths to open them.
3. **Documents** – Browse all indexed documents with pagination and sorting.
4. **Recent** – Track files you've opened and manage reindexing. When you open a file (from Search or Documents), you might edit it—and edited files should be reindexed. Since there's no automatic way to detect significant edits, this tab lets you queue and batch-reindex files as needed.
5. **Manage** – Bulk operations like filtering, deleting, and backing up documents. Includes features to export backups before deletion and restore from previously saved backups.
6. **Settings** – View database statistics and manage Docker containers.

### Working with the Recent Activity Tab

- **Purpose** – Tracks files you've opened from Search or Documents. Opening a file often means editing it, and edited files need reindexing.
- **Queue Management** – Files are automatically queued when opened. Use "Reindex Queued" to batch-reindex all queued files at once.
- **Context Menu** – Right-click any file to access: Open, Open with…, Show in Folder, Copy Path, Queue/Unqueue, Reindex Now, or Remove from Recent.
- **No Auto-Detection** – The system can't automatically detect if edits were significant, so manual reindexing control is provided here.

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
- Start your container runtime (Docker Desktop, Rancher Desktop, Podman, etc.)
- Run `docker ps` to verify it's working
- The desktop app can start containers for you

### "Can't see Windows files"
- Make sure you're running from Windows PowerShell, not WSL
- The file picker should show C:\, D:\, etc.

---

---

## Alternative: Manual Installation (Windows - Advanced)

This section is for developers or advanced users who want full control over the installation process.

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
