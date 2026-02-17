"""014 – Canonical identity, lock key migration, and P1 fixes.

Revision ID: 014
Revises: 013
Create Date: 2026-02-17

Phase 6b.2:
  1. P1 fix: add UNIQUE constraint on watched_folders.root_id
  2. P1 fix: correct normalized_folder_path backfill
     (013 used LOWER() unconditionally; runtime only lowercases on Windows)
  3. Add canonical_source_key column to document_chunks
  4. Add root_id + relative_path columns to document_locks
"""

from alembic import op

# revision identifiers
revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade():
    # ------------------------------------------------------------------ #
    # P1 Fix 1: root_id must be globally unique                           #
    # ------------------------------------------------------------------ #
    # Guard: deduplicate any root_id collisions (extremely unlikely but
    # prevents the ALTER from failing).
    op.execute("""
        UPDATE watched_folders wf
        SET root_id = gen_random_uuid()
        FROM (
            SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER (PARTITION BY root_id ORDER BY created_at) rn
                FROM watched_folders
            ) sub WHERE rn > 1
        ) dupes
        WHERE wf.id = dupes.id;
    """)

    op.execute("""
        ALTER TABLE watched_folders
            ADD CONSTRAINT uq_watched_folders_root_id UNIQUE (root_id);
    """)

    # ------------------------------------------------------------------ #
    # P1 Fix 2: correct normalized_folder_path backfill                   #
    # ------------------------------------------------------------------ #
    # Migration 013 used LOWER() unconditionally, but runtime normalize
    # only lowercases on Windows.  Re-normalize without LOWER() so the
    # stored value matches what runtime code produces on Linux/macOS.
    # This is safe: no new rows use LOWER() since runtime was always
    # case-preserving on non-Windows.  The unique indexes will prevent
    # conflicts.
    op.execute("""
        UPDATE watched_folders
        SET normalized_folder_path = RTRIM(
            REGEXP_REPLACE(folder_path, '/+', '/', 'g'),
            '/'
        )
        WHERE normalized_folder_path != RTRIM(
            REGEXP_REPLACE(folder_path, '/+', '/', 'g'),
            '/'
        );
    """)

    # ------------------------------------------------------------------ #
    # 1. canonical_source_key on document_chunks                          #
    # ------------------------------------------------------------------ #
    op.execute("""
        ALTER TABLE document_chunks
            ADD COLUMN IF NOT EXISTS canonical_source_key TEXT NULL;
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_chunks_canonical_key
            ON document_chunks (canonical_source_key)
            WHERE canonical_source_key IS NOT NULL;
    """)

    # ------------------------------------------------------------------ #
    # 2. root_id + relative_path on document_locks                        #
    # ------------------------------------------------------------------ #
    op.execute("""
        ALTER TABLE document_locks
            ADD COLUMN IF NOT EXISTS root_id UUID NULL,
            ADD COLUMN IF NOT EXISTS relative_path TEXT NULL;
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_locks_root_path
            ON document_locks (root_id, relative_path)
            WHERE root_id IS NOT NULL;
    """)


def downgrade():
    # Drop lock columns
    op.execute("DROP INDEX IF EXISTS idx_locks_root_path;")
    op.execute("""
        ALTER TABLE document_locks
            DROP COLUMN IF EXISTS relative_path,
            DROP COLUMN IF EXISTS root_id;
    """)

    # Drop canonical key
    op.execute("DROP INDEX IF EXISTS idx_chunks_canonical_key;")
    op.execute("""
        ALTER TABLE document_chunks
            DROP COLUMN IF EXISTS canonical_source_key;
    """)

    # Re-lowercase normalized paths (restore 013 behavior)
    op.execute("""
        UPDATE watched_folders
        SET normalized_folder_path = LOWER(RTRIM(folder_path, '/'));
    """)

    # Drop root_id unique constraint
    op.execute("""
        ALTER TABLE watched_folders
            DROP CONSTRAINT IF EXISTS uq_watched_folders_root_id;
    """)
