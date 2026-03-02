# Phase C One-Machine Manual QA Checklist

Purpose: validate Phase C (`SettingsTab` UI + `SettingsController` + `LicenseService`) on a single desktop with no second server machine.

## Scope

This checklist covers:
- Settings tab behavior parity.
- Local mode and remote mode behavior.
- License install success/error paths.
- Docker controls visibility/behavior by mode.

This checklist does not cover:
- Automated Qt signal/slot tests.
- Multi-client concurrency.

## Test Environment

1. Start from project root.
2. Ensure Docker is running.
3. Start backend locally:

```bash
docker compose up -d
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/api/version
```

4. Launch desktop app.

## Test Matrix

Run all scenarios in order.

## Scenario 1: Local Docker Mode Baseline

1. Open `Settings` tab.
2. Select `Local Docker`.
3. Click `Save`.

Expected:
- Confirmation dialog appears: `Backend Settings Saved`.
- URL shown as local default.
- Docker controls group is visible.
- Logs group can be shown.

4. Click `Refresh Statistics`.

Expected:
- Stats load without crash.
- Labels update for documents, chunks, and DB size.

5. Click `View Application Logs`.

Expected:
- Logs panel becomes visible.
- Logs text is populated.

## Scenario 2: Remote Mode on Same Machine (Loopback)

Use the same desktop as both client and server by targeting loopback URL.

1. In `Settings`, select `Remote Server`.
2. Set URL to `http://127.0.0.1:8000`.
3. Enter API key for remote auth if your server requires it.
4. Click `Test Connection`.

Expected:
- Status becomes `Testing...`.
- Success status: `Connected — server v<version>` if reachable/authenticated.
- If auth fails: `Authentication failed — check API key.`

5. Click `Save`.

Expected:
- Confirmation dialog appears with `Mode: Remote`.
- Docker controls group is hidden.
- Logs group is hidden.

## Scenario 3: Remote Validation Errors

1. Keep `Remote Server` selected.
2. Clear URL and click `Save`.

Expected:
- Warning dialog: `Missing URL`.

3. Set URL to `127.0.0.1:8000` (no scheme) and click `Save`.

Expected:
- Warning dialog: `Invalid URL`.

4. Set URL to `http://127.0.0.1:8000`, clear API key, click `Save`.

Expected:
- Warning dialog: `Missing API Key`.

5. Click `Test Connection` with URL `127.0.0.1:8000` (no scheme).

Expected:
- Inline status: `URL must start with http:// or https://`.

## Scenario 4: Remote Unreachable Path

1. Keep `Remote Server`.
2. Set URL to `http://127.0.0.1:65530`.
3. Click `Test Connection`.

Expected:
- Inline error: `Connection refused — is the server running?` or timeout.
- No UI freeze.
- `Test Connection` button is re-enabled.

## Scenario 5: License Panel Refresh

1. In `Settings`, observe license panel in `Local Docker` mode.

Expected:
- Edition/organization/expiry/seats render without crash.
- Upgrade link visibility matches edition state.

2. Switch to `Remote Server` with reachable URL, then return to local mode.

Expected:
- License panel still refreshes correctly.
- Warning text is shown only when applicable.

## Scenario 6: License Key Entry Error Path

1. Click `Enter License Key`.
2. Paste invalid text such as `not-a-jwt`.
3. Confirm dialog.

Expected:
- Error dialog: `Invalid License Key`.
- Existing valid key, if any, remains intact.

## Scenario 7: Docker Controls Guardrails

1. In `Remote Server` mode, verify Docker section is hidden.
2. Switch back to `Local Docker`, verify Docker section returns.
3. Click `Restart Containers`.

Expected:
- Confirmation prompt appears.
- On confirm, success/error dialog appears.
- App remains responsive.

## Pass/Fail Criteria

Pass:
- All expected outcomes match.
- No crashes, hangs, or broken widget states.
- Mode toggling always updates visibility correctly.

Fail:
- Any mismatch in expected status/dialog text severity.
- Any missing/hung action after button click.
- Any stale UI state after mode switch.

## Evidence to Record

Capture for each failed step:
- Scenario number and step number.
- Screenshot.
- Exact status text or dialog text.
- Whether issue reproduces in Local mode, Remote loopback mode, or both.
