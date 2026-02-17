"""013 – Server-first automation profile for watched folders.

Revision ID: 013
Revises: 012
Create Date: 2026-02-17

Extends watched_folders with execution scope, executor identity,
normalized paths, scan watermarks, and failure tracking.
Foundation for #6b Server-First Automation.
"""

from alembic import op

# revision identifiers
revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade():
    # ------------------------------------------------------------------ #
    # 1. Add new columns                                                  #
    # ------------------------------------------------------------------ #
    op.execute("""
        ALTER TABLE watched_folders
            ADD COLUMN IF NOT EXISTS execution_scope TEXT NOT NULL DEFAULT 'client',
            ADD COLUMN IF NOT EXISTS executor_id TEXT NULL,
            ADD COLUMN IF NOT EXISTS normalized_folder_path TEXT NOT NULL DEFAULT '',
            ADD COLUMN IF NOT EXISTS root_id UUID NOT NULL DEFAULT gen_random_uuid(),
            ADD COLUMN IF NOT EXISTS last_scan_started_at TIMESTAMPTZ NULL,
            ADD COLUMN IF NOT EXISTS last_scan_completed_at TIMESTAMPTZ NULL,
            ADD COLUMN IF NOT EXISTS last_successful_scan_at TIMESTAMPTZ NULL,
            ADD COLUMN IF NOT EXISTS last_error_at TIMESTAMPTZ NULL,
            ADD COLUMN IF NOT EXISTS consecutive_failures INT NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS paused BOOLEAN NOT NULL DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS max_concurrency INT NOT NULL DEFAULT 1;
    """)

    # ------------------------------------------------------------------ #
    # 2. Backfill existing rows                                           #
    # ------------------------------------------------------------------ #
    op.execute("""
        UPDATE watched_folders
        SET
            execution_scope = 'client',
            executor_id = client_id,
            normalized_folder_path = LOWER(RTRIM(folder_path, '/'))
        WHERE normalized_folder_path = '' OR normalized_folder_path IS NULL;
    """)

    # ------------------------------------------------------------------ #
    # 3. CHECK constraint for scope/executor invariant                    #
    # ------------------------------------------------------------------ #
    op.execute("""
        ALTER TABLE watched_folders
            ADD CONSTRAINT chk_scope_executor CHECK (
                (execution_scope = 'client' AND executor_id IS NOT NULL)
                OR
                (execution_scope = 'server' AND executor_id IS NULL)
            );
    """)

    # Also restrict execution_scope values
    op.execute("""
        ALTER TABLE watched_folders
            ADD CONSTRAINT chk_execution_scope_values CHECK (
                execution_scope IN ('client', 'server')
            );
    """)

    # ------------------------------------------------------------------ #
    # 4. Replace global unique path index with scoped indexes             #
    # ------------------------------------------------------------------ #
    op.execute("DROP INDEX IF EXISTS idx_watched_folders_path;")

    # Client scope: unique per executor + normalized path
    op.execute("""
        CREATE UNIQUE INDEX idx_wf_client_path
            ON watched_folders (executor_id, normalized_folder_path)
            WHERE execution_scope = 'client';
    """)

    # Server scope: unique normalized path (no executor)
    op.execute("""
        CREATE UNIQUE INDEX idx_wf_server_path
            ON watched_folders (normalized_folder_path)
            WHERE execution_scope = 'server';
    """)

    # Composite indexes for scheduler queries
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_wf_scope_enabled_cron
            ON watched_folders (execution_scope, enabled, schedule_cron);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_wf_scope_paused_enabled
            ON watched_folders (execution_scope, paused, enabled);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_wf_root_scope
            ON watched_folders (root_id, execution_scope);
    """)


def downgrade():
    # Drop new indexes
    op.execute("DROP INDEX IF EXISTS idx_wf_root_scope;")
    op.execute("DROP INDEX IF EXISTS idx_wf_scope_paused_enabled;")
    op.execute("DROP INDEX IF EXISTS idx_wf_scope_enabled_cron;")
    op.execute("DROP INDEX IF EXISTS idx_wf_server_path;")
    op.execute("DROP INDEX IF EXISTS idx_wf_client_path;")

    # Restore global unique path index
    op.execute("""
        CREATE UNIQUE INDEX idx_watched_folders_path
            ON watched_folders (folder_path);
    """)

    # Drop constraints
    op.execute("ALTER TABLE watched_folders DROP CONSTRAINT IF EXISTS chk_execution_scope_values;")
    op.execute("ALTER TABLE watched_folders DROP CONSTRAINT IF EXISTS chk_scope_executor;")

    # Drop new columns
    op.execute("""
        ALTER TABLE watched_folders
            DROP COLUMN IF EXISTS max_concurrency,
            DROP COLUMN IF EXISTS paused,
            DROP COLUMN IF EXISTS consecutive_failures,
            DROP COLUMN IF EXISTS last_error_at,
            DROP COLUMN IF EXISTS last_successful_scan_at,
            DROP COLUMN IF EXISTS last_scan_completed_at,
            DROP COLUMN IF EXISTS last_scan_started_at,
            DROP COLUMN IF EXISTS root_id,
            DROP COLUMN IF EXISTS normalized_folder_path,
            DROP COLUMN IF EXISTS executor_id,
            DROP COLUMN IF EXISTS execution_scope;
    """)
