.PHONY: test test-fast test-slow test-slow-full test-all

PYTHON := python -m
PYTEST  := $(PYTHON) pytest

# Fast: skip slow Qt UI / integration tests (default for development).
test-fast:
	$(PYTEST) tests/ -m "not slow" -q

# Slow: Qt UI tests + integration tests WITHOUT real model load (~9s).
# Qt tests cannot be parallelised (single QApplication per process).
test-slow:
	$(PYTEST) tests/ -m "slow and not requires_model" -q

# Slow-full: everything including real sentence-transformers model inference.
test-slow-full:
	$(PYTEST) tests/ -m "slow" -q

# All: complete suite (sequential — safe for DB session fixtures and Qt).
test-all:
	$(PYTEST) tests/ -q

# Default: fast tests
test: test-fast
