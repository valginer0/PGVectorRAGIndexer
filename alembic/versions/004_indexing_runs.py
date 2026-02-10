"""004 – Indexing runs table for health dashboard.

Revision ID: 004
Revises: 003
Create Date: 2026-02-10

Tracks each indexing operation: when it ran, how many files were
processed, and any errors encountered. Foundation for #4 Health
Dashboard and future features (#6, #7, #10).
"""

from alembic import op

# revision identifiers
revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS indexing_runs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            completed_at TIMESTAMPTZ,
            status TEXT NOT NULL DEFAULT 'running'
                CHECK (status IN ('running', 'success', 'partial', 'failed')),
            trigger TEXT NOT NULL DEFAULT 'manual'
                CHECK (trigger IN ('manual', 'upload', 'cli', 'scheduled', 'api')),
            files_scanned INT NOT NULL DEFAULT 0,
            files_added INT NOT NULL DEFAULT 0,
            files_updated INT NOT NULL DEFAULT 0,
            files_skipped INT NOT NULL DEFAULT 0,
            files_failed INT NOT NULL DEFAULT 0,
            errors JSONB DEFAULT '[]'::jsonb,
            source_uri TEXT,
            metadata JSONB DEFAULT '{}'::jsonb
        );

        CREATE INDEX IF NOT EXISTS idx_indexing_runs_started
            ON indexing_runs (started_at DESC);

        CREATE INDEX IF NOT EXISTS idx_indexing_runs_status
            ON indexing_runs (status);
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE IF EXISTS indexing_runs;
    """)
