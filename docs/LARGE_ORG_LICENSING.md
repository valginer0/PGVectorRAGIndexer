# Large-Organization Licensing & Enforcement

## Summary

This document describes the monetization and enforcement strategy for organizations
exceeding 25 users. It uses **soft / "shame" enforcement** rather than hard access
blocks, and **license stacking** to serve >25-user customers without modifying the
Stripe configuration.

---

## Design Decisions

| Question | Decision | Rationale |
|----------|----------|-----------|
| Hard block vs. soft shame | **Soft shame** — red banner + warning headers, no functional lock | Hard blocks create support tickets; shame banners create sales conversations |
| Banner dismissibility | **Per-session dismissible** | Permanent banners get ignored within days (banner blindness). Re-shown on each app restart keeps admin aware |
| Seat metric | **`COUNT(*) FROM users WHERE is_active = true`** | Simple, auditable, matches the "Named User" promise. Does not count unauthenticated desktop clients |
| >25-user pricing | **License stacking** (buy N × Organization licenses) | Zero Stripe changes, existing JWT issuance and webhook work as-is |
| Multi-key storage | **JSON array in `server_settings` under key `license_keys`** (not a file directory) | Server keys are loaded via Admin UI, not filesystem; a directory approach only makes sense for desktop installs |

---

## Architecture

### 1. Seat Count — `users.py`

New function `count_active_users() -> int`:
```python
SELECT COUNT(*) FROM users WHERE is_active = true
```
No joins, no client-table involvement. Transparent to administrators.

### 2. Multi-Key Storage — `server_settings_store.py`

Three new functions alongside the existing single-key helpers (kept for backward compat):

| Function | Description |
|----------|-------------|
| `get_server_license_keys() -> List[str]` | Returns all stored JWT strings. Migrates the old single `license_key` entry on first read |
| `add_server_license_key(jwt_str)` | Appends a new key; deduplicates by `kid` claim |
| `remove_server_license_key(kid)` | Removes by JWT `kid` claim |

Storage: JSON array under `server_settings` key `"license_keys"`.

### 3. License Aggregation — `license.py`

New `AggregatedLicense` dataclass and `load_all_licenses()` function:

```
AggregatedLicense
  .licensed_seats: int       # SUM of seats from all valid, unexpired keys
  .edition: Edition          # Highest edition (ORGANIZATION > TEAM > COMMUNITY)
  .org_name: str             # From first valid key
  .active_key_ids: List[str] # kid values of every accepted key
  .warnings: List[str]       # Per-key warnings (expired, invalid)
  .is_team: bool             # True if edition >= TEAM
```

`load_all_licenses()` behavior:
- Loads all keys from `get_server_license_keys()` (DB) and the single filesystem key
- Validates each independently; expired / invalid keys are skipped with a warning (never fail-hard)
- Falls back to `COMMUNITY_LICENSE` if no valid keys remain

`get_current_license()` is updated to return an `AggregatedLicense`-compatible interface.
All existing call sites that use `.edition`, `.seats`, `.is_team`, `.to_dict()` continue
to work without modification because `AggregatedLicense` exposes the same fields.

### 4. Usage Endpoint — `GET /api/v1/license/usage`

Auth: `require_api_key`

Response:
```json
{
  "licensed_seats": 25,
  "active_seats": 28,
  "overage": 3
}
```

`overage = max(0, active_seats - licensed_seats)`.  
Community edition: `licensed_seats = 0` (no seat limit concept — overage is never positive).

### 5. Shame Middleware — `license_overage.py`

A Starlette middleware added to the FastAPI app:

- Maintains an in-memory overage cache with a **5-minute TTL** to avoid per-request DB hits
- On each response, if `overage > 0`, injects:
  - `X-License-Overage: true`
  - `X-License-Overage-Count: <n>`
  - `Warning: 299 RAGVault "Seat count exceeded: N active users on M-seat license"`
- Community edition: middleware is a no-op (no seat limit)
- Does not modify response body or status code

### 6. License Install Endpoint Update — `POST /api/v1/license/install`

New behavior: **add** (stack), not replace.

Request body gains an optional `action` field:
```json
{"license_key": "...", "action": "add"}   // default — add to stack
{"license_key": "...", "action": "replace"} // remove all existing keys, set this one
```

Response includes the updated seat total:
```json
{"status": "stored", "total_licensed_seats": 50, "active_keys": 2}
```

New `DELETE /api/v1/license/{kid}` endpoint removes a single key by its `kid` claim.

### 7. Desktop App Overage Banner — `main_window.py`

On startup, after the initial health check succeeds, the desktop app calls
`GET /api/v1/license/usage`. If `overage > 0`:

- Shows a bold red banner **above the tab bar** (inserted after the existing
  license-expiry banner, before the remote-mode banner):
  ```
  ⚠  License Non-Compliance: 28 active users on a 25-seat license.
     Purchase additional Organization licenses at ragvault.net/pricing.  [Dismiss]
  ```
- Dismiss button hides the banner for the current session only
- Banner is never shown for Community edition (no seat concept)
- Banner is refreshed if the usage changes (re-checked every 10 minutes)

### 8. Admin Console Integration (future)

Phase 2 (not in this sprint): navigate Admin directly to the License tab with a modal
on startup when overage is detected. Tracked as a follow-up issue.

---

## Implementation Order

1. `users.py` — `count_active_users()`
2. `server_settings_store.py` — multi-key helpers
3. `license.py` — `AggregatedLicense` + `load_all_licenses()`
4. `routers/system_api.py` — `GET /api/v1/license/usage` + updated install endpoint
5. `license_overage.py` — shame middleware
6. Wire middleware into `app.py` / `main.py`
7. Desktop `system_client.py` — `get_license_usage()`
8. Desktop `main_window.py` — overage banner
9. Tests
10. Website FAQ

---

## Verification Plan

### Automated Tests
- `load_all_licenses()`: two valid 5-seat keys → 10 licensed seats; one expired key
  ignored; no keys → community
- `count_active_users()`: returns correct count from mock DB
- `GET /api/v1/license/usage`: correct `overage` arithmetic, Community → `overage=0`
- Middleware: `overage > 0` → headers present; `overage = 0` → headers absent

### Manual Verification
1. Load a 5-seat Team license via `POST /api/v1/license/install`
2. Create 6 active users in Admin Console
3. Verify `GET /api/v1/license/usage` returns `{"licensed_seats":5,"active_seats":6,"overage":1}`
4. Verify API responses contain `X-License-Overage: true`
5. Verify desktop app shows the red overage banner
6. Add a second 5-seat license (total: 10 seats)
7. Verify `overage` drops to 0, banner vanishes on next check

---

## Pricing FAQ (ragvault.net update)

> **Have more than 25 users?**  
> Purchase multiple Organization licenses — each covers 25 named users.  
> Load all keys into your server to combine seat limits automatically.  
> 50 users = 2 × $799/yr. No enterprise negotiations required.
