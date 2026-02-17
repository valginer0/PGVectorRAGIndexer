# RFC: #6b Server-First Automation Profile

Status: Draft (proposed, amended after review)
Owner: Core backend
Related roadmap items: #6, #6b, #9, #10, #11, #3 (document locks)

## 1. Problem

Current scheduled indexing (#6) is desktop-app scoped (in-app `QTimer`) and assumes the scheduler is attached to a user session. This does not reliably cover deployments where source folders live on server disks or server-mounted shares and no desktop app is always open.

This RFC introduces a server-first automation profile that can safely run side-by-side with existing desktop scheduling.

## 2. Goals

1. Support explicit root ownership and execution scope (`client` vs `server`).
2. Preserve backward compatibility for desktop-only users by default.
3. Prevent cross-scheduler conflicts in mixed environments.
4. Keep implementation operationally simple (single active scheduler process).
5. Add observability and safe failure handling.

## 3. Non-goals

1. Distributed scheduler cluster election across multiple API replicas.
2. Cross-tenant/global dedupe.
3. Mandatory migration to enterprise Phase 4b (DB-backed roles/compliance) for this feature.

## 4. Compatibility and rollout principles

- Existing installations must continue to work with desktop scheduling only.
- New fields default to client-compatible behavior.
- Server scheduler is opt-in and disabled unless explicitly enabled.
- Old clients continue to operate against existing endpoints.

## 5. Data model changes

## 5.1 `watched_folders` extension (migration)

Add columns:
- `execution_scope TEXT NOT NULL DEFAULT 'client' CHECK (execution_scope IN ('client','server'))`
- `executor_id TEXT NULL`
  - client scope: set to `client_id`
  - server scope: must be `NULL`
- `normalized_folder_path TEXT NOT NULL`
- `root_id UUID NOT NULL DEFAULT gen_random_uuid()`
- `last_scan_started_at TIMESTAMPTZ NULL`
- `last_scan_completed_at TIMESTAMPTZ NULL`
- `last_successful_scan_at TIMESTAMPTZ NULL`
- `last_error_at TIMESTAMPTZ NULL`
- `consecutive_failures INT NOT NULL DEFAULT 0`
- `paused BOOLEAN NOT NULL DEFAULT FALSE`
- `max_concurrency INT NOT NULL DEFAULT 1`

Constraints and indexes:
- `CHECK ((execution_scope='client' AND executor_id IS NOT NULL) OR (execution_scope='server' AND executor_id IS NULL))`
- Replace legacy global unique path constraint on `folder_path` with scoped uniqueness on normalized path:
  - partial unique index: `(executor_id, normalized_folder_path)` where `execution_scope='client'`
  - partial unique index: `(normalized_folder_path)` where `execution_scope='server'`
- `(execution_scope, enabled, schedule_cron)`
- `(root_id, execution_scope)`
- `(execution_scope, paused, enabled)`

Backfill:
- Existing rows: `execution_scope='client'`
- `executor_id = client_id`
- `normalized_folder_path` generated from existing `folder_path`
- `root_id` auto-generated

Scope transition invariants:
- `execution_scope` must not be changed through generic update paths.
- Scope changes must use an explicit transition API with preflight conflict checks against target-scope unique constraints.
- Transition is in-place update (same row, same `root_id`) so scheduler identity remains stable.

## 5.2 Document identity (`canonical_source_key`)

> **Deferred to Phase 6b.2.** Not required for MVP — the 409 wrong-scope protection prevents cross-scope collisions operationally.

Add `canonical_source_key TEXT NULL` to `document_chunks` and index it.

Format:
- client scope: `client:<client_id>:<normalized_path>`
- server scope: `server:<root_id>:<normalized_path>`

Dedupe policy:
1. Canonical key match => update/replace that logical document.
2. If no key match, optionally dedupe by content hash if configured.
3. Content-hash dedupe is OFF by default — enable per-root to avoid surprising behavior.

## 5.3 Document lock keying migration

> **Deferred to Phase 6b.2.** Not required for MVP.

Current lock identity is `source_uri`, which is not safe for mixed scope.

Target lock identity:
- `root_id` + `relative_path` (+ existing TTL fields)

Migration strategy:
1. Add `root_id UUID NULL`, `relative_path TEXT NULL` to `document_locks`.
2. Keep `source_uri` during transition.
3. Update lock APIs to write/read the new key for watched-folder scans.
4. Deprecate `source_uri` locking after one compatibility window.

## 6. Runtime architecture

## 6.1 Desktop scheduler (existing)

- Continues unchanged for `execution_scope='client'` roots.
- Client scheduler must only scan roots where `executor_id == client_id`.
- **Amendment:** `FolderScheduler._check_folders()` must filter by scope and executor ownership. Each folder returned from the API must satisfy:
  - `execution_scope == 'client'`
  - `executor_id == self._client_id` (or `executor_id` is absent for legacy rows)
- Alternatively, the desktop scheduler should call `list_watched_folders(execution_scope='client', executor_id=<client_id>)` so the server returns only relevant roots (see §7.1).

## 6.2 Server scheduler (new)

- Runs inside API process as a background scheduler loop.
- Enabled by env flag (default off): `SERVER_SCHEDULER_ENABLED=false`.
- Uses DB advisory lease with non-blocking `pg_try_advisory_lock(...)` to ensure one active scheduler instance.
- Scans only `execution_scope='server'` and `paused=false` roots.

### Advisory lock ID

Use a deterministic, well-known constant for the advisory lock to avoid ID collisions:

```python
# CRC32("pgvector_server_scheduler") → deterministic constant
SERVER_SCHEDULER_LOCK_ID = 2050923308
```

### Async scan execution

**Critical:** The existing `scan_folder()` in `watched_folders.py` is synchronous (uses `os.walk()` + `DocumentIndexer`). Running it directly in the FastAPI async event loop would block all API requests for the duration of the scan.

The server scheduler must wrap scan calls with `asyncio.to_thread()`:

```python
async def _run_scan(folder_path: str, client_id=None):
    """Run a folder scan in a thread pool to avoid blocking the event loop."""
    result = await asyncio.to_thread(scan_folder, folder_path, client_id)
    return result
```

This keeps the existing sync `scan_folder()` code unchanged while preventing event loop starvation. No refactoring of `indexer_v2.py` or `watched_folders.py` is needed.

### Filesystem access requirements

Server-scope roots require that the folder path is accessible from the API server process filesystem:
- **Docker deployments:** Source directories must be bind-mounted into the container (e.g., `-v /data/docs:/data/docs`).
- **Bare-metal deployments:** The path must be readable by the API process user.

The `POST /watched-folders` endpoint should validate that the path exists on the server when `execution_scope='server'` to fail fast rather than failing silently during the first scheduled scan.

## 6.3 Wrong-scope protection

All scan requests validate scope and executor ownership.
- Wrong executor/scope => HTTP 409 with explicit diagnostic.

## 7. API surface

## 7.1 Existing endpoints (compatible extensions)

`/watched-folders` payload adds optional fields:
- `execution_scope`
- `executor_id`
- `paused`
- `max_concurrency`

Defaults preserve current behavior when omitted.

### Query filter parameters (amendment)

`GET /watched-folders` must support optional query parameters for efficient scope/owner filtering:
- `execution_scope=client|server` — filter by scope
- `executor_id=<client_id>` — filter by owner (client-scope roots)
- `enabled=true|false` — filter by enabled state (already exists as `enabled_only`)

Both the desktop scheduler and the server scheduler should use these filters to query only their relevant roots, rather than fetching all roots and filtering client-side. This avoids unnecessary data transfer and scales better with many roots.

## 7.2 New endpoints

- `GET /scheduler/roots/status` (list root scheduler state)
- `GET /scheduler/roots/{root_id}/status`
- `POST /scheduler/roots/{root_id}/pause`
- `POST /scheduler/roots/{root_id}/resume`
- `POST /scheduler/roots/{root_id}/scan-now`
- `POST /watched-folders/{id}/transition-scope` (explicit `client <-> server` transition with conflict check)

## 7.3 API versioning behavior

- Keep routes under existing v1 router.
- New fields are additive and optional for old clients.
- Add server capability flags to `GET /api`/`GET /api/version` response (non-breaking).

## 8. Safety controls

- Dry-run mode for server scans (`dry_run=true`) to emit planned operations without writes.
- Failure backoff based on `consecutive_failures` and `last_error_at`.
- Root-level pause/resume.
- Concurrency cap per root (default 1).
- (Optional in phase 2) soft-delete quarantine before hard delete.

## 9. Observability

Activity log details should include:
- `executor_scope`
- `executor_id`
- `root_id`
- `run_id`
- `dry_run`

Scheduler status response should include:
- next run
- last start/completion/success
- current state (`idle`, `running`, `paused`, `degraded`, `error`)
- failure streak

## 10. Phased implementation plan

### Phase 6b-MVP
1. `watched_folders` schema extension + backfill.
2. Scope/ownership checks + 409 path.
3. Server scheduler (opt-in) with singleton lease and `asyncio.to_thread()` scan wrapper.
4. Desktop `FolderScheduler` scope filtering (skip non-client roots).
5. `GET /watched-folders` query filter params (`execution_scope`, `executor_id`).
6. Filesystem path validation for server-scope roots on creation.
7. Scheduler status + pause/resume + scan-now endpoints.
8. Basic tests for mixed-mode conflict and wrong-scope rejection.

### Phase 6b.2
1. `canonical_source_key` column and indexing behavior.
2. Lock key migration (`root_id`, `relative_path`).
3. Lock race tests across client/server schedulers.

### Phase 6b.3
1. Dry-run reporting polish.
2. Quarantine delete lifecycle (soft-delete window + hard delete worker).
3. Lifecycle tests.

## 11. Testing matrix (minimum)

- Migration backfill correctness for existing watched folders.
- Desktop-only regression tests (no behavior change with defaults).
- Wrong-scope write rejection (409) tests.
- Mixed root collision tests (same relative path across scopes).
- Server scheduler lease/singleton behavior.
- Server scheduler async scan execution (does not block event loop).
- Concurrency cap behavior.
- Failure backoff and recovery.
- Activity log field presence for scheduler runs.
- Filesystem validation for server-scope root creation.

## 12. Open decisions

1. ~~Keep server scheduler in-process (recommended for MVP) vs external worker.~~ **Decided: in-process with `asyncio.to_thread()`.**
2. ~~Whether quarantine delete ships in MVP or phase 2.~~ **Decided: deferred to Phase 6b.3.**
3. ~~Whether content-hash dedupe is enabled by default.~~ **Decided: OFF by default, enable per-root.**

## 13. Expected effort

- MVP (Phase 6b-MVP): ~8-14h
- With lock migration + canonical identity in same pass: ~14-20h
- With quarantine lifecycle in same pass: +4-8h

## 14. Automated acceptance gates (no manual testing)

Every checkpoint in this RFC must be validated by automated tests only.

### 14.1 Required test files (new/updated)

Existing files to extend:
- `tests/test_watched_folders.py`
- `tests/test_folder_scheduler.py`
- `tests/test_document_locks.py`
- `tests/test_migrations.py`
- `tests/test_api_versioning.py`

New files to add:
- `tests/test_server_scheduler.py` (singleton lease, scope filtering, pause/resume, async scan)
- `tests/test_server_first_api.py` (409 wrong-scope, scheduler status/admin endpoints, query filter params)
- `tests/test_canonical_source_key.py` (canonical identity format + dedupe behavior — Phase 6b.2)

### 14.2 Checkpoint-to-test mapping

1. Existing desktop calls still work (`/watched-folders`, `/watched-folders/{id}/scan`):
   - API compatibility tests in `tests/test_server_first_api.py`
   - Desktop scheduler regression in `tests/test_folder_scheduler.py`
   - API client compatibility tests in `tests/test_api_client.py`

2. Migration/backfill correctness:
   - Unit-level migration metadata tests in `tests/test_migrations.py`
   - Integration migration/backfill verification in `tests/test_migrations_integration.py`

3. Wrong-scope protection (409):
   - API tests in `tests/test_server_first_api.py`

4. Server scheduler singleton and scope behavior:
   - `tests/test_server_scheduler.py`

5. Lock conflict/race behavior across root-relative keys:
   - `tests/test_document_locks.py`

6. Canonical identity + dedupe invariants:
   - `tests/test_canonical_source_key.py`

7. Additive API versioning/non-breaking responses:
   - `tests/test_api_versioning.py`

8. Filesystem validation for server-scope roots:
   - `tests/test_server_first_api.py`

### 14.3 Commands (local + CI)

Fast pre-merge run:

```bash
python -m pytest tests/test_migrations.py tests/test_migrations_integration.py tests/test_watched_folders.py tests/test_folder_scheduler.py tests/test_document_locks.py tests/test_api_versioning.py tests/test_api_client.py tests/test_server_scheduler.py tests/test_server_first_api.py tests/test_canonical_source_key.py -m "not slow" -v
```

Broad regression run:

```bash
python -m pytest tests/ -m "not slow" -v
```

### 14.4 Merge criteria

- No checkpoint is considered complete without a corresponding automated test assertion.
- No manual QA step is required for RFC acceptance.
- All new tests must pass in CI and locally before merge.

## 15. Amendment log

| # | Amendment | Rationale |
|---|---|---|
| 1 | Server scheduler must use `asyncio.to_thread()` for scan execution | `scan_folder()` is synchronous — would block the entire API event loop during scans |
| 2 | Desktop `FolderScheduler._check_folders()` must filter by scope + executor | Without filtering, desktop scheduler would attempt to scan server-scope roots |
| 3 | Server-scope roots require filesystem access documentation + path validation on creation | Fail fast on invalid paths instead of silent failure at first scan |
| 4 | Advisory lock ID specified as deterministic constant (`2050923308`) | Avoids collision risk from arbitrary ID selection |
| 5 | `GET /watched-folders` must support `execution_scope` and `executor_id` query filter params | Both schedulers need efficient server-side filtering, not client-side post-fetch filtering |
