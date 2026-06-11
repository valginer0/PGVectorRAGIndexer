# Access Control Guide — Users, Roles, Document Visibility & Collections

This guide is for teams running a shared PGVectorRAGIndexer server. It covers
who can see which documents and how to manage that. If you run the app
locally as a single user (no API key auth), none of this restricts you —
everything below is inert in local mode.

## Concepts in one minute

- **API keys** authenticate every request (`X-API-Key` header).
- **Users** are linked to API keys and have a **role**.
- **Roles** control *actions* (search, upload, delete, admin…). Built-in:
  `admin`, `user`; example custom roles ship in `role_permissions.json`
  (`researcher`, `sre`, `support`).
- **Document visibility** controls *who sees a specific document*:
  `shared` (everyone, the default) or `private` (owner + admins only).
- **Collection grants** control *which document sets a role can search*
  (opt-in per role; ungranted roles see everything).

Search results enforce visibility and collection grants automatically.

## Document visibility (shared / private)

### How a document gets an owner

Ownership is what makes "private" meaningful — a private document with no
owner is still treated as shared (backward compatibility for documents
indexed before ownership existed).

- **Automatic:** documents uploaded or indexed through the API while
  authenticated are owned by the uploading user. No action needed.
- **Existing documents:** an admin assigns an owner via the transfer
  endpoint:

```bash
curl -X POST "$BASE/api/v1/documents/<document_id>/transfer" \
  -H "X-API-Key: $ADMIN_KEY" -H "Content-Type: application/json" \
  -d '{"owner_id": "<user_id>"}'
```

### Making a document private — desktop app

In the **Documents** tab (list view), right-click a document →
**Make Private** (or **Make Shared** to undo). If the document has no owner
yet, the app tells you so and explains how to assign one — the document
stays visible to everyone until it has an owner.

### Making a document private — API

```bash
curl -X PUT "$BASE/api/v1/documents/<document_id>/visibility" \
  -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"visibility": "private"}'
```

Bulk variant: `POST /api/v1/documents/bulk-visibility` with
`{"document_ids": [...], "visibility": "private"}` (admin only).

### What private means in practice

- Search results never include another user's private documents — neither
  the content nor the file as a result. Admins see everything.
- An API key that is not linked to any user cannot see any private
  documents.

## Collections: restrict a role to document sets

A **collection** is the document's `namespace` — set it when uploading:

```bash
curl -X POST "$BASE/api/v1/upload-and-index" \
  -H "X-API-Key: $KEY" \
  -F "file=@q3_budget.pdf" \
  -F 'metadata={"namespace": "finance"}'
```

### Granting access (admin only)

By default every role searches everything. Granting a role its first
collection **restricts** it to its granted collections:

```bash
# Researchers may now search ONLY the finance collection
curl -X PUT "$BASE/api/v1/roles/researcher/collections/finance" \
  -H "X-API-Key: $ADMIN_KEY"

# Add a second collection
curl -X PUT "$BASE/api/v1/roles/researcher/collections/legal" \
  -H "X-API-Key: $ADMIN_KEY"

# Review all grants
curl "$BASE/api/v1/roles/collections" -H "X-API-Key: $ADMIN_KEY"

# Revoke
curl -X DELETE "$BASE/api/v1/roles/researcher/collections/legal" \
  -H "X-API-Key: $ADMIN_KEY"
```

### Rules

| Situation | What the role can search |
|---|---|
| Role has no grants | Everything (default — grants are opt-in) |
| Role has grants | Only documents in its granted collections |
| Role granted `*` | Everything (explicit wildcard) |
| Admin (`system.admin`) | Everything, always |

Notes:

- A restricted role does **not** see documents that have no namespace.
  Grant `*` instead if a role should see uncategorized documents too.
- Visibility and grants combine: a restricted role still never sees other
  users' private documents inside its granted collections.

## Current enforcement scope (read this)

- **Enforced today:** search results (`/search`) and RAG context
  (`/context`) — both the LanceDB and PostgreSQL search engines.
- **Admin-only:** `/documents/export` and `/documents/restore`. Export
  returns full text of all matching documents regardless of visibility
  (a visibility-filtered export would silently produce incomplete backups);
  restore can overwrite any document — including private ones — with
  caller-supplied content. Backup and restore are admin operations.
- **Permission-gated writes:** uploading/indexing requires
  `documents.write` (the read-only `support` role cannot upload). Deleting
  documents requires `documents.delete` (the built-in `user` and
  `researcher` roles cannot delete; `admin` and `sre` can). Changing a
  document's visibility requires `documents.visibility` and, unless the
  role has `documents.visibility.all`, only works on documents the caller
  owns — so nobody can flip your private document to shared.
