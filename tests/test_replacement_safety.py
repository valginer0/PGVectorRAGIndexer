"""
Replacement-safety tests (third-party review 2026-06-11).

Covers two P1 findings:
1. /index must enforce the same overwrite guard as /upload-and-index so a
   writer cannot take over another user's document by reindexing its source.
2. Replacing an existing document must not lose the old version when the
   replacement fails partway (insert failure or LanceDB upsert failure).
"""

import io
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

BACKUP_CHUNKS = [
    ("doc-1", 0, "old chunk 0", "t.txt", [0.0, 0.0], {"file_hash": "oldhash"}),
    ("doc-1", 1, "old chunk 1", "t.txt", [0.0, 0.1], {"file_hash": "oldhash"}),
]


def _fake_processed_doc(doc_id="doc-1", source="t.txt", n_chunks=2, file_hash="newhash"):
    chunks = [SimpleNamespace(page_content=f"new chunk {i}", metadata={}) for i in range(n_chunks)]
    doc = SimpleNamespace(
        document_id=doc_id,
        source_uri=source,
        chunks=chunks,
        metadata={"file_hash": file_hash, "source_uri": source, "document_id": doc_id},
        processed_at=datetime.now(timezone.utc),
    )
    doc.get_chunk_texts = lambda: [c.page_content for c in chunks]
    return doc


def _failing_first_insert(repo):
    """Make repo.insert_chunks fail on the first (replacement) insert only."""
    inserts = []

    def insert_chunks(chunks):
        inserts.append(chunks)
        if len(inserts) == 1:
            raise RuntimeError("insert blew up")
        return len(chunks)

    repo.insert_chunks.side_effect = insert_chunks
    return inserts


def _make_indexer(repo, lancedb_enabled=False):
    from indexer_v2 import DocumentIndexer

    idx = DocumentIndexer.__new__(DocumentIndexer)
    idx.config = SimpleNamespace(retrieval=SimpleNamespace(lancedb_enabled=lancedb_enabled))
    idx.db_manager = MagicMock()
    idx.repository = repo
    idx.embedding_service = MagicMock()
    idx.embedding_service.encode_batch.side_effect = (
        lambda texts, show_progress=False: [[0.1, 0.2] for _ in texts]
    )
    idx.processor = MagicMock()
    idx.processor.process.return_value = _fake_processed_doc()
    return idx


def _repo_with_existing(file_hash="oldhash"):
    repo = MagicMock()
    repo.get_document_by_id.return_value = {"metadata": {"file_hash": file_hash}}
    repo.get_document_chunks_for_reinsert.return_value = BACKUP_CHUNKS
    return repo


# ---------------------------------------------------------------------------
# Replacement authorization on the indexer (/index path)
# ---------------------------------------------------------------------------


def test_index_guard_denies_replacement_of_existing_doc():
    from indexer_v2 import ReplacementNotAuthorizedError

    repo = _repo_with_existing()
    idx = _make_indexer(repo)

    with pytest.raises(ReplacementNotAuthorizedError):
        idx.index_document("t.txt", force_reindex=True, may_replace=lambda doc_id: False)

    repo.delete_document.assert_not_called()
    repo.insert_chunks.assert_not_called()


def test_index_guard_allows_owner_replacement():
    repo = _repo_with_existing()
    idx = _make_indexer(repo)

    res = idx.index_document("t.txt", force_reindex=True, may_replace=lambda doc_id: True)

    assert res["status"] == "success"
    repo.get_document_chunks_for_reinsert.assert_called_once_with("doc-1")
    repo.delete_document.assert_called_once_with("doc-1")
    repo.insert_chunks.assert_called_once()


def test_index_guard_not_consulted_for_new_document():
    repo = MagicMock()
    repo.get_document_by_id.return_value = None
    idx = _make_indexer(repo)
    guard = MagicMock(return_value=False)

    res = idx.index_document("t.txt", may_replace=guard)

    assert res["status"] == "success"
    guard.assert_not_called()


def test_index_guard_not_consulted_for_identical_hash_skip():
    # Existing hash matches the new file hash -> skip path, no replacement.
    repo = _repo_with_existing(file_hash="newhash")
    idx = _make_indexer(repo)
    guard = MagicMock(return_value=False)

    res = idx.index_document("t.txt", may_replace=guard)

    assert res["status"] == "skipped"
    guard.assert_not_called()
    repo.delete_document.assert_not_called()


# ---------------------------------------------------------------------------
# Replacement-safe rollback in the indexer (/index path)
# ---------------------------------------------------------------------------


def test_index_replacement_restores_old_doc_on_insert_failure():
    repo = _repo_with_existing()
    inserts = _failing_first_insert(repo)
    idx = _make_indexer(repo)

    res = idx.index_document("t.txt", force_reindex=True)

    assert res["status"] == "error"
    # Delete #1 removes the old version, delete #2 clears the failed replacement.
    assert repo.delete_document.call_count == 2
    # The second insert restored the backed-up old chunks.
    assert inserts[-1] == BACKUP_CHUNKS


