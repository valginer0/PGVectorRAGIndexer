from pathlib import Path
import shutil

import pytest

from document_processor import OfficeDocumentLoader


@pytest.mark.skipif(
    not any(shutil.which(cmd) for cmd in ("soffice", "libreoffice")),
    reason="LibreOffice binary not available on host",
)
def test_office_loader_detects_libreoffice():
    loader = OfficeDocumentLoader()
    binary = loader._find_converter_command()

    assert binary, "Expected OfficeDocumentLoader to locate LibreOffice executable"
    assert Path(binary).exists(), "Discovered LibreOffice path must exist on disk"
