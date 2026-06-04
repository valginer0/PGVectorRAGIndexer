import pytest
import json
from pathlib import Path
from lancedb_adapter import BackendLanceDBAdapter, generate_chunk_id


def test_generate_chunk_id():
    """Test deterministic integer generation for chunks."""
    h1 = generate_chunk_id("doc-1", 0)
    h2 = generate_chunk_id("doc-1", 0)
    h3 = generate_chunk_id("doc-1", 1)
    h4 = generate_chunk_id("doc-2", 0)
    
    assert isinstance(h1, int)
    assert h1 > 0
    assert h1 == h2
    assert h1 != h3
    assert h1 != h4


def test_backend_lancedb_lifecycle(tmp_path):
    """Test table creation, upsert, delete, stats, and search filtering."""
    db_dir = tmp_path / "test_lancedb"
    adapter = BackendLanceDBAdapter(db_path=str(db_dir), embedding_dimension=4)
    
    # 1. Table schema checks
    assert "parent_documents" in adapter.db.table_names()
    assert "document_chunks" in adapter.db.table_names()
    
    # 2. Upsert document
    doc_id = "test-doc-1"
    chunks = [
        (0, "The quick brown fox jumps over the lazy dog.", [0.8, 0.6, 0.0, 0.0], {"page": 1, "type": "story"}),
        (1, "Artificial intelligence is revolutionizing backend search.", [0.0, 0.0, 0.6, 0.8], {"page": 2, "type": "story"})
    ]
    
    doc_metadata = {"type": "story", "namespace": "testing", "category": "general", "author": "Alice"}
    
    adapter.upsert_document(
        document_id=doc_id,
        source_uri="/docs/story.txt",
        chunks=chunks,
        aggregated_text="The quick brown fox jumps over the lazy dog.\n\nArtificial intelligence is revolutionizing backend search.",
        doc_metadata=doc_metadata
    )
    
    # Verify statistics
    stats = adapter.get_statistics()
    assert stats["total_documents"] == 1
    assert stats["total_chunks"] == 2
    
    # 3. Simple parent-child search
    results = adapter.search_parent_child(
        query_text="fox jumps",
        query_vector=[1.0, 0.0, 0.0, 0.0],
        parent_limit=1,
        child_limit=2
    )
    
    assert len(results) == 2
    assert results[0]["document_id"] == doc_id
    assert results[0]["chunk_index"] == 0
    assert results[0]["source_uri"] == "/docs/story.txt"
    assert results[0]["parent_rank"] == 1
    assert results[0]["metadata"]["page"] == 1
    
    # 4. Search filtering
    # Core filters
    results_type = adapter.search_parent_child(
        query_text="backend search",
        query_vector=[0.0, 0.0, 0.0, 1.0],
        filters={"type": "story"}
    )
    assert len(results_type) == 2
    
    # Non-matching filter
    results_no_match = adapter.search_parent_child(
        query_text="backend search",
        query_vector=[0.0, 0.0, 0.0, 1.0],
        filters={"type": "policy"}
    )
    assert len(results_no_match) == 0
    
    # Metadata nested filter query simulation
    results_meta_filter = adapter.search_parent_child(
        query_text="backend search",
        query_vector=[0.0, 0.0, 0.0, 1.0],
        filters={"metadata.author": "Alice"}
    )
    assert len(results_meta_filter) == 2
    
    # Non-matching metadata nested filter
    results_meta_no_match = adapter.search_parent_child(
        query_text="backend search",
        query_vector=[0.0, 0.0, 0.0, 1.0],
        filters={"metadata.author": "Bob"}
    )
    assert len(results_meta_no_match) == 0
    
    # Extension filtering
    results_ext = adapter.search_parent_child(
        query_text="fox",
        query_vector=[1.0, 0.0, 0.0, 0.0],
        filters={"extensions": ["txt"]}
    )
    assert len(results_ext) == 2
    
    results_ext_mismatch = adapter.search_parent_child(
        query_text="fox",
        query_vector=[1.0, 0.0, 0.0, 0.0],
        filters={"extensions": ["pdf"]}
    )
    assert len(results_ext_mismatch) == 0
    
    # 4.5. Test list_documents with prefix and column projection
    docs_all = adapter.list_documents()
    assert len(docs_all) == 1
    assert docs_all[0]["document_id"] == doc_id
    assert docs_all[0]["source_uri"] == "/docs/story.txt"
    assert docs_all[0]["chunk_count"] == 2
    
    docs_prefix = adapter.list_documents(prefix="/docs")
    assert len(docs_prefix) == 1
    
    docs_prefix_mismatch = adapter.list_documents(prefix="/other")
    assert len(docs_prefix_mismatch) == 0

    # Test prefix with underscore to verify starts_with correctness (no wildcard over-matching)
    # We index two documents: one matching the prefix exactly, and one with a character
    # replacing the underscore (which SQL LIKE would over-match as a wildcard).
    doc_id_under = "test-doc-under"
    adapter.upsert_document(
        document_id=doc_id_under,
        source_uri="/docs/ecua_garbage_water/doc.txt",
        chunks=[(0, "content", [0.0, 0.0, 0.0, 0.0], {})],
        aggregated_text="content",
        doc_metadata={"type": "story"}
    )
    
    doc_id_x = "test-doc-x"
    adapter.upsert_document(
        document_id=doc_id_x,
        source_uri="/docs/ecuaXgarbage_water/doc.txt",
        chunks=[(0, "content", [0.0, 0.0, 0.0, 0.0], {})],
        aggregated_text="content",
        doc_metadata={"type": "story"}
    )
    
    # Prefix contains underscore. Under starts_with, only doc_id_under matches.
    # If reverted to LIKE, both doc_id_under and doc_id_x would match because LIKE
    # treats '_' as a wildcard matching 'X'.
    docs_under_match = adapter.list_documents(prefix="/docs/ecua_garbage")
    assert len(docs_under_match) == 1
    assert docs_under_match[0]["document_id"] == doc_id_under
    
    # Cleanup both docs
    adapter.delete_document(doc_id_under)
    adapter.delete_document(doc_id_x)



    # 5. Bulk delete
    # Delete based on mismatching filter (no-op)
    deleted_count = adapter.bulk_delete(filters={"type": "policy"})
    assert deleted_count == 0

    
    # Delete based on valid filter
    deleted_count = adapter.bulk_delete(filters={"type": "story"})
    assert deleted_count == 1  # 1 document deleted
    
    stats_post_delete = adapter.get_statistics()
    assert stats_post_delete["total_documents"] == 0
    assert stats_post_delete["total_chunks"] == 0


