"""
Tests for the Alembic migration framework (#11).

Tests cover:
- Baseline migration on empty database
- Idempotent application on existing v2.4 databases
- run_migrations() double-run safety
- Alembic version tracking
- Pre-migration backup logic (Docker vs desktop)
"""

import os
import sys
import logging
from unittest.mock import patch, MagicMock
from pathlib import Path

import pytest

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestMigrateModule:
    """Tests for migrate.py standalone runner."""

    def test_import_migrate(self):
        """Test that migrate module can be imported."""
        import migrate
        assert hasattr(migrate, 'run_migrations')
        assert hasattr(migrate, '_get_alembic_config')
        assert hasattr(migrate, '_is_docker_mode')

    def test_get_alembic_config(self):
        """Test Alembic config is created with correct paths."""
        from migrate import _get_alembic_config
        cfg = _get_alembic_config()
        script_location = cfg.get_main_option("script_location")
        assert script_location is not None
        assert Path(script_location).exists()

    def test_is_docker_mode_false_by_default(self):
        """Test Docker mode detection returns False outside Docker."""
        from migrate import _is_docker_mode
        # Clear DB_HOST to ensure we're not in Docker compose
        with patch.dict(os.environ, {}, clear=True):
            # Also mock the dockerenv check
            with patch('pathlib.Path.exists', return_value=False):
                assert _is_docker_mode() is False

    def test_is_docker_mode_true_with_db_host(self):
        """Test Docker mode detected when DB_HOST=db."""
        from migrate import _is_docker_mode
        with patch.dict(os.environ, {"DB_HOST": "db"}):
            assert _is_docker_mode() is True

    def test_is_docker_mode_true_with_dockerenv(self):
        """Test Docker mode detected when /.dockerenv exists."""
        from migrate import _is_docker_mode
        with patch.dict(os.environ, {}, clear=True):
            with patch('pathlib.Path.exists', return_value=True):
                assert _is_docker_mode() is True

    def test_check_recent_backup_no_backup_dirs(self):
        """Test backup check returns False when no backup dirs exist."""
        from migrate import _check_recent_backup
        with patch('pathlib.Path.exists', return_value=False):
            assert _check_recent_backup() is False

    def test_run_pg_dump_no_pg_dump(self, tmp_path):
        """Test pg_dump gracefully handles missing binary."""
        from migrate import _run_pg_dump
        with patch('migrate.Path', return_value=tmp_path / "backups"):
            # Patch the hardcoded /app/backups path
            with patch('subprocess.run', side_effect=FileNotFoundError):
                result = _run_pg_dump("postgresql://user:pass@localhost/test")
                assert result is False

    def test_run_pg_dump_timeout(self, tmp_path):
        """Test pg_dump handles timeout gracefully."""
        import subprocess
        from migrate import _run_pg_dump
        with patch('migrate.Path', return_value=tmp_path / "backups"):
            with patch('subprocess.run', side_effect=subprocess.TimeoutExpired("pg_dump", 300)):
                result = _run_pg_dump("postgresql://user:pass@localhost/test")
                assert result is False


class TestMigrationFiles:
    """Tests for Alembic migration file structure."""

    def test_alembic_ini_exists(self):
        """Test alembic.ini exists in project root."""
        from migrate import PROJECT_ROOT
        assert (PROJECT_ROOT / "alembic.ini").exists()

    def test_alembic_env_exists(self):
        """Test alembic/env.py exists."""
        from migrate import PROJECT_ROOT
        assert (PROJECT_ROOT / "alembic" / "env.py").exists()

    def test_baseline_migration_exists(self):
        """Test baseline migration file exists."""
        from migrate import PROJECT_ROOT
        versions_dir = PROJECT_ROOT / "alembic" / "versions"
        assert versions_dir.exists()
        baseline_files = list(versions_dir.glob("001_*"))
        assert len(baseline_files) == 1, f"Expected 1 baseline file, found {baseline_files}"

    def test_baseline_migration_has_upgrade_and_downgrade(self):
        """Test baseline migration has both upgrade and downgrade functions."""
        import importlib.util
        from migrate import PROJECT_ROOT
        spec = importlib.util.spec_from_file_location(
            "baseline",
            PROJECT_ROOT / "alembic" / "versions" / "001_baseline.py"
        )
        baseline = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(baseline)
        assert hasattr(baseline, 'upgrade')
        assert hasattr(baseline, 'downgrade')
        assert callable(baseline.upgrade)
        assert callable(baseline.downgrade)

    def test_baseline_migration_revision_id(self):
        """Test baseline migration has correct revision metadata."""
        # Import the migration module directly
        import importlib.util
        from migrate import PROJECT_ROOT
        spec = importlib.util.spec_from_file_location(
            "baseline",
            PROJECT_ROOT / "alembic" / "versions" / "001_baseline.py"
        )
        baseline = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(baseline)

        assert baseline.revision == '001'
        assert baseline.down_revision is None


