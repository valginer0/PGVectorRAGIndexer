"""019 - Fix document_stats view array_agg

Revision ID: 019
Revises: 018
Create Date: 2026-04-07

Fixes non-deterministic array_agg functions in the document_stats view.
"""

from alembic import op

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None

def upgrade():
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
            (array_agg(owner_id ORDER BY indexed_at ASC))[1] as owner_id,
            (array_agg(visibility ORDER BY indexed_at ASC))[1] as visibility
        FROM document_chunks
        GROUP BY document_id, source_uri
    """)

def downgrade():
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
