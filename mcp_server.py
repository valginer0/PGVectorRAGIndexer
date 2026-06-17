#!/usr/bin/env python3
"""
MCP Server for PGVectorRAGIndexer.

The server exposes PGVectorRAGIndexer to MCP-compatible AI agents over stdio.
It talks to the supported REST API instead of importing backend internals, so
MCP requests inherit the same authentication, visibility filtering, LanceDB
readiness behavior, and error handling as the desktop client.
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import requests

# Configure logging to stderr so it does not interfere with JSON-RPC on stdout.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("mcp_server")

DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_TIMEOUT_SECONDS = 7200


@dataclass(frozen=True)
class MCPConfig:
    """Runtime configuration for the REST-backed MCP tools."""

    api_base: str
    api_key: Optional[str] = None
    timeout: int = DEFAULT_TIMEOUT_SECONDS


class MCPAPIError(Exception):
    """Raised when the PGVectorRAGIndexer API returns an error."""

    def __init__(self, message: str, *, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class MCPAPIClient:
    """Small REST client used by the MCP tool implementations."""

    def __init__(self, config: MCPConfig):
        self.config = config
        self.session = requests.Session()
        if config.api_key:
            self.session.headers.update({"X-API-Key": config.api_key})

    def search(
        self,
        *,
        query: str,
        top_k: int,
        use_hybrid: bool,
        source: str,
    ) -> dict[str, Any]:
        payload = {
            "query": query,
            "top_k": top_k,
            "use_hybrid": use_hybrid,
            "source": source,
        }
        return self._request("POST", "/search", json=payload).json()

    def upload_and_index(
        self,
        *,
        path: Path,
        force: bool,
        document_type: Optional[str],
    ) -> dict[str, Any]:
        data: dict[str, str] = {
            "force_reindex": str(force).lower(),
            "custom_source_uri": str(path),
        }
        if document_type:
            data["document_type"] = document_type

        with path.open("rb") as handle:
            files = {"file": (path.name, handle)}
            return self._request(
                "POST",
                "/upload-and-index",
                files=files,
                data=data,
            ).json()

    def list_documents(self, *, limit: int) -> dict[str, Any]:
        return self._request(
            "GET",
            "/documents",
            params={"limit": limit, "offset": 0, "sort_by": "indexed_at", "sort_dir": "desc"},
        ).json()

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        url = f"{self.config.api_base}{path}"
        kwargs.setdefault("timeout", self.config.timeout)
        try:
            response = self.session.request(method, url, **kwargs)
        except requests.exceptions.RequestException as exc:
            raise MCPAPIError(
                f"Could not reach PGVectorRAGIndexer API at {self.config.api_base}: {exc}"
            ) from exc

        if response.status_code >= 400:
            raise MCPAPIError(
                _extract_api_error(response),
                status_code=response.status_code,
            )
        return response


_api_client: Optional[MCPAPIClient] = None


def load_config() -> MCPConfig:
    """Load MCP configuration from environment variables."""

    base_url = _first_env(
        "PGVECTOR_MCP_BASE_URL",
        "PGVECTOR_API_BASE_URL",
        "PGVECTOR_API_URL",
        default=DEFAULT_BASE_URL,
    )
    api_key = _first_env(
        "PGVECTOR_MCP_API_KEY",
        "PGVECTOR_API_KEY",
        "PGVECTOR_API_TOKEN",
        default="",
    )
    timeout_raw = _first_env(
        "PGVECTOR_MCP_TIMEOUT",
        "PGVECTOR_API_TIMEOUT",
        default=str(DEFAULT_TIMEOUT_SECONDS),
    )
    try:
        timeout = int(timeout_raw)
    except (TypeError, ValueError):
        logger.warning("Invalid MCP API timeout %r; using %s", timeout_raw, DEFAULT_TIMEOUT_SECONDS)
        timeout = DEFAULT_TIMEOUT_SECONDS

    return MCPConfig(
        api_base=_normalize_api_base(base_url),
        api_key=api_key or None,
        timeout=timeout,
    )


def _get_api_client() -> MCPAPIClient:
    global _api_client
    if _api_client is None:
        _api_client = MCPAPIClient(load_config())
    return _api_client


def _first_env(*names: str, default: str) -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return default


def _normalize_api_base(base_url: str) -> str:
    normalized = (base_url or DEFAULT_BASE_URL).rstrip("/")
    if normalized.endswith("/api/v1"):
        return normalized
    return f"{normalized}/api/v1"


def _extract_api_error(response: requests.Response) -> str:
    prefix = f"PGVectorRAGIndexer API error ({response.status_code})"
    try:
        data = response.json()
    except ValueError:
        return f"{prefix}: {response.text[:300]}" if response.text else prefix

    if isinstance(data, dict):
        detail = data.get("message") or data.get("detail") or data.get("error")
        if detail:
            return f"{prefix}: {detail}"
    return prefix


# ================ TOOL IMPLEMENTATIONS ================
# These functions are tested independently of the MCP runtime.


def search_documents_impl(
    query: str,
    top_k: int = 5,
    use_hybrid: bool = False,
    source: str = "lancedb",
) -> dict[str, Any]:
    """Search visible indexed documents through the public REST API."""

    logger.info("Searching via API: query=%r top_k=%s hybrid=%s source=%s", query, top_k, use_hybrid, source)
    try:
        data = _get_api_client().search(
            query=query,
            top_k=top_k,
            use_hybrid=use_hybrid,
            source=source,
        )
        results = data.get("results", [])
        return {
            "ok": True,
            "query": data.get("query", query),
            "total_results": data.get("total_results", len(results)),
            "search_time_ms": data.get("search_time_ms"),
            "message": data.get("message"),
            "diagnostics": data.get("diagnostics"),
            "results": [_format_search_result(row, rank) for rank, row in enumerate(results, 1)],
        }
    except Exception as exc:
        logger.error("Search failed: %s", exc)
        return _error_result("search", exc)


def index_document_impl(
    path: str,
    force: bool = False,
    document_type: Optional[str] = None,
) -> dict[str, Any]:
    """Upload and index a local file through the public REST API."""

    logger.info("Indexing via API upload: path=%r force=%s type=%s", path, force, document_type)
    file_path = Path(path).expanduser()
    if not file_path.exists() or not file_path.is_file():
        return {
            "ok": False,
            "operation": "index",
            "error": f"File not found at {path}",
        }

    try:
        data = _get_api_client().upload_and_index(
            path=file_path,
            force=force,
            document_type=document_type,
        )
        return {
            "ok": data.get("status") != "error",
            "status": data.get("status"),
            "document_id": data.get("document_id"),
            "source_uri": data.get("source_uri") or str(file_path),
            "chunks_indexed": data.get("chunks_indexed"),
            "message": data.get("message"),
            "indexed_at": data.get("indexed_at"),
        }
    except Exception as exc:
        logger.error("Indexing failed: %s", exc)
        return _error_result("index", exc)


def list_documents_impl(limit: int = 20) -> dict[str, Any]:
    """List visible indexed documents through the public REST API."""

    logger.info("Listing documents via API: limit=%s", limit)
    try:
        data = _get_api_client().list_documents(limit=limit)
        documents = data.get("items") or data.get("documents") or []
        return {
            "ok": True,
            "total": data.get("total", len(documents)),
            "limit": data.get("limit", limit),
            "offset": data.get("offset", 0),
            "documents": [_format_document(row) for row in documents],
        }
    except Exception as exc:
        logger.error("Listing failed: %s", exc)
        return _error_result("list_documents", exc)


def _format_search_result(row: dict[str, Any], rank: int) -> dict[str, Any]:
    score = row.get("rank_score")
    if score is None:
        score = row.get("relevance_score")
    if score is None:
        score = row.get("distance")
    return {
        "rank": rank,
        "document_id": row.get("document_id"),
        "chunk_id": row.get("chunk_id"),
        "chunk_index": row.get("chunk_index"),
        "source_uri": row.get("source_uri"),
        "document_type": row.get("document_type"),
        "score": score,
        "rank_score": row.get("rank_score"),
        "relevance_score": row.get("relevance_score"),
        "distance": row.get("distance"),
        "metadata": row.get("metadata") or {},
        "text": (row.get("text_content") or "").strip(),
    }


def _format_document(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "document_id": row.get("document_id"),
        "source_uri": row.get("source_uri"),
        "document_type": row.get("document_type"),
        "chunk_count": row.get("chunk_count"),
        "indexed_at": row.get("indexed_at"),
        "last_updated": row.get("last_updated"),
        "visibility": row.get("visibility"),
        "owner_id": row.get("owner_id"),
        "metadata": row.get("metadata") or {},
    }


def _error_result(operation: str, exc: Exception) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": False,
        "operation": operation,
        "error": str(exc),
    }
    status_code = getattr(exc, "status_code", None)
    if status_code is not None:
        result["status_code"] = status_code
    return result


# ================ MCP SERVER SETUP ================
# Only executed when running as main script (not during imports/tests).


def create_mcp_server():
    """Create and configure the MCP server with tools."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        logger.error("Failed to import 'mcp'. Please install it: pip install mcp")
        sys.exit(1)

    mcp = FastMCP("PGVectorRAGIndexer")

    @mcp.tool()
    def search_documents(
        query: str,
        top_k: int = 5,
        use_hybrid: bool = False,
        source: str = "lancedb",
    ) -> dict[str, Any]:
        """Search visible indexed documents using the configured PGVectorRAGIndexer API."""
        return search_documents_impl(query, top_k, use_hybrid, source)

    @mcp.tool()
    def index_document(
        path: str,
        force: bool = False,
        document_type: Optional[str] = None,
    ) -> dict[str, Any]:
        """Upload and index a local document via the configured PGVectorRAGIndexer API."""
        return index_document_impl(path, force, document_type)

    @mcp.tool()
    def list_documents(limit: int = 20) -> dict[str, Any]:
        """List visible indexed documents from the configured PGVectorRAGIndexer API."""
        return list_documents_impl(limit)

    return mcp


if __name__ == "__main__":
    config = load_config()
    logger.info("Starting MCP Server against %s", config.api_base)
    mcp = create_mcp_server()
    mcp.run()
