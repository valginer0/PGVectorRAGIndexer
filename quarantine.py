"""
Quarantine lifecycle module (Phase 6b.3).

Provides soft-delete semantics for document chunks whose source
files have gone missing.  Instead of immediately deleting,
chunks are marked with a quarantine timestamp and reason.
After a configurable retention window they can be permanently purged.

Environment:
    QUARANTINE_RETENTION_DAYS  (default 30)
"""

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

QUARANTINE_RETENTION_DAYS_ENV = "QUARANTINE_RETENTION_DAYS"
DEFAULT_RETENTION_DAYS = 30


def _get_db_connection():
    """Get a database connection from the global DB manager."""
    from database import get_db_manager
    return get_db_manager().get_connection()


def get_retention_days() -> int:
    """Return the quarantine retention period from env, default 30."""
    try:
        return int(os.environ.get(QUARANTINE_RETENTION_DAYS_ENV, DEFAULT_RETENTION_DAYS))
    except (ValueError, TypeError):
        return DEFAULT_RETENTION_DAYS


# ---------------------------------------------------------------------------
# Quarantine operations
# ---------------------------------------------------------------------------


def quarantine_chunks(source_uri: str, reason: str = "source_file_missing") -> int:
    """Mark all chunks for a source_uri as quarantined.

    Only quarantines chunks that are not already quarantined.

    Args:
        source_uri: The document's source path.
        reason: Human-readable reason for quarantine.

    Returns:
        Number of chunks quarantined.
    """
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE document_chunks
            SET quarantined_at = now(),
                quarantine_reason = %s
            WHERE source_uri = %s
              AND quarantined_at IS NULL
            """,
            (reason, source_uri),
        )
        count = cur.rowcount
        conn.commit()
        cur.close()
        conn.close()
        if count > 0:
            logger.info("Quarantined %d chunks for %s: %s", count, source_uri, reason)
        return count
    except Exception as e:
        logger.warning("Failed to quarantine chunks for %s: %s", source_uri, e)
        return 0


def restore_chunks(source_uri: str) -> int:
    """Remove quarantine status from all chunks for a source_uri.

    Called when a previously missing source file reappears.

    Returns:
        Number of chunks restored.
    """
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE document_chunks
            SET quarantined_at = NULL,
                quarantine_reason = NULL
            WHERE source_uri = %s
              AND quarantined_at IS NOT NULL
            """,
            (source_uri,),
        )
        count = cur.rowcount
        conn.commit()
        cur.close()
        conn.close()
        if count > 0:
            logger.info("Restored %d quarantined chunks for %s", count, source_uri)
        return count
    except Exception as e:
        logger.warning("Failed to restore quarantined chunks for %s: %s", source_uri, e)
        return 0


def list_quarantined(
    limit: int = 50,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """List quarantined documents (grouped by source_uri).

    Returns a list of dicts with source_uri, chunk_count,
    quarantined_at (earliest), and quarantine_reason.
    """
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT source_uri,
                   COUNT(*) AS chunk_count,
                   MIN(quarantined_at) AS quarantined_at,
                   MIN(quarantine_reason) AS quarantine_reason
            FROM document_chunks
            WHERE quarantined_at IS NOT NULL
            GROUP BY source_uri
            ORDER BY MIN(quarantined_at) ASC
            LIMIT %s OFFSET %s
            """,
            (limit, offset),
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [
            {
                "source_uri": r[0],
                "chunk_count": r[1],
                "quarantined_at": r[2].isoformat() if r[2] else None,
                "quarantine_reason": r[3],
            }
            for r in rows
        ]
    except Exception as e:
        logger.warning("Failed to list quarantined documents: %s", e)
        return []


def purge_expired(retention_days: Optional[int] = None) -> int:
    """Hard-delete chunks quarantined longer than the retention window.

    Args:
        retention_days: Override; defaults to QUARANTINE_RETENTION_DAYS env.

    Returns:
        Number of chunks permanently deleted.
    """
    days = retention_days if retention_days is not None else get_retention_days()
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            DELETE FROM document_chunks
            WHERE quarantined_at IS NOT NULL
              AND quarantined_at < now() - interval '%s days'
            """,
            (days,),
        )
        count = cur.rowcount
        conn.commit()
        cur.close()
        conn.close()
        if count > 0:
            logger.info(
                "Purged %d chunks quarantined > %d days", count, days,
            )
        return count
    except Exception as e:
        logger.warning("Failed to purge expired quarantined chunks: %s", e)
        return 0


def get_quarantine_stats() -> Dict[str, Any]:
    """Return summary statistics for quarantined chunks.

    Returns:
        Dict with total_documents, total_chunks, oldest_quarantine_at.
    """
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT COUNT(DISTINCT source_uri) AS documents,
                   COUNT(*) AS chunks,
                   MIN(quarantined_at) AS oldest
            FROM document_chunks
            WHERE quarantined_at IS NOT NULL
            """
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row:
            return {
                "total_documents": row[0],
                "total_chunks": row[1],
                "oldest_quarantine_at": row[2].isoformat() if row[2] else None,
            }
        return {"total_documents": 0, "total_chunks": 0, "oldest_quarantine_at": None}
    except Exception as e:
        logger.warning("Failed to get quarantine stats: %s", e)
        return {"total_documents": 0, "total_chunks": 0, "oldest_quarantine_at": None}
