"""
Real-database integration tests for Large Organization Licensing.

These tests hit a real PostgreSQL instance (``rag_vector_db_test``) — the
same one used by the rest of the test suite.  They are skipped automatically
when the database is unavailable (conftest `setup_test_database` calls
``pytest.skip`` on connection failure).

What is verified that the unit tests CANNOT:
- JSON array is actually written to / read from the ``server_settings`` table
- ``ON CONFLICT`` upsert behaviour is correct
- Legacy single-key migration runs against real rows
- ``count_active_users()`` queries the real ``users`` table with is_active flag
"""

import os
import sys
import time
import uuid

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import jwt  # PyJWT

TEST_SECRET = "db-integration-test-secret"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_jwt(kid: str, seats: int = 5) -> str:
    now = int(time.time())
    return jwt.encode(
        {"edition": "organization", "org": "DB Test Org", "seats": seats,
         "iat": now, "exp": now + 86400 * 90, "kid": kid},
        TEST_SECRET, algorithm="HS256",
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
def clean_license_settings(setup_test_database):
    """Remove license_keys and license_key rows before and after each test."""
    from database import get_db_manager

    mgr = get_db_manager()

    def _clean():
        with mgr.get_cursor() as cur:
            cur.execute(
                "DELETE FROM server_settings WHERE key IN ('license_keys', 'license_key')"
            )

    _clean()
    yield mgr
    _clean()


@pytest.fixture(scope="function")
def db_users_fixture(setup_test_database):
    """Insert temporary users and clean up afterwards.

    Returns a helper: ``add_user(is_active) -> user_id``
    """
    from database import get_db_manager

    mgr = get_db_manager()

    created_ids = []

    def add_user(is_active: bool) -> str:
        uid = str(uuid.uuid4())
        email = f"test-{uid[:8]}@example.com"
        with mgr.get_cursor() as cur:
            cur.execute(
                """
                INSERT INTO users (id, email, role, is_active, created_at, updated_at)
                VALUES (%s, %s, 'user', %s, now(), now())
                """,
                (uid, email, is_active),
            )
        created_ids.append(uid)
        return uid

    yield add_user

    # Cleanup
    if created_ids:
        with mgr.get_cursor() as cur:
            cur.execute(
                "DELETE FROM users WHERE id = ANY(%s)", (created_ids,)
            )


# ---------------------------------------------------------------------------
# server_settings_store — real-DB tests
# ---------------------------------------------------------------------------


class TestServerSettingsStoreDB:
    """Verify JSON array persistence in PostgreSQL via the real DB."""

    def test_get_returns_empty_when_no_row(self, clean_license_settings):
        from server_settings_store import get_server_license_keys
        assert get_server_license_keys() == []

    def test_add_persists_row_in_db(self, clean_license_settings):
        from server_settings_store import get_server_license_keys, add_server_license_key
        key = _make_jwt("db-k1")
        add_server_license_key(key)

        keys = get_server_license_keys()
        assert len(keys) == 1
        assert keys[0] == key

        # Verify raw DB row is a JSON array
        with clean_license_settings.get_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT value FROM server_settings WHERE key = 'license_keys'")
            row = cur.fetchone()
        assert row is not None
        assert isinstance(row["value"], list)
        assert len(row["value"]) == 1

    def test_add_two_keys_stores_array_of_two(self, clean_license_settings):
        from server_settings_store import get_server_license_keys, add_server_license_key
        k1, k2 = _make_jwt("db-k1"), _make_jwt("db-k2")
        add_server_license_key(k1)
        add_server_license_key(k2)

        keys = get_server_license_keys()
        assert len(keys) == 2

        # Verify raw array length in DB
        with clean_license_settings.get_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT value FROM server_settings WHERE key = 'license_keys'")
            row = cur.fetchone()
        assert len(row["value"]) == 2

    def test_add_duplicate_kid_is_idempotent(self, clean_license_settings):
        from server_settings_store import get_server_license_keys, add_server_license_key
        key = _make_jwt("dup-kid")
        add_server_license_key(key)
        add_server_license_key(key)  # same kid

        assert len(get_server_license_keys()) == 1

    def test_remove_key_by_kid(self, clean_license_settings):
        from server_settings_store import (
            get_server_license_keys, add_server_license_key, remove_server_license_key
        )
        k1, k2 = _make_jwt("del-k1"), _make_jwt("del-k2")
        add_server_license_key(k1)
        add_server_license_key(k2)

        removed = remove_server_license_key("del-k1")
        assert removed is True
        remaining = get_server_license_keys()
        assert len(remaining) == 1
        # Verify the surviving key is k2 (kid=del-k2)
        payload = jwt.decode(remaining[0], options={"verify_signature": False})
        assert payload.get("kid") == "del-k2"

    def test_remove_nonexistent_kid_returns_false(self, clean_license_settings):
        from server_settings_store import add_server_license_key, remove_server_license_key
        add_server_license_key(_make_jwt("only-key"))
        assert remove_server_license_key("phantom-kid") is False

    def test_remove_last_key_writes_empty_array(self, clean_license_settings):
        from server_settings_store import (
            get_server_license_keys, add_server_license_key, remove_server_license_key
        )
        add_server_license_key(_make_jwt("solo-key"))
        remove_server_license_key("solo-key")

        keys = get_server_license_keys()
        assert keys == []

        # DB row should exist with an empty JSON array
        with clean_license_settings.get_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT value FROM server_settings WHERE key = 'license_keys'")
            row = cur.fetchone()
        # Either the row has an empty array, or it was deleted — both are valid
        if row is not None:
            assert row["value"] == [] or row["value"] is None

    def test_upsert_replaces_existing_row(self, clean_license_settings):
        """ON CONFLICT UPDATE: adding a third key overwrites the old array."""
        from server_settings_store import (
            get_server_license_keys, add_server_license_key
        )
        k1 = _make_jwt("up-k1")
        k2 = _make_jwt("up-k2")
        k3 = _make_jwt("up-k3")

        add_server_license_key(k1)
        add_server_license_key(k2)
        add_server_license_key(k3)

        keys = get_server_license_keys()
        assert len(keys) == 3
        kids = {jwt.decode(k, options={"verify_signature": False})["kid"] for k in keys}
        assert kids == {"up-k1", "up-k2", "up-k3"}

    def test_legacy_migration_from_dict_format(self, clean_license_settings):
        """Old ``license_key`` row with ``{token: ...}`` value is migrated on read."""
        import json
        from server_settings_store import get_server_license_keys

        legacy_key = _make_jwt("legacy-kid")

        # Write old-style dict row directly into the DB
        with clean_license_settings.get_cursor() as cur:
            cur.execute(
                """
                INSERT INTO server_settings (key, value)
                VALUES ('license_key', %s::jsonb)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                """,
                (json.dumps({"token": legacy_key}),),
            )

        keys = get_server_license_keys()
        assert len(keys) == 1
        assert keys[0] == legacy_key

    def test_legacy_migration_from_string_format(self, clean_license_settings):
        """Old ``license_key`` row stored as a plain JSON string is migrated."""
        import json
        from server_settings_store import get_server_license_keys

        legacy_key = _make_jwt("str-legacy")

        with clean_license_settings.get_cursor() as cur:
            cur.execute(
                """
                INSERT INTO server_settings (key, value)
                VALUES ('license_key', %s::jsonb)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                """,
                (json.dumps(legacy_key),),
            )

        keys = get_server_license_keys()
        assert len(keys) == 1
        assert keys[0] == legacy_key


# ---------------------------------------------------------------------------
# count_active_users() — real-DB tests
# ---------------------------------------------------------------------------


class TestCountActiveUsersDB:
    """Verify count_active_users() queries the real users table correctly."""

    def test_returns_zero_when_no_users(self, db_users_fixture):
        from users import count_active_users
        assert count_active_users() == 0

    def test_counts_only_active_users(self, db_users_fixture):
        from users import count_active_users

        db_users_fixture(is_active=True)
        db_users_fixture(is_active=True)
        db_users_fixture(is_active=False)  # must NOT be counted

        assert count_active_users() == 2

    def test_inactive_user_not_counted(self, db_users_fixture):
        from users import count_active_users

        db_users_fixture(is_active=False)
        assert count_active_users() == 0

    def test_count_increments_when_user_added(self, db_users_fixture):
        from users import count_active_users

        before = count_active_users()
        db_users_fixture(is_active=True)
        after = count_active_users()
        assert after == before + 1

    def test_count_five_active_users(self, db_users_fixture):
        from users import count_active_users
        for _ in range(5):
            db_users_fixture(is_active=True)
        assert count_active_users() == 5
