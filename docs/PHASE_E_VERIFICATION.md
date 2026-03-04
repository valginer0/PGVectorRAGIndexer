# Phase E: Deep Observability & Startup Optimization — Manual QA Checklist

Purpose: validate Phase E (`JSONFormatter`, `_get_system_metrics()`, `setup_logging()`, lazy imports, TestClient removal) on a running server instance.

## Scope

This checklist covers:
- Structured JSON logging via `LOG_FORMAT` env var.
- `/health` endpoint system metrics (uptime, CPU, memory).
- Startup performance (lazy imports preventing 25s delay).
- Log handler cleanup (no duplication).

This checklist does not cover:
- Automated unit tests (3 health + 2 logger + 7 startup regression tests).
- Desktop app behavior (Phase D covers that).

## Test Environment

1. Start from project root.
2. Ensure Docker is running.
3. Default startup (no LOG_FORMAT set):

```bash
docker compose up -d
curl http://127.0.0.1:8000/health
```

## Test Matrix

Run all scenarios in order.

## Scenario 1: Default Text Logging

1. Start the server without setting `LOG_FORMAT` (or with `LOG_FORMAT=text`).
2. Make an API request:

```bash
curl http://127.0.0.1:8000/health
```

3. Check server logs:

```bash
docker compose logs app --tail=20
```

Expected:
- Log lines are plaintext (e.g., `INFO:     127.0.0.1:xxxxx - "GET /health HTTP/1.1" 200`).
- No JSON braces `{}` in log output.
- Uvicorn access logs are readable human-formatted text.

## Scenario 2: JSON Logging Activation

1. Set `LOG_FORMAT=json` in the environment (e.g., in `docker-compose.yml` or `.env`).
2. Restart the server.
3. Make an API request:

```bash
curl http://127.0.0.1:8000/health
```

4. Capture and parse a log line:

```bash
docker compose logs app --tail=5 | head -1 | python -m json.tool
```

Expected:
- Each log line is valid JSON.
- JSON contains keys: `timestamp`, `level`, `name`, `message`.
- `timestamp` is ISO 8601 UTC format (e.g., `2026-03-04T12:00:00.000000`).
- Uvicorn and FastAPI logs also appear as JSON (propagated through root handler).

## Scenario 3: Health Endpoint Response Schema

1. Query the health endpoint:

```bash
curl -s http://127.0.0.1:8000/health | python -m json.tool
```

Expected:
- Response includes:
  - `status`: `"healthy"` (when fully initialized)
  - `timestamp`: ISO 8601 string
  - `database`: object with `status`, connection pool info
  - `embedding_model`: object with `model_name`, `dimension`
  - `system`: object with `uptime_seconds`, `cpu_load_1m`, `memory_rss_bytes`
- HTTP status code is 200.

## Scenario 4: Health During Initialization

1. Restart the server and immediately query `/health` (within the first second):

```bash
docker compose restart app && sleep 0.5 && curl -s http://127.0.0.1:8000/health | python -m json.tool
```

Expected:
- `status`: `"initializing"` (if caught before init completes).
- `database.status`: `"initializing"`.
- `embedding_model.status`: `"loading"`.
- `system` metrics are still present (uptime_seconds near 0).
- HTTP status code is 200 (not 500).

## Scenario 5: System Metrics Values

1. Query `/health` after full initialization:

```bash
curl -s http://127.0.0.1:8000/health | python -c "import sys,json; d=json.load(sys.stdin)['system']; print(f'uptime={d[\"uptime_seconds\"]:.1f}s cpu={d[\"cpu_load_1m\"]} mem={d[\"memory_rss_bytes\"]}')"
```

Expected:
- `uptime_seconds`: number >= 0, increases on subsequent calls.
- `cpu_load_1m`: number or null (null only if `os.getloadavg()` and psutil both unavailable).
- `memory_rss_bytes`: number or null (null only if psutil and `resource` module both unavailable).

2. Wait 10 seconds, query again.

Expected:
- `uptime_seconds` increased by ~10.
- Other metrics remain present.

## Scenario 6: psutil Fallback

1. In a test environment (not production), temporarily uninstall psutil:

```bash
pip uninstall -y psutil
```

2. Restart the server and query `/health`.

Expected:
- Server starts without error.
- `system` metrics still present in response.
- `cpu_load_1m` falls back to `os.getloadavg()` (Linux/macOS) or null (Windows).
- `memory_rss_bytes` falls back to `resource.getrusage()` or null.

3. Reinstall psutil:

```bash
pip install psutil
```

## Scenario 7: No Log Duplication

1. With `LOG_FORMAT=json`, make a single API request.
2. Count how many log lines are produced for that single request.

Expected:
- Each log event appears exactly once (not duplicated).
- Uvicorn access log line appears once, not twice.
- No handlers attached to uvicorn/fastapi loggers directly (all propagate to root).

## Scenario 8: Startup Time

1. Time the server startup to first healthy response:

```bash
time (docker compose restart app && until curl -sf http://127.0.0.1:8000/health > /dev/null 2>&1; do sleep 0.2; done)
```

Expected:
- First healthy response within ~5s (Docker overhead included).
- Without lazy imports, this would be ~25s+ due to sentence_transformers/numpy loading at import time.
- The `/health` endpoint responds before embedding model is fully loaded (returns "initializing").

## Pass/Fail Criteria

Pass:
- All expected outcomes match.
- JSON log format produces valid, parseable JSON.
- System metrics are present in every `/health` response.
- Startup time is under 5s to first response (excluding Docker pull).
- No log duplication.

Fail:
- JSON log lines are malformed or missing required keys.
- System metrics missing entirely (not just null values).
- Startup takes >10s to first `/health` response.
- Log lines appear twice for a single event.
- Server crashes when psutil is unavailable.

## Evidence to Record

Capture for each failed step:
- Scenario number and step number.
- Full `/health` response JSON.
- Log output sample (5-10 lines).
- Timing measurement if startup-related.
