#!/usr/bin/env python3
"""Profile bulk document uploads via the /upload-and-index API."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

import requests

SUPPORTED_EXTENSIONS = {
    ".txt",
    ".md",
    ".pdf",
    ".doc",
    ".docx",
    ".pptx",
    ".ppt",
    ".html",
    ".htm",
}


def iter_supported_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
            yield path


@dataclass
class UploadResult:
    path: Path
    elapsed: float
    status: str
    chunks_indexed: int
    message: Optional[str]

    def to_dict(self) -> dict:
        return {
            "path": str(self.path),
            "elapsed_seconds": self.elapsed,
            "status": self.status,
            "chunks_indexed": self.chunks_indexed,
            "message": self.message,
        }


def canonical_source_uri(path: Path) -> str:
    """Return a canonical source URI string for hashing consistency."""
    try:
        resolved = path.resolve()
    except FileNotFoundError:
        resolved = path.absolute()

    path_str = str(resolved)

    # Normalize WSL mount points (/mnt/c/...) to Windows-style paths
    if path_str.startswith("/mnt/") and len(path_str) > 6:
        drive_letter = path_str[5]
        if drive_letter.isalpha() and path_str[6] == "/":
            remainder = path_str[7:].replace("/", "\\")
            return f"{drive_letter.upper()}:\\{remainder}"

    # Preserve Windows paths and UNC shares as-is for desktop parity
    if os.name == "nt" or path_str.startswith("\\"):
        return path_str

    return path_str


def upload_file(
    session: requests.Session,
    base_url: str,
    path: Path,
    force_reindex: bool,
    document_type: Optional[str],
    timeout: float,
) -> UploadResult:
    url = f"{base_url.rstrip('/')}/upload-and-index"
    data = {"force_reindex": str(force_reindex).lower()}
    if document_type:
        data["document_type"] = document_type

    data["custom_source_uri"] = canonical_source_uri(path)

    with path.open("rb") as file_handle:
        files = {"file": (path.name, file_handle)}
        start = time.perf_counter()
        response = session.post(url, files=files, data=data, timeout=timeout)
        elapsed = time.perf_counter() - start

    response.raise_for_status()
    payload = response.json()
    status = payload.get("status", "unknown")
    chunks = int(payload.get("chunks_indexed", 0))
    message = payload.get("message")
    return UploadResult(path=path, elapsed=elapsed, status=status, chunks_indexed=chunks, message=message)


def ensure_health(base_url: str, timeout: float = 5.0) -> None:
    url = f"{base_url.rstrip('/')}/health"
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()


def profile_bulk_upload(
    source_dir: Path,
    base_url: str,
    force_reindex: bool,
    document_type: Optional[str],
    timeout: float,
) -> List[UploadResult]:
    ensure_health(base_url)

    files = list(iter_supported_files(source_dir))
    if not files:
        raise SystemExit(f"No supported files found under {source_dir}")

    print(f"Found {len(files)} supported files under {source_dir}")
    results: List[UploadResult] = []
    session = requests.Session()

    for idx, path in enumerate(files, start=1):
        print(f"[{idx}/{len(files)}] Uploading {path}")
        try:
            result = upload_file(session, base_url, path, force_reindex, document_type, timeout)
            status = result.status
            print(f"    -> status={status} chunks={result.chunks_indexed} time={result.elapsed:.2f}s")
        except requests.HTTPError as exc:
            elapsed = exc.response.elapsed.total_seconds() if exc.response and exc.response.elapsed else 0.0
            message = str(exc)
            print(f"    !! HTTP error after {elapsed:.2f}s: {message}")
            results.append(UploadResult(path=path, elapsed=elapsed, status="http_error", chunks_indexed=0, message=message))
            continue
        except requests.RequestException as exc:
            print(f"    !! Request failed: {exc}")
            results.append(UploadResult(path=path, elapsed=0.0, status="network_error", chunks_indexed=0, message=str(exc)))
            continue

        results.append(result)

    return results


def summarize(results: List[UploadResult]) -> None:
    total_time = sum(r.elapsed for r in results)
    successes = [r for r in results if r.status == "success"]
    skipped = [r for r in results if r.status == "skipped"]
    errors = [r for r in results if r.status not in {"success", "skipped"}]

    print("\n=== Summary ===")
    print(f"Total elapsed: {total_time:.2f}s")
    if results:
        print(f"Average per file: {total_time / len(results):.2f}s")
    print(f"Success: {len(successes)}  Skipped: {len(skipped)}  Errors: {len(errors)}")


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Profile bulk uploads via /upload-and-index")
    parser.add_argument("source_dir", type=Path, help="Directory containing documents to upload")
    parser.add_argument("--base-url", default="http://localhost:8000", help="API base URL (default: %(default)s)")
    parser.add_argument("--force-reindex", action="store_true", help="Force reindex existing documents")
    parser.add_argument("--document-type", help="Document type to apply to all uploads")
    parser.add_argument("--timeout", type=float, default=300.0, help="Request timeout seconds (default: %(default)s)")
    parser.add_argument("--json", type=Path, help="Write raw timing data to JSON file")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv or sys.argv[1:])

    try:
        results = profile_bulk_upload(
            source_dir=args.source_dir.expanduser().resolve(),
            base_url=args.base_url,
            force_reindex=args.force_reindex,
            document_type=args.document_type,
            timeout=args.timeout,
        )
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1

    summarize(results)

    if args.json:
        payload = [r.to_dict() for r in results]
        args.json.write_text(json.dumps(payload, indent=2))
        print(f"Detailed output written to {args.json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
