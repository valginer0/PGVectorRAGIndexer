# Compatibility Matrix

Tracks which server versions work with which client versions and API versions.

Update this file whenever version constraints change. See [API_VERSIONING_POLICY.md](./API_VERSIONING_POLICY.md) for rules.

---

## Current

| Server Version | API Version | Min Client | Max Client | Notes |
|---------------|-------------|------------|------------|-------|
| 2.4.5+ | 1 | 2.4.0 | — | Initial versioned API |

## History

| Date | Change | Server | API | Min Client |
|------|--------|--------|-----|------------|
| 2026-02-10 | Initial API versioning (#12) | 2.4.5 | 1 | 2.4.0 |

---

## How to Read

- **Server Version**: the `VERSION` file in the server repo
- **API Version**: the `API_VERSION` constant in `api.py`
- **Min Client**: oldest desktop app version that works with this server
- **Max Client**: newest supported client (`—` means no upper bound)

## Checking Compatibility

The desktop app automatically checks compatibility on connect via `GET /api/version`. If the client version falls outside `[min_client_version, max_client_version]`, a warning dialog is shown.

Manual check:
```bash
curl http://localhost:8000/api/version | jq
```
