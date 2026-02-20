# Implementation Tracker

Derived from [FEATURE_IDEAS_V5.md](./FEATURE_IDEAS_V5.md). Each task maps to a feature number in V5.
Update status as work progresses. Move completed items to the bottom section.

---

## Status Legend

| Symbol | Meaning |
|--------|---------|
| ⬜ | Not started |
| 🟡 | In progress |
| ✅ | Complete |
| ⏸️ | Blocked (note blocker, e.g., "⏸️ Blocked by #11") |

---

## Immediate Actions (Parallel)

These have zero dependencies on each other and should start simultaneously.

### ✅ #11 Schema Migration Framework
- **Effort**: ~4-6h | **Edition**: Both | **Dependencies**: None
- **Branch**: `feature/roadmap-v4`
- [x] Add Alembic to `requirements.txt`
- [x] Create `alembic/` directory with `alembic.ini`, `env.py`
- [x] Write baseline migration from current `init-db.sql` schema
- [x] Auto-run pending migrations on app startup (Docker + desktop)
- [x] ~~Add `alembic upgrade head` to Docker entrypoint~~ (runs in `lifespan()` instead — same effect)
- [x] Implement pre-migration backup safety (check for recent backup, prompt user, auto `pg_dump` in Docker)
- [x] Test: migration on real v2.4 database with existing data (via testcontainers)
- [x] Test: fresh install (baseline + all migrations)
- [x] Test: idempotency (running migrations twice = no-op)
- [x] Documentation for contributors on creating new migrations (`docs/MIGRATIONS_GUIDE.md`)

### ✅ #13a Self-Serve Licensing — MVP Pricing Page
- **Effort**: ~2-4h | **Edition**: N/A (website) | **Dependencies**: None
- **Repo**: `PGVectorRAGIndexerWebsite` | **Branch**: `feature/pricing-page`
- [x] Pricing section with 4 tiers: Community (Free), Team ($299/yr), Organization ($799/yr), Enterprise (Custom)
- [x] "Reserve your license" CTA (mailto) on Team tier, "Contact Us" on Org/Enterprise
- [x] Pricing FAQ: 6 questions (personal use, commercial trigger, try-before-buy, data privacy, PO/invoice, renewal)
- [x] Responsive CSS: 4-col → 2-col → 1-col grid, glassmorphism cards, featured card highlight
- [x] Nav link added between Teams and Developers

### ✅ #13b Self-Serve Licensing — Stripe Automation
- **Effort**: ~6-8h | **Edition**: N/A (website + backend) | **Dependencies**: #13a, #17
- **Repo**: `PGVectorRAGIndexerWebsite` (Vercel serverless functions)
- [x] Stripe Checkout integration (Team $299/yr + Organization $799/yr)
  - `api/checkout.js`: creates Stripe Checkout sessions per tier
  - Pricing page buttons wired to checkout API with loading state
  - Success modal on return from Stripe (`#purchase-success` hash)
- [x] License key generation: Stripe webhook → JWT signing → email delivery
  - `api/webhook.js`: handles `checkout.session.completed` event
  - Generates JWT license key (same format as `generate_license_key.py`)
  - Emails key via Zoho Mail SMTP (`hello@ragvault.net`)
  - Includes installation instructions for macOS/Linux/Windows
- [x] Manual key generation script for direct sales (`generate_license_key.py` — existed)
- [x] Stripe Products + Prices created (test mode)
- [x] Webhook endpoint configured (`checkout.session.completed`)
- [x] End-to-end tested: checkout → payment → license key email delivered
- **Note**: Yahoo Mail rejects emails from new domain (PH01 policy); Gmail/corporate works fine. Consider Resend for better deliverability.

---

## Phase 1: Security, Versioning, and Licensing Foundation

