# Windows Debug Override Checklist

Use this only for the temporary Windows Local Docker validation path.

## Goal

Validate that the Windows-installed app, using Local Docker, runs the debug backend image and
correctly propagates an Organization license into backend state.

Primary debug branch:

- `debug/windows-license-org-tab`

Primary debug image:

- `ghcr.io/valginer0/pgvectorragindexer:debug-windows-license-org-tab`

Use a non-version image tag for debug work. Public release installers and the desktop app
ignore stale same-project semver image overrides such as `ghcr.io/valginer0/pgvectorragindexer:2.14.4`
when the installed app expects a newer release.

---

## GitHub Actions

### 1. Push the debug branch

Make sure `debug/windows-license-org-tab` is committed and pushed.

### 2. Build and publish the debug backend image

Run the Docker publish workflow on branch:

- `debug/windows-license-org-tab`

Required output:

- `ghcr.io/valginer0/pgvectorragindexer:debug-windows-license-org-tab`

Do not continue until that tag exists in GHCR.

### 3. Build and download the debug MSI

Use the dev MSI automation script from WSL:

```bash
./scripts/build_dev_msi_artifact.sh debug/windows-license-org-tab \
  --app-image ghcr.io/valginer0/pgvectorragindexer:debug-windows-license-org-tab
```

The script:

- triggers the existing `Build Windows Installer` GitHub Actions workflow for
  the branch;
- waits for the workflow to finish;
- downloads the unsigned `PGVectorRAGIndexer.msi` artifact to a persistent
  validation folder under `C:\Users\v_ale\.codex\validation\PGVectorRAGIndexer`;
- writes an `install-dev-msi.ps1` helper beside the MSI with
  `PGVECTOR_REPO_REF` and `APP_IMAGE` set for the same branch/image.

To also smoke-test the experimental local LanceDB search path, add
`--local-search`. The helper then sets `PGVECTOR_LOCAL_SEARCH=1` so the MSI
Setup Wizard installs the local search dependencies (CPU Torch +
sentence-transformers) into the desktop venv:

```bash
./scripts/build_dev_msi_artifact.sh dev/v2 --local-search
```

This is a test MSI, not a public release.

---

## Windows Commands

Open PowerShell and run the generated `install-dev-msi.ps1` helper. It sets the
debug overrides before launching the MSI:

```powershell
& "C:\Users\v_ale\.codex\validation\PGVectorRAGIndexer\dev-msi\debug-windows-license-org-tab\<run-id>\install-dev-msi.ps1"
```

Use the exact helper path printed by `build_dev_msi_artifact.sh`.

---

## In-App Test Flow

1. Install the debug MSI
2. Start the app
3. Choose `Local Docker`
4. Let the backend start
5. Open `Settings`
6. Paste the Organization license
7. Save
8. Open `Organization`
9. Click `Refresh` if needed

---

## What To Verify

### Logs / diagnostics

You want to see:

- `Backend source ref: debug/windows-license-org-tab`
- `Backend image: ghcr.io/valginer0/pgvectorragindexer:debug-windows-license-org-tab`

### Backend endpoints

Check in browser or curl:

- `http://localhost:8000/license`
- `http://localhost:8000/api/v1/me`

Expected:

- `/license` reports `organization`
- `/api/v1/me` returns `200`

### UI behavior

Expected:

- Settings shows Organization
- Organization tab no longer shows the gating/warning state
- Organization tab shows real content

### Persistence

Restart app/backend and verify:

- `/license` still reports `organization`
- Organization tab still works

---

## Negative Control / Cleanup

To confirm defaults still behave correctly (and to ensure you don't break future official standard installations), you **must** wipe the override variables from your Windows Registry once you are done debugging:

```powershell
[Environment]::SetEnvironmentVariable("PGVECTOR_REPO_REF", $null, "User")
[Environment]::SetEnvironmentVariable("APP_IMAGE", $null, "User")
[Environment]::SetEnvironmentVariable("APP_IMAGE", $null, "Machine")
```

The `Machine` cleanup requires an elevated PowerShell window; skip it if no machine-level
override was created.

Then run the MSI again and verify:

- backend source ref logs as `main`
- backend image logs as `ghcr.io/valginer0/pgvectorragindexer:latest`

---

## If It Fails

Use this decision tree:

1. Wrong source ref in logs
- installer/bootstrap override failed

2. Wrong image in logs
- Docker image override failed

3. Correct image, but `/license` is not `organization`
- backend license install/sync failed

4. `/license` is `organization`, but Organization tab still warns
- UI/state handling bug remains
