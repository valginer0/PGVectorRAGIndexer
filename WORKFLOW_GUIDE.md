# Workflow Guide

This document captures the unified workflow for PGVectorRAGIndexer across Windows clients and WSL/Linux contributors.

## Windows (Clients / Testers)

Use `manage.ps1` as the single entry point. Run it from the project directory in PowerShell.

| Command | Description |
|---------|-------------|
| `./manage.ps1 -Action bootstrap [-Channel prod|dev]` | Clone/update the repo, install desktop dependencies, then refresh containers (defaults to `prod`). |
| `./manage.ps1 -Action update [-Channel prod|dev]` | Pull the selected image (`prod` → `:latest`, `dev` → `:dev`) and restart containers. |
| `./manage.ps1 -Action run` | Launch the desktop app (auto-creates venv and installs dependencies if missing). |

Notes:
- Docker Desktop or Rancher Desktop must be running before `bootstrap` or `update`.
- `-Channel` is optional; omit for production defaults.
- Use `-DryRun` on any action to preview what the script would execute.

## WSL/Linux (Contributors / Maintainers)

Use `manage.sh` from the project directory.

| Command | Description |
|---------|-------------|
| `./manage.sh update [prod|dev]` | Refresh containers. `dev` (default) rebuilds via `docker-compose.dev.yml`; `prod` pulls `:latest` via `.env.manage.tmp`. |
| `./manage.sh run` | Launch the desktop app (uses `run_desktop_app.sh`). |
| `./manage.sh release [patch|min or|major|<version>]` | Forward to `release.sh`, preserving the bump logic. |

Additional tips:
- `manage.sh update dev` is the quickest way to rebuild and start containers with local changes.
- `manage.sh release` assumes you are on the main branch with a clean tree, mirroring the requirements of `release.sh`.
- `--dry-run` is available on all actions to view commands without executing them.

## Environment Handling

Both scripts generate a temporary `.env.manage.tmp` when needed so end-users never manage environment variables manually. Override behavior:
- `manage.ps1` sets `APP_IMAGE` based on channel before invoking Docker Compose.
- `manage.sh` writes the same override (for `prod`) or switches to the dev compose file.

## Legacy Scripts

Existing helper scripts (e.g., `update-dev.ps1`, `push-dev.sh`) remain in the repository but are now considered internal building blocks. Documentation should direct users to the `manage.*` wrappers first.
