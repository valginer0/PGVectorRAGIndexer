# Code Review Notes — Second Pass

> Generated during Windsurf session, Apr 2026.
> All first-pass fixes (commit 6084dcf) are already applied.
> This file tracks second-pass findings and their fix status.

---

## 🔴 Bugs

### 1. `list_scim_groups_admin()` leaks DB connection [FIXED]
**File:** `routers/identity_api.py:535`
Called `_get_db_connection()` + `conn.close()` directly instead of
the `with` context manager. An exception between the two lines would
permanently leak the connection.
**Fix:** Wrap in `with _get_db_connection() as conn:`.

### 2. `/activity` POST missing `require_team_edition` [REVERTED — INTENTIONAL]
**File:** `routers/maintenance_api.py:41`
`GET /activity` requires Team edition but `POST /activity` only requires
`require_api_key`. This asymmetry is intentional: the desktop app records
activity entries on Community Edition, so the write endpoint must stay
ungated. `TestPostActivityNotGated` in `test_edition_gating_e2e.py`
explicitly enforces this. Not a bug.

### 3. Non-admin can change `owner_id` via PUT /visibility [FIXED]
**File:** `routers/visibility_api.py:34`
`PUT /documents/{id}/visibility` accepted `owner_id` without admin check,
allowing any key holder to silently transfer document ownership.
The dedicated `POST /documents/{id}/transfer` correctly requires admin.
**Fix:** When auth is required, reject `owner_id` in this endpoint and
direct callers to use `/transfer` instead. Loopback mode is unaffected.

### 4. `(array_agg(...))[1]` is non-deterministic [PENDING]
**Files:**
- `database.py:374` — `get_document_by_id`: `(array_agg(metadata))[1]`
- `database.py:504` — `list_documents`: `(array_agg(metadata->>'type'))[1]`
- `alembic/versions/012_document_visibility.py:47-48` — view uses
  `(array_agg(owner_id))[1]` and `(array_agg(visibility))[1]`

`array_agg` without `ORDER BY` returns an arbitrary element. For documents
with multiple chunks that could have different metadata/visibility values,
the result is undefined.
**Suggested fix:** `(array_agg(metadata ORDER BY indexed_at ASC))[1]`

---

## 🟡 Security / Fragile

### 5. Migration 016 uses `.format()` SQL for role seeding [LOW RISK]
**File:** `alembic/versions/016_activity_log_fields_and_roles.py:85`
Role/permission names are interpolated via Python `.format()` with
manual `replace("'", "''")`. The `json.dumps()` output for `permissions`
is not SQL-escaped. Safe today (hardcoded data), fragile if permission
names ever contain apostrophes.
**Note:** Migration already ran; low risk to leave as-is.

---

## 🟠 Inconsistencies

### 6. `import jwt as _jwt` called multiple times in same function [PENDING]
**File:** `server_settings_store.py:116,130,157`
`add_server_license_key()` and `remove_server_license_key()` each import
`_jwt` inside loops/branches rather than once at the top of the function.
Python caches module imports (no performance impact), but it is poor style.

### 7. Legacy `license_key` DB row never deleted after migration [PENDING]
**File:** `server_settings_store.py:84`
`get_server_license_keys()` migrates the old single `license_key` entry
to the new `license_keys` array, persists the new entry, but never
deletes the old one. The stale row stays in `server_settings` forever.

### 8. `POST /users` and `POST /keys` return HTTP 200 instead of 201 [PENDING]
**File:** `routers/identity_api.py:291` (`POST /users`) and `:20` (`POST /keys`)
Standard REST semantics for resource creation is `201 Created`.

### 9. `update_user_endpoint` logs raw request body [PENDING]
**File:** `routers/identity_api.py:343`
`log_activity(..., details={"changes": body})` — any future sensitive
body field would appear verbatim in the audit log.
**Suggested fix:** Log only field names: `"changed_fields": list(body.keys())`

### 10. SCIM users hardcoded to `auth_provider = "saml"` [LOW PRIORITY]
**File:** `routers/scim_api.py:111`
All SCIM-provisioned users get `auth_provider = "saml"` regardless of
the actual IdP protocol (e.g., OIDC-federated SCIM).

---

## 🟢 Minor

### 11. `add_server_license_key()` read-modify-write is not atomic [NOTED]
**File:** `server_settings_store.py:125`
Concurrent installs could each read the same key list, append their key,
and one write would silently drop the other.
**Mitigation:** Rare in practice; would require advisory lock or DB CAS.

### 12. `users.py` uses `SELECT *` with positional `_COLUMNS` tuple [NOTED]
**File:** `users.py:118`
All query functions use `SELECT *`. If the `users` table adds/reorders
columns, `_row_to_dict()` silently produces wrong field mappings.

### 13. Exported `VALID_ROLES` is incomplete [NOTED]
**File:** `users.py:33`
`VALID_ROLES = {ROLE_ADMIN, ROLE_USER}` doesn't include custom roles.
Nothing currently imports it (confirmed by grep), but it is a misleading
export for future developers.
