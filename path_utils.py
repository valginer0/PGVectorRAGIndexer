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


def folder_prefix_like_pattern(prefix: str) -> str | None:
    """Normalized, LIKE-escaped folder-boundary pattern ``<prefix>/%``.

    Single source of truth for matching "documents under this folder" with
    SQL LIKE against :data:`NORMALIZED_URI_SQL`. The prefix is normalized to
    forward slashes, trailing slashes stripped, and LIKE metacharacters
    (``%``, ``_``) escaped so folder names are matched literally. Matching is
    case-sensitive on purpose: folders differing only by case are distinct on
    case-sensitive filesystems.

    Returns None for empty or root prefixes — they would match everything,
    so callers should treat None as "no restriction".

    ``//`` runs are deliberately NOT collapsed: NORMALIZED_URI_SQL preserves
    them (UNC paths like ``\\\\server\\share`` normalize to ``//server/share``),
    so the pattern must preserve them to match.
    """
    norm = normalize_path(str(prefix)).rstrip("/")
    if not norm:
        return None
    return norm.replace("%", r"\%").replace("_", r"\_") + "/%"


def is_path_under(path: str, ancestor: str) -> bool:
    """True when *path* lies strictly below *ancestor* (folder-boundary aware)."""
    p = normalize_path(str(path)).rstrip("/")
    a = normalize_path(str(ancestor)).rstrip("/")
    return bool(a) and p.startswith(a + "/")
