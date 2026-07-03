import pytest

# Mark all tests in this file as slow (UI tests with QApplication)
pytestmark = pytest.mark.slow
from unittest.mock import MagicMock, patch
from pathlib import Path
from PySide6.QtWidgets import QApplication, QMessageBox, QTableWidgetItem
from PySide6.QtCore import Qt, QPoint

from desktop_app.ui.documents_tab import DocumentsTab

@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app

@pytest.fixture
def mock_api_client():
    client = MagicMock()
    client.is_api_available.return_value = True
    return client

@pytest.fixture
def mock_source_manager():
    return MagicMock()

@pytest.fixture
def documents_tab(qapp, mock_api_client):
    # Mock load_documents to prevent auto-load during init
    with patch("desktop_app.ui.documents_tab.DocumentsTab.load_documents"):
        tab = DocumentsTab(mock_api_client)
        tab.show()
        return tab

def test_initialization(documents_tab):
    """Test UI initialization."""
    assert documents_tab.api_client is not None
    assert hasattr(documents_tab, "documents_table")
    assert hasattr(documents_tab, "refresh_btn")
    assert hasattr(documents_tab, "page_size_combo")
    assert hasattr(documents_tab, "prev_page_btn")
    assert hasattr(documents_tab, "next_page_btn")
    assert documents_tab._view_mode == "tree"
    assert documents_tab._view_stack.currentIndex() == 0

def test_load_documents_success(documents_tab):
    """Test successful document loading."""
    documents_tab.is_loading = False
    
    with patch("desktop_app.ui.documents_tab.DocumentsWorker") as MockWorker:
        mock_worker_instance = MockWorker.return_value
        
        documents_tab.load_documents()
        
        MockWorker.assert_called_once()
        mock_worker_instance.start.assert_called_once()
        assert documents_tab.is_loading is True
        assert not documents_tab.refresh_btn.isEnabled()

def test_documents_loaded_success(documents_tab):
    """Test handling of loaded documents."""
    data = {
        "items": [
            {"document_id": "1", "source_uri": "/path/1", "chunk_count": 5, "indexed_at": "2023-01-01T12:00:00Z"},
            {"document_id": "2", "source_uri": "/path/2", "chunk_count": 3, "indexed_at": "2023-01-02T12:00:00Z"}
        ],
        "total": 10,
        "limit": 25,
        "offset": 0
    }
    
    documents_tab.documents_loaded(True, data)
    
    assert documents_tab.is_loading is False
    assert documents_tab.refresh_btn.isEnabled()
    assert documents_tab.documents_table.rowCount() == 2
    assert documents_tab.total_documents == 10
    # Default sort is indexed_at desc, so newer date (path/2) comes first
    assert documents_tab.documents_table.item(0, 0).text() == "/path/2"
    assert documents_tab.documents_table.item(0, 2).text() == "3"

def test_documents_loaded_failure(documents_tab):
    """Test handling of load failure."""
    with patch("PySide6.QtWidgets.QMessageBox.critical") as mock_crit:
        documents_tab.documents_loaded(False, "Error message")
        
        mock_crit.assert_called_once()
        assert documents_tab.is_loading is False
        assert documents_tab.refresh_btn.isEnabled()
        assert "failed" in documents_tab.status_label.text()

def test_pagination(documents_tab):
    """Test pagination logic."""
    documents_tab.total_documents = 100
    documents_tab.page_size = 25
    documents_tab.current_offset = 0
    
    # Test next page
    with patch.object(documents_tab, "load_documents") as mock_load:
        documents_tab.change_page(1)
        assert documents_tab.current_offset == 25
        mock_load.assert_called_once()
    
    # Test prev page
    documents_tab.current_offset = 25
    with patch.object(documents_tab, "load_documents") as mock_load:
        documents_tab.change_page(-1)
        assert documents_tab.current_offset == 0
        mock_load.assert_called_once()

def test_page_size_changed(documents_tab):
    """Test page size change."""
    documents_tab.page_size_combo.addItem("50")
    
    with patch.object(documents_tab, "load_documents") as mock_load:
        # Simulate index change to "50"
        index = documents_tab.page_size_combo.findText("50")
        documents_tab.on_page_size_changed(index)
        
        assert documents_tab.page_size == 50
        assert documents_tab.current_offset == 0
        mock_load.assert_called_once()

def test_sorting(documents_tab):
    """Test table sorting."""
    # Click on "Created" column (index 3)
    with patch.object(documents_tab, "load_documents") as mock_load:
        documents_tab.handle_header_clicked(3)
        
        assert documents_tab.sort_fields == ["indexed_at"]
        # Default for indexed_at is desc, so clicking it should toggle to asc? 
        # Wait, initial is desc.
        # Logic: if current_field == field: toggle.
        # Initial: ["indexed_at"], ["desc"]
        # Click 3 (indexed_at): toggle to asc.
        assert documents_tab.sort_directions == ["asc"]
        mock_load.assert_called_once()

