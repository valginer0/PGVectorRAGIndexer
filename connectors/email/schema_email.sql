-- Email Chunks Schema (Provider-Agnostic)
-- This table stores indexed email content for semantic search.
-- Provider-specific fields (e.g., folder names) follow each provider's conventions.

CREATE TABLE IF NOT EXISTS email_chunks (
    id SERIAL PRIMARY KEY,
    
    -- Email identification
    message_id VARCHAR(255) NOT NULL,
    thread_id VARCHAR(255),
    
    -- Metadata
    sender VARCHAR(500),
    recipient TEXT,
    subject VARCHAR(1000),
    received_at TIMESTAMP WITH TIME ZONE,
    folder VARCHAR(255),
    
    -- Content
    chunk_index INTEGER NOT NULL DEFAULT 0,
    text_content TEXT NOT NULL,
    embedding vector(384),
    
    -- Provider tracking (gmail, outlook, imap, etc.)
    provider VARCHAR(50),
    
    -- Timestamps and metadata
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    -- Unique constraint for idempotency
    UNIQUE(message_id, chunk_index)
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_email_chunks_message_id ON email_chunks(message_id);
CREATE INDEX IF NOT EXISTS idx_email_chunks_received_at ON email_chunks(received_at DESC);
CREATE INDEX IF NOT EXISTS idx_email_chunks_provider ON email_chunks(provider);
CREATE INDEX IF NOT EXISTS idx_email_chunks_folder ON email_chunks(folder);
