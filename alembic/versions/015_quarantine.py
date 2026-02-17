"""015 – Quarantine Delete Lifecycle (Phase 6b.3).

Adds soft-delete / quarantine support to document_chunks so that
stale documents can be quarantined before permanent deletion.

Revision ID: 015
Revises: 014
"""

from alembic import op

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade():
    # -- quarantined_at: timestamp when chunk was quarantined  ---------------
    op.execute(
        "ALTER TABLE document_chunks "
        "ADD COLUMN IF NOT EXISTS quarantined_at TIMESTAMPTZ NULL"
    )

    # -- quarantine_reason: human-readable reason  ---------------------------
    op.execute(
        "ALTER TABLE document_chunks "
        "ADD COLUMN IF NOT EXISTS quarantine_reason TEXT NULL"
    )

    # -- Partial index: only quarantined rows, keeps normal queries fast  ----
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_chunks_quarantined "
        "ON document_chunks (quarantined_at) "
        "WHERE quarantined_at IS NOT NULL"
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS idx_chunks_quarantined")
    op.execute("ALTER TABLE document_chunks DROP COLUMN IF EXISTS quarantine_reason")
    op.execute("ALTER TABLE document_chunks DROP COLUMN IF EXISTS quarantined_at")
