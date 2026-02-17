"""016 – Activity log fields + DB-backed roles table.

Part A: Add executor context columns to activity_log for #6b observability.
Part B: Create roles table for enterprise RBAC Phase 4b, seeded with built-in roles.

Revision ID: 016
Revises: 015
"""

from alembic import op
import json

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None

# Built-in roles to seed (matches role_permissions.BUILTIN_ROLES)
_BUILTIN_ROLES = {
    "admin": {
        "description": "Full system access",
        "permissions": [
            "audit.view", "documents.delete", "documents.read",
            "documents.visibility", "documents.visibility.all",
            "documents.write", "health.view", "keys.manage",
            "system.admin", "users.manage",
        ],
        "is_system": True,
    },
    "user": {
        "description": "Standard user — index and search documents",
        "permissions": ["documents.read", "documents.visibility", "documents.write"],
        "is_system": True,
    },
    "researcher": {
        "description": "Read-heavy role — search and index, manage own visibility",
        "permissions": ["documents.read", "documents.visibility", "documents.write"],
        "is_system": False,
    },
    "sre": {
        "description": "Operations role — full document access, health monitoring, audit",
        "permissions": [
            "audit.view", "documents.delete", "documents.read",
            "documents.visibility", "documents.visibility.all",
            "documents.write", "health.view",
        ],
        "is_system": False,
    },
    "support": {
        "description": "Support role — read-only access with health and audit visibility",
        "permissions": ["audit.view", "documents.read", "health.view"],
        "is_system": False,
    },
}


def upgrade():
    # -- Part A: activity_log executor context fields  -----------------------
    for col, coltype in [
        ("executor_scope", "TEXT"),
        ("executor_id", "TEXT"),
        ("root_id", "TEXT"),
        ("run_id", "TEXT"),
    ]:
        op.execute(
            f"ALTER TABLE activity_log ADD COLUMN IF NOT EXISTS {col} {coltype} NULL"
        )

    # -- Part B: roles table  ------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS roles (
            name        TEXT PRIMARY KEY,
            description TEXT NOT NULL DEFAULT '',
            permissions JSONB NOT NULL DEFAULT '[]'::jsonb,
            is_system   BOOLEAN NOT NULL DEFAULT FALSE,
            created_at  TIMESTAMPTZ DEFAULT now(),
            updated_at  TIMESTAMPTZ DEFAULT now()
        )
        """
    )

    # Seed built-in roles (skip if already present)
    for name, defn in _BUILTIN_ROLES.items():
        op.execute(
            "INSERT INTO roles (name, description, permissions, is_system) "
            "VALUES ('{name}', '{desc}', '{perms}'::jsonb, {sys}) "
            "ON CONFLICT (name) DO NOTHING".format(
                name=name,
                desc=defn["description"].replace("'", "''"),
                perms=json.dumps(defn["permissions"]),
                sys="TRUE" if defn["is_system"] else "FALSE",
            )
        )


def downgrade():
    # Part B
    op.execute("DROP TABLE IF EXISTS roles")

    # Part A
    for col in ("run_id", "root_id", "executor_id", "executor_scope"):
        op.execute(f"ALTER TABLE activity_log DROP COLUMN IF EXISTS {col}")
