"""010 – Users table for RBAC and enterprise auth.

Revision ID: 010
Revises: 009
Create Date: 2026-02-10

Adds a users table with role-based access control.
Foundation for #16 Enterprise Foundations (Phase 1).
"""

from alembic import op

# revision identifiers
revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
            email TEXT UNIQUE,
            display_name TEXT,
            role TEXT NOT NULL DEFAULT 'user',
            auth_provider TEXT NOT NULL DEFAULT 'api_key',
            api_key_id INTEGER REFERENCES api_keys(id) ON DELETE SET NULL,
            client_id TEXT REFERENCES clients(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_login_at TIMESTAMPTZ,
            is_active BOOLEAN NOT NULL DEFAULT true
        );

        CREATE INDEX IF NOT EXISTS idx_users_email ON users (email);
        CREATE INDEX IF NOT EXISTS idx_users_role ON users (role);
        CREATE INDEX IF NOT EXISTS idx_users_api_key_id ON users (api_key_id);
    """)


def downgrade():
    op.execute("""DROP TABLE IF EXISTS users;""")
