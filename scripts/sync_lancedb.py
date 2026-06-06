"""
Migration script to sync PostgreSQL document chunks into the backend LanceDB index.
"""

import sys
import os
import argparse
import logging
from typing import List, Dict, Any

# Add parent directory to path so we can import modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import get_config
from database import get_db_manager
from services import get_lancedb_adapter

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("sync_lancedb")


def _assert_count_parity(adapter, expected_docs: int, expected_chunks: int) -> None:
    """Raise if LanceDB does not match the PostgreSQL snapshot just synced."""
    lancedb_stats = adapter.get_statistics()

    lancedb_docs = int(lancedb_stats.get("total_documents") or 0)
    lancedb_chunks = int(lancedb_stats.get("total_chunks") or 0)

    if expected_docs != lancedb_docs or expected_chunks != lancedb_chunks:
        raise RuntimeError(
            "LanceDB sync did not converge: "
            f"PostgreSQL snapshot has {expected_docs} docs / {expected_chunks} chunks; "
            f"LanceDB has {lancedb_docs} docs / {lancedb_chunks} chunks"
        )


def sync_postgres_to_lancedb(batch_size: int = 50, force: bool = False) -> None:
    """Sync all document chunks from PostgreSQL to LanceDB in batches."""
    config = get_config()
    db_manager = get_db_manager()
    
    # Initialize adapter
    logger.info("Initializing LanceDB adapter...")
    adapter = get_lancedb_adapter()
    
    if force:
        logger.info("Force flag specified. Resetting LanceDB tables...")
        with adapter.write_lock:
            # Drop tables to recreate them fresh
            try:
                adapter.db.drop_table("parent_documents")
            except Exception:
                pass
            try:
                adapter.db.drop_table("document_chunks")
            except Exception:
                pass
        # Re-ensure tables are created empty
        adapter._ensure_tables_exist()

    logger.info("Fetching unique document IDs from PostgreSQL...")
    doc_ids_query = "SELECT DISTINCT document_id, source_uri FROM document_chunks"
    
    try:
        with db_manager.get_cursor(dict_cursor=True) as cursor:
            cursor.execute(doc_ids_query)
            all_docs = list(cursor.fetchall())
    except Exception as e:
        logger.error(f"Failed to query PostgreSQL: {e}")
        raise
        
    total_docs = len(all_docs)
    logger.info(f"Found {total_docs} documents in PostgreSQL to sync.")
    
    if total_docs == 0:
        logger.info("No documents to sync.")
        _assert_count_parity(adapter, expected_docs=0, expected_chunks=0)
        return

    # Process in batches
    chunks_query = """
    SELECT 
        document_id, 
        chunk_index, 
        text_content, 
        source_uri, 
        embedding, 
        metadata
    FROM document_chunks 
    WHERE document_id = ANY(%s)
    ORDER BY document_id, chunk_index
    """
    
    synced_docs = 0
    synced_chunks = 0
    failed_docs: List[str] = []
    
    for i in range(0, total_docs, batch_size):
        batch_docs = all_docs[i:i + batch_size]
        batch_ids = [doc["document_id"] for doc in batch_docs]
        
        try:
            with db_manager.get_cursor(dict_cursor=True) as cursor:
                cursor.execute(chunks_query, (batch_ids,))
                chunk_rows = list(cursor.fetchall())
        except Exception as e:
            logger.error(f"Failed to fetch chunk batch: {e}")
            raise

        # Group by document_id
        grouped_chunks = {}
        for row in chunk_rows:
            doc_id = row["document_id"]
            if doc_id not in grouped_chunks:
                grouped_chunks[doc_id] = []
            grouped_chunks[doc_id].append(row)
            
        # Upsert each document into LanceDB
        for doc_id, rows in grouped_chunks.items():
            # Find the source_uri and doc-level metadata
            source_uri = rows[0]["source_uri"]
            
            # Formulate chunks list for upsert_document:
            # List[Tuple[chunk_index, text_content, embedding, chunk_metadata]]
            lancedb_chunks = []
            for row in rows:
                meta = row["metadata"] or {}
                if isinstance(meta, str):
                    import json
                    try:
                        meta = json.loads(meta)
                    except Exception:
                        meta = {}
                lancedb_chunks.append((
                    row["chunk_index"],
                    row["text_content"],
                    # Convert embedding vector to list of floats if needed
                    list(row["embedding"]) if hasattr(row["embedding"], "__iter__") else row["embedding"],
                    meta
                ))
            
            # Document metadata (inherit from first chunk metadata or use empty)
            doc_metadata = lancedb_chunks[0][3] if lancedb_chunks else {}
            aggregated_text = "\n\n".join(row["text_content"] for row in rows)
            
            try:
                adapter.upsert_document(
                    document_id=doc_id,
                    source_uri=source_uri,
                    chunks=lancedb_chunks,
                    aggregated_text=aggregated_text,
                    doc_metadata=doc_metadata
                )
                synced_docs += 1
                synced_chunks += len(lancedb_chunks)
            except Exception as e:
                logger.error(f"Failed to sync document {doc_id} to LanceDB: {e}", exc_info=True)
                failed_docs.append(str(doc_id))

        logger.info(f"Processed batch: {synced_docs}/{total_docs} documents synced ({synced_chunks} chunks).")

    if failed_docs:
        sample = ", ".join(failed_docs[:10])
        more = "" if len(failed_docs) <= 10 else f" (+{len(failed_docs) - 10} more)"
        raise RuntimeError(f"Failed to sync {len(failed_docs)} documents to LanceDB: {sample}{more}")

    # Optimize vector index at the end
    logger.info("Optimizing LanceDB vector index...")
    adapter.optimize_vector_index()
    _assert_count_parity(adapter, expected_docs=total_docs, expected_chunks=synced_chunks)
    logger.info("✓ Sync completed successfully.")


def main():
    parser = argparse.ArgumentParser(description="Sync PostgreSQL document chunks to LanceDB")
    parser.add_argument("--batch-size", type=int, default=50, help="Number of documents to process in a batch")
    parser.add_argument("--force", action="store_true", help="Clear LanceDB tables before sync")
    args = parser.parse_args()
    
    sync_postgres_to_lancedb(batch_size=args.batch_size, force=args.force)


if __name__ == "__main__":
    main()
