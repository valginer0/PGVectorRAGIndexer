"""
Database connection and operations module.

Provides connection pooling, async support, and common database operations
for the PGVectorRAGIndexer system.
"""

import logging
from contextlib import contextmanager, asynccontextmanager
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime

import psycopg2
from psycopg2 import pool, sql
from psycopg2.extras import execute_values, RealDictCursor
from pgvector.psycopg2 import register_vector

from config import get_config

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
        self._initialized = False
    
    def initialize(self) -> None:
        """Initialize connection pool."""
        if self._initialized:
            logger.warning("Database manager already initialized")
            return
        
        try:
            self._pool = pool.ThreadedConnectionPool(
                minconn=1,
                maxconn=self.config.pool_size,
                host=self.config.host,
                port=self.config.port,
                dbname=self.config.name,
                user=self.config.user,
                password=self.config.password
            )
            self._initialized = True
            logger.info(
                f"Database connection pool initialized "
                f"(host={self.config.host}, db={self.config.name})"
            )
        except Exception as e:
            logger.error(f"Failed to initialize connection pool: {e}")
            raise ConnectionPoolError(f"Connection pool initialization failed: {e}")
    
    def close(self) -> None:
        """Close all connections in the pool."""
        if self._pool:
            self._pool.closeall()
            self._initialized = False
            logger.info("Database connection pool closed")
    
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
        try:
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
                    "timestamp": datetime.utcnow().isoformat()
                }
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }


class DocumentRepository:
    """Repository for document-related database operations."""
    
    def __init__(self, db_manager: DatabaseManager):
        """Initialize repository with database manager."""
        self.db = db_manager
    
    def insert_chunks(
        self,
        chunks: List[Tuple[str, int, str, str, List[float]]],
        batch_size: int = 100
    ) -> int:
        """
        Insert document chunks into database.
        
        Args:
            chunks: List of (document_id, chunk_index, text, source_uri, embedding)
            batch_size: Batch size for insertion
            
        Returns:
            Number of chunks inserted
        """
        query = """
        INSERT INTO document_chunks 
        (document_id, chunk_index, text_content, source_uri, embedding)
        VALUES %s
        """
        
        self.db.execute_many(query, chunks, page_size=batch_size)
        logger.info(f"Inserted {len(chunks)} chunks into database")
        return len(chunks)
    
    def get_document_by_id(self, document_id: str) -> Optional[Dict[str, Any]]:
        """
        Get document metadata by ID.
        
        Args:
            document_id: Document identifier
            
        Returns:
            Document metadata or None if not found
        """
        query = """
        SELECT 
            document_id,
            source_uri,
            COUNT(*) as chunk_count,
            MIN(indexed_at) as indexed_at
        FROM document_chunks
        WHERE document_id = %s
        GROUP BY document_id, source_uri
        """
        
        with self.db.get_cursor(dict_cursor=True) as cursor:
            cursor.execute(query, (document_id,))
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
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        List all indexed documents with metadata.
        
        Args:
            limit: Maximum number of documents to return
            offset: Number of documents to skip
            
        Returns:
            List of document metadata dictionaries
        """
        query = """
        SELECT 
            document_id,
            source_uri,
            COUNT(*) as chunk_count,
            MIN(indexed_at) as indexed_at,
            MAX(indexed_at) as last_updated
        FROM document_chunks
        GROUP BY document_id, source_uri
        ORDER BY indexed_at DESC
        LIMIT %s OFFSET %s
        """
        
        with self.db.get_cursor(dict_cursor=True) as cursor:
            cursor.execute(query, (limit, offset))
            results = cursor.fetchall()
            return [dict(row) for row in results]
    
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
        params = [query_embedding]
        
        if filters:
            for key, value in filters.items():
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
            embedding {operator} %s AS distance
        FROM document_chunks
        {where_sql}
        ORDER BY distance
        LIMIT %s
        """
        
        params.append(top_k)
        
        with self.db.get_cursor(dict_cursor=True) as cursor:
            cursor.execute(query, params)
            results = cursor.fetchall()
            return [dict(row) for row in results]
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get database statistics.
        
        Returns:
            Dictionary with various statistics
        """
        with self.db.get_cursor() as cursor:
            # Total chunks
            cursor.execute("SELECT COUNT(*) FROM document_chunks")
            total_chunks = cursor.fetchone()[0]
            
            # Total documents
            cursor.execute("SELECT COUNT(DISTINCT document_id) FROM document_chunks")
            total_documents = cursor.fetchone()[0]
            
            # Average chunks per document
            cursor.execute("""
                SELECT AVG(chunk_count)::INTEGER
                FROM (
                    SELECT COUNT(*) as chunk_count
                    FROM document_chunks
                    GROUP BY document_id
                ) subq
            """)
            avg_chunks = cursor.fetchone()[0] or 0
            
            # Database size
            cursor.execute("""
                SELECT pg_size_pretty(pg_database_size(current_database()))
            """)
            db_size = cursor.fetchone()[0]
            
            return {
                "total_chunks": total_chunks,
                "total_documents": total_documents,
                "avg_chunks_per_document": avg_chunks,
                "database_size": db_size
            }


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
