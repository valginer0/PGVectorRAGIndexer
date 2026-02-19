import pytest

# Mark all tests in this file as slow (UI tests with QApplication)
pytestmark = pytest.mark.slow
from unittest.mock import MagicMock, patch, mock_open
from pathlib import Path
import json
from PySide6.QtWidgets import QApplication, QMessageBox, QTableWidgetItem
from PySide6.QtCore import Qt, QPoint

from desktop_app.ui.manage_tab import ManageTab

@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app

@pytest.fixture
def mock_api_client():
    client = MagicMock()
    client.get_metadata_keys.return_value = []
    client.get_metadata_values.return_value = []
    return client

@pytest.fixture
def mock_source_manager():
    return MagicMock()

@pytest.fixture
def manage_tab(qapp, mock_api_client, mock_source_manager):
    tab = ManageTab(mock_api_client, mock_source_manager)
    tab.show()
    return tab

def test_initialization(manage_tab):
    """Test UI initialization."""
    assert manage_tab.api_client is not None
    assert manage_tab.source_manager is not None
    assert hasattr(manage_tab, "type_combo")
    assert hasattr(manage_tab, "path_filter")
    assert hasattr(manage_tab, "preview_btn")
    assert hasattr(manage_tab, "export_btn")
    assert hasattr(manage_tab, "delete_btn")
    assert hasattr(manage_tab, "undo_btn")
    assert hasattr(manage_tab, "results_table")

def test_get_filters(manage_tab):
    """Test filter construction."""
    # Test empty filters (should show warning and return None)
    # Need to clear path_filter since it defaults to '*' which would create a filter
    manage_tab.path_filter.clear()
    with patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
        assert manage_tab.get_filters() is None
        mock_warn.assert_called_once()
    
    # Test type filter
    manage_tab.type_combo.setCurrentText("resume")
    filters = manage_tab.get_filters()
    assert filters == {"type": "resume"}
    
    # Test path filter
    manage_tab.path_filter.setText("*.pdf")
    filters = manage_tab.get_filters()
    assert filters["type"] == "resume"
    assert filters["source_uri_like"] == "%.pdf"

def test_preview_delete_no_results(manage_tab, mock_api_client):
    """Test preview with no results."""
    manage_tab.type_combo.setCurrentText("resume")
    mock_api_client.bulk_delete_preview.return_value = {"document_count": 0}
    
    manage_tab.preview_delete()
    
    assert not manage_tab.results_table.isVisible()
    assert not manage_tab.export_btn.isEnabled()
    assert not manage_tab.delete_btn.isEnabled()

def test_preview_delete_with_results(manage_tab, mock_api_client):
    """Test preview with results."""
    manage_tab.type_combo.setCurrentText("resume")
    mock_api_client.bulk_delete_preview.return_value = {
        "document_count": 2,
        "sample_documents": [
            {"document_id": "1", "metadata": {"type": "resume"}, "source_uri": "/path/1"},
            {"document_id": "2", "metadata": {"type": "resume"}, "source_uri": "/path/2"}
        ]
    }
    
    manage_tab.preview_delete()
    
    assert manage_tab.results_table.isVisible()
    assert manage_tab.results_table.rowCount() == 2
    assert manage_tab.export_btn.isEnabled()
    assert manage_tab.delete_btn.isEnabled()
    
    # Verify table content
    assert manage_tab.results_table.item(0, 0).text() == "1"
    assert manage_tab.results_table.item(0, 2).text() == "/path/1"

def test_export_backup(manage_tab, mock_api_client):
    """Test export backup."""
    manage_tab.type_combo.setCurrentText("resume")
    mock_api_client.export_documents.return_value = {"backup_data": []}
    
    with patch("desktop_app.ui.shared.pick_save_file", return_value="/tmp/backup.json"), \
         patch("builtins.open", mock_open()) as mock_file, \
         patch("json.dump") as mock_json_dump, \
         patch("PySide6.QtWidgets.QMessageBox.information") as mock_info:

        manage_tab.export_backup()

        mock_api_client.export_documents.assert_called_once()
        mock_file.assert_called_once_with("/tmp/backup.json", 'w')
        mock_json_dump.assert_called_once()
        mock_info.assert_called_once()
        assert manage_tab.undo_btn.isEnabled()

