"""
Document visibility and ownership module for #3 Multi-User Support Phase 2.

Provides per-user document scoping:
- Documents can be 'shared' (visible to all) or 'private' (owner + admins only)
- Ownership is tracked via owner_id (FK to users table)
- NULL owner_id = system/shared document (backward compatible)
- Admins can see all documents regardless of visibility
- Visibility filters can be injected into search/list queries

Visibility rules:
1. shared docs: visible to everyone
2. private docs: visible to owner and admins only
3. NULL owner_id: treated as shared (backward compat for pre-existing docs)
"""

import logging
from typing import Optional, List, Dict, Any, Tuple

logger = logging.getLogger(__name__)

# Visibility constants
VISIBILITY_SHARED = "shared"
VISIBILITY_PRIVATE = "private"
VALID_VISIBILITIES = {VISIBILITY_SHARED, VISIBILITY_PRIVATE}


# ---------------------------------------------------------------------------
# DB helper
# ---------------------------------------------------------------------------


def _get_db_connection():
    """Get a pooled database connection as a context manager.

    Always use with ``with _get_db_connection() as conn:`` to ensure
    the connection is returned to the pool after use.
    """
    from database import get_db_manager
    return get_db_manager().get_connection()


# ---------------------------------------------------------------------------
# SQL filter generation
# ---------------------------------------------------------------------------


def visibility_where_clause(user_id: Optional[str] = None, is_admin: bool = False) -> Tuple[str, list]:
    """Generate a WHERE clause fragment for document visibility filtering.

    Args:
        user_id: The current user's ID (None = unauthenticated/local mode).
        is_admin: Whether the current user is an admin.

    Returns:
        Tuple of (sql_fragment, params) to AND into a query.
        Returns ("", []) if no filtering is needed (admin or no auth).
    """
    # Admins see everything
    if is_admin:
        return "", []

    # No user context (local mode / no auth) — see all shared docs
    if not user_id:
        return "(visibility = 'shared' OR visibility IS NULL OR owner_id IS NULL)", []

    # Regular user: see shared docs + own private docs
    return (
        "(visibility = 'shared' OR visibility IS NULL OR owner_id IS NULL OR owner_id = %s)",
        [user_id],
    )


def visibility_where_clause_for_document(
    document_id: str,
    user_id: Optional[str] = None,
    is_admin: bool = False,
) -> Tuple[str, list]:
    """Check if a specific document is visible to a user.

    Returns a WHERE clause that matches the document only if visible.
    """
    vis_sql, vis_params = visibility_where_clause(user_id, is_admin)
    if vis_sql:
        sql = f"document_id = %s AND {vis_sql}"
        return sql, [document_id] + vis_params
    else:
        return "document_id = %s", [document_id]


# ---------------------------------------------------------------------------
# Ownership management
# ---------------------------------------------------------------------------


def set_document_owner(document_id: str, owner_id: str) -> int:
    """Set the owner of all chunks for a document.

    Args:
        document_id: The document to update.
        owner_id: The user ID to set as owner.

    Returns:
        Number of chunks updated.
    """
    try:
        with _get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE document_chunks SET owner_id = %s WHERE document_id = %s",
                (owner_id, document_id),
            )
            conn.commit()
            return cursor.rowcount
    except Exception as e:
        logger.error("Failed to set document owner: %s", e)
        return 0


def set_document_visibility(document_id: str, visibility: str) -> int:
    """Set the visibility of all chunks for a document.

    Args:
        document_id: The document to update.
        visibility: 'shared' or 'private'.

    Returns:
        Number of chunks updated, or -1 if invalid visibility.
    """
    if visibility not in VALID_VISIBILITIES:
        logger.error("Invalid visibility: %s", visibility)
        return -1

    try:
        with _get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE document_chunks SET visibility = %s WHERE document_id = %s",
                (visibility, document_id),
            )
            conn.commit()
            return cursor.rowcount
    except Exception as e:
        logger.error("Failed to set document visibility: %s", e)
        return 0


