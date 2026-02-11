"""012 – Document visibility and ownership for per-user scoping.

Revision ID: 012
Revises: 011
Create Date: 2026-02-10

Adds owner_id and visibility columns to document_chunks for
per-user document visibility (#3 Phase 2).

- owner_id: FK to users(id), nullable (NULL = system/shared)
- visibility: 'shared' (default) or 'private'
- Existing documents remain shared (backward compatible).
"""

from alembic import op

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE document_chunks
            ADD COLUMN IF NOT EXISTS owner_id TEXT REFERENCES users(id) ON DELETE SET NULL,
            ADD COLUMN IF NOT EXISTS visibility TEXT NOT NULL DEFAULT 'shared';

        CREATE INDEX IF NOT EXISTS idx_chunks_owner_id ON document_chunks (owner_id);
        CREATE INDEX IF NOT EXISTS idx_chunks_visibility ON document_chunks (visibility);
    """)

    # Must drop and recreate view — CREATE OR REPLACE cannot add columns
    op.execute("DROP VIEW IF EXISTS document_stats")
    op.execute("""
        CREATE VIEW document_stats AS
        SELECT
            document_id,
            source_uri,
            COUNT(*) as chunk_count,
            MIN(indexed_at) as first_indexed,
            MAX(updated_at) as last_updated,
            jsonb_object_agg(
                COALESCE(metadata->>'file_type', 'unknown'),
                1
            ) as metadata_summary,
            (array_agg(owner_id))[1] as owner_id,
            (array_agg(visibility))[1] as visibility
        FROM document_chunks
        GROUP BY document_id, source_uri
    """)


def downgrade():
    # Must drop view first — it references the columns we're about to drop
    op.execute("DROP VIEW IF EXISTS document_stats")

    op.execute("""
        DROP INDEX IF EXISTS idx_chunks_visibility;
        DROP INDEX IF EXISTS idx_chunks_owner_id;
        ALTER TABLE document_chunks
            DROP COLUMN IF EXISTS visibility,
            DROP COLUMN IF EXISTS owner_id;
    """)

    # Restore original view without owner_id/visibility
    op.execute("""
        CREATE VIEW document_stats AS
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
    """)
