"""018 – SCIM Groups mapping table.

Maps IdP groups to PGVectorRAGIndexer roles for SCIM 2.0 Group
provisioning (RFC 7643 §4.2).  Each row represents one IdP group
and the internal role it maps to.

Revision ID: 018
Revises: 017
"""

from alembic import op

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS scim_groups (
            id           TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
            external_id  TEXT UNIQUE,
            display_name TEXT NOT NULL UNIQUE,
            role_name    TEXT NOT NULL REFERENCES roles(name) ON UPDATE CASCADE,
            created_at   TIMESTAMPTZ DEFAULT now(),
            updated_at   TIMESTAMPTZ DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS idx_scim_groups_role
            ON scim_groups (role_name);
        CREATE INDEX IF NOT EXISTS idx_scim_groups_external_id
            ON scim_groups (external_id);
        """
    )


def downgrade():
    op.execute("DROP TABLE IF EXISTS scim_groups")