def test_delete_document(documents_tab):
    """Test document deletion."""
    documents_tab.current_documents = [{"document_id": "1", "source_uri": "test.txt"}]
    
    with patch("PySide6.QtWidgets.QMessageBox.question", return_value=QMessageBox.Yes), \
         patch("desktop_app.ui.documents_tab.DeleteWorker") as MockWorker:
        
        mock_worker_instance = MockWorker.return_value
        
        documents_tab.delete_document("1")
        
        MockWorker.assert_called_once_with(documents_tab.api_client, "1")
        mock_worker_instance.start.assert_called_once()

def test_delete_finished_success(documents_tab):
    """Test delete completion success."""
    with patch("PySide6.QtWidgets.QMessageBox.information") as mock_info, \
         patch.object(documents_tab, "load_documents") as mock_load:
        
        documents_tab.delete_finished(True, "Deleted")
        
        mock_info.assert_called_once()
        mock_load.assert_called_once()

def test_context_menu(documents_tab, mock_source_manager):
    """Test context menu actions."""
    documents_tab.source_manager = mock_source_manager
    
    # Setup table
    documents_tab.documents_table.setRowCount(1)
    item = QTableWidgetItem("test")
    item.setData(Qt.UserRole, "/path/to/file")
    documents_tab.documents_table.setItem(0, 0, item)
    
    # Mock finding entry
    mock_entry = MagicMock()
    mock_entry.queued = False
    mock_source_manager.find_entry.return_value = mock_entry
    
    # Mock QMenu class
    with patch("desktop_app.ui.documents_tab.QMenu") as MockMenu, \
         patch.object(documents_tab.documents_table, "indexAt") as mock_index_at, \
         patch.object(documents_tab.documents_table, "item") as mock_item_method:
        
        # Setup MockMenu instance
        mock_menu_instance = MockMenu.return_value
        
        # Mock indexAt to return a valid index at column 0
        mock_index = MagicMock()
        mock_index.isValid.return_value = True
        mock_index.row.return_value = 0
        mock_index.column.return_value = 0
        mock_index_at.return_value = mock_index
        
        # Mock item return
        mock_item_method.return_value = item
        
        documents_tab.show_documents_context_menu(QPoint(0, 0))
        
        mock_index_at.assert_called_once()
        mock_item_method.assert_called_once()
        
        mock_source_manager.find_entry.assert_called_with("/path/to/file")
        mock_menu_instance.exec.assert_called_once()

def test_open_source_path_fallback(documents_tab):
    """Test open_source_path fallback logic."""
    documents_tab.source_manager = None
    
    with patch("pathlib.Path.exists", return_value=True), \
         patch("sys.platform", "linux"), \
         patch("subprocess.Popen") as mock_popen:
        
        documents_tab.open_source_path("/path/to/file")
        mock_popen.assert_called_once_with(["xdg-open", "/path/to/file"])

def test_documents_loaded_pagination_overshoot(documents_tab):
    """Test pagination overshoot handling."""
    documents_tab.current_offset = 100
    documents_tab._pending_offset = 100
    documents_tab.page_size = 25
    
    # Mock response indicating total is less than offset
    data = {
        "items": [],
        "total": 50,
        "limit": 25,
        "offset": 100
    }
    
    with patch.object(documents_tab, "load_documents") as mock_load:
        documents_tab.documents_loaded(True, data)
        
        # Should revert offset and reload
        # Logic: max_page_offset = (ceil(50/25) - 1) * 25 = (2-1)*25 = 25
        assert documents_tab.current_offset != 100, "Block was skipped"
        assert documents_tab.current_offset == 25
        mock_load.assert_called_once()

def test_update_pagination_state_estimated(documents_tab):
    """Test pagination state with estimated total."""
    documents_tab.total_documents = 50
    documents_tab.total_estimated = True
    documents_tab.current_offset = 0
    documents_tab.page_size = 25
    
    documents_tab.update_pagination_state(25)
    
    assert "≥50" in documents_tab.status_label.text()
    assert documents_tab.next_page_btn.isEnabled()

def test_delete_document_cancel(documents_tab):
    """Test cancelling document deletion."""
    documents_tab.current_documents = [{"document_id": "1", "source_uri": "test.txt"}]
    
    with patch("PySide6.QtWidgets.QMessageBox.question", return_value=QMessageBox.No), \
         patch("desktop_app.ui.documents_tab.DeleteWorker") as MockWorker:
        
        documents_tab.delete_document("1")
        
        MockWorker.assert_not_called()

