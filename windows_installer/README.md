# PGVectorRAGIndexer Windows Installer

This directory contains the source code for the Windows `.exe` installer.

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
| `installer_gui.py` | Tkinter GUI with progress display, resume prompt, reboot dialog, and virtualization guidance |
| `installer_logic.py` | Full install and repair state machine |
| `build_installer.py` | PyInstaller build script |

## What the Installer Does

The installer is not a passive checker. It detects missing prerequisites, installs
them, starts container runtimes, handles reboots, and resumes automatically. Each
phase follows a detect → install → verify pattern.

### Phase 1 — System Check

- Detects Windows version and free disk space.
- Checks whether WinGet is available. If not, downloads and installs the official
  Microsoft App Installer dependency bundle and bootstraps WinGet before
  continuing.

### Phase 2 — Python Setup

- Checks whether a usable Python installation exists.
- If missing: installs Python 3.11 via WinGet, falling back to a direct silent
  installer download from python.org.
- Refreshes PATH and verifies the installation before proceeding.

### Phase 3 — Git Setup

- Checks whether Git is available.
- If missing: installs Git via WinGet, falling back to a direct silent installer
  download from git-scm.com.
- Refreshes PATH and verifies the installation before proceeding.

### Phase 4 — Container Runtime Setup

Detects usable Docker-compatible runtimes in priority order:

1. `docker ps` works → already running, nothing to do.
2. Docker Desktop installed → defer startup to Phase 5.
3. `docker` command exists but not running → defer startup to Phase 5.
4. Rancher Desktop `rdctl.exe` found → defer startup to Phase 5.
5. Podman with Docker Compose compatibility detected → use Podman.
6. Nothing found → run pre-install gating, then install Rancher Desktop.

When no runtime is available, the installer also:

- Detects CPU architecture and warns on ARM64.
- Checks hardware virtualization support. If virtualization is disabled, records
  manufacturer-specific BIOS guidance and surfaces it in the GUI dialog.
- Checks WSL2 status. If WSL2 is missing, runs `wsl --install --no-launch` and
  requests a reboot before continuing.
- Installs Rancher Desktop via WinGet, falling back to a direct MSI download from
  GitHub releases.
- Requests a reboot after a fresh Rancher install.

### Phase 5 — Runtime Startup

- Starts the container runtime (`rdctl start --container-engine moby` for Rancher
  Desktop, or launches Docker Desktop/Rancher Desktop executables).
- Waits up to 300 seconds for `docker ps` to become responsive.
- Requests a reboot if the runtime cannot be started or does not become ready in
  time.

### Phase 6 — Application Setup

- Clones the GitHub repository if the install directory is missing.
- Updates an existing checkout if present, and checks out the configured ref.
- Removes and reclones an incomplete installation directory.
- Creates `venv-windows` and installs `requirements-desktop.txt`.

### Phase 7 — Backend Image Update

- Writes the compose environment file.
- Runs `docker compose pull` and `docker compose up -d`.
- If the pull fails but locally cached app and database images exist, proceeds
  with cached images and logs an offline warning rather than failing.

### Phase 8 — Finalization

- Creates the desktop shortcut.
- Copies the setup executable into the install directory.
- Creates a setup/reinstall shortcut.
- Launches the app when requested.

## Reboot and Resume

The installer supports automatic reboot and resume:

- Saves a state file recording the current stage, install directory, timestamp,
  installer version, and the installer phase to resume from before requesting a
  reboot.
- Registers a scheduled task to relaunch after logon (falls back to a registry
  Run key if scheduled task creation fails).
- On restart, validates the state file age and installer version, then resumes
  from the recorded phase. Most restarts resume from Phase 5 after runtime
  installation; WSL2 setup resumes from Phase 4 so runtime installation can
  continue after Windows finishes enabling WSL.
- The GUI offers a "Start Fresh" option to clear state and restart from Phase 1.

## In-App Runtime Repair

After installation, `desktop_app/utils/docker_manager.py` provides similar repair
behavior at runtime:

- Checks daemon connectivity on launch.
- Attempts to start Rancher Desktop or Docker Desktop if the daemon is down.
- Waits for readiness, can pull missing images, and can restart stopped containers.

This means the application can self-repair common container runtime issues without
requiring the user to re-run the installer.

## TODO

- Update this README whenever the installer gains new phases or repair actions.
- Emit structured diagnostic objects (stable check IDs, severity, evidence,
  allowlisted repair actions) from `installer_logic.py` to support a future AI
  repair assistant. See `docs/internal/INSTALLER_PREFLIGHT_REPAIR_MAP_V0.md` for
  the proposed schema.

## Testing

To test the GUI without building:
```bash
python installer_gui.py
```
