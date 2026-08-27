# Agent Instructions — windows_installer/

Human build/architecture docs are in `README.md` (PyInstaller build steps,
the 8-phase install/reboot/resume state machine, WiX packaging). This file
is the agent-specific gotchas that aren't there.

## API facts that will bite you if assumed otherwise

- `_run_command()` returns `tuple(bool, str)` — `(success, stdout+stderr)`,
  not just stdout.
- `_check_command()` checks via the Windows `where` command — only
  meaningful when actually run on Windows.
- `_add_to_path()` does **not** exist. Use `_refresh_path()`.
- Prefer PowerShell `Get-CimInstance` over `wmic` (deprecated) or
  `systeminfo` (slow) when adding new system-check logic.

## Two independent dependency-install paths

This installer (`installer_logic.py`) and the repo-root
`bootstrap_desktop_app.ps1` both install prerequisites, but neither calls
the other. If you change what's required to run the desktop app (a new
Python package, a new system dependency), update **both** paths or they
will silently drift out of sync.

## Testing

- Installer unit tests (`tests/test_installer.py`) are
  `@unittest.skipUnless(sys.platform == 'win32')` — they always skip on
  Linux/WSL, that's expected, not a failure.
- To test the GUI without a full build: `python installer_gui.py`
  (Windows only).