def test_delete_finished_failure(documents_tab):
    """Test delete failure handling."""
    with patch("PySide6.QtWidgets.QMessageBox.critical") as mock_crit:
        documents_tab.delete_finished(False, "Error message")
        
        mock_crit.assert_called_once()
        assert "failed" in documents_tab.status_label.text()

def test_delete_folder_documents_uses_literal_prefix(documents_tab, mock_api_client):
    # source_uri_prefix is escaped server-side, so 'report_2024' can never
    # also delete a sibling like 'reportX2024' (LIKE '_' wildcard bug).
    mock_api_client.bulk_delete_preview.return_value = {"document_count": 2}
    mock_api_client.bulk_delete.return_value = {"chunks_deleted": 8}

    with patch("PySide6.QtWidgets.QMessageBox.question", return_value=QMessageBox.Yes), \
         patch("PySide6.QtWidgets.QMessageBox.information") as mock_info, \
         patch.object(documents_tab, "_refresh_current_view") as mock_refresh:

        documents_tab.delete_folder_documents(r"G:\My Drive", "My Drive")

    expected_filters = {"source_uri_prefix": r"G:\My Drive"}
    mock_api_client.bulk_delete_preview.assert_called_once_with(expected_filters)
    mock_api_client.bulk_delete.assert_called_once_with(expected_filters)
    mock_info.assert_called_once()
    mock_refresh.assert_called_once()

def test_pagination_limits(documents_tab):
    """Test pagination boundary limits."""
    documents_tab.total_documents = 50
    documents_tab.page_size = 25
    documents_tab.current_offset = 25
    documents_tab.total_estimated = False
    
    with patch.object(documents_tab, "load_documents") as mock_load:
        # Try to go next (offset 50 >= total 50) -> should not load
        documents_tab.change_page(1)
        mock_load.assert_not_called()
        assert documents_tab.current_offset == 25
        
        # Try to go prev from 0 -> should not load
        documents_tab.current_offset = 0
        documents_tab.change_page(-1)
        mock_load.assert_not_called()
        assert documents_tab.current_offset == 0

def test_page_size_changed_no_op(documents_tab):
    """Test page size change ignored if same or invalid."""
    documents_tab.page_size = 25
    
    with patch.object(documents_tab, "load_documents") as mock_load:
        # Invalid index
        documents_tab.on_page_size_changed(-1)
        mock_load.assert_not_called()
        
        # Same size
        # Assuming current index corresponds to 25
        index = documents_tab.page_size_combo.findText("25")
        documents_tab.on_page_size_changed(index)
        mock_load.assert_not_called()


def test_tree_stats_loaded_lancedb_unavailable(documents_tab):
    """Test when LanceDB stats loading fails (returns None)."""
    documents_tab._view_mode = "tree"
    documents_tab.db_source_combo.setVisible(True)
    
    data = {
        "postgres": {"total_documents": 10, "total_chunks": 50},
        "lancedb": None
    }
    
    documents_tab._on_tree_stats_loaded(True, data)
    
    assert documents_tab._lancedb_available is False
    assert documents_tab.db_source_combo.isVisible() is False
    assert documents_tab.db_source_combo.currentIndex() == 1
    assert documents_tab.pg_stats_label.text() == "Postgres : 10 docs / 50 chunks"
    assert documents_tab.ldb_stats_label.isVisible() is False
    assert documents_tab.status_stats_label.isVisible() is False
    assert documents_tab._polling_timer is None or not documents_tab._polling_timer.isActive()


def test_tree_stats_loaded_lancedb_available_in_sync(documents_tab):
    """Test when LanceDB stats match Postgres (in sync)."""
    documents_tab._view_mode = "tree"
    documents_tab.db_source_combo.setVisible(True)
    
    data = {
        "postgres": {"total_documents": 10, "total_chunks": 50},
        "lancedb": {"total_documents": 10, "total_chunks": 50}
    }
    
    documents_tab._on_tree_stats_loaded(True, data)
    
    assert documents_tab._lancedb_available is True
    assert documents_tab.db_source_combo.isVisible() is True
    assert documents_tab.pg_stats_label.text() == "Postgres : 10 docs / 50 chunks"
    assert documents_tab.ldb_stats_label.text() == "LanceDB  : 10 docs / 50 chunks"
    assert documents_tab.ldb_stats_label.isVisible() is True
    assert documents_tab.status_stats_label.isVisible() is True
    assert documents_tab.status_stats_label.text() == "Status   : ✓ in sync"
    assert "color: #10b981" in documents_tab.status_stats_label.styleSheet()
    assert documents_tab._polling_timer is None or not documents_tab._polling_timer.isActive()


