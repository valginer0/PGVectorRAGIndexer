import os
from pathlib import Path

import pytest

from desktop_app.ui.upload_tab import UploadTab


def test_build_documents_filter_includes_doc_extension():
    filter_string = UploadTab._build_documents_filter()
    assert "*.doc" in filter_string


def test_find_supported_files_discovers_doc(tmp_path: Path):
    doc_path = tmp_path / "resume.doc"
    doc_path.write_text("dummy")

    other_path = tmp_path / "notes.txt"
    other_path.write_text("dummy")

    # Add an unsupported file to ensure it is ignored
    (tmp_path / "image.jpg").write_text("dummy")

    found = UploadTab._find_supported_files(tmp_path)
    found_paths = {p.resolve() for p in found}

    assert doc_path.resolve() in found_paths
    assert other_path.resolve() in found_paths
    # No unsupported extensions should be returned
    assert all(p.suffix.lower() in UploadTab.SUPPORTED_EXTENSIONS for p in found)
