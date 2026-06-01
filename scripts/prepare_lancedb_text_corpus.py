#!/usr/bin/env python
"""Prepare a text-only corpus for local LanceDB scale validation.

This is a validation helper, not the desktop product ingestion path. It reuses
the existing backend document loaders to extract text from mixed file formats
and writes a mirrored ``.txt`` corpus that can be consumed by
``validate_lancedb_local_desktop.py``.
"""

from __future__ import annotations

import argparse
import inspect
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

EXCLUDED_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "venv-windows",
    "node_modules",
}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--manifest-json",
        type=Path,
        help="Defaults to <output-dir>/conversion_manifest.json",
    )
    parser.add_argument(
        "--ocr-mode",
        choices=("skip", "auto", "only"),
        default="skip",
        help="Default is skip so Gate 2b prep does not depend on OCR tooling.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Delete and recreate output-dir before writing converted text files.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        manifest = prepare_text_corpus(
            source_dir=args.source_dir,
            output_dir=args.output_dir,
            manifest_json=args.manifest_json,
            ocr_mode=args.ocr_mode,
            overwrite=args.overwrite,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(
        "Prepared LanceDB text corpus: "
        f"{manifest['converted_count']} converted, "
        f"{manifest['skipped_count']} skipped -> {manifest['output_dir']}"
    )
    if manifest["converted_count"] == 0:
        return 1
    return 0


def prepare_text_corpus(
    *,
    source_dir: Path,
    output_dir: Path,
    manifest_json: Path | None = None,
    ocr_mode: str = "skip",
    overwrite: bool = False,
    processor: Any | None = None,
) -> dict[str, Any]:
    source_root = source_dir.resolve()
    output_root = output_dir.resolve()
    if not source_root.exists() or not source_root.is_dir():
        raise FileNotFoundError(f"source-dir does not exist or is not a directory: {source_dir}")
    if source_root == output_root or _is_relative_to(output_root, source_root):
        raise ValueError("output-dir must not be the same as source-dir or inside source-dir")
    if overwrite and output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    document_processor_symbols = _load_document_processor_symbols()
    DocumentProcessor = document_processor_symbols["DocumentProcessor"]
    DocumentProcessingError = document_processor_symbols["DocumentProcessingError"]
    EncryptedPDFError = document_processor_symbols["EncryptedPDFError"]
    LoaderError = document_processor_symbols["LoaderError"]
    UnsupportedFormatError = document_processor_symbols["UnsupportedFormatError"]

    processor = processor or DocumentProcessor()
    supported_extensions = {
        str(ext).lower()
        for ext in getattr(processor.config, "supported_extensions", [])
    }
    supported_filenames = {
        str(name)
        for name in getattr(processor.config, "supported_filenames", [])
    }

    converted: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for source_path in iter_source_files(source_root):
        relative_path = source_path.relative_to(source_root).as_posix()
        if not _is_supported_source(source_path, supported_extensions, supported_filenames):
            skipped.append(_skip(source_path, relative_path, "unsupported_extension"))
            continue

        output_path = output_path_for_source(source_path, source_root, output_root)
        try:
            text = extract_source_text(processor, source_path, ocr_mode=ocr_mode)
        except EncryptedPDFError as exc:
            skipped.append(_skip(source_path, relative_path, "encrypted_pdf", exc))
            continue
        except UnsupportedFormatError as exc:
            skipped.append(_skip(source_path, relative_path, "unsupported_format", exc))
            continue
        except (DocumentProcessingError, LoaderError) as exc:
            skipped.append(_skip(source_path, relative_path, "processing_error", exc))
            continue
        except Exception as exc:
            skipped.append(_skip(source_path, relative_path, "unexpected_error", exc))
            continue

        if not text.strip():
            skipped.append(_skip(source_path, relative_path, "empty_text"))
            continue

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text.rstrip() + "\n", encoding="utf-8")
        converted.append(
            {
                "source_path": str(source_path),
                "relative_path": relative_path,
                "output_path": str(output_path),
                "output_relative_path": output_path.relative_to(output_root).as_posix(),
                "char_count": len(text),
            }
        )

    manifest = {
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source_dir": str(source_root),
        "output_dir": str(output_root),
        "ocr_mode": ocr_mode,
        "converted_count": len(converted),
        "skipped_count": len(skipped),
        "converted": converted,
        "skipped": skipped,
    }
    manifest_path = manifest_json or output_root / "conversion_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def iter_source_files(source_root: Path) -> list[Path]:
    paths: list[Path] = []
    for root, dirnames, filenames in os.walk(source_root):
        dirnames[:] = [
            name for name in dirnames
            if name not in EXCLUDED_DIR_NAMES and not name.startswith(".")
        ]
        root_path = Path(root)
        for filename in filenames:
            paths.append(root_path / filename)
    return sorted(paths, key=lambda path: path.relative_to(source_root).as_posix().lower())


def output_path_for_source(source_path: Path, source_root: Path, output_root: Path) -> Path:
    relative_path = source_path.relative_to(source_root)
    return output_root / relative_path.with_name(relative_path.name + ".txt")


def extract_source_text(
    processor: Any,
    source_path: Path,
    *,
    ocr_mode: str,
) -> str:
    source_uri = str(source_path)
    processor._validate_source(source_uri)
    loader = processor._get_loader(source_uri)
    if not loader:
        raise _new_document_processing_error(
            "UnsupportedFormatError",
            f"No loader available for: {source_uri}",
        )

    signature = inspect.signature(loader.load)
    if "ocr_mode" in signature.parameters:
        documents = loader.load(source_uri, ocr_mode=ocr_mode)
    else:
        documents = loader.load(source_uri)

    for document in documents:
        if getattr(document, "page_content", None):
            document.page_content = document.page_content.replace("\x00", "")

    if not processor._has_loaded_content(documents):
        fallback_doc = processor._metadata_fallback_document(source_uri, None)
        if fallback_doc:
            documents = [fallback_doc]
        else:
            raise _new_document_processing_error(
                "LoaderError",
                "No content loaded from document",
            )

    return "\n\n".join(
        document.page_content.strip()
        for document in documents
        if getattr(document, "page_content", "").strip()
    )


def _load_document_processor_symbols() -> dict[str, Any]:
    from document_processor import (
        DocumentProcessor,
        DocumentProcessingError,
        EncryptedPDFError,
        LoaderError,
        UnsupportedFormatError,
    )

    return {
        "DocumentProcessor": DocumentProcessor,
        "DocumentProcessingError": DocumentProcessingError,
        "EncryptedPDFError": EncryptedPDFError,
        "LoaderError": LoaderError,
        "UnsupportedFormatError": UnsupportedFormatError,
    }


def _new_document_processing_error(name: str, message: str) -> Exception:
    return _load_document_processor_symbols()[name](message)


def _is_supported_source(
    source_path: Path,
    supported_extensions: set[str],
    supported_filenames: set[str],
) -> bool:
    return (
        source_path.suffix.lower() in supported_extensions
        or source_path.name in supported_filenames
    )


def _skip(
    source_path: Path,
    relative_path: str,
    reason: str,
    exc: Exception | None = None,
) -> dict[str, str]:
    item = {
        "source_path": str(source_path),
        "relative_path": relative_path,
        "reason": reason,
    }
    if exc is not None:
        item["error"] = str(exc)
    return item


def _is_relative_to(path: Path, other: Path) -> bool:
    try:
        path.relative_to(other)
        return True
    except ValueError:
        return False


if __name__ == "__main__":
    raise SystemExit(main())