def set_document_owner_and_visibility(
    document_id: str, owner_id: str, visibility: str
) -> int:
    """Set both owner and visibility for a document in one operation.

    Returns:
        Number of chunks updated, or -1 if invalid visibility.
    """
    if visibility not in VALID_VISIBILITIES:
        logger.error("Invalid visibility: %s", visibility)
        return -1

    try:
        with _get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE document_chunks SET owner_id = %s, visibility = %s WHERE document_id = %s",
                (owner_id, visibility, document_id),
            )
            conn.commit()
            return cursor.rowcount
    except Exception as e:
        logger.error("Failed to set document owner and visibility: %s", e)
        return 0


def get_document_visibility(document_id: str) -> Optional[Dict[str, Any]]:
    """Get the visibility info for a document.

    Returns:
        Dict with owner_id, visibility, chunk_count, or None if not found.
    """
    try:
        with _get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT
                    (array_agg(owner_id))[1] as owner_id,
                    (array_agg(visibility))[1] as visibility,
                    COUNT(*) as chunk_count
                FROM document_chunks
                WHERE document_id = %s
                GROUP BY document_id
                """,
                (document_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "document_id": document_id,
                "owner_id": row[0],
                "visibility": row[1],
                "chunk_count": row[2],
            }
    except Exception as e:
        logger.error("Failed to get document visibility: %s", e)
        return None


def list_user_documents(
    user_id: str,
    visibility: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """List documents owned by a specific user.

    Args:
        user_id: Owner user ID.
        visibility: Optional filter ('shared' or 'private').
        limit: Max results.
        offset: Pagination offset.

    Returns:
        List of document dicts.
    """
    try:
        with _get_db_connection() as conn:
            cursor = conn.cursor()

            where = "WHERE owner_id = %s"
            params: list = [user_id]

            if visibility and visibility in VALID_VISIBILITIES:
                where += " AND visibility = %s"
                params.append(visibility)

            params.extend([limit, offset])

            cursor.execute(
                f"""
                SELECT
                    document_id,
                    source_uri,
                    COUNT(*) as chunk_count,
                    MIN(indexed_at) as indexed_at,
                    MAX(updated_at) as last_updated,
                    (array_agg(visibility))[1] as visibility
                FROM document_chunks
                {where}
                GROUP BY document_id, source_uri
                ORDER BY MAX(updated_at) DESC
                LIMIT %s OFFSET %s
                """,
                params,
            )
            rows = cursor.fetchall()
            return [
                {
                    "document_id": r[0],
                    "source_uri": r[1],
                    "chunk_count": r[2],
                    "indexed_at": r[3].isoformat() if r[3] and hasattr(r[3], "isoformat") else r[3],
                    "last_updated": r[4].isoformat() if r[4] and hasattr(r[4], "isoformat") else r[4],
                    "visibility": r[5],
                }
                for r in rows
            ]
    except Exception as e:
        logger.error("Failed to list user documents: %s", e)
        return []


def bulk_set_visibility(document_ids: List[str], visibility: str) -> int:
    """Set visibility for multiple documents at once.

    Returns:
        Total number of chunks updated, or -1 if invalid visibility.
    """
    if visibility not in VALID_VISIBILITIES:
        return -1
    if not document_ids:
        return 0

    try:
        with _get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE document_chunks SET visibility = %s WHERE document_id = ANY(%s)",
                (visibility, document_ids),
            )
            conn.commit()
            return cursor.rowcount
    except Exception as e:
        logger.error("Failed to bulk set visibility: %s", e)
        return 0


def transfer_ownership(document_id: str, new_owner_id: str) -> int:
    """Transfer document ownership to a different user.

    Returns:
        Number of chunks updated.
    """
    try:
        with _get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE document_chunks SET owner_id = %s WHERE document_id = %s",
                (new_owner_id, document_id),
            )
            conn.commit()
            return cursor.rowcount
    except Exception as e:
        logger.error("Failed to transfer ownership: %s", e)
        return 0
