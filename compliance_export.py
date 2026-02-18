"""Compliance export — generates a ZIP report for audit purposes.

Contains metadata only (no document content):
- metadata.json: server version, export timestamp, retention policy
- users.csv: user list (id, email, role, created_at, is_active)
- activity_log.csv: recent activity entries
- indexing_summary.json: recent indexing run summaries
- quarantine_summary.json: quarantine stats
- retention_policy.json: current retention defaults
"""

from __future__ import annotations

import csv
import io
import json
import logging
import zipfile
from datetime import datetime, timezone
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def _json_default(obj: Any) -> str:
    """Serialise datetime and other non-JSON-native types."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    return str(obj)


def _users_csv(users: List[Dict[str, Any]]) -> str:
    """Convert a list of user dicts to a CSV string."""
    if not users:
        return ""
    fields = ["id", "email", "display_name", "role", "created_at", "is_active"]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(users)
    return buf.getvalue()


def export_compliance_report() -> bytes:
    """Generate an in-memory ZIP containing compliance data.

    Each section is collected independently so a failure in one area
    (e.g. no users table) does not prevent the rest of the report
    from being generated.

    Returns:
        Raw bytes of the ZIP archive.
    """
    from version import __version__

    buf = io.BytesIO()
    errors: List[str] = []

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # --- metadata.json ---
        metadata: Dict[str, Any] = {
            "server_version": __version__,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "errors": errors,  # will be updated at the end
        }

        # --- retention_policy.json ---
        try:
            from retention_policy import get_policy_defaults
            policy = get_policy_defaults()
            zf.writestr("retention_policy.json", json.dumps(policy, indent=2, default=_json_default))
            metadata["retention_policy"] = policy
        except Exception as e:
            logger.warning("Compliance export: retention_policy failed: %s", e)
            errors.append(f"retention_policy: {e}")

        # --- users.csv ---
        try:
            from users import list_users
            users = list_users(active_only=False)
            zf.writestr("users.csv", _users_csv(users))
        except Exception as e:
            logger.warning("Compliance export: users failed: %s", e)
            errors.append(f"users: {e}")

        # --- activity_log.csv ---
        try:
            from activity_log import export_csv
            csv_data = export_csv(limit=50000)
            zf.writestr("activity_log.csv", csv_data)
        except Exception as e:
            logger.warning("Compliance export: activity_log failed: %s", e)
            errors.append(f"activity_log: {e}")

        # --- indexing_summary.json ---
        try:
            from indexing_runs import get_recent_runs
            runs = get_recent_runs(limit=100)
            zf.writestr("indexing_summary.json", json.dumps(runs, indent=2, default=_json_default))
        except Exception as e:
            logger.warning("Compliance export: indexing_runs failed: %s", e)
            errors.append(f"indexing_runs: {e}")

        # --- quarantine_summary.json ---
        try:
            from quarantine import get_quarantine_stats
            stats = get_quarantine_stats()
            zf.writestr("quarantine_summary.json", json.dumps(stats, indent=2, default=_json_default))
        except Exception as e:
            logger.warning("Compliance export: quarantine failed: %s", e)
            errors.append(f"quarantine: {e}")

        # --- metadata.json (write last so errors list is complete) ---
        zf.writestr("metadata.json", json.dumps(metadata, indent=2, default=_json_default))

    return buf.getvalue()
