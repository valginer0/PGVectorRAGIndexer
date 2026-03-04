# Phase D: Desktop API Client Facade — Manual QA Checklist

Purpose: validate Phase D (`APIClient` facade, `BaseAPIClient`, 9 domain clients) on a single desktop with a running backend.

## Scope

This checklist covers:
- Facade delegation to domain clients.
- Error translation (HTTP status → typed exceptions).
- Property synchronization (base_url, api_key propagation).
- Session lifecycle and connection management.

This checklist does not cover:
- Server-side router logic (covered by E2E CI tests).
- Automated unit tests (24 tests in `test_api_client.py`).

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

## Scenario 1: System Health via Facade

1. Open the app. Observe the status bar connection indicator.

Expected:
- `is_api_available()` returns True (status bar shows connected).
- No errors in the application log.

2. Open Settings tab, click "Refresh Statistics".

Expected:
- Stats load (documents, chunks, DB size).
- Data comes through `SystemClient.get_statistics()`.

3. Open Settings tab, observe server version display.

Expected:
- Version string displayed (e.g., "v2.7.0").
- `check_version_compatibility()` runs without warning for matching versions.

## Scenario 2: Document CRUD

1. Upload a test document via the Upload tab ("Index Folder" or single file).

Expected:
- Upload succeeds. Document appears in Documents tab.
- Operation routes through `DocumentClient.upload_document()`.

2. Open Documents tab. Verify document list populates.

Expected:
- `DocumentClient.list_documents()` returns items with pagination metadata.
- Document count matches expected.

3. Select a document and view its metadata.

Expected:
- `DocumentClient.get_document()` returns full metadata.
- Source URI, chunk count, timestamps displayed.

4. Delete the test document.

Expected:
- Confirmation dialog appears.
- After confirm, document disappears from list.
- `DocumentClient.delete_document()` returns success.

## Scenario 3: Search and Metadata

1. Perform a search query in the Search tab.

Expected:
- Results appear with scores and snippets.
- `SearchClient.search()` routes correctly.

2. If metadata keys exist, verify metadata filtering works.

Expected:
- `MetadataClient.get_metadata_keys()` returns available keys.
- Filtering by metadata narrows results.

## Scenario 4: User and Activity Operations

1. Open the Recent Activity tab (if available).

Expected:
- Activity log loads without error.
- `ActivityClient.get_activity_log()` returns entries.

2. If Users management is accessible (admin role), list users.

Expected:
- `UserClient.list_users()` returns user list.
- User details (email, role, last login) displayed.

## Scenario 5: Watched Folders and Identity

1. Check that client identity was registered on first launch.

Expected:
- `IdentityClient.register_client()` was called during startup.
- Client ID stored in app config.

2. Open Watched Folders tab. List existing folders.

Expected:
- `WatchedFoldersClient.list_watched_folders()` returns folders (or empty list).
- No error on empty state.

3. Add a watched folder, then remove it.

Expected:
- Add succeeds via `WatchedFoldersClient.add_watched_folder()`.
- Remove succeeds via `WatchedFoldersClient.remove_watched_folder()`.
- Folder list updates after each operation.

## Scenario 6: Error Path Testing

1. Stop the backend (`docker compose down`). Attempt any operation from the desktop app.

Expected:
- `APIConnectionError` raised (not a raw `requests` exception).
- User sees a connection error message, not a traceback.
- App remains responsive.

2. Start the backend with auth required (`API_REQUIRE_AUTH=true`). Connect without an API key.

Expected:
- `APIAuthenticationError` raised on first API call.
- User sees an authentication error message.

3. Connect with an invalid API key.

Expected:
- 401/403 response translated to `APIAuthenticationError`.
- Error message mentions authentication, not raw HTTP status.

## Scenario 7: Property Synchronization

1. In Settings, change the backend URL from `http://127.0.0.1:8000` to `http://localhost:8000`.

Expected:
- `base_url` updates to new value.
- `api_base` auto-derives to `http://localhost:8000/api/v1`.
- Subsequent API calls use the new URL.

2. Change the API key in Settings.

Expected:
- `X-API-Key` header updates on the next request.
- No stale credentials sent.

## Scenario 8: Session Lifecycle

1. Use the app normally for several operations (search, browse, upload).

Expected:
- Shared `requests.Session` reuses connections (no connection leak).
- No socket exhaustion or timeout errors after many operations.

2. Close the app.

Expected:
- `APIClient.close()` called during shutdown.
- No orphaned connections or threads.

## Pass/Fail Criteria

Pass:
- All expected outcomes match.
- No crashes, hangs, or raw exception tracebacks shown to user.
- Error messages are user-friendly (typed exceptions, not HTTP codes).
- Property changes propagate immediately to all domain clients.

Fail:
- Any raw `requests` exception leaks to the UI.
- Any operation routes to the wrong domain client.
- Property changes don't propagate (stale URL or API key used).
- Session leak or connection pool exhaustion.

## Evidence to Record

Capture for each failed step:
- Scenario number and step number.
- Screenshot of the UI state.
- Exact error message or dialog text.
- Application log output (if relevant).