def test_stratified_children_spill_ratio(tmp_path):
    """Test parent FTS selection, stratified child retrieval, and parent capping/precision sorting logic."""
    db_dir = tmp_path / "test_lancedb_stratified"
    adapter = BackendLanceDBAdapter(db_path=str(db_dir), embedding_dimension=2)
    
    # Document A: Top parent. FTS query 'ev6' matches this document with highest rank.
    # It has 5 chunks (chunk-rich top parent).
    chunks_a = [
        (0, "The EV6 owner notes outline standard battery diagnostic procedures.", [1.0, 0.0], {"page": 1}),
        (1, "Battery capacity check diagnostic steps.", [1.0, 0.0], {"page": 2}),
        (2, "Cell voltage test instructions.", [1.0, 0.0], {"page": 3}),
        (3, "Thermal monitoring parameters.", [1.0, 0.0], {"page": 4}),
        (4, "End of diagnostic procedures.", [1.0, 0.0], {"page": 5})
    ]
    adapter.upsert_document(
        document_id="doc-a",
        source_uri="ev6_owner_notes.txt",
        chunks=chunks_a,
        aggregated_text="The EV6 owner notes outline standard battery diagnostic procedures. Battery capacity check diagnostic steps. Cell voltage test instructions. Thermal monitoring parameters. End of diagnostic procedures.",
        doc_metadata={"type": "owner_notes"}
    )
    
    # Document B: Sibling parent. FTS query 'ev6' matches this document too, but with lower rank.
    # It has 3 chunks (chunk-rich sibling).
    chunks_b = [
        (0, "General charging procedures for other vehicles.", [0.0, 1.0], {"page": 1}),
        (1, "Charging limit rules and EV6 battery warranty information.", [1.0, 0.0], {"page": 2}),
        (2, "EV6 specific winter charging guidelines and pre-heating.", [1.0, 0.0], {"page": 3})
    ]
    adapter.upsert_document(
        document_id="doc-b",
        source_uri="ev6_charging.txt",
        chunks=chunks_b,
        aggregated_text="General charging procedures. Charging limit rules and EV6 battery warranty information. EV6 specific winter charging guidelines.",
        doc_metadata={"type": "guides"}
    )
    
    # Document C: Noise parent. Does not match FTS query 'ev6' at all.
    chunks_c = [
        (0, "Banana bread recipe with vanilla and chocolate chunks.", [0.0, 0.0], {"page": 1})
    ]
    adapter.upsert_document(
        document_id="doc-c",
        source_uri="banana_bread.txt",
        chunks=chunks_c,
        aggregated_text="Banana bread recipe with vanilla and chocolate chunks.",
        doc_metadata={"type": "cooking"}
    )
    
    # Verify tables have correct row counts
    assert adapter.get_statistics()["total_documents"] == 3
    assert adapter.get_statistics()["total_chunks"] == 9

    # Rebuild FTS index so the newly upserted documents are indexed and searchable using production adapter method
    adapter.rebuild_fts_index()
    
    # Case 1: Search with spill_ratio = 1.0 (strict pre-filter / spill gate closed).
    # Since Document B's FTS score will be lower than Document A's, the spill gate
    # should restrict retrieval to Document A only.
    # A has 5 chunks, but is capped at MAX_CHUNKS_PER_PARENT = 3.
    # We expect exactly 3 results returned (all from Document A).
    results_strict = adapter.search_parent_child(
        query_text="EV6 owner notes",
        query_vector=[1.0, 0.0],
        parent_limit=3,
        child_limit=5,
        child_parent_spill_ratio=1.0
    )
    
    # Validate strict results
    assert len(results_strict) == 3
    for r in results_strict:
        assert r["document_id"] == "doc-a"
    
    # Case 2: Search with spill_ratio = 0.1 (loose pre-filter / spill gate open).
    # Document B is also allowed. We ask for child_limit = 5.
    # Since Doc A is capped at MAX_CHUNKS_PER_PARENT = 3 chunks, the remaining 2 slots
    # should be filled by Doc B's chunks (no monopoly by Doc A).
    # Also, precision-first sorting must place Doc A's chunks before Doc B's chunks.
    results_loose = adapter.search_parent_child(
        query_text="EV6 owner notes",
        query_vector=[1.0, 0.0],
        parent_limit=3,
        child_limit=5,
        child_parent_spill_ratio=0.1
    )
    
    # Validate loose results
    assert len(results_loose) == 5
    
    # First 3 chunks must belong to doc-a (precision-first rank 1)
    assert results_loose[0]["document_id"] == "doc-a"
    assert results_loose[0]["parent_rank"] == 1
    assert results_loose[1]["document_id"] == "doc-a"
    assert results_loose[1]["parent_rank"] == 1
    assert results_loose[2]["document_id"] == "doc-a"
    assert results_loose[2]["parent_rank"] == 1
    
    # Last 2 chunks must belong to doc-b (precision-first rank 2)
    assert results_loose[3]["document_id"] == "doc-b"
    assert results_loose[3]["parent_rank"] == 2
    assert results_loose[4]["document_id"] == "doc-b"
    assert results_loose[4]["parent_rank"] == 2

