# PGVectorRAGIndexer Windows Installer

This directory contains the source code for the Windows .exe installer.

## Building the Installer

**Requirements:**
- Windows 10/11
- Python 3.9+
- PyInstaller (`pip install pyinstaller`)

**Build:**
```bash
cd windows_installer
pip install pyinstaller
python build_installer.py
```

**Output:**
- `dist/PGVectorRAGIndexer-Setup.exe` (~15-20 MB)

## Files

| File | Description |
|------|-------------|
| `installer_gui.py` | Tkinter GUI with progress display |
| `installer_logic.py` | Installation functions (winget, venv, etc.) |
| `build_installer.py` | PyInstaller build script |

## How It Works

1. User downloads and double-clicks `PGVectorRAGIndexer-Setup.exe`
2. GUI window opens showing installation progress
3. Installer checks/installs: Python, Git, Rancher Desktop
4. Clones repo, creates venv, installs dependencies
5. Creates desktop shortcut
6. Launches the app

## Testing

To test the GUI without building:
```bash
python installer_gui.py
```
