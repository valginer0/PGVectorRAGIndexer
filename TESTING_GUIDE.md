# Testing Guide

Complete guide for testing the system.

## 🧪 Test Suite Overview

The v2 system includes a comprehensive test suite covering:
- **Unit tests**: Individual component testing
- **Integration tests**: Database and service integration
- **Configuration tests**: Validation and settings
- **End-to-end tests**: Complete workflows

## 📁 Test Structure

The test suite contains **~100 test files** organized by domain:

| Category | Files | Examples |
|----------|-------|---------|
| **API & Routing** | 10 | `test_api_client.py`, `test_api_client_list_documents.py`, `test_api_initialization.py`, `test_api_license.py`, `test_api_versioning.py`, `test_api_error_registry.py`, `test_server_first_api.py`, `test_retention_api.py` |
| **Auth & Identity** | 4 | `test_auth.py`, `test_auth_integration.py`, `test_client_identity.py`, `test_saml_auth.py` |
| **Search** | 4 | `test_hybrid_search.py`, `test_query_parsing.py`, `test_metadata_filtering.py`, `test_metadata_discovery.py` |
| **Documents & Indexing** | 10 | `test_documents_list.py`, `test_document_tree.py`, `test_document_locks.py`, `test_document_visibility.py`, `test_incremental.py`, `test_indexing_runs.py`, `test_canonical_source_key.py` |
| **Desktop UI Tabs** | 10 | `test_documents_tab.py`, `test_documents_tab_ui.py`, `test_search_tab.py`, `test_upload_tab.py`, `test_manage_tab.py`, `test_settings_tab.py`, `test_recent_activity_tab_ui.py` |
| **Desktop Controllers** | 3 | `test_settings_controller.py`, `test_controller_result.py`, `test_license_service.py` |
| **Licensing** | 4 | `test_license.py`, `test_license_integration.py`, `test_license_utils.py`, `test_yaml_and_license.py` |
| **Document Processing** | 5 | `test_embeddings.py`, `test_encoding.py`, `test_encrypted_pdf.py`, `test_legacy_word.py`, `test_document_processor_office.py` |
| **Infrastructure** | 8 | `test_config.py`, `test_database.py`, `test_migrations.py`, `test_migrations_integration.py`, `test_docker_compose.py`, `test_dockerfile.py`, `test_db_roles.py`, `test_app_config.py` |
| **Observability** | 3 | `test_system_health.py`, `test_logger_setup.py`, `test_startup_hang_regression.py` |
| **Enterprise** | 5 | `test_enterprise_foundations.py`, `test_role_permissions.py`, `test_scim.py`, `test_compliance_export.py`, `test_data_retention.py` |
| **Scheduling & Background** | 3 | `test_folder_scheduler.py`, `test_server_scheduler.py`, `test_watched_folders.py` |
| **E2E & Integration** | 4 | `test_e2e_split_backend.py`, `test_split_deployment.py`, `test_integration.py`, `test_demo_mode.py` |
| **Other** | ~10 | `test_activity_log.py`, `test_analytics.py`, `test_snippet_utils.py`, `test_virtual_roots.py`, `test_workers.py`, `test_upload_crash.py`, `test_quarantine.py`, etc. |
| **Support** | 2 | `conftest.py` (shared fixtures), `helpers.py` (utilities like `get_alembic_head()`) |

## 🚀 Running Tests

### Prerequisites

```bash
# Activate virtual environment
source venv/bin/activate

# Ensure database is running
docker compose up -d

# Install test dependencies (already in requirements.txt)
pip install pytest pytest-asyncio pytest-cov httpx
```

### Run All Tests

```bash
# Run all tests (excludes known-hanging tests)
python -m pytest tests/ \
  --ignore=tests/test_upload_endpoint.py \
  --ignore=tests/test_web_ui.py \
  --ignore=tests/test_web_ui_integration.py -q

# Run with verbose output
pytest -v

# Run with detailed output
pytest -vv
```

> **Note**: `test_upload_endpoint.py`, `test_web_ui.py`, and `test_web_ui_integration.py` hang in local/CI environments and should be excluded from batch runs.

### Run Specific Test Files

```bash
# Configuration tests
pytest tests/test_config.py -v

# Database tests
pytest tests/test_database.py -v

# Embedding tests
pytest tests/test_embeddings.py -v
```

### Run Specific Test Classes

```bash
# Test specific class
pytest tests/test_config.py::TestDatabaseConfig -v

# Test specific method
pytest tests/test_config.py::TestDatabaseConfig::test_default_values -v
```

