"""
Canonical Identity module (Phase 6b.2).

Provides stable, scope-aware document identity for mixed-mode
(client + server) environments.  A canonical source key uniquely
identifies a logical document across different absolute paths.

Key format:
    client scope:  client:<executor_id>:<relative_path>
    server scope:  server:<root_id>:<relative_path>

These keys are stored on document_chunks.canonical_source_key
and used for cross-scope deduplication and lock resolution.
"""

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _get_db_connection():
    """Get a database connection from the global DB manager."""
    from database import get_db_manager
    return get_db_manager().get_connection()


# ---------------------------------------------------------------------------
# Key construction & parsing
# ---------------------------------------------------------------------------


def build_canonical_key(
    scope: str,
    identity: str,
    relative_path: str,
) -> str:
    """Build a canonical source key.

    Args:
        scope:         'client' or 'server'
        identity:      executor_id (client) or root_id (server)
        relative_path: path relative to the watched root (forward slashes)

    Returns:
        e.g. 'client:abc123:/docs/readme.md'
    """
    normed = _normalize_relative(relative_path)
    return f"{scope}:{identity}:{normed}"


def resolve_canonical_key(key: str) -> Optional[Dict[str, str]]:
    """Parse a canonical source key into its components.

    Returns:
        {'scope': ..., 'identity': ..., 'relative_path': ...}
        or None if the key is malformed.
    """
    if not key:
        return None
    parts = key.split(":", 2)
    if len(parts) != 3:
        return None
    scope, identity, rel = parts
    if scope not in ("client", "server"):
        return None
    return {"scope": scope, "identity": identity, "relative_path": rel}


def extract_relative_path(folder_root: str, absolute_path: str) -> str:
    """Compute the relative path of a file within a watched root.

    Both paths are normalized before comparison.

    Args:
        folder_root:   e.g. '/data/docs'
        absolute_path: e.g. '/data/docs/sub/readme.md'

    Returns:
        Relative path with leading slash, e.g. '/sub/readme.md'
    """
    root = folder_root.replace("\\", "/").rstrip("/")
    abspath = absolute_path.replace("\\", "/")

    if abspath.startswith(root + "/"):
        rel = abspath[len(root):]  # includes leading '/'
    elif abspath == root:
        rel = "/"
    else:
        # Not under this root; return the full path as-is
        rel = abspath

    return _normalize_relative(rel)


def _normalize_relative(path: str) -> str:
    """Normalize a relative path: forward slashes, collapse doubles, strip trailing."""
    p = path.replace("\\", "/")
    while "//" in p:
        p = p.replace("//", "/")
    # Ensure leading slash
    if p and not p.startswith("/"):
        p = "/" + p
    # Strip trailing slash (keep bare '/')
    if len(p) > 1:
        p = p.rstrip("/")
    return p


# ---------------------------------------------------------------------------
# DB operations
# ---------------------------------------------------------------------------


def set_canonical_key(chunk_id: int, canonical_key: str) -> bool:
    """Set the canonical_source_key for a single document chunk."""
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "UPDATE document_chunks SET canonical_source_key = %s WHERE chunk_id = %s",
            (canonical_key, chunk_id),
        )
        updated = cur.rowcount
        conn.commit()
        cur.close()
        conn.close()
        return updated > 0
    except Exception as e:
        logger.warning("Failed to set canonical key for chunk %s: %s", chunk_id, e)
        return False


def bulk_set_canonical_keys(
    root_id: str,
    folder_path: str,
    scope: str,
    identity: str,
) -> int:
    """Backfill canonical_source_key for all chunks under a watched root.

    Finds chunks whose source_uri starts with folder_path and sets
    canonical_source_key based on their relative path within the root.

    Args:
        root_id:     UUID of the watched folder root
        folder_path: absolute path of the watched folder
        scope:       'client' or 'server'
        identity:    executor_id (client) or root_id (server)

    Returns:
        Number of chunks updated.
    """
    try:
        conn = _get_db_connection()
        cur = conn.cursor()

        # Normalize the root for prefix matching
        root_prefix = folder_path.replace("\\", "/").rstrip("/") + "/"

        # Find chunks under this root without a canonical key
        cur.execute(
            """
            SELECT chunk_id, source_uri
            FROM document_chunks
            WHERE source_uri LIKE %s
              AND canonical_source_key IS NULL
            """,
            (root_prefix + "%",),
        )
        rows = cur.fetchall()

        if not rows:
            cur.close()
            conn.close()
            return 0

        updated = 0
        for chunk_id, source_uri in rows:
            rel = extract_relative_path(folder_path, source_uri)
            key = build_canonical_key(scope, identity, rel)
            cur.execute(
                "UPDATE document_chunks SET canonical_source_key = %s WHERE chunk_id = %s",
                (key, chunk_id),
            )
            updated += cur.rowcount

        conn.commit()
        cur.close()
        conn.close()
        logger.info(
            "Backfilled %d canonical keys for root %s (%s)",
            updated, root_id, folder_path,
        )
        return updated

    except Exception as e:
        logger.warning(
            "Failed to backfill canonical keys for root %s: %s", root_id, e,
        )
        return 0


def find_by_canonical_key(key: str) -> List[Dict[str, Any]]:
    """Find document chunks by canonical source key.

    Returns:
        List of dicts with chunk_id, source_uri, document_id, canonical_source_key.
    """
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT chunk_id, document_id, source_uri, canonical_source_key
            FROM document_chunks
            WHERE canonical_source_key = %s
            ORDER BY chunk_index
            """,
            (key,),
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [
            {
                "chunk_id": r[0],
                "document_id": r[1],
                "source_uri": r[2],
                "canonical_source_key": r[3],
            }
            for r in rows
        ]
    except Exception as e:
        logger.warning("Failed to find chunks by canonical key %s: %s", key, e)
        return []
