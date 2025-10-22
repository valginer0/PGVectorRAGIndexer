import pytest
from fastapi.testclient import TestClient
from api import app


class TestDocumentsList:
    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_list_documents_includes_metadata_type(self, client, db_manager):
        # Upload two docs with distinct types
        client.post(
            "/upload-and-index",
            files={"file": ("resume.txt", b"Resume content", "text/plain")},
            data={"document_type": "resume"}
        )
        client.post(
            "/upload-and-index",
            files={"file": ("policy.txt", b"Policy content", "text/plain")},
            data={"document_type": "policy"}
        )

        r = client.get("/documents")
        assert r.status_code == 200
        docs = r.json()
        assert isinstance(docs, list)
        assert len(docs) >= 2

        # Validate minimal contract for DocumentsTab
        for doc in docs:
            assert "source_uri" in doc
            assert "chunk_count" in doc
            assert "indexed_at" in doc
            assert "last_updated" in doc or True  # optional
            # UI needs metadata.type; enforce presence of metadata dict with type
            assert "metadata" in doc and isinstance(doc["metadata"], dict)
            assert "type" in doc["metadata"]

    def test_openapi_has_documents_and_metadata_values(self, client, db_manager):
        r = client.get("/openapi.json")
        assert r.status_code == 200
        paths = r.json().get("paths", {})
        assert "/documents" in paths
        assert "/metadata/values" in paths
