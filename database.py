"""
Database connection and operations module.

Provides connection pooling, async support, and common database operations
for the PGVectorRAGIndexer system.
"""

import logging
import json
import os
import threading
from contextlib import contextmanager, asynccontextmanager
from typing import Optional, List, Dict, Any, Tuple, Union, Sequence
from datetime import datetime, timezone

import psycopg2
from psycopg2 import pool, sql
from psycopg2.extras import execute_values, RealDictCursor
from pgvector.psycopg2 import register_vector

from config import get_config
from path_utils import normalize_path as _normalize_prefix, NORMALIZED_URI_SQL

logger = logging.getLogger(__name__)


class DatabaseError(Exception):
    """Base exception for database errors."""
    pass


class ConnectionPoolError(DatabaseError):
    """Exception for connection pool errors."""
    pass


class QueryError(DatabaseError):
    """Exception for query execution errors."""
    pass


class _PooledConnection:
    """Thin wrapper that returns the connection to the pool on close().

    psycopg2 connection objects have read-only C-level attributes, so we
    can't monkey-patch ``close()``.  This wrapper delegates every attribute
    to the real connection but overrides ``close()`` to call ``putconn()``.
    """

    def __init__(self, conn, pool, release_slot=None):
        self._conn = conn
        self._pool = pool
        self._release_slot = release_slot
        self._closed = False

    # --- public override ---------------------------------------------------
    def close(self):
        """Return the connection to the pool instead of closing it."""
        if self._closed:
            return
        self._closed = True
        try:
            self._pool.putconn(self._conn)
        except Exception:
            pass
        finally:
            if self._release_slot:
                self._release_slot()

    # --- delegate everything else to the real connection --------------------
    def __getattr__(self, name):
        return getattr(self._conn, name)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class DatabaseManager:
    """
    Manages database connections with connection pooling.

    Provides both synchronous and context manager interfaces for
    database operations with automatic connection management.
    """
    
    def __init__(self):
        """Initialize database manager."""
        self.config = get_config().database
        self._pool: Optional[pool.ThreadedConnectionPool] = None
        self._pool_semaphore: Optional[threading.BoundedSemaphore] = None
        self._pool_capacity = 0
        self._initialized = False
    
    def initialize(self) -> None:
        """Initialize connection pool."""
        if self._initialized:
            logger.warning("Database manager already initialized")
            return
        
        try:
            conn_kwargs = dict(
                host=self.config.host,
                port=self.config.port,
                dbname=self.config.name,
                user=self.config.user,
                password=self.config.password,
                connect_timeout=self.config.connect_timeout,
                options=f"-c statement_timeout={self.config.statement_timeout * 1000}"
            )
            if self.config.sslmode:
                conn_kwargs['sslmode'] = self.config.sslmode
            self._pool_capacity = max(
                1,
                int(self.config.pool_size) + max(0, int(self.config.max_overflow)),
            )
            self._pool = pool.ThreadedConnectionPool(
                minconn=1,
                maxconn=self._pool_capacity,
                **conn_kwargs,
            )
            self._pool_semaphore = threading.BoundedSemaphore(self._pool_capacity)
            self._initialized = True
            logger.info(
                f"Database connection pool initialized "
                f"(host={self.config.host}, db={self.config.name}, "
                f"maxconn={self._pool_capacity})"
            )
        except Exception as e:
            logger.error(f"Failed to initialize connection pool: {e}")
            raise ConnectionPoolError(f"Connection pool initialization failed: {e}")
    
    def close(self) -> None:
        """Close all connections in the pool."""
        if self._pool:
            self._pool.closeall()
            self._pool_semaphore = None
            self._pool_capacity = 0
            self._initialized = False
            logger.info("Database connection pool closed")

    def _acquire_pool_slot(self) -> bool:
        if self._pool_semaphore is None:
            raise ConnectionPoolError("Connection pool is not initialized")
        return self._pool_semaphore.acquire(timeout=max(0, int(self.config.pool_timeout)))

    def _release_pool_slot(self) -> None:
        if self._pool_semaphore is None:
            return
        try:
            self._pool_semaphore.release()
        except ValueError:
            logger.warning("Attempted to release an unacquired database pool slot")
    
    @contextmanager
    def get_connection(self):
        """
        Get a connection from the pool as a context manager.
        
        Yields:
            psycopg2.connection: Database connection
            
        Raises:
            ConnectionPoolError: If pool is not initialized or connection fails
        """
        if not self._initialized:
            self.initialize()
        
        conn = None
        acquired = False
        try:
            acquired = self._acquire_pool_slot()
            if not acquired:
                raise ConnectionPoolError(
                    "Connection pool timed out waiting for an available slot"
                )
            conn = self._pool.getconn()
            register_vector(conn)
            yield conn
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"Database connection error: {e}")
            raise ConnectionPoolError(f"Connection error: {e}")
        finally:
            if conn:
                self._pool.putconn(conn)
            if acquired:
                self._release_pool_slot()
    
    def get_connection_raw(self):
        """Get a raw connection from the pool.

        Unlike get_connection(), this returns the connection directly,
        not as a context manager.  Calling ``conn.close()`` returns
        the connection to the pool (it does NOT destroy the TCP link).
        """
        if not self._initialized:
            self.initialize()
        acquired = self._acquire_pool_slot()
        if not acquired:
            raise ConnectionPoolError(
                "Connection pool timed out waiting for an available slot"
            )
        try:
            conn = self._pool.getconn()
            register_vector(conn)
            return _PooledConnection(conn, self._pool, self._release_pool_slot)
        except Exception as e:
            self._release_pool_slot()
            logger.error(f"Database connection error: {e}")
            raise ConnectionPoolError(f"Connection error: {e}")

    @contextmanager
    def get_cursor(self, dict_cursor: bool = False):
        """
        Get a cursor from a pooled connection.
        
        Args:
            dict_cursor: If True, return RealDictCursor for dict-like results
            
        Yields:
            psycopg2.cursor: Database cursor
        """
        with self.get_connection() as conn:
            cursor_factory = RealDictCursor if dict_cursor else None
            cursor = conn.cursor(cursor_factory=cursor_factory)
            try:
                yield cursor
                conn.commit()
            except Exception as e:
                conn.rollback()
                logger.error(f"Cursor operation error: {e}")
                raise QueryError(f"Query execution failed: {e}")
            finally:
                cursor.close()
    
    def execute_query(
        self,
        query: str,
        params: Optional[tuple] = None,
        fetch: bool = False
    ) -> Optional[List[tuple]]:
        """
        Execute a query with optional parameters.
        
        Args:
            query: SQL query string
            params: Query parameters
            fetch: If True, fetch and return results
            
        Returns:
            Query results if fetch=True, None otherwise
        """
        with self.get_cursor() as cursor:
            cursor.execute(query, params)
            if fetch:
                return cursor.fetchall()
            return None
    
    def execute_many(
        self,
        query: str,
        data: List[tuple],
        page_size: int = 100
    ) -> None:
        """
        Execute batch insert/update using execute_values.
        
        Args:
            query: SQL query with VALUES %s placeholder
            data: List of tuples to insert
            page_size: Number of rows per batch
        """
        with self.get_cursor() as cursor:
            execute_values(cursor, query, data, page_size=page_size)
    
    def health_check(self) -> Dict[str, Any]:
        """
        Perform database health check.
        
        Returns:
            Dict with health status information
        """
        try:
            with self.get_cursor() as cursor:
                cursor.execute("SELECT version();")
                version = cursor.fetchone()[0]
                
                cursor.execute("SELECT COUNT(*) FROM document_chunks;")
                chunk_count = cursor.fetchone()[0]
                
                cursor.execute(
                    "SELECT COUNT(DISTINCT document_id) FROM document_chunks;"
                )
                doc_count = cursor.fetchone()[0]
                
                return {
                    "status": "healthy",
                    "postgres_version": version,
                    "total_chunks": chunk_count,
                    "total_documents": doc_count,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }


