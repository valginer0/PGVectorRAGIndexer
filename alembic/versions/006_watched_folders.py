"""006 – Watched folders for scheduled automatic indexing.

Revision ID: 006
Revises: 005
Create Date: 2026-02-10

Stores folder paths that the system monitors for changes and
automatically indexes on a schedule.  Foundation for #6 Scheduled
Automatic Indexing.
"""

from alembic import op

# revision identifiers
revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS watched_folders (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            folder_path TEXT NOT NULL,
            enabled BOOLEAN NOT NULL DEFAULT true,
            schedule_cron TEXT NOT NULL DEFAULT '0 */6 * * *',
            last_scanned_at TIMESTAMPTZ,
            last_run_id UUID REFERENCES indexing_runs(id) ON DELETE SET NULL,
            client_id TEXT REFERENCES clients(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            metadata JSONB DEFAULT '{}'::jsonb
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_watched_folders_path
            ON watched_folders (folder_path);

        CREATE INDEX IF NOT EXISTS idx_watched_folders_enabled
            ON watched_folders (enabled) WHERE enabled = true;

        CREATE INDEX IF NOT EXISTS idx_watched_folders_client
            ON watched_folders (client_id);
    """)


def downgrade():
    op.execute("""DROP TABLE IF EXISTS watched_folders;""")
