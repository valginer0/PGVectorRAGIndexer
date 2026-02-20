"""
End-to-end tests for the split-backend deployment.

Runs against a live API server with real PostgreSQL, embedding model,
and API key authentication enforced (API_AUTH_FORCE_ALL=true).

This test is designed for CI — see .github/workflows/test-split-backend.yml.
It can also be run locally if a server is running on E2E_BASE_URL.

Run with:
    E2E_API_KEY=pgv_sk_... E2E_BASE_URL=http://localhost:9000 \
        pytest tests/test_e2e_split_backend.py -v
"""

import os
from pathlib import Path

import pytest
import requests

pytestmark = pytest.mark.integration

BASE_URL = os.environ.get("E2E_BASE_URL", "http://localhost:9000")
API_KEY = os.environ.get("E2E_API_KEY", "")
VERSION_FILE = Path(__file__).parent.parent / "VERSION"


def _url(path: str) -> str:
    return f"{BASE_URL}{path}"


def _auth_headers() -> dict:
    return {"X-API-Key": API_KEY}


@pytest.fixture(autouse=True)
def _require_env():
    """Skip if not running in E2E environment."""
    if not API_KEY:
        pytest.skip("E2E_API_KEY not set — skipping split-backend E2E tests")


def test_full_lifecycle():
    """Complete split-backend lifecycle: health → auth → upload → search → delete."""

    # ── Step 1: Health check ────────────────────────────────────────────
    r = requests.get(_url("/health"), timeout=10)
    assert r.status_code == 200, f"Health check failed: {r.status_code} {r.text}"
    health = r.json()
    assert health["status"] == "healthy", f"Server not healthy: {health}"

    # ── Step 2: Version check ───────────────────────────────────────────
    r = requests.get(_url("/api/version"), timeout=10)
    assert r.status_code == 200
    version_data = r.json()
    expected_version = VERSION_FILE.read_text().strip()
    assert version_data["server_version"] == expected_version, (
        f"Version mismatch: server={version_data['server_version']} "
        f"file={expected_version}"
    )

    # ── Step 3: Auth enforced — no key → 401 ────────────────────────────
    r = requests.get(_url("/api/v1/documents"), timeout=10)
    assert r.status_code == 401, (
        f"Expected 401 without API key, got {r.status_code}"
    )

    # ── Step 4: Auth enforced — bad key → 401 ──────────────────────────
    r = requests.get(
        _url("/api/v1/documents"),
        headers={"X-API-Key": "pgv_sk_bogus_key_that_does_not_exist"},
        timeout=10,
    )
    assert r.status_code == 401, (
        f"Expected 401 with bad API key, got {r.status_code}"
    )

    # ── Step 5: List documents (empty) ──────────────────────────────────
    r = requests.get(_url("/api/v1/documents"), headers=_auth_headers(), timeout=10)
    assert r.status_code == 200
    docs = r.json()
    assert docs["total"] == 0, f"Expected empty doc list, got {docs['total']}"
    assert docs["items"] == []

    # ── Step 6: Upload document ─────────────────────────────────────────
    test_content = (
        "PGVectorRAGIndexer end-to-end test document. "
        "This contains unique content about quantum flux capacitors "
        "for search verification."
    )
    r = requests.post(
        _url("/api/v1/upload-and-index"),
        headers=_auth_headers(),
        files={"file": ("e2e_test.txt", test_content.encode(), "text/plain")},
        data={"custom_source_uri": "/test/e2e_test.txt"},
        timeout=120,
    )
    assert r.status_code == 200, f"Upload failed: {r.status_code} {r.text}"
    upload = r.json()
    assert upload["status"] == "success", f"Upload not successful: {upload}"
    document_id = upload["document_id"]
    assert document_id, "No document_id returned from upload"

    # ── Step 7: List documents (has doc) ────────────────────────────────
    r = requests.get(_url("/api/v1/documents"), headers=_auth_headers(), timeout=10)
    assert r.status_code == 200
    docs = r.json()
    assert docs["total"] >= 1, f"Expected at least 1 doc, got {docs['total']}"
    doc_ids = [item["document_id"] for item in docs["items"]]
    assert document_id in doc_ids, (
        f"Uploaded doc {document_id} not in list: {doc_ids}"
    )

    # ── Step 8: Search ──────────────────────────────────────────────────
    r = requests.post(
        _url("/api/v1/search"),
        headers=_auth_headers(),
        json={"query": "quantum flux capacitors", "top_k": 5, "min_score": 0.0},
        timeout=30,
    )
    assert r.status_code == 200, f"Search failed: {r.status_code} {r.text}"
    search = r.json()
    assert search["total_results"] > 0, f"Search returned no results: {search}"
    # Verify our document is in search results
    result_doc_ids = [res["document_id"] for res in search["results"]]
    assert document_id in result_doc_ids, (
        f"Uploaded doc {document_id} not in search results: {result_doc_ids}"
    )

    # ── Step 9: Delete document ─────────────────────────────────────────
    r = requests.delete(
        _url(f"/api/v1/documents/{document_id}"),
        headers=_auth_headers(),
        timeout=10,
    )
    assert r.status_code == 200, f"Delete failed: {r.status_code} {r.text}"
    delete = r.json()
    assert delete["status"] == "success", f"Delete not successful: {delete}"

    # ── Step 10: Verify deletion ────────────────────────────────────────
    r = requests.get(_url("/api/v1/documents"), headers=_auth_headers(), timeout=10)
    assert r.status_code == 200
    docs = r.json()
    doc_ids = [item["document_id"] for item in docs["items"]]
    assert document_id not in doc_ids, (
        f"Deleted doc {document_id} still in list: {doc_ids}"
    )