def test_index_replacement_restores_old_doc_on_lancedb_failure(monkeypatch):
    repo = _repo_with_existing()
    inserts = []
    repo.insert_chunks.side_effect = lambda chunks: inserts.append(chunks) or len(chunks)

    adapter = MagicMock()
    adapter.upsert_document.side_effect = RuntimeError("LanceDB disk full")
    monkeypatch.setattr("services.get_lancedb_adapter", lambda: adapter)

    idx = _make_indexer(repo, lancedb_enabled=True)

    res = idx.index_document("t.txt", force_reindex=True)

    assert res["status"] == "error"
    assert "disk full" in res["message"]
    # New chunks inserted, then the backup restored after the LanceDB failure.
    assert len(inserts) == 2
    assert inserts[-1] == BACKUP_CHUNKS
    # Partial LanceDB replacement removed so drift repair resyncs from PostgreSQL.
    adapter.delete_document.assert_called_with("doc-1")


def test_index_no_rollback_inserts_for_brand_new_doc_failure():
    repo = MagicMock()
    repo.get_document_by_id.return_value = None
    inserts = _failing_first_insert(repo)
    idx = _make_indexer(repo)

    res = idx.index_document("t.txt")

    assert res["status"] == "error"
    # Nothing to restore: only the failed insert happened, plus a cleanup delete.
    assert len(inserts) == 1
    repo.get_document_chunks_for_reinsert.assert_not_called()


# ---------------------------------------------------------------------------
# /index route wiring
# ---------------------------------------------------------------------------


def _patch_runs(monkeypatch, completed):
    monkeypatch.setattr("indexing_runs.start_run", lambda **kw: 1)
    monkeypatch.setattr(
        "indexing_runs.complete_run", lambda run_id, **kw: completed.update(kw)
    )


async def test_index_route_maps_replacement_denied_to_403(monkeypatch):
    import routers.indexing_api as mod
    from indexer_v2 import ReplacementNotAuthorizedError
    from api_models import IndexRequest
    from fastapi import HTTPException

    fake_idx = MagicMock()
    fake_idx.index_document.side_effect = ReplacementNotAuthorizedError("doc-1")
    monkeypatch.setattr(mod, "get_indexer", lambda: fake_idx)
    completed = {}
    _patch_runs(monkeypatch, completed)

    with pytest.raises(HTTPException) as exc:
        await mod.index_document(IndexRequest(source_uri="x.txt"), key_record={"id": 2})

    assert exc.value.status_code == 403
    assert completed.get("status") == "failed"


async def test_index_route_wires_overwrite_guard(monkeypatch):
    import routers.indexing_api as mod
    from api_models import IndexRequest

    captured = {}

    def fake_index_document(**kwargs):
        captured.update(kwargs)
        return {
            "status": "success",
            "document_id": "doc-1",
            "source_uri": "x.txt",
            "chunks_indexed": 1,
        }

    fake_idx = MagicMock()
    fake_idx.index_document.side_effect = fake_index_document
    monkeypatch.setattr(mod, "get_indexer", lambda: fake_idx)
    monkeypatch.setattr(mod, "_assign_owner_if_authenticated", lambda *a: None)

    guard_calls = []

    def fake_guard(key_record, doc_id):
        guard_calls.append((key_record, doc_id))
        return False

    monkeypatch.setattr(mod, "_may_replace_document", fake_guard)
    _patch_runs(monkeypatch, {})

    await mod.index_document(IndexRequest(source_uri="x.txt"), key_record={"id": 7})

    may_replace = captured["may_replace"]
    assert may_replace("doc-9") is False
    assert guard_calls == [({"id": 7}, "doc-9")]


# ---------------------------------------------------------------------------
# /upload-and-index replacement-safe rollback
# ---------------------------------------------------------------------------


async def test_upload_replacement_restores_old_doc_on_failure(monkeypatch):
    import routers.indexing_api as mod
    from fastapi import HTTPException
    from starlette.datastructures import UploadFile as StarletteUploadFile

    repo = _repo_with_existing(file_hash="different-from-upload")
    inserts = _failing_first_insert(repo)

    fake_idx = MagicMock()
    fake_idx.repository = repo
    fake_idx.processor.process.return_value = _fake_processed_doc()
    fake_idx.embedding_service.encode_batch.side_effect = (
        lambda texts, show_progress=False: [[0.1, 0.2] for _ in texts]
    )

    monkeypatch.setattr(mod, "get_indexer", lambda: fake_idx)
    monkeypatch.setattr(
        "config.get_config",
        lambda: SimpleNamespace(retrieval=SimpleNamespace(lancedb_enabled=False)),
    )
    _patch_runs(monkeypatch, {})

    upload = StarletteUploadFile(file=io.BytesIO(b"new content"), filename="t.txt")

    with pytest.raises(HTTPException):
        await mod.upload_and_index(
            file=upload,
            force_reindex=True,
            custom_source_uri=None,
            document_type=None,
            metadata_json=None,
            ocr_mode=None,
            key_record=None,
        )

    # Old version deleted once for replacement, failed replacement cleared,
    # then the backup restored.
    assert repo.delete_document.call_count == 2
    assert inserts[-1] == BACKUP_CHUNKS
