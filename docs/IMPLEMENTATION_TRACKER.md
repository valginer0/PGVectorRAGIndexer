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
| ⏸️ | Blocked |

---

## Immediate Actions (Parallel)

These have zero dependencies on each other and should start simultaneously.

### ⬜ #11 Schema Migration Framework
- **Effort**: ~4-6h | **Edition**: Both | **Dependencies**: None
- **Branch**: `feature/schema-migrations`
- [ ] Add Alembic to `requirements.txt`
- [ ] Create `alembic/` directory with `alembic.ini`, `env.py`
- [ ] Write baseline migration from current `init-db.sql` schema
- [ ] Auto-run pending migrations on app startup (Docker + desktop)
- [ ] Add `alembic upgrade head` to Docker entrypoint
- [ ] Implement pre-migration backup safety (check for recent backup, prompt user, auto `pg_dump` in Docker)
- [ ] Test: migration on real v2.4 database with existing data
- [ ] Test: fresh install (baseline + all migrations)
- [ ] Test: idempotency (running migrations twice = no-op)
- [ ] Documentation for contributors on creating new migrations

### ⬜ #13 Self-Serve Licensing
- **Effort**: ~8-12h | **Edition**: N/A (website) | **Dependencies**: None
- **Repo**: `PGVectorRAGIndexerWebsite`
- [ ] Design pricing page with tiers (Community / Team / Organization / Enterprise)
- [ ] MVP: pricing page + "Reserve your license — email us" CTA
- [ ] FAQ page for procurement questions
- [ ] Stripe Checkout integration (Team + Organization tiers)
- [ ] License key generation: Stripe webhook → signing service → email delivery
- [ ] Manual key generation script for direct sales

---

## Phase 1: Security, Versioning, and Licensing Foundation

### ⬜ #0 Remote Security Baseline
- **Effort**: ~8-12h | **Edition**: Both | **Dependencies**: None
- **Branch**: `feature/remote-security`
- [ ] `API_KEY` auth middleware in FastAPI
- [ ] Config validation: block remote URL without API key
- [ ] TLS support: self-signed guide + reverse proxy docs (Caddy/Nginx)
- [ ] Explicit allow-list of origins and hosts
- [ ] "Remote mode" warning banner with server URL and auth status
- [ ] API key lifecycle: create via CLI (`pgvector-admin create-key --name "Alice"`) and Settings UI
- [ ] API key lifecycle: list active keys (name, created, last-used)
- [ ] API key lifecycle: revoke immediately
- [ ] API key lifecycle: rotate (new key, 24h grace period, auto-revoke old)
- [ ] API key storage: hashed (SHA-256) server-side, plaintext shown once at creation
- [ ] Key prefix: `pgv_sk_` for identification
- [ ] Quickstart docs for reverse proxy setup

### ⬜ #17 License Key Validation
- **Effort**: ~6-8h | **Edition**: Both (this IS the edition gate) | **Dependencies**: None
- **Branch**: `feature/license-validation`
- [ ] Create `license.py` module (not in config.py)
- [ ] JWT signing/validation (HMAC-SHA256): edition, org, seats, expiry
- [ ] Platform-specific key path: Linux/macOS `~/.pgvector-license/license.key`, Windows `%APPDATA%\PGVectorRAGIndexer\license.key`
- [ ] File permissions: Linux `600`, Windows user-only ACL
- [ ] Startup logic: missing → Community, valid → Team, expired/invalid → Community + warning
- [ ] Short-expiry strategy: 90-day keys, auto-renewed via Stripe webhook
- [ ] Optional online revocation check (graceful fallback, never blocks app)
- [ ] Graceful degradation on expiry: read-only fallback (owner client retains write)
- [ ] `server_settings` table with `owner_client_id`
- [ ] Expiry banner: "Team license expired on [date]. Renew at [URL]."
- [ ] UI: Settings → License section (edition, org, expiry, seats)
- [ ] UI: "Enter License Key" button (paste or browse)
- [ ] UI: Community edition "Upgrade to Team" link
- [ ] UI: Locked-feature placeholders ("🔒 Team feature — requires a license")
- [ ] Test: valid key, expired key, missing key, tampered key, offline validation
- [ ] Manual key generation script for direct sales

