"""008 – Activity and audit log.

Revision ID: 008
Revises: 007
Create Date: 2026-02-10

Tracks who indexed what and when for trust and debugging.
Foundation for #10 Activity and Audit Log.
"""

from alembic import op

# revision identifiers
revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS activity_log (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            ts TIMESTAMPTZ NOT NULL DEFAULT now(),
            client_id TEXT REFERENCES clients(id) ON DELETE SET NULL,
            user_id TEXT,
            action TEXT NOT NULL,
            details JSONB DEFAULT '{}'::jsonb
        );

        CREATE INDEX IF NOT EXISTS idx_activity_log_ts
            ON activity_log (ts DESC);

        CREATE INDEX IF NOT EXISTS idx_activity_log_client
            ON activity_log (client_id);

        CREATE INDEX IF NOT EXISTS idx_activity_log_action
            ON activity_log (action);
    """)


def downgrade():
    op.execute("""DROP TABLE IF EXISTS activity_log;""")
