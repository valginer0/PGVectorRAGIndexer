#!/usr/bin/env python3
"""
Seed the demo database with sample documents.

Connects directly to the Neon PostgreSQL database, generates embeddings
locally, and inserts sample documents so the hosted demo has data to search.

Usage:
    python scripts/seed_demo.py

Requires environment variables (or .env):
    DB_HOST, POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB, DB_PORT, DB_SSLMODE
"""

import hashlib
import json
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

import psycopg2
from psycopg2.extras import execute_values
from sentence_transformers import SentenceTransformer

# ---------------------------------------------------------------------------
# Sample documents — diverse topics to showcase search capabilities
# ---------------------------------------------------------------------------

SAMPLE_DOCUMENTS = [
    {
        "title": "Getting Started with PGVectorRAGIndexer",
        "source_uri": "docs/getting-started.md",
        "content": [
            "PGVectorRAGIndexer is a powerful document indexing and retrieval system that uses PostgreSQL with pgvector for semantic search. It processes documents, splits them into chunks, generates vector embeddings, and stores them for fast similarity search.",
            "To get started, you need PostgreSQL with the pgvector extension installed. The system supports multiple document formats including PDF, Word documents, text files, markdown, spreadsheets, and web pages.",
            "The indexing pipeline works in three stages: first, documents are loaded and parsed using format-specific loaders. Second, the text is split into overlapping chunks using recursive character splitting. Third, each chunk is encoded into a 384-dimensional vector using the all-MiniLM-L6-v2 sentence transformer model.",
            "Search queries are processed the same way — your query text is encoded into a vector, then PostgreSQL finds the most similar document chunks using cosine similarity via the HNSW index. This enables semantic search where results match by meaning, not just keywords.",
            "The system includes a REST API built with FastAPI, a desktop application for local document management, and supports both local and remote deployment configurations.",
        ],
    },
    {
        "title": "Understanding Vector Embeddings",
        "source_uri": "docs/vector-embeddings.md",
        "content": [
            "Vector embeddings are numerical representations of text that capture semantic meaning. When two pieces of text have similar meanings, their embedding vectors will be close together in the vector space, even if they use completely different words.",
            "PGVectorRAGIndexer uses the all-MiniLM-L6-v2 model from Sentence Transformers to generate 384-dimensional embeddings. This model offers an excellent balance between quality and speed, making it suitable for both real-time search and batch indexing.",
            "The pgvector extension for PostgreSQL provides native vector storage and similarity search. It supports multiple distance metrics including cosine similarity, L2 (Euclidean) distance, and inner product. PGVectorRAGIndexer uses cosine similarity by default.",
            "HNSW (Hierarchical Navigable Small World) indexes dramatically speed up vector search. Instead of comparing your query against every stored vector, HNSW builds a graph structure that enables approximate nearest neighbor search in logarithmic time.",
            "Embedding caching is built into the system — if you search for the same query twice, the cached embedding is reused instead of re-encoding. This significantly improves response times for repeated or similar queries.",
        ],
    },
    {
        "title": "Document Processing Pipeline",
        "source_uri": "docs/document-processing.md",
        "content": [
            "The document processing pipeline handles multiple file formats through specialized loaders. PDF files are processed using pypdf for text extraction, with optional OCR support via Tesseract for scanned documents. Word documents (.docx) use python-docx, while spreadsheets are handled by openpyxl and pandas.",
            "Text splitting uses LangChain's RecursiveCharacterTextSplitter, which intelligently breaks text at natural boundaries like paragraphs, sentences, and words. The default chunk size is 1000 characters with 200 characters of overlap to maintain context across chunk boundaries.",
            "Each document is assigned a unique ID based on the SHA-256 hash of its source URI. This ensures consistent identification across re-indexing operations. File content hashes are also tracked to detect changes — unchanged files are automatically skipped during re-indexing.",
            "Metadata is preserved throughout the pipeline. Each chunk retains information about its source document, page number (for PDFs), file type, file size, and any custom metadata provided during indexing. This metadata is stored as JSONB in PostgreSQL for flexible querying.",
            "The pipeline supports OCR in three modes: 'auto' (detect and OCR scanned documents), 'only' (process only image-based files), and 'skip' (disable OCR entirely). This flexibility allows users to optimize processing based on their document types.",
        ],
    },
    {
        "title": "API Reference and Authentication",
        "source_uri": "docs/api-reference.md",
        "content": [
            "The REST API is built with FastAPI and provides endpoints for document indexing, search, and management. All endpoints are versioned under /api/v1/ and return JSON responses. Interactive API documentation is available at /docs (Swagger UI) and /redoc.",
            "Authentication uses API keys stored securely in the database. Keys can be created, rotated, and revoked through the API. Each key has a name, optional expiration date, and permission scopes. Loopback requests (from localhost) bypass authentication for local development convenience.",
            "The search endpoint POST /api/v1/search accepts a query string and optional parameters: top_k (number of results, default 5), threshold (minimum similarity score), and document_id (filter to specific document). Results include the matched text, similarity score, source document, and metadata.",
            "Document management endpoints include GET /api/v1/documents for listing indexed documents with pagination and sorting, GET /api/v1/documents/{id} for document details, and DELETE /api/v1/documents/{id} for removal. The POST /api/v1/index endpoint accepts both URIs and file uploads.",
            "Health monitoring is available at GET /health, which reports the status of the database connection, embedding model, and overall system health. The GET /api/v1/stats endpoint provides aggregate statistics including total documents, chunks, and database size.",
        ],
    },
    {
        "title": "Retrieval-Augmented Generation (RAG) Concepts",
        "source_uri": "docs/rag-concepts.md",
        "content": [
            "Retrieval-Augmented Generation (RAG) is a technique that enhances large language model responses by providing relevant context from a knowledge base. Instead of relying solely on the LLM's training data, RAG retrieves pertinent documents and includes them in the prompt.",
            "The RAG pipeline has two main phases: retrieval and generation. During retrieval, the user's question is converted to a vector embedding and used to find the most relevant document chunks. During generation, these chunks are provided as context to the LLM along with the original question.",
            "PGVectorRAGIndexer handles the retrieval phase of RAG. It indexes your documents, stores their embeddings, and provides fast semantic search. The retrieved chunks can then be passed to any LLM — OpenAI GPT, Anthropic Claude, local models like Llama, or any other provider.",
            "Chunking strategy significantly impacts RAG quality. Chunks that are too small may lack context, while chunks that are too large may dilute the relevant information. The default 1000-character chunks with 200-character overlap provide a good balance for most use cases.",
            "Hybrid search combines semantic similarity with keyword matching for better results. When a query has an exact match in the database, it's returned first. Otherwise, the system falls back to semantic search. This ensures both precise lookups and fuzzy meaning-based retrieval work well.",
        ],
    },
    {
        "title": "Deployment and Configuration Guide",
        "source_uri": "docs/deployment-guide.md",
        "content": [
            "PGVectorRAGIndexer can be deployed using Docker, docker-compose, or directly on a host system. The Docker setup includes a pre-configured PostgreSQL instance with pgvector, making it the easiest way to get started. Production deployments should use a managed PostgreSQL service like Neon, AWS RDS, or Azure Database.",
            "Configuration is managed through environment variables and a config.yaml file. Key settings include database connection parameters, embedding model selection, chunking parameters, API host/port, and authentication requirements. Environment variables take precedence over config file values.",
            "For production deployments, enable authentication by setting API_REQUIRE_AUTH=true and creating API keys. Configure SSL for database connections using DB_SSLMODE=require when connecting to cloud PostgreSQL providers. Set appropriate resource limits based on your document volume.",
            "The desktop application connects to the API server and provides a graphical interface for document management, search, and configuration. It supports both local (same machine) and remote server connections, with automatic discovery of local instances.",
            "Database migrations are managed by Alembic and run automatically on startup. The migration system supports upgrades across multiple versions, ensuring smooth updates. Always back up your database before major version upgrades.",
        ],
    },
    {
        "title": "Security Best Practices",
        "source_uri": "docs/security.md",
        "content": [
            "API key authentication should be enabled for any deployment accessible over a network. Create separate API keys for different clients and services, and set expiration dates for temporary access. Revoke compromised keys immediately through the API or database.",
            "Database connections should use SSL/TLS encryption, especially for cloud-hosted databases. Set DB_SSLMODE=require in your configuration to enforce encrypted connections. Never expose database credentials in client-side code or public repositories.",
            "The API server should be bound to 127.0.0.1 (localhost) unless remote access is specifically needed. If binding to 0.0.0.0 (all interfaces), always enable authentication. The system logs a security warning when it detects an open binding without authentication.",
            "Document visibility controls allow restricting which users can see which documents. This is useful in multi-tenant environments where different teams or departments should only access their own documents. Visibility rules are enforced at the database query level.",
            "Audit logging tracks all API operations including document indexing, searches, deletions, and authentication events. Logs include timestamps, user identification, and operation details. Regular log review helps detect unauthorized access or unusual patterns.",
        ],
    },
    {
        "title": "Performance Tuning and Optimization",
        "source_uri": "docs/performance.md",
        "content": [
            "The HNSW index parameters m and ef_construction control the trade-off between index build time, search speed, and recall accuracy. The defaults (m=16, ef_construction=64) work well for most datasets. Increase ef_construction for better recall at the cost of slower index building.",
            "Batch indexing is significantly faster than indexing documents one at a time. The system processes embeddings in batches and uses PostgreSQL's execute_values for efficient bulk insertion. For large document collections, use the batch indexing API or command-line tools.",
            "Connection pooling is managed automatically using psycopg2's connection pool. The pool size is configurable and defaults to a minimum of 2 and maximum of 10 connections. Adjust these values based on your concurrent query load.",
            "Embedding cache reduces redundant computation for repeated queries. The cache stores recently computed embeddings in memory and reuses them for identical query strings. Cache size is configurable and can be disabled if memory is constrained.",
            "For large databases (millions of chunks), consider partitioning the document_chunks table by document type or date range. PostgreSQL's native partitioning combined with pgvector indexes on each partition can significantly improve query performance.",
        ],
    },
]


