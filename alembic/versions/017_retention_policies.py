"""017 – Retention policies table.

Stores per-category retention overrides so admins can configure
retention periods at runtime via the API.

Empty table = use env-var or coded defaults.  Rows are upserted on
first PUT /retention/{category}.

Revision ID: 017
Revises: 016
"""

from alembic import op

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS retention_policies (
            category       TEXT PRIMARY KEY,
            retention_days INTEGER NOT NULL,
            updated_at     TIMESTAMPTZ DEFAULT now()
        )
        """
    )


def downgrade():
    op.execute("DROP TABLE IF EXISTS retention_policies")
