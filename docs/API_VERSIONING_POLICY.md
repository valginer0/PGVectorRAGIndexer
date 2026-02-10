# API Versioning Policy

How PGVectorRAGIndexer manages API versions and client compatibility.

---

## Version Scheme

| Component | Format | Example | Where |
|-----------|--------|---------|-------|
| **Server version** | Semantic versioning (`MAJOR.MINOR.PATCH`) | `2.4.5` | `VERSION` file |
| **API version** | Integer, incremented on breaking changes | `1` | `API_VERSION` in `api.py` |
| **Client version** | Same as server version | `2.4.5` | `VERSION` file |

## Versioned Endpoints

All data endpoints are served under `/api/v1/`:

```
GET  /api/v1/documents
POST /api/v1/search
POST /api/v1/upload-and-index
...
```

**Backward compatibility**: the same endpoints are also available at the root path (`/documents`, `/search`, etc.) for older clients that don't use the versioned prefix.

**Unversioned endpoints** (always at root):
- `GET /` — Web UI
- `GET /api` — API info
- `GET /api/version` — Version and compatibility info
- `GET /health` — Health check
- `GET /license` — License info
- `GET /docs` — OpenAPI docs

---

## Compatibility Rules

### When to bump API_VERSION

Increment `API_VERSION` (e.g., `1` → `2`) when making **breaking changes**:

- Removing an endpoint
- Changing request/response schema in an incompatible way
- Renaming a field that clients depend on
- Changing authentication requirements

### When NOT to bump API_VERSION

These are backward-compatible and don't require a version bump:

- Adding new endpoints
- Adding optional fields to requests
- Adding new fields to responses
- Adding new query parameters with defaults
- Performance improvements
- Bug fixes

### Client Version Window

The server declares a compatibility window via `GET /api/version`:

```json
{
    "server_version": "2.4.5",
    "api_version": "1",
    "min_client_version": "2.4.0",
    "max_client_version": "99.99.99"
}
```

- **min_client_version**: oldest desktop client that works correctly
- **max_client_version**: newest client supported (set to `99.99.99` until we need to cap it)

The desktop app checks this on connect and warns the user if their version is outside the window.

---

## Deprecation Process

When deprecating an API version:

1. **Announce**: add a deprecation notice to release notes
2. **Warn**: return `Deprecation: true` header on old version endpoints for 2 releases
3. **Maintain**: keep the old version working for at least 6 months
4. **Remove**: drop the old version in a major release

We currently only have `v1`. When `v2` is needed, both will coexist:
- `/api/v1/...` — old behavior
- `/api/v2/...` — new behavior

---

## For Contributors

When making API changes:

1. Check if the change is breaking (see rules above)
2. If breaking: increment `API_VERSION`, update `MIN_CLIENT_VERSION`, update compatibility matrix
3. If non-breaking: just make the change, no version bump needed
4. Always update `docs/COMPATIBILITY_MATRIX.md` when changing version constraints
5. Run `python -m pytest tests/test_api_versioning.py` to verify version constants are valid

---

## Release Checklist

Before each release, verify:

- [ ] `VERSION` file updated
- [ ] `API_VERSION` bumped if breaking changes were made
- [ ] `MIN_CLIENT_VERSION` / `MAX_CLIENT_VERSION` updated if needed
- [ ] `docs/COMPATIBILITY_MATRIX.md` updated with new row
- [ ] `tests/test_api_versioning.py` passes