def get_db_connection():
    """Connect to the Neon database using environment variables."""
    conn = psycopg2.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        port=int(os.environ.get("DB_PORT", "5432")),
        user=os.environ.get("POSTGRES_USER", "postgres"),
        password=os.environ.get("POSTGRES_PASSWORD", "postgres"),
        dbname=os.environ.get("POSTGRES_DB", "pgvectorrag"),
        sslmode=os.environ.get("DB_SSLMODE", "prefer"),
    )
    conn.autocommit = True
    return conn


def generate_document_id(source_uri: str) -> str:
    """Generate document ID matching the app's logic."""
    return hashlib.sha256(source_uri.encode()).hexdigest()[:16]


def seed():
    """Seed the demo database with sample documents."""
    print("Loading embedding model (all-MiniLM-L6-v2)...")
    model = SentenceTransformer("all-MiniLM-L6-v2")

    print(f"Connecting to database at {os.environ.get('DB_HOST', 'localhost')}...")
    conn = get_db_connection()
    cur = conn.cursor()

    total_chunks = 0

    for doc in SAMPLE_DOCUMENTS:
        doc_id = generate_document_id(doc["source_uri"])
        source_uri = doc["source_uri"]
        title = doc["title"]

        # Check if already seeded
        cur.execute(
            "SELECT COUNT(*) FROM document_chunks WHERE document_id = %s", (doc_id,)
        )
        existing = cur.fetchone()[0]
        if existing > 0:
            print(f"  ⏭  {title} — already seeded ({existing} chunks), skipping")
            total_chunks += existing
            continue

        print(f"  📄 {title} ({len(doc['content'])} chunks)")

        # Generate embeddings
        embeddings = model.encode(doc["content"], normalize_embeddings=True)

        # Prepare rows
        rows = []
        for i, (text, emb) in enumerate(zip(doc["content"], embeddings)):
            metadata = json.dumps(
                {
                    "document_id": doc_id,
                    "source_uri": source_uri,
                    "title": title,
                    "file_type": ".md",
                    "chunk_count": len(doc["content"]),
                    "demo_sample": True,
                }
            )
            rows.append(
                (doc_id, i, text, source_uri, emb.tolist(), metadata)
            )

        # Insert
        execute_values(
            cur,
            """
            INSERT INTO document_chunks
                (document_id, chunk_index, text_content, source_uri, embedding, metadata)
            VALUES %s
            ON CONFLICT (document_id, chunk_index) DO NOTHING
            """,
            rows,
            template="(%s, %s, %s, %s, %s::vector, %s::jsonb)",
        )
        total_chunks += len(rows)
        print(f"     ✓ Inserted {len(rows)} chunks")

    cur.close()
    conn.close()

    print(f"\nDone! Seeded {len(SAMPLE_DOCUMENTS)} documents, {total_chunks} total chunks.")
    print("The demo is ready for search queries.")


if __name__ == "__main__":
    seed()