- **Overwrite protection:** uploading or indexing a file with the same name
  as a document owned by another user is rejected — only the owner or an
  admin can replace it. (Re-uploading an identical file is still skipped
  harmlessly.) A failed replacement restores the previous version instead
  of losing it.
- **Visibility-filtered reads:** document listing (`/documents`,
  `/documents/{id}`), the document tree (children, stats, path search, for
  both the PostgreSQL and LanceDB sources), `/statistics` counts,
  `/extensions`, and metadata discovery (`/metadata/keys`,
  `/metadata/values`) only reflect documents the caller can see: shared
  documents plus their own. Hidden documents return 404 from
  `/documents/{id}` — their existence is not revealed.
- **Filtered auxiliary listings:** document lock listings and indexing-run
  history omit entries whose source path maps to a document hidden from the
  caller; the encrypted-PDF report only shows (and clears) the caller's own
  entries unless the caller is an admin.
- The server must be migrated (`alembic upgrade head`) to at least
  migration `020` for collection grants.

## Validating Team mode (staging checklist)

Before rolling Team mode out on your internal server, you can validate the
entire access-control stack on any machine with Docker — no external hosting
is involved at any point (the server in this product is always *your*
machine, on *your* network).

### 1. Start the stack with auth enforced

The same image you already run; auth is a runtime switch:

```bash
APP_IMAGE=ghcr.io/valginer0/pgvectorragindexer:latest \
  docker compose -f docker-compose.yml -f docker-compose.smoke.yml up -d
docker compose run --rm app alembic upgrade head
```

(`docker-compose.smoke.yml` sets `API_REQUIRE_AUTH=true`. It also sets
`API_AUTH_FORCE_ALL=true`, which is for CI — on a real server omit it so the
desktop app running on the server machine itself stays exempt while all
remote connections require keys.)

### 2. Install a Team license

Licensing is fully offline — there is no license server and the app never
phones home. A license is a signed token (issued by the vendor); the app
verifies it with a built-in public key. **No license = Community edition**
(team features off). **Team license = Team edition** (users, roles, seat
watching).

Install the license token one of two ways:

```bash
# Option A — license file on the server host (picked up at startup;
# docker-compose already mounts this folder into the container):
mkdir -p ~/.pgvector-license
cp license.key ~/.pgvector-license/license.key
docker compose restart app

# Option B — via the API. Security note: this endpoint only accepts
# requests from the server machine itself (loopback), even with a key:
curl -X POST "http://localhost:8000/api/v1/license/install" \
  -H "X-API-Key: $ADMIN_KEY" -H "Content-Type: application/json" \
  -d '{"license_key": "<token>"}'

# Verify the edition took effect:
curl "http://localhost:8000/license"
```

Multiple keys stack: seats add up across valid keys (e.g. buy 10 seats now,
add 5 later). `"action": "replace"` swaps the whole stack instead.

### 3. Bootstrap the admin key and create users

```bash
# First (admin) API key — run on the server:
docker compose run --rm app python -c \
  "from auth import create_api_key_record; print(create_api_key_record('admin')['key'])"

# Create users linked to keys (admin key required; Team edition)
curl -X POST "$BASE/api/v1/users" -H "X-API-Key: $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"email": "alice@example.com", "role": "researcher", "api_key_id": 2}'
```

### 4. Connect a desktop client from another machine

Point the desktop app's server URL at the host's **LAN address** (not
`localhost`) — e.g. `http://192.168.1.20:8000` — and enter that user's API
key. A non-loopback connection is exactly what your team members' desktops
will be: auth enforced, role applied.

### 5. What to verify

- [ ] Search without a key → rejected (401)
- [ ] User A's private document never appears in user B's search results
- [ ] A role granted one collection only gets results from that collection
- [ ] An admin key sees everything
- [ ] Exceeding licensed seats adds `X-License-Overage` warning headers
      (requests keep working — seat watching, not lockout)

The repository's CI runs the deployment half of this automatically on every
push (`.github/workflows/fresh-image-smoke.yml`): fresh image, clean
volumes, migrations, enforced auth, index → search → restart persistence →
drift self-heal.

## Related guides

- [DEPLOYMENT.md](DEPLOYMENT.md) — running the shared server
- [SCIM_SETUP.md](SCIM_SETUP.md) — provisioning users/roles from your IdP
- [LARGE_ORG_LICENSING.md](LARGE_ORG_LICENSING.md) — seats and licensing
