"""011 – SAML sessions table for SSO/SAML authentication.

Revision ID: 011
Revises: 010
Create Date: 2026-02-10

Adds a saml_sessions table to track active SAML sessions.
Foundation for #16 Enterprise Foundations (Phase 2 – Okta SSO).
"""

from alembic import op

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS saml_sessions (
            id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            session_index TEXT,
            name_id TEXT NOT NULL,
            name_id_format TEXT,
            idp_entity_id TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at TIMESTAMPTZ NOT NULL,
            is_active BOOLEAN NOT NULL DEFAULT true
        );

        CREATE INDEX IF NOT EXISTS idx_saml_sessions_user_id ON saml_sessions (user_id);
        CREATE INDEX IF NOT EXISTS idx_saml_sessions_name_id ON saml_sessions (name_id);
        CREATE INDEX IF NOT EXISTS idx_saml_sessions_expires ON saml_sessions (expires_at);
    """)


def downgrade():
    op.execute("""DROP TABLE IF EXISTS saml_sessions;""")
