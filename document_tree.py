"""
Document Tree module (#7).

Builds a hierarchical folder tree from document source_uri paths.
Supports lazy loading (one level at a time) and aggregated counts
per folder for the Hierarchical Document Browser.
"""

import logging
import posixpath
from typing import Any, Dict, List, Optional

from path_utils import normalize_path, NORMALIZED_URI_SQL

logger = logging.getLogger(__name__)


def _get_db_connection():
    """Get a database connection from the global DB manager."""
    from database import get_db_manager
    return get_db_manager().get_connection_raw()


def _normalize_path(path: str) -> str:
    """Normalize a path to forward slashes for consistent tree building.

    Delegates to :func:`path_utils.normalize_path` (single source of truth).
    Kept as a thin wrapper for backward compatibility with tests.
    """
    return normalize_path(path)


def get_tree_children(
    parent_path: str = "",
    limit: int = 200,
    offset: int = 0,
) -> Dict[str, Any]:
    """Get one level of the document tree under parent_path.

    Returns folders and files at the immediate next level.
    Each folder includes aggregated document count and latest indexed_at.
    Each file includes document_id, chunk_count, and indexed_at.

    Args:
        parent_path: The parent folder path (empty string for root).
                     Uses forward slashes, no trailing slash.
        limit: Max items to return.
        offset: Pagination offset.

    Returns:
        Dict with 'folders', 'files', 'total_folders', 'total_files'.
    """
    try:
        conn = _get_db_connection()
        cur = conn.cursor()

        # Normalize parent
        parent = _normalize_path(parent_path).rstrip("/")
        if parent:
            like_prefix = parent + "/%"
        else:
            like_prefix = "%"

        # Get all distinct normalized source_uri paths under this parent
        cur.execute(
            f"""
            SELECT
                {NORMALIZED_URI_SQL} AS norm_uri,
                document_id,
                COUNT(*) AS chunk_count,
                MIN(indexed_at) AS indexed_at,
                MAX(indexed_at) AS last_updated
            FROM document_chunks
            WHERE {NORMALIZED_URI_SQL} LIKE %s
            GROUP BY norm_uri, document_id
            ORDER BY norm_uri
            """,
            (like_prefix,),
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()

        # Build tree level
        folders: Dict[str, Dict[str, Any]] = {}
        files: List[Dict[str, Any]] = []

        parent_depth = len(parent.split("/")) if parent else 0

        for norm_uri, document_id, chunk_count, indexed_at, last_updated in rows:
            # Strip the parent prefix to get relative path
            if parent:
                if not norm_uri.startswith(parent + "/"):
                    continue
                relative = norm_uri[len(parent) + 1:]
            else:
                relative = norm_uri

            # Handle absolute Linux paths: /home/... → treat "/" as a root folder
            # so the first split component isn't an empty string.
            if not parent and relative.startswith("/"):
                relative = relative.lstrip("/")
                # Reconstruct with "/" prefix for folder_path below
                _linux_root = True
            else:
                _linux_root = False

            parts = relative.split("/")

            if len(parts) == 1:
                # Direct child file
                files.append({
                    "name": parts[0],
                    "path": norm_uri,
                    "type": "file",
                    "document_id": document_id,
                    "chunk_count": chunk_count,
                    "indexed_at": indexed_at.isoformat() if indexed_at else None,
                    "last_updated": last_updated.isoformat() if last_updated else None,
                })
            else:
                # Child is inside a subfolder
                folder_name = parts[0]
                if _linux_root:
                    # Use "/" prefix so expanding this folder fetches the right children
                    folder_path = "/" + folder_name
                elif parent:
                    folder_path = parent + "/" + folder_name
                else:
                    folder_path = folder_name

                if folder_name not in folders:
                    folders[folder_name] = {
                        "name": folder_name,
                        "path": folder_path,
                        "type": "folder",
                        "document_count": 0,
                        "latest_indexed_at": None,
                    }

                folders[folder_name]["document_count"] += 1
                if indexed_at:
                    ts = indexed_at.isoformat()
                    prev = folders[folder_name]["latest_indexed_at"]
                    if prev is None or ts > prev:
                        folders[folder_name]["latest_indexed_at"] = ts

        # Sort folders alphabetically, files alphabetically
        sorted_folders = sorted(folders.values(), key=lambda f: f["name"].lower())
        sorted_files = sorted(files, key=lambda f: f["name"].lower())

        total_folders = len(sorted_folders)
        total_files = len(sorted_files)

        # Combine and paginate
        all_items = sorted_folders + sorted_files
        paginated = all_items[offset:offset + limit]

        return {
            "parent_path": parent,
            "children": paginated,
            "total_folders": total_folders,
            "total_files": total_files,
            "total": total_folders + total_files,
            "limit": limit,
            "offset": offset,
        }
    except Exception as e:
        logger.warning("Failed to get tree children for '%s': %s", parent_path, e)
        return {
            "parent_path": parent_path,
            "children": [],
            "total_folders": 0,
            "total_files": 0,
            "total": 0,
            "limit": limit,
            "offset": offset,
        }


def get_tree_stats() -> Dict[str, Any]:
    """Get overall tree statistics.

    Returns:
        Dict with total_documents, total_folders (top-level), total_chunks.
    """
    try:
        conn = _get_db_connection()
        cur = conn.cursor()

        cur.execute("SELECT COUNT(DISTINCT document_id) FROM document_chunks")
        total_docs = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM document_chunks")
        total_chunks = cur.fetchone()[0]

        # Count distinct top-level folders
        cur.execute(f"""
            SELECT COUNT(DISTINCT
                SPLIT_PART(
                    {NORMALIZED_URI_SQL},
                    '/', 1
                )
            )
            FROM document_chunks
        """)
        top_level_count = cur.fetchone()[0]

        cur.close()
        conn.close()

        return {
            "total_documents": total_docs,
            "total_chunks": total_chunks,
            "top_level_items": top_level_count,
        }
    except Exception as e:
        logger.warning("Failed to get tree stats: %s", e)
        return {
            "total_documents": 0,
            "total_chunks": 0,
            "top_level_items": 0,
        }


def search_tree(
    query: str,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Search for documents matching a path pattern.

    Returns matching documents with their full paths.
    """
    try:
        conn = _get_db_connection()
        cur = conn.cursor()

        pattern = f"%{_normalize_path(query)}%"
        cur.execute(
            f"""
            SELECT
                {NORMALIZED_URI_SQL} AS norm_uri,
                document_id,
                COUNT(*) AS chunk_count,
                MIN(indexed_at) AS indexed_at
            FROM document_chunks
            WHERE {NORMALIZED_URI_SQL} ILIKE %s
            GROUP BY norm_uri, document_id
            ORDER BY norm_uri
            LIMIT %s
            """,
            (pattern, limit),
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()

        return [
            {
                "path": norm_uri,
                "document_id": doc_id,
                "chunk_count": chunk_count,
                "indexed_at": indexed_at.isoformat() if indexed_at else None,
            }
            for norm_uri, doc_id, chunk_count, indexed_at in rows
        ]
    except Exception as e:
        logger.warning("Failed to search tree for '%s': %s", query, e)
        return []