### ✅ #0 Remote Security Baseline
- **Effort**: ~8-12h | **Edition**: Both | **Dependencies**: None
- **Branch**: `feature/roadmap-v4`
- [x] `API_KEY` auth middleware in FastAPI (`auth.py`, `require_api_key` dependency)
- [x] Config validation: `API_REQUIRE_AUTH=true` env var enables auth
- [x] TLS support: self-signed guide + reverse proxy docs (`docs/REVERSE_PROXY_GUIDE.md`)
- [x] Explicit allow-list of origins and hosts (`API_ALLOWED_HOSTS` + `TrustedHostMiddleware`)
- [x] "Remote mode" warning banner with server URL and auth status (implemented via #1)
- [x] API key lifecycle: create via API (`POST /api/keys?name=...`)
- [x] API key lifecycle: create via CLI (`pgvector_admin.py create-key --name "Alice"`)
- [x] API key lifecycle: list active keys (`GET /api/keys` — name, created, last-used)
- [x] API key lifecycle: revoke immediately (`DELETE /api/keys/{id}`)
- [x] API key lifecycle: rotate (`POST /api/keys/{id}/rotate`, 24h grace period)
- [x] API key storage: hashed (SHA-256) server-side, plaintext shown once at creation
- [x] Key prefix: `pgv_sk_` for identification
- [x] Desktop `api_client.py`: `X-API-Key` header on all requests
- [x] `api_keys` table via Alembic migration 003
- [x] Test: 32 unit + 7 integration tests (key gen, hash, verify, lifecycle)
- [x] Quickstart docs for reverse proxy setup (`docs/REVERSE_PROXY_GUIDE.md`)

### ✅ #17 License Key Validation (Backend ✅, UI ✅, Polish ✅)
- **Effort**: ~6-8h | **Edition**: Both (this IS the edition gate) | **Dependencies**: #11 ✅
- **Branch**: `feature/roadmap-v4`
- [x] Create `license.py` module — Edition enum, LicenseInfo dataclass, JWT validation
- [x] JWT signing/validation (HMAC-SHA256): edition, org, seats, expiry
- [x] Platform-specific key path: Linux/macOS `~/.pgvector-license/license.key`, Windows `%APPDATA%\PGVectorRAGIndexer\license.key`
- [x] Startup logic in `api.py`: missing → Community, valid → Team, expired/invalid → Community + warning
- [x] `GET /license` API endpoint + edition in `/api` info
- [x] `server_settings` table via Alembic migration 002
- [x] `generate_license_key.py` CLI tool for manual sales
- [x] Test: valid key, expired key, missing key, tampered key, offline validation (42 unit + 7 integration)
- [x] UI: Settings → License section (edition badge, org, expiry, seats)
- [x] UI: "Enter License Key" button (file picker → installs .key)
- [x] UI: Community edition "Upgrade to Team" link (opens pricing page)
- [x] UI: Locked-feature placeholder widget (`GatedFeatureWidget`)
- [x] `edition.py` helper: `TEAM_FEATURES` map, `is_feature_available()`, `get_edition_display()`
- [x] Test: 15 edition UI tests (feature map, gating logic, display, pricing URL)
- [x] File permissions: Linux `600`, Windows user-only ACL (`secure_license_file()` in `license.py`)
- [x] Short-expiry strategy: 90-day keys, auto-renewed via Stripe webhook (`invoice.paid`)
- [x] Optional online revocation check (`check_license_revocation()` in `license.py`, graceful fallback, off by default)
- [x] Graceful degradation on expiry: read-only fallback (`is_write_allowed()` in `edition.py`)
- [x] Expiry banner: amber warning < 30 days, red on expired (`_update_license_banner()` in `main_window.py`)

### ✅ #12 API Versioning
- **Effort**: ~3-5h | **Edition**: Both | **Dependencies**: None
- **Branch**: `feature/roadmap-v4`
- [x] Add `/api/v1/` prefix to all endpoints (v1_router + backward compat at `/`)
- [x] `GET /api/version` endpoint (server_version, api_version, min/max client versions)
- [x] Desktop app: version check on connect, warn if incompatible (`check_version_compatibility()`)
- [x] Desktop app: all data calls use `/api/v1/` prefix (`api_base` property)
- [x] Test: 11 tests (version constants, client compat check, prefix validation)
- [x] Document versioning policy (`docs/API_VERSIONING_POLICY.md`)
- [x] Create compatibility matrix (`docs/COMPATIBILITY_MATRIX.md`)
- [x] Release checklist with compat matrix update reminder (in versioning policy doc)

### ✅ #4 Indexing Health Dashboard
- **Effort**: ~7-9h | **Edition**: Both | **Dependencies**: #11
- **Branch**: `feature/roadmap-v4`
- [x] Alembic migration 004: `indexing_runs` table (id, started_at, completed_at, status, trigger, files_scanned/added/updated/skipped/failed, errors JSONB)
- [x] `indexing_runs.py` module: `start_run()`, `complete_run()`, `get_recent_runs()`, `get_run_summary()`, `get_run_by_id()`
- [x] API endpoints: `GET /indexing/runs`, `GET /indexing/runs/summary`, `GET /indexing/runs/{run_id}`
- [x] Integration: `/index` and `/upload-and-index` endpoints record runs with file counts and errors
- [x] Desktop client: `get_indexing_runs()`, `get_indexing_summary()`, `get_indexing_run_detail()`
- [x] UI: `HealthTab` with summary cards, runs table, error detail panel
- [x] Test: 18 tests (migration, helpers, DB resilience, endpoint registration)

---

## Phase 2: Team Enablement

### ✅ #1 Remote Backend Support
- **Effort**: ~4-6h | **Edition**: Team | **Dependencies**: #0
- **Branch**: `feature/roadmap-v4`
- [x] `app_config.py` module: persistent JSON config (backend mode, URL, API key)
- [x] Settings tab: "Backend URL" input + "Local Docker" / "Remote Server" radio toggle
- [x] Hide Docker controls (container mgmt, logs, status bar) in Remote mode
- [x] Require API key for remote URLs (validated on save, tested via `/api/version`)
- [x] Test connection button with server version display
- [x] Main window loads saved config on startup, initializes API client accordingly
- [x] Tests: 21 tests (config persistence, backend mode helpers, API client init)

### ✅ #8 Client Identity and Sync
- **Effort**: ~8-12h | **Edition**: Team | **Dependencies**: #4, #11
- **Branch**: `feature/roadmap-v4`
- [x] Alembic migration 005: `clients` table (id, display_name, os_type, app_version, last_seen_at, created_at)
- [x] Alembic migration 005: `client_id` column on `indexing_runs` (FK → clients)
- [x] `client_identity.py` module: register, heartbeat, get, list, desktop helpers
- [x] API endpoints: `POST /clients/register`, `POST /clients/heartbeat`, `GET /clients`
- [x] Desktop client: auto-registration on first run (generates UUID, stores in app_config)
- [x] Per-run attribution: `client_id` parameter in `start_run()`
- [x] Desktop API methods: `register_client()`, `client_heartbeat()`, `list_clients()`
- [x] Tests: 20 tests (migration, helpers, DB resilience, endpoint registration)

### ✅ #15 Hosted Demo Instance
- **Effort**: ~6-10h | **Edition**: N/A (marketing) | **Dependencies**: None
- **Branch**: `feature/roadmap-v4`
- [x] Read-only mode: `DEMO_MODE=1` env var blocks all write operations (middleware)
  - Allows GET/HEAD/OPTIONS + POST to /search and /virtual-roots/resolve
  - Returns 403 with helpful message for blocked writes
  - `/api` and `/api/version` include `"demo": true` flag
- [x] `Dockerfile.demo`: demo image with DEMO_MODE=1, healthcheck
- [x] `docker-compose.demo.yml`: full demo stack (db + app), auto-reset instructions
- [x] Tests: 11 tests (constants, API responses, Docker files)
- [x] `render.yaml`: Render Blueprint for free tier deployment
- [x] SSL/sslmode support: `DB_SSLMODE` config field for cloud PostgreSQL (Neon)
- [x] Warm-up interstitial page (`demo.html` in Website repo)
  - Polls demo server `/health` endpoint every 3s during cold start
  - Shows feature cards and sample queries while waiting
  - Auto-redirects when server responds; graceful fallback on timeout
- [x] "Try Live Demo" button on website (bold gradient CTA in hero section)
- [x] Deployed to Render free tier (auto-sleep) + Neon free tier (pgvector DB)
  - URL: https://demo-pgvectorrag.onrender.com
  - CPU-only PyTorch for 512MB RAM limit; deferred init for fast port binding
  - HEAD support on root endpoint for Render port detection
- [x] Sample corpus: `scripts/seed_demo.py` — 8 documents, 40 chunks seeded into Neon
  - Topics: getting started, vector embeddings, document processing, API reference,
    RAG concepts, deployment guide, security, performance tuning
- [x] Demo UX: capabilities banner listing full app features + "Learn more →" link to ragvault.net
- [x] Demo UX: hide Upload tab and Delete buttons in demo mode (detected via `/api` demo flag)
- [x] Demo UX: clickable sample query buttons so users know what to search
- [x] Demo UX: desktop app hint banners on Search and Documents tabs

---

## Phase 3: Automation and Navigation

### ✅ #6 Scheduled Automatic Indexing
- **Effort**: ~14-20h | **Edition**: Team | **Dependencies**: #4, #8
- **Branch**: `feature/roadmap-v4`
- [x] Alembic migration 006: `watched_folders` table (path, cron, enabled, last_scanned_at, client_id)
- [x] `watched_folders.py` module: CRUD (add/remove/update/get/list), mark_scanned, scan_folder
- [x] API endpoints: `GET/POST /watched-folders`, `PUT/DELETE /watched-folders/{id}`, `POST /watched-folders/{id}/scan`
- [x] Desktop client API methods: list, add, update, remove, scan watched folders
- [x] `folder_scheduler.py`: In-app QTimer-based scheduler with cron parsing, due-check, auto-scan
- [x] `watched_folders_tab.py`: Full UI tab (add/remove/enable/disable, schedule presets, Scan Now, scheduler toggle)
- [x] Main window integration: Folders tab, scheduler init, client_id wiring in on_api_ready
- [x] Tests: 39 tests (cron parsing, scheduler lifecycle, check logic, CRUD resilience, endpoints)
- [ ] Background service: Linux systemd (deferred — in-app scheduler sufficient for now)
- [ ] Background service: macOS launchd (deferred)
- [ ] Background service: Windows Task Scheduler (deferred)

### ✅ #6b Server-First Automation Profile — MVP (safe mixed-mode scheduling)
- **Effort**: ~8-14h | **Edition**: Team | **Dependencies**: #6, #9, #10, #11
- **Branch**: `feature/roadmap-v5-server-first-automation` (recommended)
- **Design reference**: `docs/RFC_6B_SERVER_FIRST_AUTOMATION.md`
- **Compatibility guardrails**:
  - [x] backward compatible by default (`execution_scope='client'` for existing rows)
  - [x] server scheduler is opt-in (disabled by default)
  - [x] no dependency on #16 Phase 4b (DB-backed roles/compliance)
- [x] Add explicit watched-root execution scope: `client` vs `server`
- [x] Enforce source partitioning:
  - [x] `client` roots can only be scanned by matching client scheduler
  - [x] `server` roots can only be scanned by server scheduler
  - [x] reject wrong-scope scan requests with clear 409 error
- [x] Add stable scheduler root identity (`root_id`) and executor identity (`executor_id`)
- [x] Add normalized path + scoped uniqueness model for watched roots:
  - [x] add `normalized_folder_path` and normalize existing paths during backfill
  - [x] replace global unique `folder_path` with partial unique `(executor_id, normalized_folder_path)` for `client` scope
  - [x] add partial unique `(normalized_folder_path)` for `server` scope
- [x] Enforce DB invariants with `CHECK` constraint:
  - [x] `execution_scope='client' => executor_id IS NOT NULL`
  - [x] `execution_scope='server' => executor_id IS NULL`
- [x] Enforce explicit scope transition flow:
  - [x] disallow ad-hoc `execution_scope` changes in generic update paths
  - [x] add explicit transition API with preflight conflict check
  - [x] perform transition as in-place update preserving `root_id`
- [x] Server scheduler with async scan execution (amendments 1, 4):
  - [x] `asyncio.to_thread()` wrapper for `scan_folder()` to avoid blocking event loop
  - [x] deterministic advisory lock ID (`2050923308` = CRC32 of `pgvector_server_scheduler`)
  - [x] singleton scheduler loop, scans `execution_scope='server'` + `paused=false` roots
- [x] Desktop `FolderScheduler` scope filtering (amendment 2):
  - [x] `_check_folders()` must skip roots where `execution_scope != 'client'`
  - [x] `_check_folders()` must skip roots where `executor_id != self._client_id`
- [x] `GET /watched-folders` query filter params (amendment 5):
  - [x] `execution_scope=client|server` filter
  - [x] `executor_id=<client_id>` filter
- [x] Filesystem access validation for server roots (amendment 3):
  - [x] `POST /watched-folders` validates path exists when `execution_scope='server'`
  - [x] doc: Docker bind-mount requirement, bare-metal process user access (DEPLOYMENT.md)
- [x] Add server automation safety controls:
  - [x] per-root scan watermarks (`last_scan_started_at`, `last_scan_completed_at`, `last_successful_scan_at`)
  - [x] failure backoff with `consecutive_failures` and `last_error_at`
  - [x] per-root concurrency cap (default 1)
- [x] Add observability and admin controls:
  - [x] scheduler status API by root (next run, last run, failure streak)
  - [x] activity log fields: `executor_scope`, `executor_id`, `root_id`, `run_id` (migration 016)
  - [x] admin UI controls for server roots: pause/resume/scan-now
- [x] Alembic migration updates:
  - [x] extend `watched_folders` with `execution_scope`, `executor_id`, `normalized_folder_path`, `root_id`, failure fields
  - [x] backfill existing rows (`execution_scope='client'`, `executor_id=client_id`, generated `root_id`)
  - [x] add indexes on `(execution_scope, enabled, schedule_cron)` and `(root_id, execution_scope)`
- [x] Tests (38 tests):
  - [x] mixed-mode conflict tests (server root + desktop root with same relative path)
  - [x] wrong-scope rejection tests (409 path)
  - [x] async scan execution test (does not block event loop)
  - [x] desktop scheduler scope filtering regression
  - [x] filesystem validation for server-scope root creation
  - [x] API filter params (`execution_scope`, `executor_id`)

Implementation sequencing (recommended):
- [x] Phase 6b-MVP: scope partitioning + server scheduler (async, singleton) + desktop scope filtering + API filter params + filesystem validation + status/pause/resume/scan-now + 409 protection
- [x] Phase 6b.2: canonical identity (`canonical_source_key`) + lock key migration `(root_id, relative_path)`:
  - [x] Alembic migration 014: `UNIQUE(root_id)` constraint, `canonical_source_key TEXT` on `document_chunks`, `root_id`/`relative_path` on `document_locks`
  - [x] `canonical_identity.py`: build/resolve canonical keys (`client:<id>:<path>`, `server:<root>:<path>`), `bulk_set_canonical_keys`, `find_by_canonical_key`
  - [x] `document_locks.py`: dual-key lock resolution (`root_id`+`relative_path` with `source_uri` fallback)
  - [x] `watched_folders.py`: `root_id` param on `scan_folder()`, `_backfill_canonical_keys()` post-scan
  - [x] `server_scheduler.py`: passes `root_id` to `scan_folder()`
  - [x] Tests: 32 tests in `test_canonical_source_key.py`
- [x] Phase 6b.3: quarantine delete lifecycle + dry-run reporting:
  - [x] Alembic migration 015: `quarantined_at TIMESTAMPTZ`, `quarantine_reason TEXT`, partial index on `document_chunks`
  - [x] `quarantine.py`: quarantine/restore/list/purge/stats with configurable retention (`QUARANTINE_RETENTION_DAYS`)
  - [x] `watched_folders.py`: `dry_run=True` param, `_dry_run_scan()`, `_quarantine_missing_sources()` post-scan
  - [x] `server_scheduler.py`: `_maybe_purge_quarantine()` periodic purge (24h interval)
  - [x] `api.py`: `?dry_run=true` on scan endpoint + 4 quarantine endpoints (`GET /quarantine`, `POST /quarantine/{uri}/restore`, `POST /quarantine/purge`, `GET /quarantine/stats`)
  - [x] Tests: 23 tests in `test_quarantine.py`
  - [x] Full regression: 93 tests pass across 4 #6b suites, zero failures

### ✅ #9 Path Mapping / Virtual Roots
- **Effort**: ~6-10h | **Edition**: Team | **Dependencies**: #1
- **Branch**: `feature/roadmap-v4`
- [x] Alembic migration 007: `virtual_roots` table (name, client_id, local_path, unique constraint)
- [x] `virtual_roots.py` module: CRUD (add/remove/get/list), list_root_names, get_mappings_for_root
- [x] Path resolution: `resolve_path()` splits virtual path → root name + remainder → local path
- [x] API endpoints: `GET/POST /virtual-roots`, `GET /virtual-roots/names`, `GET /virtual-roots/{name}/mappings`, `DELETE /virtual-roots/{id}`, `POST /virtual-roots/resolve`
- [x] Desktop client API methods: list, list_names, get_mappings, add, remove, resolve
- [x] Tests: 22 tests (migration, _row_to_dict, DB resilience, path resolution, endpoints)

### ✅ #7 Hierarchical Document Browser
- **Effort**: ~12-16h | **Edition**: Both | **Dependencies**: #4, #9
- **Branch**: `feature/roadmap-v4`
- [x] `document_tree.py` module: get_tree_children (lazy one-level-at-a-time), get_tree_stats, search_tree
- [x] Path normalization (backslashes, tabs → forward slashes) for cross-platform consistency
- [x] Aggregated counts/timestamps per folder (computed server-side from source_uri paths)
- [x] Pagination support (limit/offset on combined folders+files)
- [x] API endpoints: `GET /documents/tree`, `GET /documents/tree/stats`, `GET /documents/tree/search`
- [x] Desktop client API methods: get_document_tree, get_document_tree_stats, search_document_tree
- [x] Tests: 14 tests (normalize_path, tree building with mocked DB, stats, search, endpoints)
- [x] Desktop UI: `QTreeView` + `QAbstractItemModel` with `canFetchMore()`/`fetchMore()` lazy-loading (`document_tree_model.py`)
- [x] WSL support: Windows native file dialogs via PowerShell, WSL path resolution for file opening
- [x] Linux path handling: paths starting with `/` appear as proper root-level entries (no empty-name folder)

### ✅ #10 Activity and Audit Log
- **Effort**: ~6-10h | **Edition**: Team | **Dependencies**: #4, #11
- **Branch**: `feature/roadmap-v4`
- [x] Alembic migration 008: `activity_log` table (id, ts, client_id, user_id, action, details JSONB)
- [x] `activity_log.py` module: log_activity, get_recent, get_activity_count, get_action_types, export_csv, apply_retention
- [x] API endpoints: `GET/POST /activity`, `GET /activity/actions`, `GET /activity/export`, `POST /activity/retention`
- [x] Desktop client API methods: get_activity_log, post_activity, get_activity_action_types, export_activity_csv, apply_activity_retention
- [x] CSV export with proper header and JSON details serialization
- [x] Retention policy: delete entries older than N days
- [x] Tests: 17 tests (migration, _row_to_dict, DB resilience, CSV export, endpoints)

---

## Phase 4: Multi-User and Enterprise

### ✅ #2 Split Deployment
- **Effort**: ~6-10h | **Edition**: Team | **Dependencies**: #1, #0, #12
- **Branch**: `feature/roadmap-v4`
- [x] `server-setup.sh` for Linux/macOS/NAS (port config, auto-key generation, Docker health wait)
- [x] `server-setup-wsl.sh` for Windows servers (WSL2 detection, delegates to main script, firewall notes)
- [x] `bootstrap_desktop_app.sh` — `--remote-backend URL` flag (skips Docker, pre-seeds remote config)
- [x] `bootstrap_desktop_app.ps1` — `-RemoteBackend URL` parameter (same behavior)
- [x] `docs/DEPLOYMENT.md` — platform support matrix, architecture diagram, security guide, troubleshooting
- [x] Version compatibility check on client connect (pre-existing via `GET /api/version` + `check_version_compatibility()`)
- [x] Tests: 24 tests (script existence, flags, docs content, version endpoint, app_config helpers)

### ✅ #3 Multi-User Support
- **Effort**: ~20-30h | **Edition**: Team | **Dependencies**: #1, #2, #8, #10, #17
- **Branch**: `feature/roadmap-v4`
- **Phase 1 — Shared corpus** (complete):
  - [x] API key authentication (per-user keys) — pre-existing via #12
  - [x] Per-client identity and last seen — pre-existing via #8
  - [x] Conflict-safe indexing: `document_locks` table with TTL (10 min default)
    - Alembic migration 009: `document_locks` table with `source_uri`, `client_id`, `locked_at`, `expires_at`, `lock_reason`
    - Unique index on `source_uri` prevents double-locking
    - Expired locks auto-cleaned on acquire attempts
  - [x] Clear error: "Document X is being indexed by Client Y (lock expires at ...)"
  - [x] Same-client lock extension (re-acquire extends TTL)
  - [x] Force-release (admin operation)
  - [x] Auditable activity log — pre-existing via #10
  - [x] All users see all documents (shared corpus — default behavior)
  - [x] API endpoints: POST acquire/release/force-release/cleanup, GET list/check
  - [x] Desktop client API methods: acquire, release, force_release, list, check, cleanup
  - [x] Tests: 20 tests (migration, row conversion, DB resilience, conflict logic, endpoints)
- **Phase 2 — User scoping** (complete):
  - [x] Alembic migration 012: `owner_id` (FK → users) and `visibility` columns on `document_chunks`
  - [x] `document_visibility.py` module: visibility_where_clause (SQL filter generation), set_document_owner, set_document_visibility, set_document_owner_and_visibility, get_document_visibility, list_user_documents, bulk_set_visibility, transfer_ownership
  - [x] Visibility rules: shared (default, visible to all), private (owner + admins only), NULL owner = shared (backward compat)
  - [x] Updated `document_stats` view to include owner_id and visibility
  - [x] API endpoints (5): GET/PUT /documents/{id}/visibility, POST /documents/{id}/transfer (admin), GET /users/{id}/documents, POST /documents/bulk-visibility (admin)
  - [x] Desktop client API methods: get_document_visibility, set_document_visibility, transfer_document_ownership, list_user_documents, bulk_set_document_visibility
  - [x] Audit log: document.visibility_changed, document.ownership_transferred, document.bulk_visibility_changed events
  - [x] Tests: 28 tests (migration, constants, SQL filter generation, DB resilience, validation, endpoints)
- **Phase 3 — Enterprise auth** (complete via #16):
  - [x] SSO/SAML integration (Okta) — see #16 Phase 2
  - [x] RBAC with admin/user roles — see #16 Phase 1

### ⬜ #14 Usage Analytics
- **Effort**: ~6-10h | **Edition**: Both (opt-in) | **Dependencies**: #4 (optional)
- [ ] Opt-in dialog (off by default, clear one-sentence explanation)
- [ ] Self-hosted collector (PostHog self-hosted or custom endpoint)
- [ ] Events: install, first index, first search, daily active, errors, feature usage, OS/version
- [ ] Settings tab: log of every event that would be sent
- [ ] "What we collect" page on website with example JSON payload
- [ ] No PII, no document content, no file names, no search queries

### ✅ #16 Enterprise Foundations
- **Effort**: ~15-25h | **Edition**: Team (enterprise tier) | **Dependencies**: #0, #8
- **Branch**: `feature/roadmap-v4`
- **Phase 1 — RBAC and Users** (complete):
  - [x] Alembic migration 010: `users` table (id, email, display_name, role, auth_provider, api_key_id FK, client_id FK, timestamps, is_active)
  - [x] `users.py` module: create, get, get_by_email, get_by_api_key, list, update, delete, deactivate, is_admin, record_login, change_role, count_admins
  - [x] RBAC: `require_admin` FastAPI dependency in `auth.py` — checks API key → user → admin role
    - Bootstrap mode: allows access when no admin users exist yet
    - Graceful degradation on DB errors
  - [x] Audit log extension: user.created, user.updated, user.deleted, user.role_changed events via activity_log
  - [x] Safety: cannot delete or demote the last admin user
  - [x] API endpoints (6): GET /users, GET /users/{id}, POST /users (admin), PUT /users/{id} (admin), DELETE /users/{id} (admin), POST /users/{id}/role (admin)
  - [x] Desktop client API methods: list_users, get_user, create_user, update_user, delete_user, change_user_role
  - [x] Tests: 26 tests (migration, constants, row conversion, DB resilience, role validation, require_admin, endpoints)
- **Phase 2 — SSO/SAML** (complete — Okta):
  - [x] Alembic migration 011: `saml_sessions` table (id, user_id FK, session_index, name_id, name_id_format, idp_entity_id, created_at, expires_at, is_active)
  - [x] `saml_auth.py` module: SP metadata, login initiation, ACS callback, SLO, session CRUD, auto-provisioning
  - [x] Configuration via env vars: SAML_ENABLED, SAML_IDP_*, SAML_SP_*, SAML_SESSION_LIFETIME_HOURS, SAML_AUTO_PROVISION, SAML_DEFAULT_ROLE
  - [x] Auto-provision users on first SAML login (configurable)
  - [x] Graceful degradation: python3-saml is optional; all endpoints return 404 if SAML not enabled
  - [x] API endpoints (6): GET /saml/metadata, GET /saml/login, POST /saml/acs, GET /saml/logout, GET /saml/status, POST /saml/sessions/cleanup (admin)
  - [x] Audit log: user.saml_login, user.saml_logout events
  - [x] Tests: 29 tests (migration, config, settings builder, request prep, session conversion, DB resilience, auto-provisioning, endpoints)
  - [x] `python3-saml` added to requirements.txt
- **Phase 3 — SCIM Provisioning** (complete):
  - [x] `scim.py` module: RFC 7643/7644 compliant SCIM 2.0 server
  - [x] Schema mapping: SCIM User ↔ users table (userName→email, displayName→display_name, active→is_active, custom role extension)
  - [x] SCIM filter parser: eq, ne, co, sw, ew operators; and/or combinators; attribute mapping
  - [x] SCIM PATCH processor: replace, add, remove operations; path-based and dict-based updates
  - [x] Bearer token authentication via SCIM_BEARER_TOKEN env var
  - [x] Discovery endpoints: GET /scim/v2/ServiceProviderConfig, /Schemas, /ResourceTypes
  - [x] User CRUD: GET/POST /scim/v2/Users, GET/PUT/PATCH/DELETE /scim/v2/Users/{id}
  - [x] DELETE = soft-deactivate (is_active=false), not hard delete
  - [x] Graceful degradation: all endpoints return 404 if SCIM_ENABLED != true
  - [x] Audit log: user.scim_provisioned, user.scim_updated, user.scim_patched, user.scim_deprovisioned events
  - [x] Tests: 50 tests (config, bearer auth, user↔SCIM mapping, filter parser, PATCH ops, discovery, constants, endpoints)
  - [x] Configuration: SCIM_ENABLED, SCIM_BEARER_TOKEN, SCIM_DEFAULT_ROLE env vars
- **Phase 4a — Custom Roles & Permissions** (complete):
  - [x] `role_permissions.py` module: 10 granular permissions (documents.read/write/delete/visibility/visibility.all, health.view, audit.view, users.manage, keys.manage, system.admin)
  - [x] Config-driven roles via `role_permissions.json` — no restart needed to add roles (just edit JSON)
  - [x] Built-in roles: admin (all perms), user (read+write+visibility), researcher (same as user), sre (full docs+health+audit), support (read-only+health+audit)
  - [x] `require_permission()` factory in auth.py — creates FastAPI dependencies for any permission
  - [x] `require_admin()` now delegates to `require_permission("system.admin")` — backward compatible
  - [x] `users.py` dynamic role validation — accepts any role defined in config, not just admin/user
  - [x] system.admin permission grants all other permissions automatically
  - [x] Admin role always gets all permissions even if config file is edited (safety guard)
  - [x] API endpoints (4): GET /roles, GET /roles/{name}, GET /permissions, GET /roles/{name}/check/{permission}
  - [x] Tests: 54 tests (constants, built-in roles, config loading, permission checks, role validation, listing, require_permission factory, dynamic users.py, endpoints)
  - [x] Upgrade path documented: replace `load_role_config()` to read from DB `roles` table for Phase 4b
- **Phase 4b — DB-Backed Roles** (complete):
  - [x] DB-backed roles table (migration 016) — runtime CRUD via API
  - [x] `role_permissions.py`: `load_role_config()` reads from DB first, falls back to JSON/built-in
  - [x] `create_role()`, `update_role()`, `delete_role()` CRUD functions
  - [x] API endpoints: POST/PUT/DELETE `/roles` (admin-only, system role protection)
  - [x] Tests: 26 tests in `test_db_roles.py` + 54 existing in `test_role_permissions.py` pass
  - [x] Data retention policies (scoped rollout):
    - [x] Policy matrix defaults (by data class):
      - [x] `document_chunks`: keep indefinitely by default (no auto-purge)
      - [x] quarantine rows: 30 days (configurable) before hard purge
      - [x] `activity_log`: 2555 days (~7 years) default, configurable
      - [x] `indexing_runs`: 10950 days (~30 years) default, terminal states only
      - [x] SAML/auth sessions: expiry-driven cleanup only (explicitly excluded from long-retention presets)
    - [x] Safety predicates for `indexing_runs` purge:
      - [x] never delete active/running rows
      - [x] purge only terminal states
      - [x] document timestamp predicate (`COALESCE(completed_at, started_at)`) in code + tests
    - [x] API compatibility/deprecation path:
      - [x] keep existing `/activity/retention` and `/quarantine/purge` endpoints for compatibility
      - [x] add `/retention/*` orchestration endpoints as additive layer
      - [x] deprecate legacy endpoints only after client migration window
    - [x] Runtime model:
      - [x] retention execution must not depend only on server scheduler flag
      - [x] add independent maintenance loop/startup path (or external cron) for purge jobs
    - [x] Automated tests:
      - [x] per-category retention policy tests
      - [x] indexing-runs guardrail tests (active rows preserved)
      - [x] endpoint compatibility tests (legacy + new orchestration)
    - [x] Rollout order:
      - [x] docs/policy matrix first
      - [x] additive APIs + maintenance runner second
      - [x] deprecation notices last
  - [x] Compliance exports (`compliance_export.py`, admin-only `GET /compliance/export` ZIP endpoint)
  - **Note**: Migration 017 creates a `retention_policies` DB table (schema-only). DB-backed admin overrides are a future item — runtime currently reads from env vars / hardcoded defaults only.

---

## Lower Priority (Any Time)

### ✅ #5 Upload Tab UI Streamlining
- **Effort**: ~3-5h | **Edition**: Both | **Dependencies**: None
- **Branch**: `feature/roadmap-v4`
- [x] Make "Index Folder" the primary action (larger button, `primary` class, listed first)
- [x] Show "Last Indexed" timestamp per folder (queries document tree API on folder select)
- [x] Minimize "Select Individual Files" button (smaller, subdued styling, secondary position)
- [x] Renamed group box from "Select File" to "Select Documents"
- [x] Tests: 11 tests (button properties, label visibility, API error handling, timestamp display)

---

## Completed

(Move completed features here with completion date)

---

Last updated: 2026-02-19
