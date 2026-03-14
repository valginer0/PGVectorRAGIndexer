# Feature Ideas & Roadmap v6

This revision reflects the state after **all v5 features have been completed**. The product is functionally complete for team/organization deployments. v6 focuses on **hardening, operational maturity, and reducing friction** — the work that turns a feature-complete product into one that enterprise buyers confidently purchase.

---

## V5 Completion Status

All 18 features from v5 (#0–#17) are **shipped and tested**:

| # | Feature | Status |
|---|---------|--------|
| 0 | Remote Security Baseline | ✅ Done |
| 1 | Remote Backend Support | ✅ Done |
| 2 | Split Deployment | ✅ Done |
| 3 | Multi-User (all 3 phases) | ✅ Done |
| 4 | Indexing Health Dashboard | ✅ Done |
| 5 | Upload Streamlining | ✅ Done |
| 6 | Scheduled Indexing + 6b Server-First | ✅ Done |
| 7 | Hierarchical Document Browser | ✅ Done |
| 8 | Client Identity and Sync | ✅ Done |
| 9 | Path Mapping / Virtual Roots | ✅ Done |
| 10 | Activity and Audit Log | ✅ Done |
| 11 | Schema Migration Framework | ✅ Done |
| 12 | API Versioning | ✅ Done |
| 13 | Self-Serve Licensing (Stripe) | ✅ Done |
| 14 | Usage Analytics (opt-in) | ✅ Done |
| 15 | Hosted Demo Instance | ✅ Done |
| 16 | Enterprise Foundations (RBAC, SAML, SCIM, retention, compliance) | ✅ Done |
| 17 | License Key Validation (RS256 JWT) | ✅ Done |

**Additional work completed beyond v5 scope:**
- SCIM 2.0 Group provisioning (RFC 7643/7644)
- Desktop admin console with full CRUD (users, API keys, groups, retention, compliance)
- Organization edition with 3-tier licensing (Community/Team/Organization)
- Admin console capability probing and permission-aware UI gating
- 1527+ automated tests across 106 test files

---

## Guiding Principles (v6)

1. **Feature-complete is not product-complete.** The gap between "works" and "sells" is operational maturity, onboarding, and trust signals.
2. **Enterprise buyers evaluate with checklists.** Rate limiting, backups, monitoring, and encryption are checkbox items — missing any one can disqualify the product.
3. **Reduce time-to-value.** The fastest path from download to "wow" determines conversion.
4. **Don't build what customers won't pay for.** Validate demand before investing in horizontal scaling, SaaS mode, or exotic integrations.
5. **Enforce what you sell.** Seat limits, rate limits, and edition boundaries must be real, not honor-system.
6. **Enforcement should feel like a natural boundary, not a punishment.** "You've filled your team — time to grow?" not "ACCESS DENIED." Grace zones and clear upgrade paths preserve goodwill.

---

## Implementation Sequence

Revised based on external review and internal analysis.

### Phase 1: Conversion & Trust

| # | Feature | Effort | Why now |
|---|---------|--------|---------|
| 18 | First-Run Onboarding Wizard | 8–12h | Reduces time-to-value from hours to minutes |
| 19 | Server-Side Rate Limiting | 4–6h | Checks critical security box |
| 20 | Seat Enforcement | 3–5h | Enforces what we sell |

### Phase 2: Enterprise Readiness

| # | Feature | Effort | Why now |
|---|---------|--------|---------|
| 21a | Scheduled Backups | 6–8h | Checks ops box, builds trust |
| 22 | Prometheus/OpenTelemetry Metrics | 6–10h | Enables enterprise monitoring integration |
| 26 | Performance Benchmarks | 4–6h | Answers the #1 buyer question — cheap, credible, directly helps sales |
| 27 | Support Diagnostics Bundle | 4–6h | One-click system report for support and evaluations |

### Phase 3: Integration & Recovery

| # | Feature | Effort | Why now |
|---|---------|--------|---------|
| 21b | Restore Workflow | 4–6h | Completes backup story with tested recovery path |
| 23 | Event Webhooks | 10–14h | Enables workflow integration — build when customer pull exists |

### Phase 4: Compliance & Demand-Driven

| # | Feature | Effort | Why now |
|---|---------|--------|---------|
| 24 | Encryption at Rest | 20–30h | Only when a regulated-industry customer requires it |
| 25 | Email Notifications | 4–6h | Proactive admin alerting — lower priority than diagnostics |

---

## Feature Details

### 18. First-Run Onboarding Wizard
**Effort**: ~8–12h | **Dependencies**: None | **Edition**: Both

**Problem**: New users face a blank screen after install. Enterprise evaluators who can't get to "first search" in 10 minutes move on.

**Why it matters**: The hosted demo (#15) reduces the install barrier, but once installed, the desktop app has no guided setup. The gap between "installed" and "productive" is where most evaluations die.

Key deliverables:
- Multi-step wizard on first launch (detect → connect → verify → index → search):
  1. **Server connection**: Auto-detect local Docker or enter remote URL + API key
  2. **Verify connection**: Test connectivity, show server version and edition
  3. **License setup**: Paste license key or continue as Community
  4. **Index sample docs**: Offer to index a small sample corpus (bundled or user-selected folder)
  5. **First search**: Pre-populated search query against the indexed docs → "It works!"
- "Skip" option at every step (power users)
- Wizard state persisted so it doesn't re-appear after completion
- Re-accessible from Settings → "Run Setup Wizard"

**UX treatment**: The wizard should feel like a conversation, not a form. Each step shows one thing, explains why, and lets the user proceed. No multi-column layouts, no walls of options.

**Sample corpus**: Bundle 5–10 lightweight documents (project README, sample reports, etc.) totaling <1MB. These should be interesting enough to produce meaningful search results but small enough to index in seconds.

---

### 19. Server-Side Rate Limiting
**Effort**: ~4–6h | **Dependencies**: None | **Edition**: Both

**Problem**: Any enterprise security review will ask "what prevents API abuse?" The config field `rate_limit_per_minute` exists but isn't enforced. Client-side 429 handling exists but the server never sends 429.

Key deliverables:
- SlowAPI middleware on FastAPI (or equivalent)
- Per-API-key rate limiting (configurable via env var, default: 60 req/min)
- `429 Too Many Requests` response with `Retry-After` header
- Rate limit headers on every response: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`
- Separate limits for read vs write endpoints (searches vs indexing)
- Admin endpoints exempt (or higher limit)
- Activity log entry on rate limit triggers

Configuration:
```
RATE_LIMIT_DEFAULT=60/minute
RATE_LIMIT_SEARCH=120/minute
RATE_LIMIT_INDEX=30/minute
```

**What it does NOT do**: Per-user quotas (document count, storage) — that's a separate feature if demand exists.

---

### 20. Seat Enforcement
**Effort**: ~3–5h | **Dependencies**: #17 | **Edition**: Team, Organization

**Problem**: License keys encode seat counts (Team: 5, Organization: 25) but the server doesn't enforce them. Any number of users can be created regardless of license tier.

Key deliverables:
- On user creation (`POST /api/v1/users`): check active user count vs license seat limit
- On SCIM provisioning (`POST /scim/v2/Users`): same check
- `GET /api/v1/license/status` endpoint returns: edition, seats_used, seats_total, expiry
- Desktop admin console: show "N of M seats used" in Overview panel

**Enforcement model — firm but fair**:
- **Grace zone**: Allow 1 extra seat beyond the limit (Team gets 6 usable, not 5). Show a warning but don't block.
- **Hard block at limit + 2**: Return `403` with: "Your Team license allows 5 users (7 currently active). Deactivate a user or upgrade to Organization (25 users)."
- **Warning at 80% capacity**: "4 of 5 seats used — consider upgrading."
- **Deactivated users don't count** toward seats.
- **License downgrade** (Org → Team) with more active users than new limit: existing users remain active, but no new users can be created until count drops below limit. Never lock out existing users.
- **Community edition**: 1 user (the admin). No enforcement needed — single-user mode.

**Why not strict enforcement?** Strict seat caps feel punitive and create friction at the worst possible moment (when a team is growing and excited about the product). The grace zone lets a team temporarily exceed their limit while they decide to upgrade — this converts better than a hard wall. The precedent: Slack allows you to exceed seats and bills retroactively. We allow a grace zone and prompt upgrade.

---

### 21a. Scheduled Backups
**Effort**: ~6–8h | **Dependencies**: None | **Edition**: Team, Organization

**Problem**: Export/restore exists as manual UI operations. Enterprise buyers need scheduled, automated backups.

**Why split from restore?** Scheduled backup creation is low-risk and immediately useful. Restore orchestration (schema validation, partial recovery, rollback on failure) is a separate, higher-risk workflow that deserves its own scope and testing.

Key deliverables:
- Scheduled `pg_dump` via server-side scheduler (reuse existing scheduler infrastructure)
- Configurable: frequency (daily/weekly), retention count (keep last N), storage path
- Backup manifest: timestamp, size, document count, schema version
- `GET /api/v1/backups` — list available backups with size and age
- Automatic cleanup: when backup count exceeds retention limit, oldest are deleted
- Desktop admin console: Backup section showing backup list and last run status
- Activity log entries: `backup.created`, `backup.expired` (auto-deleted)

Configuration:
```
BACKUP_ENABLED=true
BACKUP_SCHEDULE=0 2 * * *          # daily at 2 AM
BACKUP_RETENTION_COUNT=7           # keep last 7
BACKUP_PATH=/backups               # inside container or host path
```

**Edition gating and disk cleanup**:

| Capability | Community | Team | Organization |
|---|---|---|---|
| Manual export/restore (already exists) | Yes | Yes | Yes |
| Scheduled automatic backups | No | Yes | Yes |
| Configurable retention count | — | Fixed: 3 | Configurable (default: 7) |

Community users use manual export (already implemented). Automated backups are Team+ because the data is shared and admin-managed. Retention count is the cleanup mechanism — when backup #N+1 is created, backup #1 is automatically deleted. For Team, this is fixed at 3 to keep disk usage bounded without configuration burden. Organization admins can adjust based on their storage capacity.

**Disk usage estimate**: A 50K-document corpus produces ~200MB pg_dump. With retention=7, that's ~1.4GB of backup storage. Document this in deployment guide.

---

### 21b. Restore Workflow
**Effort**: ~4–6h | **Dependencies**: #21a | **Edition**: Team, Organization

**Problem**: Having backups without a tested restore path is a false safety net.

Key deliverables:
- `POST /api/v1/backups/restore/{id}` — restore from a specific backup
- Pre-restore validation: check schema version compatibility
- Restore confirmation dialog in desktop admin console
- Dry-run mode: validate backup integrity without applying
- Activity log: `backup.restored`

**What it does NOT do**: Point-in-time recovery, incremental restore, cross-version restore (backup must match current schema version or be within one Alembic migration step).

---

### 22. Prometheus/OpenTelemetry Metrics
**Effort**: ~6–10h | **Dependencies**: None | **Edition**: Team, Organization

**Problem**: Enterprise ops teams need to plug into their existing monitoring stack. A `/health` endpoint isn't enough — they need time-series metrics for alerting and dashboarding.

Key deliverables:
- `GET /metrics` endpoint (Prometheus exposition format)
- Metrics exposed:
  - `pgvector_search_requests_total` (counter, labels: status)
  - `pgvector_search_latency_seconds` (histogram)
  - `pgvector_index_operations_total` (counter, labels: status)
  - `pgvector_index_latency_seconds` (histogram)
  - `pgvector_documents_total` (gauge)
  - `pgvector_active_users` (gauge)
  - `pgvector_api_requests_total` (counter, labels: method, endpoint, status)
  - `pgvector_db_pool_active` / `pgvector_db_pool_idle` (gauges)
  - `pgvector_rate_limit_hits_total` (counter, after #19)
- Optional: OpenTelemetry trace context propagation for distributed tracing
- Docker Compose snippet for Prometheus + Grafana (optional add-on, not required)

Configuration:
```
METRICS_ENABLED=true
METRICS_PATH=/metrics
```

**What it does NOT do**: Built-in dashboards (let customers use their own Grafana). Hosted metrics collection (stays local-first).

---

### 23. Event Webhooks
**Effort**: ~10–14h | **Dependencies**: #10 | **Edition**: Team, Organization

**Problem**: Customers want to integrate PGVectorRAGIndexer into their workflows — Slack notifications when documents are indexed, PagerDuty alerts on failures, custom pipelines triggered by events.

**Priority note**: This is integration-platform work, not core product hardening. For a local-first product selling into small team/org deployments, most buyers don't need webhooks on day one. Build this when there is concrete customer pull, not speculatively.

Key deliverables:
- Webhook registration: `POST /api/v1/webhooks` with URL, secret, event filter
- Event types:
  - `document.indexed`, `document.deleted`
  - `user.created`, `user.deactivated`
  - `backup.completed`, `backup.failed`
  - `retention.purge_completed`
  - `scim.user_provisioned`, `scim.group_created`
  - `system.health_degraded`
- HMAC-SHA256 signature on each delivery (`X-PGVector-Signature` header)
- Retry logic: exponential backoff, 3 attempts, then mark as failed
- `GET /api/v1/webhooks/{id}/deliveries` — delivery log with status
- Desktop admin console: Webhooks section (list, create, view delivery status)
- Activity log: `webhook.delivered`, `webhook.failed`

Data model:
```sql
CREATE TABLE webhooks (
    id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    secret TEXT NOT NULL,
    events TEXT[] NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE webhook_deliveries (
    id TEXT PRIMARY KEY,
    webhook_id TEXT REFERENCES webhooks(id),
    event_type TEXT NOT NULL,
    payload JSONB,
    status TEXT,  -- 'delivered', 'failed', 'pending'
    attempts INT DEFAULT 0,
    last_attempt_at TIMESTAMPTZ,
    response_code INT
);
```

---

### 24. Encryption at Rest
**Effort**: ~20–30h | **Dependencies**: #11 | **Edition**: Organization, Enterprise

**Problem**: Compliance-sensitive buyers (healthcare, finance, government) require data encryption at rest.

**Why the high estimate?** This is significantly more complex than it appears:
- **Schema migration**: Alembic migration to add encrypted columns, backfill existing data
- **Existing data re-encryption**: Large corpora (100K+ docs) need batch processing with progress tracking
- **Key management**: Key rotation procedure, key backup, what happens if key is lost (answer: all content is permanently unrecoverable — this must be prominently documented)
- **Backup interaction**: Encrypted backups need a separate key or the backup is useless without the encryption key. Key and backup must be stored separately.
- **Performance impact**: Every search result requires decryption. Estimated 10–30% latency increase on search, more on bulk indexing. Embeddings (vectors) stay unencrypted since they're meaningless without content — vector similarity search stays fast.
- **Failure recovery**: What if migration fails mid-way through re-encryption? Need rollback capability.

**Build only when demanded**: This is a regulated-industry feature, not generic polish. For most team/org deployments, PostgreSQL TLS (data in transit) + OS-level full-disk encryption (data at rest) is sufficient and much simpler. Recommend FDE in deployment docs as the default approach.

Key deliverables (when built):
- Column-level encryption for `document_chunks.content` using `pgcrypto`
- Server-managed encryption key (env var `ENCRYPTION_KEY`)
- Transparent encrypt-on-write, decrypt-on-read (no API changes)
- Batch migration tool for existing data with progress indicator and rollback
- Encrypted backup option (AES-256, key separate from backup)
- Documentation: key management, rotation procedure, FDE recommendation for simpler setups
- Performance benchmark: before/after comparison at 10K, 50K, 100K docs

**What it does NOT do**: Client-side encryption (server must decrypt to generate embeddings). Full-disk encryption (recommend OS/cloud-level FDE instead).

---

### 25. Email Notifications
**Effort**: ~4–6h | **Dependencies**: None | **Edition**: Team, Organization

**Problem**: Admins have no proactive alerts. They discover problems only by checking the UI.

**Priority note**: Lower priority than Support Diagnostics (#27). Diagnostics helps more users more immediately — email alerts are nice-to-have for mature deployments.

Key deliverables:
- SMTP configuration (reuse existing Zoho Mail pattern from Stripe webhooks)
- Notification triggers:
  - License expiring (30 days, 7 days, 1 day before)
  - Retention purge completed (summary)
  - SCIM sync failure
  - Backup failure
  - Rate limit threshold exceeded
- Per-admin notification preferences (which events, which email)
- `POST /api/v1/notifications/test` — send a test email

Configuration:
```
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=alerts@example.com
SMTP_PASSWORD=...
SMTP_FROM=PGVectorRAGIndexer <alerts@example.com>
NOTIFICATION_EMAILS=admin@company.com
```

---

### 26. Performance Benchmarks & Documentation
**Effort**: ~4–6h | **Dependencies**: None | **Edition**: N/A (documentation)

**Problem**: "How many documents can it handle?" is the #1 technical question from enterprise buyers, and there's no published answer. This is cheap to produce and directly helps sales.

Key deliverables:
- Benchmark script: index N documents, measure throughput and latency
- Published results for:
  - 10K, 50K, 100K, 500K documents
  - Search latency (p50, p95, p99) at each scale
  - Indexing throughput (docs/minute) by document type
  - Memory and disk usage at each scale
- Hardware recommendations table (small/medium/large deployments)
- Add to README and website

---

### 27. Support Diagnostics Bundle (NEW)
**Effort**: ~4–6h | **Dependencies**: None | **Edition**: Both

**Problem**: When a customer reports a problem, the first 30 minutes of support is "what version? what OS? can you reach the server? what does the health endpoint say?" A one-click diagnostic export eliminates this.

**Why it matters**: The product now has local Docker, remote mode, licensing, SCIM/SAML, and an admin console. Debugging requires information from many subsystems. This is more immediately useful than email notifications for both support and enterprise evaluations.

Key deliverables:
- "Export Diagnostics" button in Settings tab and/or Organization Overview
- Generates a ZIP or JSON report containing:
  - App version, OS, Python version, Qt version
  - Server version, API version, edition
  - Docker container/image info (if local mode)
  - License status (edition, seats used/total, expiry — NOT the key itself)
  - Capability probe results (all 8 endpoints, status for each)
  - Health endpoint response (uptime, CPU, memory, DB pool)
  - Recent error log entries (last 50, sanitized — no document content or PII)
  - Configuration summary (which features enabled: SCIM, SAML, retention, etc. — NOT secrets/tokens)
  - Database stats (document count, chunk count, table sizes)
- File is saved locally (user chooses save path)
- Privacy: prominently labeled "No document content, no API keys, no passwords included"
- API endpoint: `GET /api/v1/diagnostics` (admin only)

---

## Not Planned

These have been considered and intentionally deferred:

| Idea | Why not now |
|------|------------|
| **Horizontal scaling / sharding** | Overkill for 5–25 user deployments. Single-node PostgreSQL with pgvector handles 500K+ docs. |
| **Full SaaS mode** | Wrong market. Local-first is the core differentiator. Hosted demo (#15) tests appetite. |
| **Built-in Grafana dashboards** | Let customers use their own monitoring. Just expose `/metrics`. |
| **Per-user storage quotas** | No customer has asked. Add if demand emerges. |
| **Mobile app** | Out of scope. Web UI covers mobile browser access. |
| **Multi-region / geo-replication** | Enterprise-custom scope only. Not a product feature. |
| **AI-powered search ranking** | Interesting but speculative. Current hybrid search (vector + full-text) is competitive. |

---

## Synergy with V5

| V6 Feature | Builds on V5 |
|------------|-------------|
| #18 Onboarding | #1 Remote Backend, #17 License Validation |
| #19 Rate Limiting | #0 API Key Auth |
| #20 Seat Enforcement | #17 License Validation, #3 Multi-User |
| #21a/b Backups | #6b Server Scheduler infrastructure |
| #22 Metrics | #4 Health Dashboard, #10 Activity Log |
| #23 Webhooks | #10 Activity Log event model |
| #24 Encryption | #11 Alembic Migrations |
| #25 Notifications | #13 Stripe email infrastructure |
| #26 Benchmarks | #4 Health Dashboard, #7 Document Browser |
| #27 Diagnostics | #4 Health, #12 API Versioning, all capability probes |

---

## Risk Register

| Risk | Impact | Mitigation |
|------|--------|------------|
| Onboarding wizard (#18) over-engineered | Medium — delays other work | Time-box to 12h. MVP = 3 steps (connect, index, search). Polish later. |
| Rate limiting (#19) breaks existing integrations | Low — new feature, no existing behavior | Default limit generous (60/min). Clearly document in API changelog. |
| Seat enforcement (#20) angers existing over-limit users | Medium — customer friction | Grace zone: 1 extra seat allowed. Warn for 30 days before hard block. Never lock out existing users. |
| Backup automation (#21a) causes disk bloat | Low — bounded by retention count | Team: fixed at 3. Org: configurable, default 7. Document disk requirements. |
| Restore (#21b) causes data loss | High — wrong backup or failed restore | Dry-run validation. Pre-restore schema check. Never delete current data before restore succeeds. |
| Metrics endpoint (#22) leaks info | Low — internal metrics | Gate behind auth or configurable path. No document content in metrics. |
| Webhook delivery (#23) creates load | Medium — external calls from server | Rate-limit outbound webhooks. Circuit breaker per destination. |
| Encryption (#24) key loss = total data loss | **Critical** — all content unrecoverable | Prominent documentation. Key backup procedure. Migration rollback capability. Recommend FDE as simpler alternative. |
| Encryption (#24) performance degradation | Medium — 10–30% search latency increase | Benchmark before/after. Encrypt content only, not embeddings. |
| Diagnostics (#27) leaks sensitive info | Low — must sanitize output | Exclude: API keys, tokens, passwords, license keys, document content. Include only operational metadata. |

---

Last updated: 2026-03-14
