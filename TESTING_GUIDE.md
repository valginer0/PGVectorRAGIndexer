# Testing Guide - PGVectorRAGIndexer v2.0

Complete guide for testing the system.

## 🧪 Test Suite Overview

The v2 system includes a comprehensive test suite covering:
- **Unit tests**: Individual component testing
- **Integration tests**: Database and service integration
- **Configuration tests**: Validation and settings
- **End-to-end tests**: Complete workflows

## 📁 Test Structure

```
tests/
├── __init__.py              # Test package initialization
├── conftest.py              # Shared fixtures and configuration
├── test_config.py           # Configuration management tests
├── test_database.py         # Database operations tests
└── test_embeddings.py       # Embedding service tests
```

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
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run with detailed output
pytest -vv
```

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

### 1. Configuration Tests (`test_config.py`)

**What's Tested**:
- Default configuration values
- Environment variable loading
- Validation rules
- Configuration composition
- Singleton pattern

**Example Tests**:
```python
def test_database_config_defaults():
    """Test default database configuration."""
    config = DatabaseConfig()
    assert config.host == 'localhost'
    assert config.port == 5432

def test_embedding_dimension_validation():
    """Test embedding dimension validation."""
    with pytest.raises(ValidationError):
        EmbeddingConfig(dimension=-1)
```

**Run**:
```bash
pytest tests/test_config.py -v
```

### 2. Database Tests (`test_database.py`)

**What's Tested**:
- Connection pooling
- CRUD operations
- Vector search
- Transaction management
- Error handling
- Health checks

**Example Tests**:
```python
def test_insert_chunks(db_manager, sample_embeddings):
    """Test inserting document chunks."""
    repo = DocumentRepository(db_manager)
    chunks = [('doc1', 0, 'Text', '/path', sample_embeddings[0])]
    count = repo.insert_chunks(chunks)
    assert count == 1

def test_search_similar(db_manager, sample_embeddings):
    """Test vector similarity search."""
    repo = DocumentRepository(db_manager)
    # Insert test data
    # Perform search
    # Verify results
```

**Run**:
```bash
pytest tests/test_database.py -v
```

**Note**: Requires running PostgreSQL database

### 3. Embedding Tests (`test_embeddings.py`)

**What's Tested**:
- Model loading
- Embedding generation
- Caching mechanism
- Similarity calculations
- Batch processing

**Example Tests**:
```python
def test_encode_single_text(embedding_service):
    """Test encoding a single text."""
    text = "Test sentence."
    embedding = embedding_service.encode(text)
    assert len(embedding) == 384

def test_embedding_caching(embedding_service):
    """Test that embeddings are cached."""
    text = "Test sentence."
    emb1 = embedding_service.encode(text)
    emb2 = embedding_service.encode(text)
    assert emb1 == emb2
```

**Run**:
```bash
pytest tests/test_embeddings.py -v
```

## 🔧 Test Fixtures

### Database Fixtures

```python
@pytest.fixture
def db_manager(setup_test_database):
    """Provide database manager for tests."""
    manager = DatabaseManager()
    manager.initialize()
    yield manager
    # Cleanup
    manager.close()
```

### Mock Fixtures

```python
@pytest.fixture
def mock_embedding_service():
    """Provide mock embedding service."""
    mock = Mock()
    mock.encode.return_value = [0.1] * 384
    return mock
```

### Sample Data Fixtures

```python
@pytest.fixture
def sample_documents():
    """Provide sample documents for testing."""
    return [
        {'document_id': 'doc1', 'chunks': ['chunk1', 'chunk2']},
        {'document_id': 'doc2', 'chunks': ['chunk3']}
    ]
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

### GitHub Actions Example

```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    
    services:
      postgres:
        image: pgvector/pgvector:pg16
        env:
          POSTGRES_PASSWORD: test_password
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    
    steps:
      - uses: actions/checkout@v2
      
      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
      
      - name: Run tests
        run: |
          pytest --cov=. --cov-report=xml
      
      - name: Upload coverage
        uses: codecov/codecov-action@v2
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
