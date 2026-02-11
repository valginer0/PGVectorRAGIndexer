"""009 – Document locks for conflict-safe multi-user indexing.

Revision ID: 009
Revises: 008
Create Date: 2026-02-10

Prevents two clients from indexing the same document simultaneously.
Locks have a TTL and auto-expire if a client dies.
Foundation for #3 Multi-User Support (Phase 1).
"""

from alembic import op

# revision identifiers
revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS document_locks (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            source_uri TEXT NOT NULL,
            client_id TEXT REFERENCES clients(id) ON DELETE CASCADE,
            locked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at TIMESTAMPTZ NOT NULL DEFAULT (now() + interval '10 minutes'),
            lock_reason TEXT DEFAULT 'indexing'
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_document_locks_source_uri
            ON document_locks (source_uri);

        CREATE INDEX IF NOT EXISTS idx_document_locks_expires
            ON document_locks (expires_at);
    """)


def downgrade():
    op.execute("""DROP TABLE IF EXISTS document_locks;""")
