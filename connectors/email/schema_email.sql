-- Email Chunks Schema (Provider-Agnostic)
-- This table stores indexed email content for semantic search.
-- Follows the same pattern as document_chunks: source_uri is the locator.

-- Ensure pgvector extension is available
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS email_chunks (
    id SERIAL PRIMARY KEY,
    
    -- Email identification
    message_id VARCHAR(255) NOT NULL,
    thread_id VARCHAR(255),
    
    -- Locator (like source_uri for documents)
    -- Format: <Provider>/<Folder>/<Subject> (<Sender>, <YYYY-MM-DD>)
    -- Example: Gmail/Inbox/Re: licensing question (Vitaly, 2026-01-02)
    source_uri TEXT NOT NULL,
    
    -- Content
    chunk_index INTEGER NOT NULL DEFAULT 0,
    text_content TEXT NOT NULL,
    embedding vector(384),
    
    -- Timestamps and metadata
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    -- Unique constraint for idempotency
    UNIQUE(message_id, chunk_index)
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_email_chunks_message_id ON email_chunks(message_id);
CREATE INDEX IF NOT EXISTS idx_email_chunks_source_uri ON email_chunks(source_uri);
CREATE INDEX IF NOT EXISTS idx_email_chunks_created_at ON email_chunks(created_at DESC);
