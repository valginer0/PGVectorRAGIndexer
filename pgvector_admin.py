#!/usr/bin/env python3
"""
pgvector-admin — CLI tool for managing PGVectorRAGIndexer API keys.

Usage:
    python pgvector_admin.py create-key --name "Alice"
    python pgvector_admin.py list-keys
    python pgvector_admin.py revoke-key --id 3
    python pgvector_admin.py rotate-key --id 3

Requires DATABASE_URL environment variable (or defaults from config.py).
"""

import argparse
import json
import logging
import sys

logging.basicConfig(level=logging.WARNING, format="%(message)s")
logger = logging.getLogger(__name__)


def cmd_create_key(args):
    """Create a new API key."""
    from auth import create_api_key_record
    result = create_api_key_record(args.name)
    print(f"\n  API Key created successfully!\n")
    print(f"  Name:    {result['name']}")
    print(f"  ID:      {result['id']}")
    print(f"  Prefix:  {result['prefix']}")
    print(f"  Key:     {result['key']}")
    print(f"\n  ⚠️  Store this key securely. It will NOT be shown again.\n")


def cmd_list_keys(args):
    """List all API keys."""
    from auth import list_api_keys
    keys = list_api_keys()
    if not keys:
        print("No API keys found.")
        return

    # Header
    print(f"\n{'ID':<6} {'Name':<20} {'Prefix':<16} {'Created':<22} {'Active'}")
    print("-" * 75)
    for k in keys:
        active = "✓" if k.get("is_active", True) else "✗"
        print(f"{k['id']:<6} {k['name']:<20} {k['prefix']:<16} {k['created_at']:<22} {active}")
    print()


def cmd_revoke_key(args):
    """Revoke an API key."""
    from auth import revoke_api_key
    revoked = revoke_api_key(args.id)
    if revoked:
        print(f"Key {args.id} revoked successfully.")
    else:
        print(f"Key {args.id} not found or already revoked.", file=sys.stderr)
        sys.exit(1)


def cmd_rotate_key(args):
    """Rotate an API key (create new, grace period on old)."""
    from auth import rotate_api_key
    result = rotate_api_key(args.id)
    if not result:
        print(f"Key {args.id} not found or already revoked.", file=sys.stderr)
        sys.exit(1)

    print(f"\n  Key rotated successfully!\n")
    print(f"  New Name:    {result['name']}")
    print(f"  New ID:      {result['id']}")
    print(f"  New Prefix:  {result['prefix']}")
    print(f"  New Key:     {result['key']}")
    print(f"  Old Key ID:  {result['old_key_id']} (valid for {result['grace_period_hours']}h)")
    print(f"\n  ⚠️  Store the new key securely. It will NOT be shown again.\n")


def main():
    parser = argparse.ArgumentParser(
        prog="pgvector-admin",
        description="Manage PGVectorRAGIndexer API keys",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # create-key
    p_create = subparsers.add_parser("create-key", help="Create a new API key")
    p_create.add_argument("--name", required=True, help="Human-readable name for the key")
    p_create.set_defaults(func=cmd_create_key)

    # list-keys
    p_list = subparsers.add_parser("list-keys", help="List all API keys")
    p_list.set_defaults(func=cmd_list_keys)

    # revoke-key
    p_revoke = subparsers.add_parser("revoke-key", help="Revoke an API key immediately")
    p_revoke.add_argument("--id", required=True, type=int, help="Key ID to revoke")
    p_revoke.set_defaults(func=cmd_revoke_key)

    # rotate-key
    p_rotate = subparsers.add_parser("rotate-key", help="Rotate a key (new key + 24h grace period)")
    p_rotate.add_argument("--id", required=True, type=int, help="Key ID to rotate")
    p_rotate.set_defaults(func=cmd_rotate_key)

    args = parser.parse_args()
    try:
        args.func(args)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
