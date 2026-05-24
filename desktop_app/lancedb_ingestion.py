"""Local file ingestion adapter for the desktop LanceDB search engine.

This module is intentionally UI-free. It converts local text files into
``LocalDocument`` objects and delegates indexing to ``LocalLanceDBEngine``.
Broader extraction formats still belong to the existing backend/API pipeline
until the desktop LanceDB path is explicitly expanded.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, Sequence

from .lancedb_engine import IngestionStats, LocalDocument


SUPPORTED_LOCAL_TEXT_EXTENSIONS = {".txt", ".md", ".markdown"}
DEFAULT_TEXT_ENCODINGS = ("utf-8-sig", "utf-8", "cp1252", "latin-1")


class LanceDBIngestionEngine(Protocol):
    def ingest_documents(
        self,
        documents: Sequence[LocalDocument],
        *,
        chunk_size: int = 1200,
        chunk_overlap: int = 120,
        mode: str = "overwrite",
    ) -> IngestionStats:
        ...


@dataclass(frozen=True)
class SkippedLocalFile:
    path: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "reason": self.reason}


@dataclass(frozen=True)
class LocalTextCorpus:
    documents: list[LocalDocument]
    skipped_files: list[SkippedLocalFile] = field(default_factory=list)

    @property
    def document_count(self) -> int:
        return len(self.documents)

    @property
    def skipped_count(self) -> int:
        return len(self.skipped_files)


@dataclass(frozen=True)
class LocalLanceDBIngestionResult:
    stats: IngestionStats
    indexed_documents: int
    skipped_files: list[SkippedLocalFile] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_count": self.stats.source_count,
            "chunk_count": self.stats.chunk_count,
            "db_path": self.stats.db_path,
            "indexed_documents": self.indexed_documents,
            "skipped_files": [skipped.to_dict() for skipped in self.skipped_files],
        }


class LocalTextIngestionError(ValueError):
    """Raised when no local text files can be prepared for LanceDB ingestion."""


def build_local_text_corpus(
    paths: Sequence[str | Path],
    *,
    recursive: bool = True,
    supported_extensions: set[str] | None = None,
    encodings: Sequence[str] = DEFAULT_TEXT_ENCODINGS,
) -> LocalTextCorpus:
    """Build a stable local text corpus from files and/or folders."""
    if not paths:
        raise LocalTextIngestionError("at least one local path is required")

    extensions = {
        extension.lower()
        for extension in (supported_extensions or SUPPORTED_LOCAL_TEXT_EXTENSIONS)
    }
    documents: list[LocalDocument] = []
    skipped: list[SkippedLocalFile] = []

    for candidate in _iter_candidate_files(paths, recursive=recursive):
        if candidate.name.startswith("~$"):
            skipped.append(_skip(candidate, "temporary_office_file"))
            continue
        if candidate.suffix.lower() not in extensions:
            skipped.append(_skip(candidate, "unsupported_extension"))
            continue
        try:
            text, encoding = _read_text(candidate, encodings=encodings)
        except UnicodeDecodeError:
            skipped.append(_skip(candidate, "decode_error"))
            continue
        except OSError as exc:
            skipped.append(_skip(candidate, f"read_error: {exc}"))
            continue

        if not text.strip():
            skipped.append(_skip(candidate, "empty_text"))
            continue

        resolved = candidate.resolve()
        documents.append(
            LocalDocument(
                source_uri=str(resolved),
                text=text,
                metadata={
                    "source_uri": str(resolved),
                    "file_name": candidate.name,
                    "file_extension": candidate.suffix.lower(),
                    "file_size": candidate.stat().st_size,
                    "encoding": encoding,
                    "ingestion_source": "local_text_adapter",
                },
            )
        )

    documents.sort(key=lambda doc: doc.source_uri.lower())
    skipped.sort(key=lambda item: item.path.lower())
    return LocalTextCorpus(documents=documents, skipped_files=skipped)


def ingest_local_text_paths(
    engine: LanceDBIngestionEngine,
    paths: Sequence[str | Path],
    *,
    recursive: bool = True,
    chunk_size: int = 1200,
    chunk_overlap: int = 120,
    mode: str = "overwrite",
) -> LocalLanceDBIngestionResult:
    """Collect supported local text files and index them into LanceDB."""
    corpus = build_local_text_corpus(paths, recursive=recursive)
    if not corpus.documents:
        raise LocalTextIngestionError("no supported non-empty local text files found")

    stats = engine.ingest_documents(
        corpus.documents,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        mode=mode,
    )
    return LocalLanceDBIngestionResult(
        stats=stats,
        indexed_documents=len(corpus.documents),
        skipped_files=corpus.skipped_files,
    )


def _iter_candidate_files(
    paths: Sequence[str | Path],
    *,
    recursive: bool,
) -> list[Path]:
    candidates: list[Path] = []
    for raw_path in paths:
        path = Path(raw_path)
        if path.is_file():
            candidates.append(path)
            continue
        if path.is_dir():
            iterator = path.rglob("*") if recursive else path.iterdir()
            candidates.extend(item for item in iterator if item.is_file())
            continue
        candidates.append(path)
    return sorted(candidates, key=lambda item: str(item).lower())


def _read_text(path: Path, *, encodings: Sequence[str]) -> tuple[str, str]:
    last_decode_error: UnicodeDecodeError | None = None
    for encoding in encodings:
        try:
            return path.read_text(encoding=encoding), encoding
        except UnicodeDecodeError as exc:
            last_decode_error = exc
    if last_decode_error:
        raise last_decode_error
    raise UnicodeDecodeError("utf-8", b"", 0, 1, "no text encodings configured")


def _skip(path: Path, reason: str) -> SkippedLocalFile:
    try:
        rendered = str(path.resolve())
    except OSError:
        rendered = os.fspath(path)
    return SkippedLocalFile(path=rendered, reason=reason)