### Run with Markers

```bash
# Run only unit tests
pytest -m unit

# Run only integration tests
pytest -m integration

# Skip slow tests
pytest -m "not slow"
```

## 📊 Coverage Reports

### Generate Coverage Report

```bash
# Run tests with coverage
pytest --cov=. --cov-report=html --cov-report=term

# View HTML report
# Open htmlcov/index.html in browser
```

### Coverage by Module

```bash
# Coverage for specific module
pytest --cov=config --cov-report=term tests/test_config.py

# Coverage with missing lines
pytest --cov=. --cov-report=term-missing
```

## 🧩 Test Categories

### API & Client Tests
Tests for the REST API layer, desktop API client facade, and error handling:
- `test_api_client.py` — 24 tests covering the `APIClient` facade and all 9 domain clients
- `test_api_client_list_documents.py` — Pagination and filtering for document listing
- `test_api_initialization.py` — Server startup and lifespan management
- `test_api_error_registry.py` — Structured error codes and machine-readable responses
- `test_api_license.py`, `test_api_versioning.py` — License endpoint and API version negotiation

### Search & Metadata Tests
- `test_hybrid_search.py` — Vector + keyword hybrid search
- `test_query_parsing.py` — Query syntax parsing
- `test_metadata_filtering.py`, `test_metadata_discovery.py` — Metadata-based filtering and key/value discovery
- `test_metadata_openapi.py` — OpenAPI schema validation for metadata endpoints

### Infrastructure & Observability Tests
- `test_config.py` — Configuration defaults, env loading, validation
- `test_database.py` — Connection pooling, CRUD, vector search (requires PostgreSQL)
- `test_migrations.py`, `test_migrations_integration.py` — Alembic migration chain
- `test_system_health.py` — 3 async tests for `/health` system metrics schema
- `test_logger_setup.py` — 2 tests for JSON/text log format switching
- `test_startup_hang_regression.py` — 7 tests ensuring lazy imports prevent startup hangs

### Desktop UI & Controller Tests
- `test_settings_controller.py` — 22 tests for `SettingsController` with `ControllerResult`/`UiAction`
- `test_documents_tab.py`, `test_search_tab.py`, `test_upload_tab.py`, `test_manage_tab.py` — Tab UI logic
- `test_controller_result.py`, `test_license_service.py` — Controller pattern and service facades

### Enterprise & Compliance Tests
- `test_enterprise_foundations.py`, `test_role_permissions.py` — RBAC and enterprise features
- `test_scim.py` — SCIM provisioning
- `test_data_retention.py`, `test_retention_api.py`, `test_retention_policy.py` — Data retention orchestration
- `test_compliance_export.py` — Audit log export

### E2E Tests
- `test_e2e_split_backend.py` — Full server E2E (run in CI with live PostgreSQL + uvicorn)
- `test_split_deployment.py` — Split deployment topology validation

## 🔧 Test Fixtures

All shared fixtures are defined in `tests/conftest.py`. Two **autouse** fixtures apply to every test automatically:

### Autouse Fixtures

```python
@pytest.fixture(autouse=True)
def auto_mock_embeddings(mock_embedding_service):
    """Automatically mock embeddings for all tests to ensure speed and isolation."""
    with patch('embeddings.get_embedding_service', return_value=mock_embedding_service):
        yield mock_embedding_service

@pytest.fixture(autouse=True)
def mock_license_revocation_check():
    """Automatically mock license revocation check to prevent 5.0s network timeouts during tests."""
    with patch('license.check_license_revocation', return_value=None):
        yield
```

### Database Fixtures

```python
@pytest.fixture(scope='session')
def setup_test_database(db_connection_params):
    """Create test database, wipe schema, run alembic migrations. Session-scoped."""

@pytest.fixture(scope='function')
def db_manager(setup_test_database):
    """Provide DatabaseManager with per-test TRUNCATE cleanup."""
```

### Helper Utilities (`tests/helpers.py`)

```python
from tests.helpers import get_alembic_head  # Dynamic revision lookup — never hardcode migration IDs
```

## 🎯 Writing New Tests

### Test Template

```python
"""
Tests for [module_name].
"""

import pytest
from [module] import [class_or_function]


class Test[ComponentName]:
    """Tests for [ComponentName]."""
    
    def test_[feature_name](self, fixture_name):
        """Test [specific behavior]."""
        # Arrange
        input_data = "test"
        
        # Act
        result = function_under_test(input_data)
        
        # Assert
        assert result == expected_value
    
    def test_[error_case](self):
        """Test error handling for [case]."""
        with pytest.raises(ExpectedException):
            function_that_should_fail()
```

