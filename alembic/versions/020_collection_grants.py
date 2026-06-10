"""020 – Role-based collection grants for document-set access control.

Revision ID: 020
Revises: 019
Create Date: 2026-06-09

Adds role_collection_grants: a role may be granted read access to document
collections (the existing metadata ``namespace`` dimension).

Semantics (enforced in collection_grants.py, not in the DB):
- A role with NO grant rows is unrestricted (backward compatible — grants
  are opt-in per role).
- A role with grant rows sees only documents whose namespace is granted.
- namespace '*' grants access to all documents (incl. ones without a
  namespace).
"""

from alembic import op

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS role_collection_grants (
            role TEXT NOT NULL,
            namespace TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (role, namespace)
        );

        CREATE INDEX IF NOT EXISTS idx_collection_grants_role
            ON role_collection_grants (role);
    """)


def downgrade():
    op.execute("DROP TABLE IF EXISTS role_collection_grants")
