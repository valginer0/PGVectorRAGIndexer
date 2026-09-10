"""The first-run schema wipe, and the guards that now prevent it.

On 2026-09-10 a brand-new install was found to destroy its own schema on first
start:

  1. migrate.py sees every migration pending and writes a pre-migration
     pg_dump — of an empty database, a few hundred bytes of schema and nothing
     else.
  2. Migrations run. document_chunks exists and is empty, which is correct.
  3. detect_data_loss saw "a backup exists" and "document_chunks has 0 rows"
     and called it data loss.
  4. restore_from_pg_dump DROPPED the database and restored the empty dump.

The database ended with no tables at all, and /health called it healthy.

The guard's premise — "fresh installs have no backups, so no false positives" —
was true of a user's backups and false of the one the system writes itself,
seconds earlier, in the same startup.
"""

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from auto_recovery import backup_contains_rows, detect_data_loss, restore_from_pg_dump


# A faithful reduction of what pg_dump emits for an EMPTY database: real
# schema, a COPY header for the table, and the terminator with nothing between
# them. The dump that triggered the live bug was 721 bytes of exactly this
# shape.
EMPTY_DUMP = textwrap.dedent("""\
    --
    -- PostgreSQL database dump
    --
    SET statement_timeout = 0;
    CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;

    CREATE TABLE public.document_chunks (
        id bigint NOT NULL,
        document_id text
    );

    COPY public.document_chunks (id, document_id) FROM stdin;
    \\.

    --
    -- PostgreSQL database dump complete
    --
    """)

POPULATED_DUMP = EMPTY_DUMP.replace(
    "COPY public.document_chunks (id, document_id) FROM stdin;\n\\.",
    "COPY public.document_chunks (id, document_id) FROM stdin;\n"
    "1\tdoc_a\n"
    "2\tdoc_b\n"
    "\\.",
)

INSERT_DUMP = EMPTY_DUMP.replace(
    "COPY public.document_chunks (id, document_id) FROM stdin;\n\\.",
    "INSERT INTO public.document_chunks (id, document_id) VALUES (1, 'doc_a');",
)


def _write(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / name
    p.write_text(body)
    return p


class TestBackupContainsRows:
    def test_empty_dump_has_no_rows(self, tmp_path):
        """The whole bug in one assertion.

        The file exists, is named like a backup, and has a complete schema in
        it. Only its contents distinguish it from a real backup.
        """
        assert backup_contains_rows(_write(tmp_path, "pre_migrate_1.sql", EMPTY_DUMP)) is False

    def test_populated_copy_dump_has_rows(self, tmp_path):
        assert backup_contains_rows(_write(tmp_path, "auto_backup_1.sql", POPULATED_DUMP)) is True

    def test_insert_style_dump_has_rows(self, tmp_path):
        """pg_dump --inserts produces INSERT statements rather than COPY."""
        assert backup_contains_rows(_write(tmp_path, "auto_backup_2.sql", INSERT_DUMP)) is True

    def test_schema_only_file_has_no_rows(self, tmp_path):
        assert backup_contains_rows(_write(tmp_path, "auto_backup_3.sql", "CREATE TABLE x (id int);\n")) is False

    def test_unreadable_file_is_not_treated_as_populated(self, tmp_path):
        """Unreadable is not the same as full, and must not authorise a restore."""
        assert backup_contains_rows(tmp_path / "does_not_exist.sql") is False

    def test_rows_in_a_later_table_still_count(self, tmp_path):
        """A dump whose first COPY block is empty but which holds data further in."""
        body = EMPTY_DUMP + textwrap.dedent("""\
            COPY public.documents (id) FROM stdin;
            42
            \\.
            """)
        assert backup_contains_rows(_write(tmp_path, "auto_backup_4.sql", body)) is True


class TestDetectDataLoss:
    def test_fresh_install_with_only_a_pre_migrate_dump_is_not_data_loss(self, tmp_path):
        """The live failure, reproduced.

        The only backup present is the empty one this startup just wrote. The
        function must return False WITHOUT consulting the database: the backup
        alone settles it, and getting as far as a connection would mean the
        rowless dump had already been accepted as evidence of prior data.
        """
        _write(tmp_path, "pre_migrate_20260910_181954.sql", EMPTY_DUMP)

        import sqlalchemy

        # Track the call rather than raising from it. detect_data_loss wraps its
        # database work in `except Exception: return False`, so an exception
        # raised here would be swallowed and the test would pass with the fix
        # reverted — which is exactly what happened on the first attempt.
        engine_calls = []

        def _record(*a, **k):
            engine_calls.append(a)
            return MagicMock()

        with patch.object(sqlalchemy, "create_engine", _record):
            result = detect_data_loss("postgresql://u:p@db:5432/rag", tmp_path)

        assert result is False
        assert engine_calls == [], (
            "detect_data_loss reached the database; the rowless backup should "
            "have settled it first"
        )

    def test_no_backups_at_all_is_not_data_loss(self, tmp_path):
        assert detect_data_loss("postgresql://u:p@db:5432/rag", tmp_path) is False


class TestRestoreRefusesToDestroy:
    def test_rowless_backup_is_refused_before_the_database_is_touched(self, tmp_path):
        """The safety net, independent of detection.

        restore_from_pg_dump DROPs the target database before restoring. A dump
        with no rows cannot put anything back, so running it could only ever
        destroy. Nothing may be executed at all.
        """
        backup = _write(tmp_path, "pre_migrate_1.sql", EMPTY_DUMP)

        # Again: assert on what was CALLED, not on a raised error.
        # restore_from_pg_dump ends in `except Exception: return False`, so a
        # raising mock would make this pass even with the guard removed.
        with patch("auto_recovery.subprocess.run") as run:
            result = restore_from_pg_dump("postgresql://u:p@db:5432/rag", backup)

        assert result is False
        assert not run.called, (
            "restore ran a command for a rowless dump; the first thing it does "
            "is DROP DATABASE, so this destroys data to restore nothing"
        )

    def test_populated_backup_is_allowed_to_proceed(self, tmp_path):
        """The guard must not block a real restore, which is the point of it."""
        backup = _write(tmp_path, "auto_backup_1.sql", POPULATED_DUMP)
        calls = []

        class _Result:
            returncode = 0
            stdout = "5"
            stderr = ""

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return _Result()

        with patch("auto_recovery.subprocess.run", side_effect=fake_run):
            assert restore_from_pg_dump("postgresql://u:p@db:5432/rag", backup) is True

        joined = " ".join(" ".join(c) for c in calls)
        assert "DROP DATABASE" in joined, "a real restore should still drop and recreate"
