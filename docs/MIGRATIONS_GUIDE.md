# Database Migrations Guide

How to create and manage Alembic migrations for PGVectorRAGIndexer.

---

## Overview

We use [Alembic](https://alembic.sqlalchemy.org/) for database schema migrations. Migrations run automatically on API startup via `migrate.py`, so users never need to run them manually.

**Key files:**
- `alembic.ini` — Alembic configuration
- `alembic/env.py` — Migration environment (reads `DATABASE_URL` from config)
- `alembic/versions/` — Migration scripts (numbered: `001_`, `002_`, etc.)
- `migrate.py` — Standalone runner with pre-migration backup safety

---

## Creating a New Migration

### 1. Write the migration file

Create a new file in `alembic/versions/` following the naming convention:

```
alembic/versions/NNN_descriptive_name.py
```

Where `NNN` is the next sequential number (e.g., `004_`, `005_`).

### 2. Use this template

```python
"""Short description of what this migration does."""

from alembic import op
import sqlalchemy as sa

# Revision identifiers
revision = "004"
down_revision = "003"  # Must point to the previous migration
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create tables, add columns, etc.
    op.create_table(
        "my_new_table",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("my_new_table")
```

### 3. Set the revision chain correctly

- `revision` must be unique (use the next number)
- `down_revision` must point to the **previous** migration's `revision`
- Check existing files to find the current head:

```bash
source venv/bin/activate
alembic heads
```

### 4. Test the migration

```bash
# Run all tests including migration tests
source venv/bin/activate
python -m pytest tests/test_migrations.py tests/test_migrations_integration.py -v
```

The integration tests use [testcontainers](https://testcontainers-python.readthedocs.io/) to spin up a real PostgreSQL instance, so they verify actual SQL execution.

---

## Migration Best Practices

- **Always include `downgrade()`** — even if we rarely use it, it documents the inverse operation
- **Never modify existing migrations** — once committed, a migration is immutable. Create a new migration to fix issues
- **Use `op.execute()` for raw SQL** when Alembic's API doesn't cover your need (e.g., triggers, custom functions)
- **Test with existing data** — the integration tests seed data before migrating to catch issues
- **Keep migrations small** — one logical change per migration (one table, one column addition, etc.)
- **No Python model imports** — migrations should be self-contained SQL, not depend on ORM models that may change later

---

## How Migrations Run in Production

### Docker mode
`migrate.py` runs during `api.py` startup (`lifespan()` function). It:
1. Checks current DB revision
2. If behind, runs `pg_dump` backup automatically
3. Applies pending migrations
4. Logs results

### Desktop mode
Same startup flow, but instead of auto-backup, it checks for a recent backup file and warns the user if none exists.

### Manual run
```bash
source venv/bin/activate
python migrate.py
```

Or directly via Alembic:
```bash
source venv/bin/activate
alembic upgrade head
```

---

## Existing Migrations

| # | File | Description |
|---|------|-------------|
| 001 | `001_baseline.py` | Baseline schema matching `init-db.sql` (documents, chunks, indexes) |
| 002 | `002_server_settings.py` | `server_settings` table for server-level config (owner_client_id, etc.) |
| 003 | `003_api_keys.py` | `api_keys` table for API key authentication |

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `alembic heads` shows multiple heads | You have a branch conflict. Merge with `alembic merge heads -m "merge"` |
| Migration fails on existing DB | The DB may be at an unknown state. Check `alembic current` and stamp if needed: `alembic stamp 003` |
| Tests fail with "relation already exists" | The test DB wasn't cleaned up. Integration tests should use fresh containers |
