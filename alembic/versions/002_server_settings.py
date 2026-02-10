"""Server settings table for server-level configuration

Creates a simple key-value store for server settings like
owner_client_id and cached license information.

Revision ID: 002
Revises: 001
Create Date: 2026-02-09

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '002'
down_revision: Union[str, None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create server_settings key-value table."""

    # Create server_settings table
    op.execute('''
        CREATE TABLE IF NOT EXISTS server_settings (
            key TEXT PRIMARY KEY,
            value JSONB NOT NULL DEFAULT '{}',
            updated_at TIMESTAMP DEFAULT NOW()
        )
    ''')

    # Reuse existing trigger function for updated_at
    op.execute(
        'DROP TRIGGER IF EXISTS update_server_settings_updated_at '
        'ON server_settings'
    )
    op.execute('''
        CREATE TRIGGER update_server_settings_updated_at
            BEFORE UPDATE ON server_settings
            FOR EACH ROW
            EXECUTE FUNCTION update_updated_at_column()
    ''')


def downgrade() -> None:
    """Remove server_settings table."""
    op.execute(
        'DROP TRIGGER IF EXISTS update_server_settings_updated_at '
        'ON server_settings'
    )
    op.execute('DROP TABLE IF EXISTS server_settings')
