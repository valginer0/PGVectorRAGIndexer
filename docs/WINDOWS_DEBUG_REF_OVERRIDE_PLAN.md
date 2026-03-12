# Windows Debug Override Plan

## Goal

Allow a temporary Windows MSI build to validate the real Windows Local Docker path before a
public release.

This now requires distinguishing two different override types:

- `PGVECTOR_REPO_REF`
  - controls which git ref is checked out on disk
- `APP_IMAGE`
  - controls which backend Docker image Local Docker actually runs

Primary debug target:

- `debug/windows-license-org-tab`

This is a debug-only path. Normal production installers must continue to default to `main`.

---

## Problem

The installed Windows app can now bootstrap backend source from a non-`main` ref, but the
Windows Local Docker path still runs the production Docker image by default:

- `ghcr.io/valginer0/pgvectorragindexer:latest`

That means:

- `PGVECTOR_REPO_REF` changes local checkout state
- but does **not** by itself change the backend container behavior

For the actual Windows Local Docker test, the important path is:

- Windows desktop app
- Local Docker
- backend image actually run by Docker
- backend-side license persistence
- `/api/v1/license/install` + `/api/v1/license/reload` behavior
- Organization tab behavior when the backend is the actual local Docker backend used by the
  installed Windows app

Testing from WSL alone is insufficient because the real product path is:

1. Windows desktop app
2. local Docker backend
3. backend-managed license state

---

## Scope

Implement a temporary debug override for the Windows Local Docker flow.

In scope:

- Windows installer/bootstrap code path
- debug MSI behavior
- logging/visibility of active backend source ref
- logging/visibility of active backend image
- debug Docker image tag usage
- manual validation workflow

Out of scope:

- changing public release default away from `main`
- long-term product UI for branch selection
- changing macOS/Linux installer behavior unless needed for parity

---

## Design

### 1. Keep `PGVECTOR_REPO_REF` For Source Checkout

Keep the existing optional source checkout override:

- `PGVECTOR_REPO_REF`

Semantics:

- if unset: use `main`
- if set: use the supplied branch, tag, or commit

Examples:

- `debug/windows-license-org-tab`
- `v2.9.0`
- `b7ea414`

This is still useful for:

- installer/bootstrap source checkout
- debug logging
- script-level validation

But it is **not sufficient** for proving Local Docker backend behavior.

### 2. Add One Optional Docker Image Override

Introduce an optional environment/config override:

- `APP_IMAGE`

Semantics:

- if unset: use `ghcr.io/valginer0/pgvectorragindexer:latest`
- if set: use the supplied Docker image tag

Primary debug example:

- `ghcr.io/valginer0/pgvectorragindexer:debug-windows-license-org-tab`

### 3. Keep Production Defaults Unchanged

Production and public MSI behavior:

- clone/update from `main`
- run `ghcr.io/valginer0/pgvectorragindexer:latest`

Debug/test behavior:

- only activate alternate source ref when `PGVECTOR_REPO_REF` is explicitly set
- only activate alternate backend image when `APP_IMAGE` is explicitly set

### 4. Make The Active Source Ref And Image Visible

Log both:

- chosen git ref during install/bootstrap
- chosen Docker image before `docker compose pull/up`

Minimum required output:

- `Backend source ref: main`
- or
- `Backend source ref: debug/windows-license-org-tab`
- `Backend image: ghcr.io/valginer0/pgvectorragindexer:latest`
- or
- `Backend image: ghcr.io/valginer0/pgvectorragindexer:debug-windows-license-org-tab`

Optional:

- include ref/image in a debug dialog or diagnostics text for temporary testing builds

---

## File-Level Plan

### A. `installer.ps1`

Keep / verify source-ref logic:

1. read `PGVECTOR_REPO_REF`
2. default to `main`
3. fetch origin
4. checkout the requested ref
5. only run `git pull origin <branch>` when the ref is a branch

Add / verify image logic:

1. read `APP_IMAGE`
2. default to `ghcr.io/valginer0/pgvectorragindexer:latest`
3. surface the active image clearly in logs
4. make sure Local Docker commands run with that image value available to compose

### B. `windows_installer/installer_logic.py`

If this file orchestrates repo clone/update or Docker lifecycle, ensure:

1. the override can be passed through
2. logging makes the effective ref visible
3. logging makes the effective image visible
4. normal install path remains unchanged when overrides are absent

### C. `bootstrap_desktop_app.ps1`

Patch only if this script is part of the Windows install/runtime path for local backend setup.

If yes:

1. apply the same `PGVECTOR_REPO_REF` logic
2. apply the same `APP_IMAGE` logic if it participates in Local Docker startup
3. keep production defaults unchanged

If no:

- do not modify it further

---

## Git Checkout Logic

Recommended sequence:

1. `git fetch origin`
2. `git checkout <ref>`
3. if `<ref>` is a branch:
   - `git pull origin <ref>`

Practical branch detection rule:

- if `git show-ref --verify --quiet refs/remotes/origin/<ref>` succeeds, treat it as a branch
- otherwise do not run pull

