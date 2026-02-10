"""007 – Virtual roots for path mapping across clients.

Revision ID: 007
Revises: 006
Create Date: 2026-02-10

Maps named virtual roots to local paths per client, enabling
cross-platform path resolution in remote/multi-user setups.
Foundation for #9 Path Mapping / Virtual Roots.
"""

from alembic import op

# revision identifiers
revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS virtual_roots (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name TEXT NOT NULL,
            client_id TEXT REFERENCES clients(id) ON DELETE CASCADE,
            local_path TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE(name, client_id)
        );

        CREATE INDEX IF NOT EXISTS idx_virtual_roots_name
            ON virtual_roots (name);

        CREATE INDEX IF NOT EXISTS idx_virtual_roots_client
            ON virtual_roots (client_id);
    """)


def downgrade():
    op.execute("""DROP TABLE IF EXISTS virtual_roots;""")
