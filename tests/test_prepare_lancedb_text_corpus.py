from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def load_prepare_module():
    root = Path(__file__).resolve().parents[1]
    module_path = root / "scripts" / "prepare_lancedb_text_corpus.py"
    spec = importlib.util.spec_from_file_location("prepare_lancedb_text_corpus", module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeLoader:
    def __init__(self):
        self.calls = []

    def load(self, source_uri, ocr_mode="skip"):
        self.calls.append((Path(source_uri).name, ocr_mode))
        return [SimpleNamespace(page_content=f"Extracted text from {Path(source_uri).name}")]


class FakeProcessor:
    def __init__(self):
        self.config = SimpleNamespace(
            supported_extensions=[".txt", ".md", ".pdf"],
            supported_filenames=["LICENSE"],
        )
        self.loader = FakeLoader()

    def _validate_source(self, source_uri):
        if not Path(source_uri).exists():
            raise FileNotFoundError(source_uri)

    def _get_loader(self, source_uri):
        return self.loader

    def _has_loaded_content(self, documents):
        return any((document.page_content or "").strip() for document in documents)

    def _metadata_fallback_document(self, source_uri, custom_metadata):
        return SimpleNamespace(page_content=f"Fallback for {Path(source_uri).name}")


def test_prepare_text_corpus_mirrors_supported_files_and_manifest(tmp_path):
    prep = load_prepare_module()
    source_dir = tmp_path / "source"
    output_dir = tmp_path / "out"
    manifest_path = tmp_path / "manifest.json"
    (source_dir / "docs" / "api").mkdir(parents=True)
    (source_dir / "docs" / "api" / "README.md").write_text("markdown", encoding="utf-8")
    (source_dir / "reports").mkdir()
    (source_dir / "reports" / "report.pdf").write_bytes(b"%PDF fake")
    (source_dir / "image.bin").write_bytes(b"binary")

    fake_processor = FakeProcessor()
    manifest = prep.prepare_text_corpus(
        source_dir=source_dir,
        output_dir=output_dir,
        manifest_json=manifest_path,
        ocr_mode="skip",
        processor=fake_processor,
    )

    assert manifest["converted_count"] == 2
    assert manifest["skipped_count"] == 1
    assert (output_dir / "docs" / "api" / "README.md.txt").read_text(encoding="utf-8") == (
        "Extracted text from README.md\n"
    )
    assert (output_dir / "reports" / "report.pdf.txt").read_text(encoding="utf-8") == (
        "Extracted text from report.pdf\n"
    )
    assert manifest["skipped"][0]["relative_path"] == "image.bin"
    assert manifest["skipped"][0]["reason"] == "unsupported_extension"
    assert fake_processor.loader.calls == [("README.md", "skip"), ("report.pdf", "skip")]

    saved = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert saved["converted"][0]["output_relative_path"] == "docs/api/README.md.txt"
    assert saved["converted"][1]["output_relative_path"] == "reports/report.pdf.txt"


def test_prepare_text_corpus_rejects_output_inside_source(tmp_path):
    prep = load_prepare_module()
    source_dir = tmp_path / "source"
    source_dir.mkdir()

    with pytest.raises(ValueError, match="output-dir must not"):
        prep.prepare_text_corpus(
            source_dir=source_dir,
            output_dir=source_dir / "converted",
            processor=FakeProcessor(),
        )


def test_extract_source_text_uses_metadata_fallback_for_empty_documents(tmp_path):
    prep = load_prepare_module()
    source = tmp_path / "empty.pdf"
    source.write_bytes(b"%PDF fake")

    class EmptyLoader:
        def load(self, source_uri, ocr_mode="skip"):
            return [SimpleNamespace(page_content="   ")]

    processor = FakeProcessor()
    processor.loader = EmptyLoader()

    assert prep.extract_source_text(processor, source, ocr_mode="skip") == "Fallback for empty.pdf"


def test_output_path_appends_txt_without_losing_original_extension(tmp_path):
    prep = load_prepare_module()
    source_root = tmp_path / "source"
    output_root = tmp_path / "out"
    source = source_root / "reports" / "report.pdf"
    source.parent.mkdir(parents=True)
    source.touch()

    assert prep.output_path_for_source(source, source_root, output_root) == (
        output_root / "reports" / "report.pdf.txt"
    )
