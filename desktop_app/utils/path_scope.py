"""Folder-boundary path relations for search scope (chips and dialog).

Desktop-side counterpart of path_utils.is_path_under on the backend; kept
separate because the desktop bundle does not import repo-root modules.
"""


def is_path_under(path: str, ancestor: str) -> bool:
    """True when *path* lies strictly below *ancestor* (folder-boundary aware)."""
    p = str(path).replace("\\", "/").rstrip("/")
    a = str(ancestor).replace("\\", "/").rstrip("/")
    return bool(a) and p.startswith(a + "/")
