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
        payload = r.json()
        assert {
            "items",
            "total",
            "limit",
            "offset",
            "sort",
        } <= set(payload.keys())

        docs = payload["items"]
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

    def test_documents_pagination_and_total(self, client, db_manager):
        names = [
            ("alpha.txt", b"alpha contents"),
            ("beta.txt", b"beta contents"),
            ("gamma.txt", b"gamma contents"),
        ]

        for name, content in names:
            client.post(
                "/upload-and-index",
                files={"file": (name, content, "text/plain")},
            )

        first_page = client.get(
            "/documents",
            params={
                "limit": 2,
                "offset": 0,
                "sort_by": "source_uri",
                "sort_dir": "asc",
            },
        )
        assert first_page.status_code == 200
        payload = first_page.json()
        assert payload["total"] == 3
        assert payload["limit"] == 2
        assert payload["offset"] == 0
        assert [doc["source_uri"] for doc in payload["items"]] == [
            "alpha.txt",
            "beta.txt",
        ]

        second_page = client.get(
            "/documents",
            params={
                "limit": 2,
                "offset": 2,
                "sort_by": "source_uri",
                "sort_dir": "asc",
            },
        )
        assert second_page.status_code == 200
        payload_page_2 = second_page.json()
        assert payload_page_2["total"] == 3
        assert payload_page_2["limit"] == 2
        assert payload_page_2["offset"] == 2
        assert [doc["source_uri"] for doc in payload_page_2["items"]] == [
            "gamma.txt",
        ]

    def test_documents_sorting_direction(self, client, db_manager):
        filenames = [
            ("a_file.txt", b"aaa"),
            ("c_file.txt", b"ccc"),
            ("b_file.txt", b"bbb"),
        ]

        for name, content in filenames:
            client.post(
                "/upload-and-index",
                files={"file": (name, content, "text/plain")},
            )

        asc_resp = client.get(
            "/documents",
            params={
                "sort_by": "source_uri",
                "sort_dir": "asc",
            },
        )
        assert asc_resp.status_code == 200
        asc_items = asc_resp.json()["items"]
        assert [doc["source_uri"] for doc in asc_items[:3]] == [
            "a_file.txt",
            "b_file.txt",
            "c_file.txt",
        ]

        desc_resp = client.get(
            "/documents",
            params={
                "sort_by": "source_uri",
                "sort_dir": "desc",
            },
        )
        assert desc_resp.status_code == 200
        desc_items = desc_resp.json()["items"]
        assert [doc["source_uri"] for doc in desc_items[:3]] == [
            "c_file.txt",
            "b_file.txt",
            "a_file.txt",
        ]

    def test_documents_invalid_sort_field_rejected(self, client, db_manager):
        resp = client.get(
            "/documents",
            params={
                "sort_by": "DROP TABLE",
                "sort_dir": "asc",
            },
        )
        assert resp.status_code == 400
        assert "sort_by" in resp.json()["message"].lower()

    def test_openapi_has_documents_and_metadata_values(self, client, db_manager):
        r = client.get("/openapi.json")
        assert r.status_code == 200
        paths = r.json().get("paths", {})
        assert "/documents" in paths
        assert "/metadata/values" in paths
