import pytest
import json
from fastapi.testclient import TestClient
from api import app


class TestManagePreviewPathFilter:
    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_preview_delete_with_windows_path_like(self, client, db_manager):
        # Upload two docs with Windows-style full paths preserved
        r1 = client.post(
            "/upload-and-index",
            files={"file": ("resumeA.txt", b"Resume A content", "text/plain")},
            data={
                "document_type": "resume",
                "custom_source_uri": "C:\\tmp\\resumeA.txt",
            },
        )
        assert r1.status_code == 200

        r2 = client.post(
            "/upload-and-index",
            files={"file": ("policyB.txt", b"Policy B content", "text/plain")},
            data={
                "document_type": "policy",
                "custom_source_uri": "D:\\docs\\policyB.txt",
            },
        )
        assert r2.status_code == 200

        # Fetch documents to verify how source_uri was stored
        docs_resp = client.get("/documents")
        assert docs_resp.status_code == 200
        payload = docs_resp.json()
        docs = payload.get("items", [])
        assert len(docs) >= 2
        # Find the resume doc and derive its directory prefix
        resume_doc = next(d for d in docs if d["source_uri"].endswith("resumeA.txt"))
        stored_uri = resume_doc["source_uri"]
        # Normalize backslashes to forward slashes for readable prints
        norm_uri = stored_uri.replace("\\\\", "/")
        # Build a LIKE pattern for its directory
        if "/" in norm_uri:
            dir_prefix = norm_uri.rsplit("/", 1)[0] + "/"
        else:
            dir_prefix = norm_uri
        like_pattern = dir_prefix.replace("/", "\\\\") + "%"  # Windows-style pattern

        # Preview delete using computed pattern from stored value
        payload = {
            "filters": {
                "source_uri_like": like_pattern
            },
            "preview": True,
        }
        resp = client.post("/documents/bulk-delete", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["document_count"] >= 1

    def test_bulk_delete_matches_missing_google_drive_patterns(self, client, db_manager):
        rows = [
            (
                "g-doc-1",
                r"G:\My Drive\Obsolete\fileA.txt",
                {"type": "cloud", "custom_source_uri": r"G:\My Drive\Obsolete\fileA.txt"},
            ),
            (
                "g-doc-2",
                r"G:\Shared drives\Archive\fileB.txt",
                {"type": "cloud", "custom_source_uri": r"G:\Shared drives\Archive\fileB.txt"},
            ),
            (
                "c-doc-1",
                r"C:\Users\me\Documents\keep.txt",
                {"type": "local", "custom_source_uri": r"C:\Users\me\Documents\keep.txt"},
            ),
        ]
        with db_manager.get_cursor() as cursor:
            for doc_id, source_uri, metadata in rows:
                cursor.execute(
                    """
                    INSERT INTO document_chunks
                    (document_id, chunk_index, text_content, source_uri, metadata)
                    VALUES (%s, 0, %s, %s, %s::jsonb)
                    """,
                    (doc_id, f"content for {doc_id}", source_uri, json.dumps(metadata)),
                )

        for pattern, expected_count in [
            (r"G:\*", 2),
            ("*G*", 2),
            (r"G:\My Drive\Obsolete\fileA.txt", 1),
            ("G:/My Drive/%", 1),
        ]:
            resp = client.post(
                "/documents/bulk-delete",
                json={"filters": {"source_uri_like": pattern}, "preview": True},
            )

            assert resp.status_code == 200
            assert resp.json()["document_count"] == expected_count

        delete_resp = client.post(
            "/documents/bulk-delete",
            json={"filters": {"source_uri_like": r"G:\*"}, "preview": False},
        )

        assert delete_resp.status_code == 200
        assert delete_resp.json()["chunks_deleted"] == 2

        with db_manager.get_cursor() as cursor:
            cursor.execute("SELECT document_id FROM document_chunks ORDER BY document_id")
            assert [row[0] for row in cursor.fetchall()] == ["c-doc-1"]