AUTO_ANALYZE_ENABLED = os.getenv("ENABLE_DB_ANALYZE", "true").lower() in ("1", "true", "yes")
ANALYZE_INTERVAL_SECONDS = int(os.getenv("DB_ANALYZE_INTERVAL_SECONDS", "300"))


class DocumentRepository:
    """Repository for document-related database operations."""
    
    def __init__(self, db_manager: DatabaseManager):
        """Initialize repository with database manager."""
        self.db = db_manager

    def _normalize_source_uri_like(self, pattern: str) -> str:
        normalized = pattern.replace('\\', '/').replace('\t', '/').replace('\n', '/').replace('\r', '/')
        while '//' in normalized:
            normalized = normalized.replace('//', '/')
        normalized = normalized.replace('*', '%').replace('?', '_')
        if '%' not in normalized and '_' not in normalized:
            normalized = f"%{normalized}%"
        return normalized

    def _source_uri_like_clause(self) -> str:
        """Return SQL matching source URI filters across canonical URI fields."""
        normalized_metadata_source_uri_sql = (
            "REPLACE(REPLACE(REPLACE(REPLACE("
            "COALESCE(metadata->>'source_uri', ''), E'\\\\', '/'), "
            "E'\\t', '/'), E'\\n', '/'), E'\\r', '/')"
        )
        normalized_custom_source_uri_sql = (
            "REPLACE(REPLACE(REPLACE(REPLACE("
            "COALESCE(metadata->>'custom_source_uri', ''), E'\\\\', '/'), "
            "E'\\t', '/'), E'\\n', '/'), E'\\r', '/')"
        )
        return (
            "("
            f"{NORMALIZED_URI_SQL} ILIKE %s OR "
            f"{normalized_metadata_source_uri_sql} ILIKE %s OR "
            f"{normalized_custom_source_uri_sql} ILIKE %s"
            ")"
        )
    
    def _should_run_analyze(self) -> bool:
        """Determine whether ANALYZE should run based on recency."""
        if not AUTO_ANALYZE_ENABLED:
            return False

        if ANALYZE_INTERVAL_SECONDS <= 0:
            return True

        check_query = (
            """
            SELECT CASE
                WHEN last_analyze IS NULL AND last_autoanalyze IS NULL THEN TRUE
                ELSE NOW() - GREATEST(
                    COALESCE(last_analyze, '-infinity'::timestamp),
                    COALESCE(last_autoanalyze, '-infinity'::timestamp)
                ) > (%s * INTERVAL '1 second')
            END AS should_run
            FROM pg_stat_all_tables
            WHERE schemaname = 'public' AND relname = 'document_chunks'
            """
        )

        try:
            result = self.db.execute_query(check_query, (ANALYZE_INTERVAL_SECONDS,), fetch=True)
            if not result:
                return True
            return bool(result[0][0])
        except QueryError as exc:
            logger.warning(f"Analyze check failed, defaulting to run ANALYZE: {exc}")
            return True

    def insert_chunks(
        self,
        chunks: List[Tuple[str, int, str, str, List[float], Optional[Dict[str, Any]]]],
        batch_size: int = 100
    ) -> int:
        """
        Insert document chunks into database.
        
        Args:
            chunks: List of (document_id, chunk_index, text, source_uri, embedding, metadata)
            batch_size: Batch size for insertion
            
        Returns:
            Number of chunks inserted
        """
        import json
        
        # Convert metadata dicts to JSON strings for PostgreSQL JSONB
        chunks_with_json = []
        for chunk in chunks:
            doc_id, idx, text, uri, emb, metadata = chunk
            metadata_json = json.dumps(metadata) if metadata else '{}'
            chunks_with_json.append((doc_id, idx, text, uri, emb, metadata_json))
        
        query = """
        INSERT INTO document_chunks 
        (document_id, chunk_index, text_content, source_uri, embedding, metadata)
        VALUES %s
        """
        
        # Note: metadata is passed as JSON string and will be cast to JSONB by PostgreSQL
        
        self.db.execute_many(query, chunks_with_json, page_size=batch_size)
        logger.info(f"Inserted {len(chunks)} chunks into database")

        # Optional ANALYZE throttled to avoid blocking hot ingestion
        if self._should_run_analyze():
            try:
                self.db.execute_query("ANALYZE document_chunks")
            except QueryError as exc:
                logger.warning(f"Failed to analyze document_chunks after insert: {exc}")

        return len(chunks)
    
    def get_document_by_id(
        self,
        document_id: str,
        visibility: Optional[Tuple[str, list]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get document metadata by ID.

        Args:
            document_id: Document identifier
            visibility: Optional (sql_fragment, params) visibility filter; a
                document hidden from the caller is reported as not found.

        Returns:
            Document metadata or None if not found (or not visible)
        """
        vis_sql = ""
        vis_params: list = []
        if visibility and visibility[0]:
            vis_sql = f"AND {visibility[0]}"
            vis_params = list(visibility[1])

        query = f"""
        SELECT
            document_id,
            source_uri,
            COUNT(*) as chunk_count,
            MIN(indexed_at) as indexed_at,
            (array_agg(metadata ORDER BY indexed_at ASC))[1] as metadata
        FROM document_chunks
        WHERE document_id = %s {vis_sql}
        GROUP BY document_id, source_uri
        """

        with self.db.get_cursor(dict_cursor=True) as cursor:
            cursor.execute(query, (document_id, *vis_params))
            result = cursor.fetchone()
            return dict(result) if result else None
    
    def document_exists(self, document_id: str) -> bool:
        """
        Check if document exists in database.
        
        Args:
            document_id: Document identifier
            
        Returns:
            True if document exists, False otherwise
        """
        query = "SELECT EXISTS(SELECT 1 FROM document_chunks WHERE document_id = %s)"
        result = self.db.execute_query(query, (document_id,), fetch=True)
        return result[0][0] if result else False
    
    def get_document_chunks_for_reinsert(
        self,
        document_id: str
    ) -> List[Tuple[str, int, str, str, Any, Optional[Dict[str, Any]]]]:
        """
        Fetch all chunks for a document in the insert_chunks() tuple format.

        Used to back up an existing document before a replacement delete, so a
        failed replacement can restore the previous version instead of losing it.

        Args:
            document_id: Document identifier

        Returns:
            List of (document_id, chunk_index, text, source_uri, embedding, metadata)
        """
        query = """
        SELECT document_id, chunk_index, text_content, source_uri, embedding, metadata
        FROM document_chunks
        WHERE document_id = %s
        ORDER BY chunk_index
        """

        with self.db.get_cursor() as cursor:
            cursor.execute(query, (document_id,))
            return [tuple(row) for row in cursor.fetchall()]

    def delete_document(self, document_id: str) -> int:
        """
        Delete all chunks for a document.

        Args:
            document_id: Document identifier

        Returns:
            Number of chunks deleted
        """
        query = "DELETE FROM document_chunks WHERE document_id = %s"
        
        with self.db.get_cursor() as cursor:
            cursor.execute(query, (document_id,))
            deleted_count = cursor.rowcount
            logger.info(f"Deleted {deleted_count} chunks for document {document_id}")
            return deleted_count
    
    def list_documents(
        self,
        limit: int = 100,
        offset: int = 0,
        sort_by: Union[str, Sequence[str]] = "indexed_at",
        sort_dir: Union[str, Sequence[str]] = "desc",
        *,
        source_prefix: Optional[str] = None,
        with_total: bool = False,
        visibility: Optional[Tuple[str, list]] = None
    ) -> Union[List[Dict[str, Any]], Tuple[List[Dict[str, Any]], int]]:
        """
        List indexed documents with optional pagination metadata.

        Args:
            limit: Maximum number of documents to return
            offset: Number of documents to skip
            sort_by: Field(s) to sort by (validated against whitelist)
            sort_dir: Sort direction(s) ('asc' or 'desc')
            source_prefix: If set, filter to documents whose normalized
                source_uri starts with this prefix.  Uses trailing-slash
                semantics (``/docs`` matches ``/docs/file.txt`` but NOT
                ``/docs2/file.txt``).  ``None`` or ``"/"`` means no filter.
            with_total: If True, also return total document count
            visibility: Optional (sql_fragment, params) visibility filter from
                document_visibility, ANDed into the query.

        Returns:
            List of document metadata dictionaries or tuple(items, total)
        """
        allowed_sorts = {
            "indexed_at": "MIN(indexed_at)",
            "last_updated": "MAX(updated_at)",
            "source_uri": "source_uri",
            "document_type": "(array_agg(metadata->>'type' ORDER BY indexed_at ASC))[1]",
            "chunk_count": "COUNT(*)",
            "document_id": "document_id",
        }

        if isinstance(sort_by, str):
            sort_fields = [field.strip() for field in sort_by.split(',') if field.strip()]
        else:
            sort_fields = [field.strip() for field in sort_by if field.strip()]

        if not sort_fields:
            sort_fields = ["indexed_at"]

        if isinstance(sort_dir, str):
            sort_dirs = [direction.strip().lower() for direction in sort_dir.split(',') if direction.strip()]
        else:
            sort_dirs = [direction.strip().lower() for direction in sort_dir if direction.strip()]

        if not sort_dirs:
            sort_dirs = ["desc"]

        if len(sort_dirs) == 1 and len(sort_fields) > 1:
            sort_dirs = sort_dirs * len(sort_fields)

        if len(sort_dirs) != len(sort_fields):
            raise ValueError("sort_dir must provide the same number of entries as sort_by")

        order_clauses: List[str] = []
        for field, direction in zip(sort_fields, sort_dirs):
            if field not in allowed_sorts:
                raise ValueError(f"Invalid sort_by field: {field}")
            if direction not in {"asc", "desc"}:
                raise ValueError(f"Invalid sort_dir: {direction}")
            order_clauses.append(f"{allowed_sorts[field]} {direction.upper()}")

        if not any(clause.startswith("document_id") for clause in order_clauses):
            order_clauses.append("document_id ASC")

        order_by_sql = ", ".join(order_clauses)

        # ---- WHERE filters (source_prefix + visibility) ----------
        # source_prefix None or "/" → no prefix filter (returns all documents)
        where_clauses: List[str] = []
        where_params: list = []
        if source_prefix and source_prefix.rstrip("/") != "":
            norm = _normalize_prefix(source_prefix).rstrip("/")
            where_clauses.append(f"{NORMALIZED_URI_SQL} LIKE %s")
            where_params.append(norm + "/%")
        if visibility and visibility[0]:
            where_clauses.append(visibility[0])
            where_params.extend(visibility[1])
        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        query = f"""
        SELECT
            document_id,
            source_uri,
            COUNT(*) as chunk_count,
            MIN(indexed_at) as indexed_at,
            MAX(updated_at) as last_updated,
            (array_agg(metadata->>'type' ORDER BY indexed_at ASC))[1] as document_type
        FROM document_chunks
        {where_sql}
        GROUP BY document_id, source_uri
        ORDER BY {order_by_sql}
        LIMIT %s OFFSET %s
        """

        with self.db.get_cursor(dict_cursor=True) as cursor:
            cursor.execute(query, (*where_params, limit, offset))
            results = [dict(row) for row in cursor.fetchall()]

        if not with_total:
            return results

        total_query = f"SELECT COUNT(DISTINCT document_id) FROM document_chunks {where_sql}"
        with self.db.get_cursor() as cursor:
            cursor.execute(total_query, tuple(where_params))
            total = cursor.fetchone()[0]

        return results, total
    
    def search_similar(
        self,
        query_embedding: List[float],
        top_k: int = 5,
        distance_metric: str = 'cosine',
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Search for similar chunks using vector similarity.
        
        Args:
            query_embedding: Query vector
            top_k: Number of results to return
            distance_metric: Distance metric ('cosine', 'l2', 'inner_product')
            filters: Optional filters (e.g., {'document_id': 'abc123'})
            
        Returns:
            List of matching chunks with metadata
        """
        # Select distance operator based on metric
        operators = {
            'cosine': '<=>',
            'l2': '<->',
            'inner_product': '<#>'
        }
        operator = operators.get(distance_metric, '<=>')
        
        # Build query with optional filters
        where_clauses = []
        params = []
        
        # Convert embedding to pgvector format string
        embedding_str = '[' + ','.join(map(str, query_embedding)) + ']'
        
        if filters:
            for key, value in filters.items():
                # Support generic metadata JSONB queries
                # Use 'metadata.keyname' syntax for metadata fields
                # OR use bare key names for backward compatibility with common fields
                if key.startswith('metadata.'):
                    # Extract the actual metadata key (e.g., 'metadata.type' -> 'type')
                    metadata_key = key[9:]  # Remove 'metadata.' prefix
                    where_clauses.append(f"metadata->>%s = %s")
                    params.append(metadata_key)
                    params.append(value)
                elif key in ['type', 'namespace', 'category']:
                    # Backward compatibility: bare key names for common metadata fields
                    # Use ILIKE for case-insensitive matching
                    where_clauses.append(f"metadata->>'{key}' ILIKE %s")
                    params.append(value)
                elif key == 'extensions' and isinstance(value, list) and value:
                    # Filter by file extension: OR across all requested extensions.
                    # Each extension is matched case-insensitively at the end of source_uri.
                    ext_clauses = []
                    for ext in value:
                        normalized = ext if ext.startswith('.') else f'.{ext}'
                        ext_clauses.append("source_uri ILIKE %s")
                        params.append(f'%{normalized}')
                    where_clauses.append(f"({' OR '.join(ext_clauses)})")
                elif key == 'excluded_document_ids':
                    if isinstance(value, list) and value:
                        where_clauses.append("document_id != ALL(%s)")
                        params.append(list(value))
                elif key == 'allowed_namespaces':
                    if isinstance(value, list):
                        if value:
                            where_clauses.append("metadata->>'namespace' = ANY(%s)")
                            params.append(list(value))
                        else:
                            # Empty allowlist = access to nothing (fail closed)
                            where_clauses.append("FALSE")
                else:
                    # Direct column match (e.g., document_id, source_uri)
                    where_clauses.append(f"{key} = %s")
                    params.append(value)
        
        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        
        query = f"""
        SELECT 
            chunk_id,
            document_id,
            chunk_index,
            text_content,
            source_uri,
            indexed_at,
            metadata,
            embedding {operator} %s::vector AS distance
        FROM document_chunks
        {where_sql}
        ORDER BY distance
        LIMIT %s
        """
        
        params.insert(0, embedding_str)
        params.append(top_k)
        
        with self.db.get_cursor(dict_cursor=True) as cursor:
            cursor.execute(query, params)
            results = cursor.fetchall()
            return [dict(row) for row in results]

    def get_indexed_extensions(
        self,
        visibility: Optional[Tuple[str, list]] = None
    ) -> List[str]:
        """Return sorted list of distinct file extensions present in the index."""
        vis_sql = ""
        vis_params: list = []
        if visibility and visibility[0]:
            vis_sql = f"AND {visibility[0]}"
            vis_params = list(visibility[1])

        query = f"""
        SELECT DISTINCT
            LOWER(CONCAT('.', (REGEXP_MATCH(source_uri, '\\.([a-zA-Z0-9]{{1,10}})$'))[1])) AS ext
        FROM document_chunks
        WHERE source_uri ~ '\\.([a-zA-Z0-9]{{1,10}})$' {vis_sql}
        ORDER BY ext
        """
        with self.db.get_cursor() as cursor:
            cursor.execute(query, tuple(vis_params) if vis_params else None)
            rows = cursor.fetchall()
        return [row[0] for row in rows if row[0] and row[0] != '.']
    
    def get_statistics(
        self,
        visibility: Optional[Tuple[str, list]] = None
    ) -> Dict[str, Any]:
        """
        Get database statistics.

        Args:
            visibility: Optional (sql_fragment, params) visibility filter;
                document/chunk counts then only cover visible documents.
                Database size stays global (infrastructure metric).

        Returns:
            Dictionary with various statistics
        """
        vis_where = ""
        vis_params: tuple = ()
        if visibility and visibility[0]:
            vis_where = f"WHERE {visibility[0]}"
            vis_params = tuple(visibility[1])

        with self.db.get_cursor() as cursor:
            # Total chunks
            cursor.execute(f"SELECT COUNT(*) FROM document_chunks {vis_where}", vis_params or None)
            total_chunks = cursor.fetchone()[0]

            # Total documents
            cursor.execute(
                f"SELECT COUNT(DISTINCT document_id) FROM document_chunks {vis_where}",
                vis_params or None,
            )
            total_documents = cursor.fetchone()[0]

            # Average chunks per document
            cursor.execute(f"""
                SELECT AVG(chunk_count)::INTEGER
                FROM (
                    SELECT COUNT(*) as chunk_count
                    FROM document_chunks
                    {vis_where}
                    GROUP BY document_id
                ) subq
            """, vis_params or None)
            avg_chunks = cursor.fetchone()[0] or 0
            
            # Database size in bytes
            cursor.execute("""
                SELECT pg_database_size(current_database())
            """)
            db_size_bytes = cursor.fetchone()[0]
            
            return {
                "total_chunks": total_chunks,
                "total_documents": total_documents,
                "avg_chunks_per_document": avg_chunks,
                "database_size_bytes": db_size_bytes
            }
    
    def get_metadata_keys(
        self,
        pattern: Optional[str] = None,
        visibility: Optional[Tuple[str, list]] = None
    ) -> List[str]:
        """
        Get all unique metadata keys across all documents.

        Args:
            pattern: Optional SQL LIKE pattern to filter keys (e.g., 't%' for keys starting with 't')
            visibility: Optional (sql_fragment, params) visibility filter

        Returns:
            List of unique metadata keys
        """
        vis_sql = ""
        vis_params: list = []
        if visibility and visibility[0]:
            vis_sql = f"AND {visibility[0]}"
            vis_params = list(visibility[1])

        # Use subquery to work around set-returning function limitation
        if pattern:
            query = f"""
            SELECT DISTINCT key
            FROM (
                SELECT jsonb_object_keys(metadata) as key
                FROM document_chunks
                WHERE metadata IS NOT NULL AND metadata != '{{}}'::jsonb {vis_sql}
            ) subq
            WHERE key LIKE %s
            ORDER BY key
            """
            params = vis_params + [pattern]
        else:
            query = f"""
            SELECT DISTINCT jsonb_object_keys(metadata) as key
            FROM document_chunks
            WHERE metadata IS NOT NULL AND metadata != '{{}}'::jsonb {vis_sql}
            ORDER BY key
            """
            params = vis_params

        with self.db.get_cursor(dict_cursor=True) as cursor:
            cursor.execute(query, params if params else None)
            results = cursor.fetchall()
            return [row['key'] for row in results]

    def get_metadata_values(
        self,
        key: str,
        limit: int = 100,
        visibility: Optional[Tuple[str, list]] = None
    ) -> List[str]:
        """
        Get all unique values for a specific metadata key.

        Args:
            key: The metadata key to get values for
            limit: Maximum number of values to return
            visibility: Optional (sql_fragment, params) visibility filter

        Returns:
            List of unique values for the key
        """
        vis_sql = ""
        vis_params: list = []
        if visibility and visibility[0]:
            vis_sql = f"AND {visibility[0]}"
            vis_params = list(visibility[1])

        query = f"""
        SELECT DISTINCT metadata->>%s as value
        FROM document_chunks
        WHERE metadata->>%s IS NOT NULL {vis_sql}
        ORDER BY value
        LIMIT %s
        """

        with self.db.get_cursor(dict_cursor=True) as cursor:
            cursor.execute(query, (key, key, *vis_params, limit))
            results = cursor.fetchall()
            return [row['value'] for row in results if row['value']]
    
    def preview_delete(self, filters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Preview what would be deleted with given filters (dry-run).
        
        Args:
            filters: Filter criteria (same format as search_similar)
            
        Returns:
            Dictionary with preview information
        """
        where_clauses = []
        params = []
        
        for key, value in filters.items():
            if key.startswith('metadata.'):
                metadata_key = key[9:]
                where_clauses.append(f"metadata->>%s = %s")
                params.append(metadata_key)
                params.append(value)
            elif key in ['type', 'namespace', 'category']:
                # Skip wildcard value (match all)
                if value == '*':
                    continue
                where_clauses.append(f"metadata->>'{key}' = %s")
                params.append(value)
            elif key == 'source_uri_like':
                # Case-insensitive matching tolerant to Windows backslashes and control characters.
                # Accept both SQL LIKE wildcards and UI glob wildcards (*, ?).
                normalized = self._normalize_source_uri_like(value)
                where_clauses.append(self._source_uri_like_clause())
                params.extend([normalized, normalized, normalized])
            else:
                where_clauses.append(f"{key} = %s")
                params.append(value)
        
        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        
        # Get count and sample documents
        count_query = f"SELECT COUNT(DISTINCT document_id) FROM document_chunks {where_sql}"
        sample_query = f"""
        SELECT document_id,
               source_uri,
               (array_agg(metadata ORDER BY indexed_at ASC))[1] AS metadata
        FROM document_chunks
        {where_sql}
        GROUP BY document_id, source_uri
        LIMIT 10
        """
        
        with self.db.get_cursor(dict_cursor=True) as cursor:
            cursor.execute(count_query, params)
            count = cursor.fetchone()['count']
            
            cursor.execute(sample_query, params)
            samples = cursor.fetchall()
            
            return {
                "document_count": count,
                "sample_documents": [dict(row) for row in samples],
                "filters_applied": filters
            }
    
    def bulk_delete(self, filters: Dict[str, Any]) -> int:
        """
        Delete documents matching the given filters.
        
        Args:
            filters: Filter criteria (same format as search_similar)
            
        Returns:
            Number of chunks deleted
        """
        where_clauses = []
        params = []
        
        for key, value in filters.items():
            if key.startswith('metadata.'):
                metadata_key = key[9:]
                where_clauses.append(f"metadata->>%s = %s")
                params.append(metadata_key)
                params.append(value)
            elif key in ['type', 'namespace', 'category']:
                # Skip wildcard value (match all)
                if value == '*':
                    continue
                where_clauses.append(f"metadata->>'{key}' = %s")
                params.append(value)
            elif key == 'source_uri_like':
                # Case-insensitive matching consistent with preview_delete
                normalized = self._normalize_source_uri_like(value)
                where_clauses.append(self._source_uri_like_clause())
                params.extend([normalized, normalized, normalized])
            else:
                where_clauses.append(f"{key} = %s")
                params.append(value)
        
        if not where_clauses:
            raise ValueError("Filters are required for bulk delete (safety check)")
        
        where_sql = f"WHERE {' AND '.join(where_clauses)}"
        
        # Delete chunks matching the filters
        delete_query = f"DELETE FROM document_chunks {where_sql}"
        
        with self.db.get_cursor() as cursor:
            cursor.execute(delete_query, params)
            deleted_count = cursor.rowcount
            logger.info(f"Bulk deleted {deleted_count} chunks matching filters: {filters}")
            return deleted_count
    
    def export_documents(self, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Export documents matching filters as JSON (for backup before delete).
        
        Args:
            filters: Filter criteria (same format as search_similar)
            
        Returns:
            List of document chunks with all data
        """
        where_clauses = []
        params = []
        
        for key, value in filters.items():
            if key.startswith('metadata.'):
                metadata_key = key[9:]
                where_clauses.append(f"metadata->>%s = %s")
                params.append(metadata_key)
                params.append(value)
            elif key in ['type', 'namespace', 'category']:
                # Skip wildcard value (match all)
                if value == '*':
                    continue
                where_clauses.append(f"metadata->>'{key}' = %s")
                params.append(value)
            elif key == 'source_uri_like':
                # LIKE pattern matching for source_uri
                normalized = self._normalize_source_uri_like(value)
                where_clauses.append(self._source_uri_like_clause())
                params.extend([normalized, normalized, normalized])
            else:
                where_clauses.append(f"{key} = %s")
                params.append(value)
        
        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        
        # Export all chunk data
        query = f"""
        SELECT 
            chunk_id,
            document_id,
            chunk_index,
            text_content,
            source_uri,
            embedding::text as embedding,
            metadata,
            indexed_at
        FROM document_chunks
        {where_sql}
        ORDER BY document_id, chunk_index
        """
        
        with self.db.get_cursor(dict_cursor=True) as cursor:
            cursor.execute(query, params)
            results = cursor.fetchall()
            
            # Convert to serializable format
            export_data = []
            for row in results:
                export_data.append({
                    'chunk_id': row['chunk_id'],
                    'document_id': row['document_id'],
                    'chunk_index': row['chunk_index'],
                    'text_content': row['text_content'],
                    'source_uri': row['source_uri'],
                    'embedding': row['embedding'],
                    'metadata': row['metadata'],
                    'indexed_at': row['indexed_at'].isoformat() if row['indexed_at'] else None
                })
            
            logger.info(f"Exported {len(export_data)} chunks matching filters: {filters}")
            return export_data
    
    def restore_documents(self, backup_data: List[Dict[str, Any]]) -> int:
        """
        Restore documents from backup data.
        
        Args:
            backup_data: List of document chunks from export_documents
            
        Returns:
            Number of chunks restored
        """
        if not backup_data:
            return 0
        
        # Prepare data for insertion
        chunks_to_insert = []
        for chunk in backup_data:
            chunks_to_insert.append((
                chunk['document_id'],
                chunk['chunk_index'],
                chunk['text_content'],
                chunk['source_uri'],
                chunk['embedding'],  # Already in text format from export
                json.dumps(chunk['metadata']) if isinstance(chunk['metadata'], dict) else chunk['metadata']
            ))
        
        # Insert chunks
        query = """
        INSERT INTO document_chunks 
        (document_id, chunk_index, text_content, source_uri, embedding, metadata)
        VALUES %s
        ON CONFLICT (document_id, chunk_index) DO NOTHING
        """
        
        self.db.execute_many(query, chunks_to_insert, page_size=100)
        logger.info(f"Restored {len(chunks_to_insert)} chunks from backup")
        return len(chunks_to_insert)


# Global database manager instance
_db_manager: Optional[DatabaseManager] = None


def get_db_manager() -> DatabaseManager:
    """Get or create global database manager instance."""
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager()
        _db_manager.initialize()
    return _db_manager


def close_db_manager() -> None:
    """Close global database manager."""
    global _db_manager
    if _db_manager:
        _db_manager.close()
        _db_manager = None