def test_delete_documents(manage_tab, mock_api_client):
    """Test delete documents."""
    manage_tab.type_combo.setCurrentText("resume")
    mock_api_client.bulk_delete.return_value = {"chunks_deleted": 10}
    
    with patch("PySide6.QtWidgets.QMessageBox.question", return_value=QMessageBox.Yes), \
         patch("PySide6.QtWidgets.QMessageBox.information") as mock_info:
        
        manage_tab.delete_documents()
        
        mock_api_client.bulk_delete.assert_called_once()
        mock_info.assert_called_once()
        assert not manage_tab.results_table.isVisible()

def test_undo_delete(manage_tab, mock_api_client):
    """Test undo delete."""
    manage_tab.last_backup = {"backup_data": [{"id": "1"}]}
    mock_api_client.restore_documents.return_value = {"chunks_restored": 1}
    
    with patch("PySide6.QtWidgets.QMessageBox.question", return_value=QMessageBox.Yes), \
         patch("PySide6.QtWidgets.QMessageBox.information") as mock_info:
        
        manage_tab.undo_delete()
        
        mock_api_client.restore_documents.assert_called_once()
        mock_info.assert_called_once()
        assert manage_tab.last_backup is None
        assert not manage_tab.undo_btn.isEnabled()

def test_handle_results_cell_clicked(manage_tab, mock_source_manager):
    """Test clicking on results table cell."""
    # Setup table
    manage_tab.results_table.setRowCount(1)
    item = QTableWidgetItem("test")
    item.setData(Qt.UserRole, "/path/to/file")
    manage_tab.results_table.setItem(0, 2, item)
    
    # Click on source column (2)
    manage_tab.handle_results_cell_clicked(0, 2)
    mock_source_manager.open_path.assert_called_with("/path/to/file")
    
    # Click on other column (0)
    mock_source_manager.reset_mock()
    manage_tab.handle_results_cell_clicked(0, 0)
    mock_source_manager.open_path.assert_not_called()

def test_context_menu(manage_tab, mock_source_manager):
    """Test context menu actions."""
    # Setup table
    manage_tab.results_table.setRowCount(1)
    item = QTableWidgetItem("test")
    item.setData(Qt.UserRole, "/path/to/file")
    manage_tab.results_table.setItem(0, 2, item)
    
    # Mock finding entry
    mock_entry = MagicMock()
    mock_entry.queued = False
    mock_source_manager.find_entry.return_value = mock_entry
    
    # Mock QMenu class
    with patch("desktop_app.ui.manage_tab.QMenu") as MockMenu, \
         patch.object(manage_tab.results_table, "indexAt") as mock_index_at, \
         patch.object(manage_tab.results_table, "item") as mock_item_method:
        
        # Setup MockMenu instance
        mock_menu_instance = MockMenu.return_value
        
        # Mock indexAt to return a valid index at column 2
        mock_index = MagicMock()
        mock_index.isValid.return_value = True
        mock_index.row.return_value = 0
        mock_index.column.return_value = 2
        mock_index_at.return_value = mock_index
        
        # Mock item return
        mock_item_method.return_value = item
        
        manage_tab.show_results_context_menu(QPoint(0, 0))
        
        mock_index_at.assert_called_once()
        mock_item_method.assert_called_once()
        
        mock_source_manager.find_entry.assert_called_with("/path/to/file")
        mock_menu_instance.exec.assert_called_once()

def test_open_source_path_fallback(manage_tab):
    """Test open_source_path fallback logic (when source_manager is None)."""
    manage_tab.source_manager = None
    
    with patch("pathlib.Path.exists", return_value=True), \
         patch("sys.platform", "linux"), \
         patch("subprocess.Popen") as mock_popen:
        
        manage_tab.open_source_path("/path/to/file")
        mock_popen.assert_called_once_with(["xdg-open", "/path/to/file"])
