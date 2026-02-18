"""Shared path normalization utilities.

Provides a single source of truth for normalizing file paths to
forward slashes, used by both Python code and SQL queries.

This module is intentionally kept at the repo root alongside
``document_tree.py`` so that both server-side tree logic and the
``DocumentRepository`` source_prefix filter share identical behaviour.
"""

from __future__ import annotations


def normalize_path(path: str) -> str:
    """Normalize a path to forward slashes for consistent matching.

    Replaces backslashes (``\\``), tabs, newlines, and carriage returns
    with forward slashes.  This is identical to the SQL expression
    :data:`NORMALIZED_URI_SQL`.
    """
    return (
        path
        .replace("\\", "/")
        .replace("\t", "/")
        .replace("\n", "/")
        .replace("\r", "/")
    )


# ---------------------------------------------------------------------------
# Shared SQL expression — MUST match :func:`normalize_path` exactly.
#
# WARNING: This is a *trusted* SQL fragment.  Never interpolate user
# input into it.  Always bind filter values via parameterised queries
# (``%s``).
# ---------------------------------------------------------------------------

NORMALIZED_URI_SQL: str = (
    "REPLACE(REPLACE(REPLACE(REPLACE("
    "source_uri, E'\\\\', '/'), E'\\t', '/'), E'\\n', '/'), E'\\r', '/')"
)
