# Phase D: Desktop API Client Facade — Verification

Purpose: validate Phase D (`APIClient` facade, `BaseAPIClient`, 9 domain clients).

## Automated Test Coverage

Phase D acceptance criteria are verified by automated tests. A small number of desktop UI integration scenarios remain manual-only (see bottom).

```bash
# Run all Phase D verification tests (29 tests, <1s)
python -m pytest tests/test_api_client_facade_verification.py -v

# Run existing facade routing tests (24 tests)
python -m pytest tests/test_api_client.py -v

# Run list_documents edge cases (3 tests)
python -m pytest tests/test_api_client_list_documents.py -v
```

### Test Matrix

| Scenario | Test Class / File | Tests | What's Verified |
|----------|-------------------|-------|-----------------|
| Property sync | `TestPropertySynchronization` | 9 | `base_url` → `api_base` derivation, trailing slash normalization, `api_key` → session header, facade→base propagation, manual `api_base` override |
| Error translation | `TestErrorTranslation` | 11 | 401/403 → `APIAuthenticationError`, 429 → `APIRateLimitError`, 404/500 → `APIError`, 200 passthrough, JSON detail preservation, text fallback, ConnectionError/Timeout/RequestException mapping |
| Session lifecycle | `TestSessionLifecycle` | 3 | `close()` delegates, shared session across requests, default timeout applied |
| Domain routing | `TestDomainClientRouting` | 2 | All 9 clients instantiated, all share same `BaseAPIClient` |
| Error hierarchy | `TestErrorHierarchy` | 4 | Inheritance chain, `status_code` attribute |
| Facade delegation | `test_api_client.py` | 24 | Every public method routes to correct domain client with correct URL/params |
| List pagination | `test_api_client_list_documents.py` | 3 | Pagination, sorting, legacy response handling |

### Acceptance Criteria → Test Mapping

| Criterion | Automated Test |
|-----------|---------------|
| `base_url` change re-derives `api_base` | `test_base_url_change_updates_api_base` |
| `api_key` change updates session header | `test_api_key_change_updates_header` |
| `api_key=None` removes header | `test_api_key_none_removes_header` |
| Facade property changes reach BaseAPIClient | `test_facade_propagates_base_url_to_base`, `test_facade_propagates_api_key_to_base` |
| HTTP 401/403 → `APIAuthenticationError` | `test_401_raises_auth_error`, `test_403_raises_auth_error` |
| HTTP 429 → `APIRateLimitError` | `test_429_raises_rate_limit_error` |
| HTTP 4xx/5xx → `APIError` with `status_code` | `test_404_raises_api_error`, `test_500_raises_api_error` |
| Error detail from JSON `detail` field | `test_error_detail_preserved_from_json` |
| `ConnectionError` → `APIConnectionError` | `test_connection_error_translated` |
| `Timeout` → `APIConnectionError` | `test_timeout_error_translated` |
| `close()` releases session | `test_close_closes_session` |
| Shared session reuse | `test_shared_session_across_requests` |
| All 9 domain clients instantiated | `test_all_nine_domain_clients_instantiated` |
| All domain clients share one `BaseAPIClient` | `test_domain_clients_share_base` |

### Scenarios NOT Automated (Desktop UI Integration)

These require a running desktop app and cannot be unit tested:

- Scenario 1: Status bar connection indicator updates on connect/disconnect
- Scenario 2: Upload tab → Documents tab visual flow
- Scenario 5: Client identity auto-registration on first launch
- Scenario 8: No socket exhaustion after many operations (long-running soak test)

These are low-risk given the facade is fully tested at the API client layer.
