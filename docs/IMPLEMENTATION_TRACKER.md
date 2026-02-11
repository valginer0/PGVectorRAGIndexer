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

### ⬜ #13a Self-Serve Licensing — MVP Pricing Page
- **Effort**: ~2-4h | **Edition**: N/A (website) | **Dependencies**: None
- **Repo**: `PGVectorRAGIndexerWebsite`
- [ ] Design pricing page with tiers (Community / Team / Organization / Enterprise)
- [ ] MVP: pricing page + "Reserve your license — email us" CTA
- [ ] FAQ page for procurement questions

### ⬜ #13b Self-Serve Licensing — Stripe Automation
- **Effort**: ~6-8h | **Edition**: N/A (website + backend) | **Dependencies**: #13a, #17
- **Repo**: `PGVectorRAGIndexerWebsite` + signing service
- [ ] Stripe Checkout integration (Team + Organization tiers)
- [ ] License key generation: Stripe webhook → signing service → email delivery
- [ ] Manual key generation script for direct sales

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

### 🟡 #17 License Key Validation (Backend ✅, UI ✅, Polish Pending)
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
- [ ] Short-expiry strategy: 90-day keys, auto-renewed via Stripe webhook
- [ ] Optional online revocation check (graceful fallback, never blocks app)
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

### ⬜ #15 Hosted Demo Instance
- **Effort**: ~6-10h | **Edition**: N/A (marketing) | **Dependencies**: None
- [ ] Pre-built Docker image with sample corpus baked in
- [ ] Read-only mode (indexing disabled)
- [ ] Deploy to small VM (Railway/Fly.io/$5 VPS)
- [ ] "Try it now" button on website
- [ ] Banner: "This demo runs on our server with sample data. The real product runs entirely on yours."
- [ ] Conversion CTA: "Like what you see? Install the local version →"
- [ ] Auto-reset daily

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
- [ ] `QTreeView` with custom model (lazy/virtual loading) — deferred to UI polish pass

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

### ⬜ #3 Multi-User Support
- **Effort**: ~20-30h | **Edition**: Team | **Dependencies**: #1, #2, #8, #10, #17
- **Branch**: `feature/multi-user`
- **Phase 1 — Shared corpus** (~12-16h):
  - [ ] API key authentication (per-user keys)
  - [ ] Per-client identity and last seen (via #8)
  - [ ] Conflict-safe indexing: `document_locks` table with TTL (10 min default)
  - [ ] PostgreSQL advisory locks for short operations
  - [ ] Clear error: "Document X is being indexed by Client Y (lock expires in N min)"
  - [ ] Auditable activity log (via #10)
  - [ ] All users see all documents (shared corpus)
- **Phase 2 — User scoping** (8-14h, only if paid demand):
  - [ ] Per-user document visibility
  - [ ] Shared vs. private document spaces
  - [ ] Admin role for managing users
- **Phase 3 — Enterprise auth** (via #16, only when paying customer requests):
  - [ ] SSO/SAML integration
  - [ ] RBAC with custom roles
- [ ] Test: concurrent writes (multiple clients indexing simultaneously)
- [ ] Test: conflict resolution
- [ ] Test: permission boundaries (Phase 2+)

### ⬜ #14 Usage Analytics
- **Effort**: ~6-10h | **Edition**: Both (opt-in) | **Dependencies**: #4 (optional)
- [ ] Opt-in dialog (off by default, clear one-sentence explanation)
- [ ] Self-hosted collector (PostHog self-hosted or custom endpoint)
- [ ] Events: install, first index, first search, daily active, errors, feature usage, OS/version
- [ ] Settings tab: log of every event that would be sent
- [ ] "What we collect" page on website with example JSON payload
- [ ] No PII, no document content, no file names, no search queries

### ⬜ #16 Enterprise Foundations
- **Effort**: ~15-25h | **Edition**: Team (enterprise tier) | **Dependencies**: #0, #8
- **Build on-demand only** — when a paying customer requests it.
- **Phase 1** (~10-15h):
  - [ ] Alembic migration: `users` table (id, email, display_name, role, auth_provider)
  - [ ] RBAC: Admin and User roles
  - [ ] Audit log extension: login/logout, permission changes
- **Phase 2** (~10-15h, only when paid demand):
  - [ ] SSO/SAML: one provider (Okta or Azure AD)
- **Phase 3** (future, multiple enterprise customers):
  - [ ] SCIM provisioning
  - [ ] Custom roles
  - [ ] Data retention policies
  - [ ] Compliance exports

---

## Lower Priority (Any Time)

### ⬜ #5 Upload Tab UI Streamlining
- **Effort**: ~3-5h | **Edition**: Both | **Dependencies**: None
- [ ] Make "Index Folder" the primary action
- [ ] Show "Last Indexed" timestamp per folder
- [ ] Minimize "Index File" button (secondary option)

---

## Completed

(Move completed features here with completion date)

---

Last updated: 2026-02-10