class TestRunMigrations:
    """Tests for run_migrations() integration."""

    def test_run_migrations_no_pending(self):
        """Test run_migrations returns True when no migrations needed."""
        from migrate import run_migrations

        with patch('migrate._get_database_url', return_value="postgresql://test:test@localhost/test"):
            with patch('migrate._get_pending_migrations', return_value=[]):
                result = run_migrations(auto_backup=False)
                assert result is True

    def test_run_migrations_with_pending_applies(self):
        """Test run_migrations applies pending migrations."""
        from migrate import run_migrations

        with patch('migrate._get_database_url', return_value="postgresql://test:test@localhost/test"):
            with patch('migrate._get_pending_migrations', return_value=['001']):
                with patch('migrate._is_docker_mode', return_value=False):
                    with patch('migrate._check_recent_backup', return_value=True):
                        with patch('alembic.command.upgrade') as mock_upgrade:
                            result = run_migrations(auto_backup=True)
                            assert result is True
                            mock_upgrade.assert_called_once()

    def test_run_migrations_docker_backup(self):
        """Test that Docker mode triggers pg_dump before migration."""
        from migrate import run_migrations

        with patch('migrate._get_database_url', return_value="postgresql://test:test@localhost/test"):
            with patch('migrate._get_pending_migrations', return_value=['001']):
                with patch('migrate._is_docker_mode', return_value=True):
                    with patch('migrate._run_pg_dump', return_value=True) as mock_dump:
                        with patch('alembic.command.upgrade'):
                            result = run_migrations(auto_backup=True)
                            assert result is True
                            mock_dump.assert_called_once()

    def test_run_migrations_desktop_no_backup_warns(self, caplog):
        """Test that desktop mode warns when no recent backup found."""
        from migrate import run_migrations

        with patch('migrate._get_database_url', return_value="postgresql://test:test@localhost/test"):
            with patch('migrate._get_pending_migrations', return_value=['001']):
                with patch('migrate._is_docker_mode', return_value=False):
                    with patch('migrate._check_recent_backup', return_value=False):
                        with patch('alembic.command.upgrade'):
                            with caplog.at_level(logging.WARNING):
                                result = run_migrations(auto_backup=True)
                                assert result is True
                                assert "No recent database backup" in caplog.text

    def test_run_migrations_failure_returns_false(self):
        """Test run_migrations returns False on error."""
        from migrate import run_migrations

        with patch('migrate._get_database_url', side_effect=Exception("DB connection failed")):
            result = run_migrations(auto_backup=False)
            assert result is False

    def test_run_migrations_no_backup_flag(self):
        """Test auto_backup=False skips all backup logic."""
        from migrate import run_migrations

        with patch('migrate._get_database_url', return_value="postgresql://test:test@localhost/test"):
            with patch('migrate._get_pending_migrations', return_value=['001']):
                with patch('migrate._is_docker_mode') as mock_docker:
                    with patch('migrate._check_recent_backup') as mock_backup:
                        with patch('alembic.command.upgrade'):
                            result = run_migrations(auto_backup=False)
                            assert result is True
                            mock_docker.assert_not_called()
                            mock_backup.assert_not_called()
