
import pytest
from fastapi.testclient import TestClient
from api import app

class TestDocumentsListSortingRegression:
    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_list_documents_sort_by_all_fields(self, client, db_manager):
        """
        Verify that all supported sorting fields in /documents work without 500 errors.
        This specifically tests fields that use aggregate aliases (MIN/MAX/COUNT) which 
        previously caused SQL ambiguity or GROUP BY errors.
        """
        # Seed several documents
        docs = [
            ("apple.txt", "resume"),
            ("banana.txt", "policy"),
            ("cherry.txt", "resume"),
        ]

        for name, dtype in docs:
            resp = client.post(
                "/upload-and-index",
                files={"file": (name, b"some content", "text/plain")},
                data={"document_type": dtype}
            )
            assert resp.status_code == 200, f"Setup failed to upload {name}: {resp.text}"

        # Test sorting by each allowed field
        fields = ["indexed_at", "last_updated", "source_uri", "document_type", "chunk_count", "document_id"]
        for field in fields:
            for direction in ["asc", "desc"]:
                resp = client.get(
                    "/api/v1/documents",
                    params={"sort_by": field, "sort_dir": direction, "limit": 10}
                )
                assert resp.status_code == 200, f"Sorting by {field} {direction} failed: {resp.text}"
                payload = resp.json()
                assert "items" in payload
                assert len(payload["items"]) >= 3
                
    def test_list_documents_with_source_prefix_and_sort(self, client, db_manager):
        """
        Verify that combining source_prefix filter with sorting works correctly.
        """
        resp = client.get(
            "/api/v1/documents",
            params={
                "source_prefix": "/", 
                "sort_by": "indexed_at",
                "sort_dir": "desc"
            }
        )
        assert resp.status_code == 200
