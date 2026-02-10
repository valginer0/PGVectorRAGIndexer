"""005 – Clients table and client_id on indexing_runs.

Revision ID: 005
Revises: 004
Create Date: 2026-02-10

Introduces explicit client identity so the server can track which
desktop performed scans and uploads.  Foundation for #8 Client Identity
and Sync, and prerequisite for #6 Scheduled Indexing, #9 Path Mapping,
#3 Multi-User, and #10 Activity Log.
"""

from alembic import op

# revision identifiers
revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS clients (
            id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            os_type TEXT NOT NULL DEFAULT 'unknown',
            app_version TEXT,
            last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE INDEX IF NOT EXISTS idx_clients_last_seen
            ON clients (last_seen_at DESC);

        ALTER TABLE indexing_runs
            ADD COLUMN IF NOT EXISTS client_id TEXT
            REFERENCES clients(id) ON DELETE SET NULL;

        CREATE INDEX IF NOT EXISTS idx_indexing_runs_client
            ON indexing_runs (client_id);
    """)


def downgrade():
    op.execute("""
        ALTER TABLE indexing_runs DROP COLUMN IF EXISTS client_id;
        DROP TABLE IF EXISTS clients;
    """)
