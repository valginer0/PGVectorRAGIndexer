"""Retention policy orchestration for enterprise data lifecycle.

Provides per-category defaults and a single orchestration function that
applies retention across activity logs, quarantine, indexing runs, and
SAML sessions.

Configuration sources (current):
    - Environment variables: ``ACTIVITY_RETENTION_DAYS``,
      ``INDEXING_RUNS_RETENTION_DAYS``
    - Quarantine retention via ``quarantine.get_retention_days()``

Note:
    Migration 017 creates a ``retention_policies`` DB table, but it is
    **not yet wired** to this module.  The table is reserved for a future
    admin API that will allow per-category DB-backed overrides.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Default policy values
# ---------------------------------------------------------------------------

ACTIVITY_RETENTION_DAYS_ENV = "ACTIVITY_RETENTION_DAYS"
INDEXING_RUNS_RETENTION_DAYS_ENV = "INDEXING_RUNS_RETENTION_DAYS"

DEFAULT_ACTIVITY_RETENTION_DAYS = 2555  # ~7 years
DEFAULT_INDEXING_RUNS_RETENTION_DAYS = 10950  # ~30 years


def _safe_int_env(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
        return value if value > 0 else default
    except (TypeError, ValueError):
        return default


def get_policy_defaults() -> Dict[str, Any]:
    """Return currently effective retention defaults.

    Note:
        Quarantine retention is sourced from quarantine.get_retention_days().
        SAML session cleanup is expiry-driven and does not use a day count.
    """
    from quarantine import get_retention_days

    return {
        "activity_days": _safe_int_env(
            ACTIVITY_RETENTION_DAYS_ENV,
            DEFAULT_ACTIVITY_RETENTION_DAYS,
        ),
        "quarantine_days": get_retention_days(),
        "indexing_runs_days": _safe_int_env(
            INDEXING_RUNS_RETENTION_DAYS_ENV,
            DEFAULT_INDEXING_RUNS_RETENTION_DAYS,
        ),
        "saml_sessions": "expiry_only",
    }


def apply_retention(
    *,
    activity_days: Optional[int] = None,
    quarantine_days: Optional[int] = None,
    indexing_runs_days: Optional[int] = None,
    cleanup_saml_sessions: bool = True,
) -> Dict[str, Any]:
    """Apply retention actions across supported data classes.

    Returns:
        Dict with deletion/cleanup counters and the policy days used.
    """
    from activity_log import apply_retention as apply_activity_retention
    from indexing_runs import apply_retention as apply_indexing_runs_retention
    from quarantine import purge_expired

    defaults = get_policy_defaults()

    activity_days = activity_days or defaults["activity_days"]
    quarantine_days = quarantine_days if quarantine_days is not None else defaults["quarantine_days"]
    indexing_runs_days = indexing_runs_days or defaults["indexing_runs_days"]

    result: Dict[str, Any] = {
        "ok": True,
        "activity_days": activity_days,
        "quarantine_days": quarantine_days,
        "indexing_runs_days": indexing_runs_days,
        "saml_sessions_policy": defaults["saml_sessions"],
        "activity_deleted": 0,
        "quarantine_purged": 0,
        "indexing_runs_deleted": 0,
        "saml_sessions_deleted": 0,
    }

    try:
        result["activity_deleted"] = apply_activity_retention(activity_days)
        result["quarantine_purged"] = purge_expired(retention_days=quarantine_days)
        result["indexing_runs_deleted"] = apply_indexing_runs_retention(indexing_runs_days)
        if cleanup_saml_sessions:
            from saml_auth import cleanup_expired_sessions
            result["saml_sessions_deleted"] = cleanup_expired_sessions()
    except Exception as e:
        logger.warning("Retention orchestration failed: %s", e)
        result["ok"] = False
        result["error"] = str(e)

    return result