def test_tree_stats_loaded_lancedb_available_behind(documents_tab):
    """Test when LanceDB is behind Postgres (syncing)."""
    documents_tab._view_mode = "tree"
    documents_tab.db_source_combo.setVisible(True)
    
    data = {
        "postgres": {"total_documents": 10, "total_chunks": 50},
        "lancedb": {"total_documents": 8, "total_chunks": 40}
    }
    
    documents_tab._on_tree_stats_loaded(True, data)
    
    assert documents_tab._lancedb_available is True
    assert documents_tab.db_source_combo.isVisible() is True
    assert documents_tab.pg_stats_label.text() == "Postgres : 10 docs / 50 chunks"
    assert documents_tab.ldb_stats_label.text() == "LanceDB  : 8 docs / 40 chunks"
    assert documents_tab.ldb_stats_label.isVisible() is True
    assert documents_tab.status_stats_label.isVisible() is True
    assert documents_tab.status_stats_label.text() == "Status   : ⟳ syncing — LanceDB behind"
    assert "color: #f59e0b" in documents_tab.status_stats_label.styleSheet()
    assert documents_tab._polling_timer is not None and documents_tab._polling_timer.isActive()



# ---------------------------------------------------------------------------
# Document visibility context-menu actions
# ---------------------------------------------------------------------------


def test_set_visibility_shared_updates_status(documents_tab):
    """Successful 'Make Shared' shows confirmation in the status label."""
    documents_tab.api_client.set_document_visibility = MagicMock()

    with patch.object(documents_tab, "_refresh_current_view") as refresh:
        documents_tab.set_document_visibility("doc-1", "shared")

    documents_tab.api_client.set_document_visibility.assert_called_once_with(
        "doc-1", visibility="shared"
    )
    assert "shared" in documents_tab.status_label.text()
    refresh.assert_called_once()


def test_set_visibility_private_with_owner_updates_status(documents_tab):
    documents_tab.api_client.set_document_visibility = MagicMock()
    documents_tab.api_client.get_document_visibility = MagicMock(
        return_value={"owner_id": "u-1", "visibility": "private"}
    )

    with patch.object(documents_tab, "_refresh_current_view") as refresh:
        documents_tab.set_document_visibility("doc-1", "private")

    assert "private" in documents_tab.status_label.text()
    refresh.assert_called_once()


def test_set_visibility_private_without_owner_warns(documents_tab):
    """Private without an owner is ineffective — the user must be told."""
    documents_tab.api_client.set_document_visibility = MagicMock()
    documents_tab.api_client.get_document_visibility = MagicMock(
        return_value={"owner_id": None, "visibility": "private"}
    )

    with patch.object(QMessageBox, "information") as info_box, \
         patch.object(documents_tab, "_refresh_current_view") as refresh:
        documents_tab.set_document_visibility("doc-1", "private")

    info_box.assert_called_once()
    assert "no owner" in info_box.call_args[0][2]
    refresh.assert_called_once()


def test_set_visibility_api_failure_shows_error(documents_tab):
    documents_tab.api_client.set_document_visibility = MagicMock(
        side_effect=RuntimeError("backend down")
    )

    with patch.object(QMessageBox, "critical") as critical_box:
        documents_tab.set_document_visibility("doc-1", "private")

    critical_box.assert_called_once()


def test_display_documents_stores_document_id_for_menu(documents_tab):
    """Rows must carry document_id so the context menu can act on them."""
    docs = [{
        "source_uri": "/tmp/a.txt",
        "document_id": "doc-abc",
        "chunk_count": 1,
        "metadata": {},
    }]
    documents_tab.display_documents(docs)

    item = documents_tab.documents_table.item(0, 0)
    assert item.data(Qt.UserRole + 1) == "doc-abc"


def test_display_documents_marks_owned_private_rows_with_lock(documents_tab):
    docs = [{
        "source_uri": "/tmp/private.txt",
        "document_id": "doc-private",
        "visibility": "private",
        "owner_id": "user-1",
        "chunk_count": 1,
        "metadata": {},
    }]

    documents_tab.display_documents(docs)

    item = documents_tab.documents_table.item(0, 0)
    assert not item.icon().isNull()
    assert "owner and admins" in item.toolTip()


def test_display_documents_does_not_lock_ownerless_private_rows(documents_tab):
    docs = [{
        "source_uri": "/tmp/ownerless.txt",
        "document_id": "doc-ownerless",
        "visibility": "private",
        "owner_id": None,
        "chunk_count": 1,
        "metadata": {},
    }]

    documents_tab.display_documents(docs)

    item = documents_tab.documents_table.item(0, 0)
    assert item.icon().isNull()
    assert "no owner" in item.toolTip()
