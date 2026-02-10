"""003 – API keys table for remote authentication.

Revision ID: 003
Revises: 002
Create Date: 2026-02-10

Stores hashed API keys for authenticating remote clients.
Full keys are never stored — only SHA-256 hashes.
"""

from alembic import op

# revision identifiers
revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('''
        CREATE TABLE IF NOT EXISTS api_keys (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            key_hash TEXT NOT NULL UNIQUE,
            key_prefix TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW(),
            last_used_at TIMESTAMP,
            revoked_at TIMESTAMP,
            expires_at TIMESTAMP
        )
    ''')

    # Index for fast lookup by hash (only active keys)
    op.execute('''
        CREATE INDEX IF NOT EXISTS idx_api_keys_hash
        ON api_keys (key_hash)
        WHERE revoked_at IS NULL
    ''')

    # Index for listing active keys
    op.execute('''
        CREATE INDEX IF NOT EXISTS idx_api_keys_active
        ON api_keys (created_at DESC)
        WHERE revoked_at IS NULL
    ''')


def downgrade() -> None:
    op.execute('DROP INDEX IF EXISTS idx_api_keys_active')
    op.execute('DROP INDEX IF EXISTS idx_api_keys_hash')
    op.execute('DROP TABLE IF EXISTS api_keys')
