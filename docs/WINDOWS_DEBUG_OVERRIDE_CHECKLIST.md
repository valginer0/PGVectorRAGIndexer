# Windows Debug Override Checklist

Use this only for the temporary Windows Local Docker validation path.

## Goal

Validate that the Windows-installed app, using Local Docker, runs the debug backend image and
correctly propagates an Organization license into backend state.

Primary debug branch:

- `debug/windows-license-org-tab`

Primary debug image:

- `ghcr.io/valginer0/pgvectorragindexer:debug-windows-license-org-tab`

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

### 3. Build the debug MSI

Run the Windows installer workflow on branch:

- `debug/windows-license-org-tab`

Download artifact:

- `PGVectorRAGIndexer.msi`

This is a test MSI, not a public release.

---

## Windows Commands

Open PowerShell and set the debug overrides before running the MSI:

```powershell
$env:PGVECTOR_REPO_REF="debug/windows-license-org-tab"
$env:APP_IMAGE="ghcr.io/valginer0/pgvectorragindexer:debug-windows-license-org-tab"
```

Then launch the downloaded MSI from the same PowerShell session.

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

## Negative Control

To confirm defaults still behave correctly, unset the overrides:

```powershell
Remove-Item Env:PGVECTOR_REPO_REF -ErrorAction SilentlyContinue
Remove-Item Env:APP_IMAGE -ErrorAction SilentlyContinue
```

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