This avoids broken behavior for tags and detached SHAs.

---

## Docker Image Logic

The production compose file already supports image override:

- `APP_IMAGE=${APP_IMAGE:-ghcr.io/valginer0/pgvectorragindexer:latest}`

So the required debug path is:

1. build/publish a debug backend image from branch `debug/windows-license-org-tab`
2. tag it as:
   - `ghcr.io/valginer0/pgvectorragindexer:debug-windows-license-org-tab`
3. set:
   - `APP_IMAGE=ghcr.io/valginer0/pgvectorragindexer:debug-windows-license-org-tab`
4. run the normal Windows Local Docker path

Without this image override, Local Docker will keep using `latest`, even if the repo checkout is
on a debug branch.

---

## Safety Rules

1. Never change the default production ref from `main`
2. Never change the default production image from `ghcr.io/valginer0/pgvectorragindexer:latest`
3. Never silently persist debug overrides into normal user configuration
4. Always log the active ref when override is used
5. Always log the active backend image when override is used
6. Prefer environment-driven override over hardcoding debug values in source
7. Keep this path suitable for removal after the debug cycle

---

## Backend License Token Storage Note

For this debug-path Windows flow, the backend may persist the installed license token in
`server_settings` so the local Docker/backend process can continue to validate and reload the
active license even when it cannot directly read the desktop app's local license file.

Current decision for debug validation:

- store the original token in backend-managed server state
- scope writes to the local-machine sync path only
- assume a local self-hosted trust model for this temporary debug flow

Why this exists:

- hashing alone is not sufficient because the backend must still be able to validate/reload the
  original license token

Future hardening option:

- move to encrypted-at-rest storage if this backend-managed license sync path graduates beyond
  debug/local-server validation

---

## Manual Test Flow

### Debug MSI Validation

1. Commit and push branch `debug/windows-license-org-tab`
2. Build and publish debug backend image:
   - `ghcr.io/valginer0/pgvectorragindexer:debug-windows-license-org-tab`
3. Build a debug MSI from branch `debug/windows-license-org-tab`
4. On Windows, set:
   - `PGVECTOR_REPO_REF=debug/windows-license-org-tab`
   - `APP_IMAGE=ghcr.io/valginer0/pgvectorragindexer:debug-windows-license-org-tab`
5. Install/run the Windows app
6. Choose `Local Docker`
7. Paste an Organization license
8. Verify:
   - success dialog shows save path
   - backend source ref is logged as `debug/windows-license-org-tab`
   - backend image is logged as `ghcr.io/valginer0/pgvectorragindexer:debug-windows-license-org-tab`
   - backend starts successfully
   - `http://localhost:8000/license` reports `organization`
   - `http://localhost:8000/api/v1/me` returns `200`
   - Organization tab unlocks and shows real content
9. Restart app/backend and confirm persistence

### Negative Control

Repeat with no override:

1. unset `PGVECTOR_REPO_REF`
2. unset `APP_IMAGE`
3. install/run debug MSI
4. verify:
   - backend source ref logs as `main`
   - backend image logs as `ghcr.io/valginer0/pgvectorragindexer:latest`

---

## Test Plan

### Unit / Integration

Add tests for:

1. default ref selection:
   - unset override -> `main`

2. branch override:
   - override `debug/windows-license-org-tab` -> correct checkout path

3. tag/SHA override:
   - no invalid `git pull` on detached refs

4. pass-through behavior:
   - installer logic preserves env var into bootstrap process

5. image override:
   - unset override -> production image
   - set override -> debug image value is preserved

6. logging:
   - active backend source ref is emitted
   - active backend image is emitted

7. license install auth hardening:
   - loopback/local request to `/api/v1/license/install` is allowed
   - non-loopback request to `/api/v1/license/install` is denied

### Manual Windows Validation

Required because the bug is environment-specific:

1. install debug MSI on Windows
2. verify local Docker backend comes from debug image tag
3. verify Organization license reaches backend state
4. verify Organization tab matches backend license

---

## Acceptance Criteria

1. Public/default installer behavior remains `main`
2. Public/default Local Docker behavior remains `ghcr.io/valginer0/pgvectorragindexer:latest`
3. Debug image override successfully runs backend image `ghcr.io/valginer0/pgvectorragindexer:debug-windows-license-org-tab`
4. Active backend source ref is visible in debug install/bootstrap logs
5. Active backend image is visible in debug install/bootstrap logs
6. Organization license can be installed from Windows app and becomes visible to local backend
7. `GET /license` on local backend reflects the new backend license
8. Organization tab no longer warns when backend is Organization-licensed
9. Restart preserves the backend license state

---

## Recommended Order

1. Confirm `/api/v1/license/install` remains loopback-only
2. Commit and push branch `debug/windows-license-org-tab`
3. Publish debug backend image `ghcr.io/valginer0/pgvectorragindexer:debug-windows-license-org-tab`
4. Implement / verify `APP_IMAGE` override path and image logging
5. Build debug MSI artifact
6. Run Windows Local Docker validation
7. Remove or keep overrides behind debug-only discipline as appropriate