### ⬜ #12 API Versioning
- **Effort**: ~3-5h | **Edition**: Both | **Dependencies**: None
- **Branch**: `feature/api-versioning`
- [ ] Add `/api/v1/` prefix to all endpoints (keep `/` redirecting to v1)
- [ ] `GET /api/version` endpoint (server_version, api_version, min/max client versions)
- [ ] Desktop app: version check on connect, warn if incompatible
- [ ] Document versioning policy
- [ ] Create compatibility matrix in docs
- [ ] Add compatibility matrix update to PR template checkbox

### ⬜ #4 Indexing Health Dashboard
- **Effort**: ~7-9h | **Edition**: Both | **Dependencies**: #11
- **Branch**: `feature/health-dashboard`
- [ ] Alembic migration: `indexing_runs` table (id, started_at, completed_at, status, files_scanned/added/updated, errors)
- [ ] API endpoints for run history and status
- [ ] UI: dashboard showing recent runs, success/failure rates
- [ ] Integration with existing indexing flow (record runs)

---

## Phase 2: Team Enablement

### ⬜ #1 Remote Backend Support
- **Effort**: ~4-6h | **Edition**: Team | **Dependencies**: #0
- **Branch**: `feature/remote-backend`
- [ ] Settings tab: "Backend URL" setting
- [ ] Toggle: "Local Docker" vs "Remote Server"
- [ ] Hide Docker controls in Remote mode
- [ ] Require API key for remote URLs (enforced by #0)

### ⬜ #8 Client Identity and Sync
- **Effort**: ~8-12h | **Edition**: Team | **Dependencies**: #4, #11
- **Branch**: `feature/client-identity`
- [ ] Alembic migration: `clients` table (id, display_name, os_type, app_version, last_seen_at)
- [ ] Alembic migration: add `client_id` column to `indexing_runs`
- [ ] Client registration on first run (client_id + device name + OS info)
- [ ] Per-run attribution: client_id stored in indexing_runs
- [ ] UI: "Last seen" status for clients

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

### ⬜ #6 Scheduled Automatic Indexing
- **Effort**: ~14-20h | **Edition**: Team | **Dependencies**: #4, #8
- **Branch**: `feature/scheduled-indexing`
- [ ] Alembic migration: `watched_folders` table
- [ ] Background service: Linux systemd (start here)
- [ ] Background service: macOS launchd
- [ ] Background service: Windows Task Scheduler
- [ ] Fallback: in-app QTimer-based scheduler
- [ ] UI: watched folders list (add/remove/enable/disable)
- [ ] UI: per-folder schedule settings
- [ ] UI: "Scan Now" button, status indicators, service toggle

### ⬜ #9 Path Mapping / Virtual Roots
- **Effort**: ~6-10h | **Edition**: Team | **Dependencies**: #1
- **Branch**: `feature/path-mapping`
- [ ] Alembic migration: `virtual_roots` table
- [ ] Prompt for virtual root name when adding watched folder
- [ ] "Show local paths" toggle in tree view toolbar
- [ ] Details panel for selected virtual root (all client mappings)
- [ ] Cross-platform path resolution using `clients.os_type`

### ⬜ #7 Hierarchical Document Browser
- **Effort**: ~12-16h | **Edition**: Both | **Dependencies**: #4, #9
- **Branch**: `feature/hierarchical-browser`
- [ ] `GET /documents/tree` API endpoint (paginated, cached, keyed by virtual root)
- [ ] `QTreeView` with custom model (lazy/virtual loading)
- [ ] Expand-on-demand: child nodes fetched on parent expand
- [ ] Aggregated counts/timestamps per folder (server-side, cached)
- [ ] Search-within-tree: filter to matching paths

### ⬜ #10 Activity and Audit Log
- **Effort**: ~6-10h | **Edition**: Team | **Dependencies**: #4, #11
- **Branch**: `feature/audit-log`
- [ ] Alembic migration: `activity_log` table + indexes
- [ ] Record events: index_start, index_complete, delete, upload, search
- [ ] UI: recent activity panel (filter by client, user, action)
- [ ] Export to CSV
- [ ] Retention policy setting (auto-delete after N days)

---

## Phase 4: Multi-User and Enterprise

### ⬜ #2 Split Deployment
- **Effort**: ~6-10h | **Edition**: Team | **Dependencies**: #1, #0, #12
- **Branch**: `feature/split-deployment`
- [ ] `server-setup.sh` for Linux/macOS/NAS
- [ ] Modified bootstrap script with `--remote-backend` flag
- [ ] WSL-based setup for Windows servers
- [ ] Platform support matrix in deployment docs
- [ ] Version compatibility check on client connect (via #12)

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
