# Phase E: Deep Observability & Startup Optimization — Verification

Purpose: validate Phase E (`JSONFormatter`, `_get_system_metrics()`, `setup_logging()`, lazy imports, TestClient removal).

## Automated Test Coverage

Phase E acceptance criteria are verified by automated tests. A small number of Docker-environment scenarios remain manual-only (see bottom).

```bash
# Run all Phase E verification tests (17 tests, <1s)
python -m pytest tests/test_observability_verification.py -v

# Run existing observability tests
python -m pytest tests/test_logger_setup.py tests/test_system_health.py tests/test_startup_hang_regression.py -v
```

### Test Matrix

| Scenario | Test Class / File | Tests | What's Verified |
|----------|-------------------|-------|-----------------|
| JSONFormatter edge cases | `TestJSONFormatterEdgeCases` | 7 | exc_info traceback, falsy exc_info guard, extra attributes, non-serializable → `str()`, ISO 8601 timestamp, standard attrs not leaked |
| Log handler idempotency | `TestSetupLoggingIdempotency` | 4 | No duplicate handlers after 2x `setup_logging()`, no duplicate JSON handlers, single log line per event, framework loggers have 0 handlers + propagate=True |
| System metrics | `TestSystemMetrics` | 6 | All 3 keys present, `uptime_seconds` non-negative and monotonically increasing, `cpu_load_1m` type, `memory_rss_bytes` type, psutil fallback returns valid dict |
| Text/JSON format switch | `test_logger_setup.py` | 2 | Default plaintext output, `LOG_FORMAT=json` produces valid JSON with correct keys |
| Health endpoint schema | `test_system_health.py` | 3 | Initializing path metrics, healthy path metrics, psutil-unavailable fallback |
| Startup offloading | `test_startup_hang_regression.py` | 8 | DB health check offloaded to thread, event loop responsive during slow DB, scheduler lease offloaded, scan watermarks offloaded, scheduler init guard blocks before init, scheduler init guard proceeds after init, init error stops loop, DB timeout config |

### Acceptance Criteria → Test Mapping

| Criterion | Automated Test |
|-----------|---------------|
| `LOG_FORMAT=json` outputs valid JSON | `test_json_formatting_assertion` |
| `LOG_FORMAT` default is plaintext | `test_default_plaintext_assertion` |
| `setup_logging()` idempotent (no dup handlers) | `test_no_duplicate_handlers`, `test_no_duplicate_json_handlers` |
| Single log line per event (no duplication) | `test_no_duplicate_log_output` |
| Framework loggers propagate to root | `test_framework_loggers_have_no_handlers` |
| exc_info produces `exception` key | `test_exc_info_included_in_json` |
| Falsy `(None, None, None)` exc_info ignored | `test_falsy_exc_info_excluded` |
| Extra attributes serialized in JSON | `test_extra_attributes_serialized` |
| Non-serializable extras → `str()` | `test_non_serializable_extra_stringified` |
| Timestamp is ISO 8601 UTC | `test_timestamp_is_iso8601` |
| Standard LogRecord attrs not leaked | `test_standard_attrs_not_leaked` |
| `uptime_seconds` always present, non-negative | `test_uptime_is_nonnegative_number` |
| `uptime_seconds` monotonically increases | `test_uptime_increases` |
| `cpu_load_1m` is None or number | `test_cpu_load_type` |
| `memory_rss_bytes` is None or number | `test_memory_rss_type` |
| psutil unavailable → graceful fallback | `test_psutil_fallback_still_returns_dict`, `test_health_system_metrics_without_psutil` |
| `/health` returns metrics during init | `test_health_system_metrics_schema` |
| `/health` returns metrics when healthy | `test_health_system_metrics_healthy_path` |
| DB health check offloaded (non-blocking) | `test_health_check_db_offloaded` |
| Event loop responsive during slow DB | `test_health_check_remains_responsive_during_slow_db` |

### Scenarios NOT Automated

These require a running Docker environment:

- Startup time measurement (< 2s to first `/health` response) — verified indirectly by lazy import regression tests
- Uvicorn access log formatting in production Docker context — verified by unit test log propagation checks

These are low-risk given the formatter, metrics, and handler cleanup are all fully unit tested.
