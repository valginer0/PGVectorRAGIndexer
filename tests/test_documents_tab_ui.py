import sys
import pytest

# Skip if PySide6 is unavailable in CI environment
pytestmark = pytest.mark.skipif(
    pytest.importorskip("PySide6", reason="PySide6 not installed for UI tests") is None,
    reason="PySide6 not installed"
)

from PySide6.QtWidgets import QApplication
from desktop_app.ui.documents_tab import DocumentsTab


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_documents_tab_displays_document_type(qapp):
    class FakeApi:
        def is_api_available(self):
            return True
        def list_documents(self):
            return [
                {
                    "document_id": "doc-1",
                    "source_uri": "C:/tmp/doc-1.txt",
                    "chunk_count": 3,
                    "indexed_at": "2025-01-01T12:00:00Z",
                    "last_updated": "2025-01-01T12:00:00Z",
                    "metadata": {"type": "resume"},
                }
            ]

    tab = DocumentsTab(api_client=FakeApi())
    docs = tab.api_client.list_documents()
    tab.display_documents(docs)

    assert tab.documents_table.rowCount() == 1
    # Column order: 0 Source URI, 1 Document Type, 2 Chunks, 3 Created, 4 Updated, 5 Actions
    assert tab.documents_table.item(0, 1).text() == "resume"
