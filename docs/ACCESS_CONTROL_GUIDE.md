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

- **Enforced today:** search results (`/search`) — both the LanceDB and
  PostgreSQL search engines.
- **Not yet enforced:** document *listing* and tree views still show names
  and metadata of all documents (not their content). Treat lists as visible
  to all authenticated users for now; this is planned before the visible
  multi-user release.
- The server must be migrated (`alembic upgrade head`) to at least
  migration `020` for collection grants.

## Related guides

- [DEPLOYMENT.md](DEPLOYMENT.md) — running the shared server
- [SCIM_SETUP.md](SCIM_SETUP.md) — provisioning users/roles from your IdP
- [LARGE_ORG_LICENSING.md](LARGE_ORG_LICENSING.md) — seats and licensing
