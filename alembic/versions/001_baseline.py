"""Baseline schema - matches init-db.sql v2.4

Creates the initial document_chunks table, indexes, trigger,
and document_stats view. Uses IF NOT EXISTS throughout so this
migration is safe to run on existing databases that were set up
via init-db.sql.

Revision ID: 001
Revises: None
Create Date: 2026-02-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create baseline schema matching init-db.sql."""

    # 1. Enable required extensions
    # env.py uses AUTOCOMMIT mode so these are committed immediately
    # before subsequent statements use the VECTOR type
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')
    op.execute('CREATE EXTENSION IF NOT EXISTS pg_trgm')

    # 2. Create the core document_chunks table
    op.execute('''
        CREATE TABLE IF NOT EXISTS document_chunks (
            chunk_id BIGSERIAL PRIMARY KEY,
            document_id TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            text_content TEXT NOT NULL,
            source_uri TEXT NOT NULL,
            embedding VECTOR(384),
            metadata JSONB DEFAULT '{}',
            indexed_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(document_id, chunk_index)
        )
    ''')

    # 3. Create HNSW index for vector search
    op.execute('''
        CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw
        ON document_chunks USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    ''')

    # 4. Create standard indexes
    op.execute(
        'CREATE INDEX IF NOT EXISTS idx_chunks_document_id '
        'ON document_chunks(document_id)'
    )
    op.execute(
        'CREATE INDEX IF NOT EXISTS idx_chunks_source_uri '
        'ON document_chunks(source_uri)'
    )
    op.execute(
        'CREATE INDEX IF NOT EXISTS idx_chunks_indexed_at '
        'ON document_chunks(indexed_at DESC)'
    )

    # 5. Create GIN index for full-text search
    op.execute('''
        CREATE INDEX IF NOT EXISTS idx_chunks_text_search
        ON document_chunks USING gin(to_tsvector('english', text_content))
    ''')

    # 6. Create GIN index for metadata JSONB queries
    op.execute(
        'CREATE INDEX IF NOT EXISTS idx_chunks_metadata '
        'ON document_chunks USING gin(metadata)'
    )

    # 7. Create updated_at trigger function
    op.execute('''
        CREATE OR REPLACE FUNCTION update_updated_at_column()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    ''')

    # 8. Create trigger (drop first to avoid duplicate errors)
    op.execute(
        'DROP TRIGGER IF EXISTS update_document_chunks_updated_at '
        'ON document_chunks'
    )
    op.execute('''
        CREATE TRIGGER update_document_chunks_updated_at
            BEFORE UPDATE ON document_chunks
            FOR EACH ROW
            EXECUTE FUNCTION update_updated_at_column()
    ''')

    # 9. Create document_stats view
    op.execute('''
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
        GROUP BY document_id, source_uri
    ''')


def downgrade() -> None:
    """Remove baseline schema.

    WARNING: This drops ALL data. Only use in development.
    """
    op.execute('DROP VIEW IF EXISTS document_stats')
    op.execute(
        'DROP TRIGGER IF EXISTS update_document_chunks_updated_at '
        'ON document_chunks'
    )
    op.execute('DROP FUNCTION IF EXISTS update_updated_at_column()')
    op.execute('DROP TABLE IF EXISTS document_chunks CASCADE')
