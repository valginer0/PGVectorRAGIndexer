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


def _paginated_payload(items, *, total=None, limit=100, offset=0, sort_by="indexed_at", sort_dir="desc"):
    calculated_total = total if total is not None else len(items)
    return {
        "items": items,
        "total": calculated_total,
        "limit": limit,
        "offset": offset,
        "sort": {"by": sort_by, "direction": sort_dir},
    }


def test_documents_tab_displays_document_type(qapp, monkeypatch):
    class FakeApi:
        def is_api_available(self):
            return True

        def list_documents(self, **_kwargs):
            return _paginated_payload([
                {
                    "document_id": "doc-1",
                    "source_uri": "C:/tmp/doc-1.txt",
                    "chunk_count": 3,
                    "indexed_at": "2025-01-01T12:00:00Z",
                    "last_updated": "2025-01-01T12:00:00Z",
                    "metadata": {"type": "resume"},
                }
            ])

    monkeypatch.setattr(DocumentsTab, "load_documents", lambda self: None)
    api = FakeApi()
    tab = DocumentsTab(api_client=api)

    response = api.list_documents()
    tab.documents_loaded(True, response)

    assert tab.documents_table.rowCount() == 1
    assert tab.documents_table.item(0, 1).text() == "resume"


def test_documents_tab_updates_status_with_pagination(qapp, monkeypatch):
    class FakeApi:
        def is_api_available(self):
            return True

        def list_documents(self, **_kwargs):
            return _paginated_payload(
                [
                    {
                        "document_id": "doc-3",
                        "source_uri": "C:/tmp/doc-3.txt",
                        "chunk_count": 1,
                        "indexed_at": "2025-01-03T12:00:00Z",
                        "last_updated": "2025-01-03T12:00:00Z",
                        "metadata": {"type": "report"},
                    },
                    {
                        "document_id": "doc-4",
                        "source_uri": "C:/tmp/doc-4.txt",
                        "chunk_count": 2,
                        "indexed_at": "2025-01-04T12:00:00Z",
                        "last_updated": "2025-01-04T12:00:00Z",
                        "metadata": {"type": "memo"},
                    },
                ],
                total=5,
                limit=2,
                offset=2,
            )

    monkeypatch.setattr(DocumentsTab, "load_documents", lambda self: None)
    api = FakeApi()
    tab = DocumentsTab(api_client=api)

    response = api.list_documents()
    tab.documents_loaded(True, response)

    assert tab.documents_table.rowCount() == 2
    assert tab.status_label.text() == "Showing 3-4 of 5 documents (Page 2 of 3)"


def test_change_page_requests_next_when_total_missing(qapp, monkeypatch):
    class FakeApi:
        def is_api_available(self):
            return True

        def list_documents(self, **_kwargs):
            return []

    # Prevent auto-loading during widget construction
    monkeypatch.setattr(DocumentsTab, "load_documents", lambda self, reset_offset=False: None)

    api = FakeApi()
    tab = DocumentsTab(api_client=api)

    # Simulate a full page response without total metadata
    page_size = tab.page_size
    items = [
        {
            "document_id": f"doc-{i}",
            "source_uri": f"C:/tmp/doc-{i}.txt",
            "chunk_count": 1,
            "indexed_at": "2025-10-01T12:00:00Z",
        }
        for i in range(page_size)
    ]

    tab.documents_loaded(True, items)

    load_calls = []

    def capture_load(self, *, reset_offset=False):
        load_calls.append({
            "offset": self.current_offset,
            "limit": self.page_size,
            "reset": reset_offset,
        })

    monkeypatch.setattr(DocumentsTab, "load_documents", capture_load)

    tab.change_page(1)

    assert load_calls, "Expected next-page navigation to trigger a reload"
    assert load_calls[-1]["offset"] == page_size
    assert tab.current_offset == page_size
