"""
Backend-side LanceDB adapter for PGVectorRAGIndexer.

Manages embedded LanceDB parent-child tables, indexing operations with 
process-safe file locking, and parent-stratified hybrid search.
"""

import logging
import os
import json
import xxhash
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Sequence
import pyarrow as pa
import lancedb
from filelock import FileLock

logger = logging.getLogger(__name__)

PARENT_TABLE = "parent_documents"
CHUNK_TABLE = "document_chunks"
VECTOR_METRIC = "cosine"


def generate_chunk_id(document_id: str, chunk_index: int) -> int:
    """Generate a deterministic, unique positive int64 ID for a chunk."""
    h = xxhash.xxh64(f"{document_id}:{chunk_index}")
    return h.intdigest() & 0x7fffffffffffffff


class BackendLanceDBAdapter:
    """Manages backend-side LanceDB tables and search query routing."""

    def __init__(self, db_path: str, embedding_dimension: int = 384):
        self.db_path = Path(db_path)
        self.embedding_dimension = embedding_dimension
        self.db_path.mkdir(parents=True, exist_ok=True)
        
        # Initialize connection and file lock
        self.db = lancedb.connect(str(self.db_path))
        self.lock_path = self.db_path / "lancedb_write.lock"
        self.write_lock = FileLock(str(self.lock_path))
        
        # Define schemas
        self.parent_schema = pa.schema([
            pa.field("document_id", pa.string(), nullable=False),
            pa.field("source_uri", pa.string(), nullable=False),
            pa.field("aggregated_text", pa.string(), nullable=False),
            pa.field("chunk_count", pa.int32(), nullable=False),
            pa.field("document_type", pa.string(), nullable=True),
            pa.field("namespace", pa.string(), nullable=True),
            pa.field("category", pa.string(), nullable=True),
            pa.field("metadata", pa.string(), nullable=False)  # JSON-serialized metadata
        ])

        self.chunk_schema = pa.schema([
            pa.field("chunk_id", pa.int64(), nullable=False),
            pa.field("document_id", pa.string(), nullable=False),
            pa.field("chunk_index", pa.int32(), nullable=False),
            pa.field("text_content", pa.string(), nullable=False),
            pa.field("source_uri", pa.string(), nullable=False),
            pa.field("embedding", pa.list_(pa.float32(), self.embedding_dimension), nullable=False),
            pa.field("document_type", pa.string(), nullable=True),
            pa.field("namespace", pa.string(), nullable=True),
            pa.field("category", pa.string(), nullable=True),
            pa.field("metadata", pa.string(), nullable=False)  # JSON-serialized metadata
        ])

        # Auto-create tables on init
        self._ensure_tables_exist()

    def _ensure_tables_exist(self) -> None:
        """Create tables and FTS indexes if they do not exist. Thread/Process safe."""
        with self.write_lock:
            tables = set(self.db.table_names())
            
            if PARENT_TABLE not in tables:
                logger.info(f"Creating LanceDB table: {PARENT_TABLE}")
                parent_table = self.db.create_table(PARENT_TABLE, schema=self.parent_schema)
                parent_table.create_fts_index("aggregated_text")
                
            if CHUNK_TABLE not in tables:
                logger.info(f"Creating LanceDB table: {CHUNK_TABLE}")
                chunk_table = self.db.create_table(CHUNK_TABLE, schema=self.chunk_schema)
                chunk_table.create_fts_index("text_content")

            # Create scalar indexes to speed up pre-filtered queries
            try:
                self.db.open_table(PARENT_TABLE).create_scalar_index("document_id")
            except Exception as e:
                logger.warning(f"Failed to create scalar index on parent table document_id: {e}")

            try:
                self.db.open_table(CHUNK_TABLE).create_scalar_index("document_id")
            except Exception as e:
                logger.warning(f"Failed to create scalar index on chunk table document_id: {e}")

    def upsert_document(
        self,
        document_id: str,
        source_uri: str,
        chunks: List[Tuple[int, str, List[float], Dict[str, Any]]],
        aggregated_text: str,
        doc_metadata: Dict[str, Any]
    ) -> None:
        """
        Insert or update a document in LanceDB.
        
        Deletes any pre-existing rows for the document_id before inserting.
        Acquires a write lock to prevent concurrent modifications from multiple workers.
        """
        with self.write_lock:
            parent_table = self.db.open_table(PARENT_TABLE)
            chunk_table = self.db.open_table(CHUNK_TABLE)
            
            # Clean up existing records to avoid duplicates
            safe_doc_id = document_id.replace("'", "''")
            parent_table.delete(f"document_id = '{safe_doc_id}'")
            chunk_table.delete(f"document_id = '{safe_doc_id}'")
            
            if not chunks:
                return

            # Extract standard metadata fields
            doc_type = doc_metadata.get("type") or doc_metadata.get("document_type")
            namespace = doc_metadata.get("namespace")
            category = doc_metadata.get("category")
            
            # Prepare parent row
            parent_rows = [{
                "document_id": document_id,
                "source_uri": source_uri,
                "aggregated_text": aggregated_text,
                "chunk_count": len(chunks),
                "document_type": doc_type,
                "namespace": namespace,
                "category": category,
                "metadata": json.dumps(doc_metadata)
            }]
            
            # Prepare chunk rows
            chunk_rows = []
            for chunk_index, text, embedding, chunk_meta in chunks:
                chunk_id = generate_chunk_id(document_id, chunk_index)
                
                # Inherit core metadata if not specified in chunk
                c_type = chunk_meta.get("type") or chunk_meta.get("document_type") or doc_type
                c_namespace = chunk_meta.get("namespace") or namespace
                c_category = chunk_meta.get("category") or category
                
                # Merge document-level and chunk-level metadata
                merged_meta = {**doc_metadata, **chunk_meta}
                
                chunk_rows.append({
                    "chunk_id": chunk_id,
                    "document_id": document_id,
                    "chunk_index": chunk_index,
                    "text_content": text,
                    "source_uri": source_uri,
                    "embedding": embedding,
                    "document_type": c_type,
                    "namespace": c_namespace,
                    "category": c_category,
                    "metadata": json.dumps(merged_meta)
                })

            # Append new records to tables
            parent_arrow = pa.Table.from_pylist(parent_rows, schema=self.parent_schema)
            chunk_arrow = pa.Table.from_pylist(chunk_rows, schema=self.chunk_schema)
            
            parent_table.add(parent_arrow)
            chunk_table.add(chunk_arrow)
            
            logger.info(f"Upserted document {document_id} with {len(chunks)} chunks to LanceDB.")

    def delete_document(self, document_id: str) -> int:
        """
        Delete a document by document_id.
        
        Acquires a write lock to prevent concurrent modifications.
        Returns the number of deleted chunk records.
        """
        with self.write_lock:
            parent_table = self.db.open_table(PARENT_TABLE)
            chunk_table = self.db.open_table(CHUNK_TABLE)
            
            safe_doc_id = document_id.replace("'", "''")
            
            # Count chunks before deletion to return count (estimate based on parent metadata)
            chunk_count = 0
            parent_rows = parent_table.search().where(f"document_id = '{safe_doc_id}'").to_arrow().to_pylist()
            if parent_rows:
                chunk_count = int(parent_rows[0].get("chunk_count") or 0)
            
            parent_table.delete(f"document_id = '{safe_doc_id}'")
            chunk_table.delete(f"document_id = '{safe_doc_id}'")
            
            logger.info(f"Deleted document {document_id} from LanceDB.")
            return chunk_count

    def list_documents(self) -> List[Dict[str, Any]]:
        """
        List all parent documents in LanceDB.
        
        Returns a list of dicts with document_id, source_uri, chunk_count, 
        and indexed_at (parsed from metadata).
        """
        parent_table = self.db.open_table(PARENT_TABLE)
        rows = parent_table.search().to_arrow().to_pylist()
        
        results = []
        for row in rows:
            doc_meta_str = row.get("metadata", "{}")
            doc_meta = {}
            if doc_meta_str:
                try:
                    doc_meta = json.loads(doc_meta_str) if isinstance(doc_meta_str, str) else doc_meta_str
                except Exception:
                    pass
            
            indexed_at = doc_meta.get("processed_at") or doc_meta.get("indexed_at")
            
            results.append({
                "document_id": row["document_id"],
                "source_uri": row["source_uri"],
                "chunk_count": int(row["chunk_count"]),
                "indexed_at": indexed_at
            })
            
        return results

    def bulk_delete(self, filters: Dict[str, Any]) -> int:
        """
        Delete documents matching the filters.
        
        Acquires a write lock to prevent concurrent modifications.
        Returns the number of deleted parent records.
        """
        with self.write_lock:
            parent_table = self.db.open_table(PARENT_TABLE)
            chunk_table = self.db.open_table(CHUNK_TABLE)
            
            where_clause = self._build_lancedb_filter_clause(filters)
            if not where_clause:
                raise ValueError("Filters are required for bulk delete")
                
            # Count parents before deleting
            parent_rows = parent_table.search().where(where_clause).to_arrow().to_pylist()
            deleted_count = len(parent_rows)
            
            parent_table.delete(where_clause)
            chunk_table.delete(where_clause)
            
            logger.info(f"Bulk deleted {deleted_count} documents matching filters from LanceDB.")
            return deleted_count

    def search_parent_child(
        self,
        query_text: str,
        query_vector: List[float],
        parent_limit: int = 5,
        child_limit: int = 10,
        child_parent_spill_ratio: float = 1.0,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Perform a parent-stratified child chunk vector retrieval.
        
        1. FTS search on parent aggregated text.
        2. Qualify parents based on FTS score and spill ratio.
        3. Local vector search per qualified parent.
        4. Interleave results.
        """
        parents = self.db.open_table(PARENT_TABLE)
        chunks = self.db.open_table(CHUNK_TABLE)
        
        # 1. Search parent documents using FTS
        parent_search = parents.search(query_text, query_type="fts")
        
        # Apply filters to parents
        if filters:
            parent_where = self._build_lancedb_filter_clause(filters)
            if parent_where:
                parent_search = parent_search.where(parent_where)
                
        parent_rows = parent_search.limit(parent_limit).to_arrow().to_pylist()
        
        if not parent_rows:
            return []
            
        # 2. Stratify child chunks based on FTS score of parents
        matched_parent_details = [
            {
                "rank": rank,
                "document_id": row["document_id"],
                "source_uri": row["source_uri"],
                "fts_score": float(row["_score"]) if row.get("_score") is not None else None,
            }
            for rank, row in enumerate(parent_rows, 1)
        ]
        
        top_fts = matched_parent_details[0]["fts_score"]
        
        # Determine allowed parent document_ids based on spill ratio
        allowed_parent_ids = []
        parent_ranks = {}
        for detail in matched_parent_details:
            doc_id = detail["document_id"]
            if detail["rank"] == 1:
                allowed_parent_ids.append(doc_id)
                parent_ranks[doc_id] = detail["rank"]
                continue
                
            score = detail["fts_score"]
            if (
                top_fts is not None
                and top_fts > 0
                and score is not None
                and score >= top_fts * child_parent_spill_ratio
            ):
                allowed_parent_ids.append(doc_id)
                parent_ranks[doc_id] = detail["rank"]
                
        # 3. Vector search per allowed parent
        stratified_rows = []
        for doc_id in allowed_parent_ids:
            chunk_search = chunks.search(query_vector, vector_column_name="embedding").metric("cosine")
            
            # Formulate the filter: document_id must match doc_id AND any additional chunk-level filters
            filter_clauses = [f"document_id = '{doc_id}'"]
            if filters:
                chunk_filter = self._build_lancedb_filter_clause(filters)
                if chunk_filter:
                    filter_clauses.append(chunk_filter)
                    
            chunk_search = chunk_search.where(" AND ".join(filter_clauses), prefilter=True)
            
            per_parent_rows = chunk_search.limit(child_limit).to_arrow().to_pylist()
            stratified_rows.extend(per_parent_rows)
            
        # 4. Sort aggregated chunks: first by parent_rank, then by vector distance (_distance)
        stratified_rows.sort(
            key=lambda row: (
                parent_ranks.get(row["document_id"], len(parent_ranks) + 1),
                float(row.get("_distance", 1.0))
            )
        )
        
        # Take the top child_limit chunks
        final_rows = stratified_rows[:child_limit]
        
        # 5. Format results to match search API model
        formatted_results = []
        for row in final_rows:
            meta_str = row.get("metadata", "{}")
            try:
                metadata = json.loads(meta_str) if isinstance(meta_str, str) else meta_str
            except Exception:
                metadata = {}
                
            formatted_results.append({
                "chunk_id": int(row["chunk_id"]),
                "document_id": str(row["document_id"]),
                "chunk_index": int(row["chunk_index"]),
                "text_content": str(row["text_content"]),
                "source_uri": str(row["source_uri"]),
                "distance": float(row.get("_distance", 1.0)),
                "metadata": metadata,
                "parent_rank": parent_ranks.get(row["document_id"])
            })
            
        return formatted_results

    def _build_lancedb_filter_clause(self, filters: Dict[str, Any]) -> Optional[str]:
        """Convert standard filters to a SQL-like string compatible with LanceDB/DataFusion."""
        clauses = []
        for key, value in filters.items():
            if key == 'extensions' and isinstance(value, list) and value:
                ext_clauses = []
                for ext in value:
                    normalized = ext if ext.startswith('.') else f'.{ext}'
                    # Defensive comparison using lower() to prevent ILIKE variations
                    ext_clauses.append(f"lower(source_uri) LIKE '%{normalized.lower()}'")
                clauses.append(f"({' OR '.join(ext_clauses)})")
            elif key in ['type', 'namespace', 'category']:
                col_name = "document_type" if key == "type" else key
                safe_val = str(value).replace("'", "''")
                clauses.append(f"{col_name} = '{safe_val}'")
            elif key.startswith('metadata.'):
                meta_key = key[9:]
                safe_val = str(value).replace("'", "''")
                if meta_key in ['type', 'namespace', 'category']:
                    col_name = "document_type" if meta_key == "type" else meta_key
                    clauses.append(f"{col_name} = '{safe_val}'")
                else:
                    # Fallback to wildcard search inside JSON metadata string
                    safe_key = meta_key.replace("'", "''")
                    clauses.append(
                        f"(metadata LIKE '%\"{safe_key}\": \"{safe_val}\"%' OR "
                        f"metadata LIKE '%\"{safe_key}\":\"{safe_val}\"%')"
                    )
            elif key in ['document_id', 'source_uri']:
                safe_val = str(value).replace("'", "''")
                clauses.append(f"{key} = '{safe_val}'")
        
        return " AND ".join(clauses) if clauses else None

    def rebuild_fts_index(self, parent_only: bool = False) -> None:
        """
        Rebuild FTS index on parent and optionally chunk tables.
        
        Since LanceDB FTS indexes are static and do not dynamically index newly 
        appended rows, a freshness lag exists where live-indexed documents are not 
        searchable until rebuild_fts_index() or optimize_vector_index() is run.
        Rebuilding the parent index only is fast and suitable for single document
        or batch indexing freshness.
        """
        with self.write_lock:
            logger.info("Rebuilding FTS index on LanceDB parent table...")
            try:
                self.db.open_table(PARENT_TABLE).create_fts_index("aggregated_text", replace=True)
            except Exception as e:
                logger.warning(f"Failed to rebuild FTS index on parent table: {e}")

            if not parent_only:
                logger.info("Rebuilding FTS index on LanceDB chunk table...")
                try:
                    self.db.open_table(CHUNK_TABLE).create_fts_index("text_content", replace=True)
                except Exception as e:
                    logger.warning(f"Failed to rebuild FTS index on chunk table: {e}")

    def optimize_vector_index(self) -> None:
        """
        Compact files and optimize tables to reclaim space and improve performance.
        Also explicitly rebuilds the FTS indexes to refresh search freshness.
        """
        with self.write_lock:
            logger.info("Optimizing LanceDB parent table...")
            parent_table = self.db.open_table(PARENT_TABLE)
            try:
                parent_table.compact_files()
                parent_table.cleanup_old_versions()
            except Exception as e:
                logger.warning(f"Parent table optimization failed: {e}")
                
            logger.info("Optimizing LanceDB chunk table...")
            chunk_table = self.db.open_table(CHUNK_TABLE)
            try:
                chunk_table.compact_files()
                chunk_table.cleanup_old_versions()
            except Exception as e:
                logger.warning(f"Chunk table optimization failed: {e}")
        
        # Explicitly rebuild FTS indexes to restore query freshness
        self.rebuild_fts_index()

    def get_statistics(self) -> Dict[str, Any]:
        """Get statistics of the LanceDB index."""
        parents = self.db.open_table(PARENT_TABLE)
        chunks = self.db.open_table(CHUNK_TABLE)
        
        total_documents = parents.count_rows()
        total_chunks = chunks.count_rows()
        avg_chunks = int(total_chunks / total_documents) if total_documents > 0 else 0
        
        return {
            "total_documents": total_documents,
            "total_chunks": total_chunks,
            "avg_chunks_per_document": avg_chunks
        }