### Best Practices

1. **Use descriptive names**: `test_insert_chunks_with_valid_data`
2. **Follow AAA pattern**: Arrange, Act, Assert
3. **One assertion per test**: Focus on single behavior
4. **Use fixtures**: Reuse common setup
5. **Test edge cases**: Empty inputs, large inputs, invalid inputs
6. **Mock external dependencies**: Database, APIs, file system
7. **Clean up after tests**: Use fixtures with yield

## 🐛 Debugging Tests

### Run with Debug Output

```bash
# Show print statements
pytest -s

# Show local variables on failure
pytest -l

# Drop into debugger on failure
pytest --pdb

# Stop on first failure
pytest -x
```

### Verbose Logging

```bash
# Show log output
pytest --log-cli-level=DEBUG

# Capture warnings
pytest -W all
```

## 📈 Continuous Integration

### GitHub Actions — Split-Backend E2E

The actual CI workflow (`.github/workflows/test-split-backend.yml`) runs end-to-end tests against a live server:

```yaml
name: Split-Backend E2E Tests
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  e2e-split-backend:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    services:
      postgres:
        image: pgvector/pgvector:pg16
        env:
          POSTGRES_DB: rag_vector_db
          POSTGRES_USER: rag_user
          POSTGRES_PASSWORD: rag_password
        ports: ["5432:5432"]
        options: >-
          --health-cmd "pg_isready -U rag_user -d rag_vector_db"
          --health-interval 10s --health-timeout 5s --health-retries 5
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.10", cache: "pip" }
      - run: pip install -r requirements.txt && pip install pytest requests
      - name: Bootstrap API key, start server, run E2E tests
        env:
          DB_HOST: localhost
          API_REQUIRE_AUTH: "true"
          API_AUTH_FORCE_ALL: "true"
        run: |
          # 1. alembic upgrade head
          # 2. Bootstrap API key via auth.create_api_key_record('e2e-test')
          # 3. Start uvicorn on 127.0.0.1:9000
          # 4. Health-check loop (60 retries × 2s)
          # 5. pytest tests/test_e2e_split_backend.py -v
      - uses: actions/upload-artifact@v4
        if: failure()
        with: { name: server-log, path: server.log, retention-days: 7 }
```

## ✅ Test Checklist

Before committing code:

- [ ] All tests pass locally
- [ ] New features have tests
- [ ] Edge cases are covered
- [ ] Error cases are tested
- [ ] Coverage is maintained (>80%)
- [ ] No skipped tests without reason
- [ ] Tests are documented
- [ ] Fixtures are reused appropriately

## 🎓 Testing Best Practices

### Do's ✅

- ✅ Write tests before fixing bugs
- ✅ Test public interfaces, not implementation
- ✅ Use meaningful test names
- ✅ Keep tests simple and focused
- ✅ Use fixtures for common setup
- ✅ Mock external dependencies
- ✅ Test error conditions
- ✅ Maintain test independence

### Don'ts ❌

- ❌ Don't test implementation details
- ❌ Don't write tests that depend on order
- ❌ Don't use sleep() for timing
- ❌ Don't test third-party libraries
- ❌ Don't commit failing tests
- ❌ Don't skip tests without good reason
- ❌ Don't test everything (focus on critical paths)

## 📚 Additional Resources

### pytest Documentation
- [pytest.org](https://docs.pytest.org/)
- [pytest fixtures](https://docs.pytest.org/en/stable/fixture.html)
- [pytest markers](https://docs.pytest.org/en/stable/mark.html)

### Testing Patterns
- [Arrange-Act-Assert](https://automationpanda.com/2020/07/07/arrange-act-assert-a-pattern-for-writing-good-tests/)
- [Test Doubles](https://martinfowler.com/bliki/TestDouble.html)
- [Testing Best Practices](https://testdriven.io/blog/testing-best-practices/)

## 🚀 Quick Commands Reference

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov

# Run specific file
pytest tests/test_config.py

# Run specific test
pytest tests/test_config.py::test_name

# Run with markers
pytest -m unit

# Debug mode
pytest --pdb

# Verbose output
pytest -vv

# Stop on first failure
pytest -x

# Show print statements
pytest -s

# Generate HTML coverage report
pytest --cov --cov-report=html
```

---

**Happy Testing! 🧪**

Remember: Good tests are the foundation of maintainable code!
