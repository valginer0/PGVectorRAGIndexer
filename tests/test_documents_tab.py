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
