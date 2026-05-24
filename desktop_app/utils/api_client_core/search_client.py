import logging
from typing import Dict, Any, Optional

from desktop_app.utils.api_client_core.base_client import BaseAPIClient
from desktop_app.utils.search_limits import candidate_limit_for_unique_files

logger = logging.getLogger(__name__)

DOCUMENT_GROUPING_KEYS = (
    "group_by_document",
    "literal_tail_suppression",
    "literal_anchor_threshold",
    "literal_tail_threshold",
)


class SearchClient:
    """Domain client for search operations."""

    def __init__(self, base_client: BaseAPIClient):
        self._base = base_client

    def search(
        self,
        query: str,
        top_k: Optional[int] = 10,
        min_score: float = 0.5,
        metric: str = "cosine",
        document_type: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
        extensions: Optional[list] = None,
        group_by_document: bool = False,
        literal_tail_suppression: Optional[str] = None,
        literal_anchor_threshold: Optional[float] = None,
        literal_tail_threshold: Optional[float] = None,
    ) -> list:
        """Search the indexed documents."""
        payload = {
            "query": query,
            "top_k": top_k,
            "min_score": min_score,
            "metric": metric,
            "use_hybrid": True
        }
        if group_by_document:
            payload["group_by_document"] = True
        if literal_tail_suppression:
            payload["literal_tail_suppression"] = literal_tail_suppression
        if literal_anchor_threshold is not None:
            payload["literal_anchor_threshold"] = literal_anchor_threshold
        if literal_tail_threshold is not None:
            payload["literal_tail_threshold"] = literal_tail_threshold

        merged_filters: Dict[str, Any] = dict(filters) if filters else {}
        if document_type:
            merged_filters["type"] = document_type
        if extensions:
            merged_filters["extensions"] = extensions
        if merged_filters:
            payload["filters"] = merged_filters

        data = self._post_search(payload)
        if group_by_document and not _group_by_document_confirmed(data):
            logger.info(
                "Backend did not confirm document-level search; retrying with legacy over-fetch"
            )
            fallback_payload = _legacy_document_grouping_fallback_payload(payload, top_k)
            data = self._post_search(fallback_payload)

        return data.get("results", [])

    def _post_search(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        response = self._base.request(
            "POST",
            f"{self._base.api_base}/search",
            json=payload
        )
        return response.json()

    def get_extensions(self) -> list:
        """Return distinct file extensions present in the index."""
        try:
            response = self._base.request("GET", f"{self._base.api_base}/extensions")
            return response.json()
        except Exception:
            return []


def _group_by_document_confirmed(data: Dict[str, Any]) -> bool:
    diagnostics = data.get("diagnostics") or {}
    grouping = diagnostics.get("group_by_document") or {}
    return bool(grouping.get("active"))


def _legacy_document_grouping_fallback_payload(
    payload: Dict[str, Any],
    visible_top_k: Optional[int],
) -> Dict[str, Any]:
    fallback = dict(payload)
    for key in DOCUMENT_GROUPING_KEYS:
        fallback.pop(key, None)
    fallback["top_k"] = candidate_limit_for_unique_files(visible_top_k)
    return fallback
