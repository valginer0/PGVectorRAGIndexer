-- This script runs once when the Docker container starts

-- 1. Enable required extensions
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;  -- For full-text search support

-- 2. Define the core table structure for storing vectorized document chunks
CREATE TABLE IF NOT EXISTS document_chunks (
    chunk_id BIGSERIAL PRIMARY KEY,
    document_id TEXT NOT NULL,          -- Identifier for the original document (e.g., hash or file path)
    chunk_index INTEGER NOT NULL,       -- Order of the chunk in the original document
    text_content TEXT NOT NULL,         -- The actual text chunk used for embedding (the content)
    source_uri TEXT NOT NULL,           -- The document's original address (local path, URL, etc.)
    embedding VECTOR(384),              -- The vector representation (384 dimensions for all-MiniLM-L6-v2)
    metadata JSONB DEFAULT '{}',        -- Additional metadata (file type, size, tags, etc.)
    indexed_at TIMESTAMP DEFAULT NOW(), -- When the chunk was indexed
    updated_at TIMESTAMP DEFAULT NOW(), -- Last update timestamp
    UNIQUE(document_id, chunk_index)    -- Prevent duplicate chunks
);

-- 3. Create indexes for fast Approximate Nearest Neighbor (ANN) search
-- HNSW is highly recommended for performance in RAG applications
CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw 
ON document_chunks USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);

-- 4. Create indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_chunks_document_id ON document_chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_source_uri ON document_chunks(source_uri);
CREATE INDEX IF NOT EXISTS idx_chunks_indexed_at ON document_chunks(indexed_at DESC);

-- 5. Create GIN index for full-text search on text_content
CREATE INDEX IF NOT EXISTS idx_chunks_text_search 
ON document_chunks USING gin(to_tsvector('english', text_content));

-- 6. Create GIN index for metadata JSONB queries
CREATE INDEX IF NOT EXISTS idx_chunks_metadata ON document_chunks USING gin(metadata);

-- 7. Create function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 8. Create trigger to automatically update updated_at
DROP TRIGGER IF EXISTS update_document_chunks_updated_at ON document_chunks;
CREATE TRIGGER update_document_chunks_updated_at
    BEFORE UPDATE ON document_chunks
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- 9. Create view for document statistics
CREATE OR REPLACE VIEW document_stats AS
SELECT 
    document_id,
    source_uri,
    COUNT(*) as chunk_count,
    MIN(indexed_at) as first_indexed,
    MAX(updated_at) as last_updated,
    jsonb_object_agg(
        COALESCE(metadata->>'file_type', 'unknown'),
        1
    ) as metadata_summary
FROM document_chunks
GROUP BY document_id, source_uri;
