import pytest

# Mark all tests in this file as slow (UI tests with QApplication)
pytestmark = pytest.mark.slow
from unittest.mock import MagicMock, patch
from pathlib import Path
from PySide6.QtWidgets import QApplication, QMessageBox, QTableWidgetItem
from PySide6.QtCore import Qt, QPoint

from desktop_app.ui.search_tab import SearchTab

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
    client.get_metadata_keys.return_value = []
    client.get_metadata_values.return_value = []
    return client

@pytest.fixture
def mock_source_manager():
    return MagicMock()

@pytest.fixture
def search_tab(qapp, mock_api_client, mock_source_manager):
    tab = SearchTab(mock_api_client, source_manager=mock_source_manager)
    tab.show()
    return tab

def test_initialization(search_tab):
    """Test UI initialization."""
    assert search_tab.api_client is not None
    assert search_tab.source_manager is not None
    assert hasattr(search_tab, "query_input")
    assert hasattr(search_tab, "search_btn")
    assert hasattr(search_tab, "results_table")
    assert hasattr(search_tab, "top_k_spin")
    assert hasattr(search_tab, "min_score_spin")
    assert hasattr(search_tab, "metric_combo")

def test_perform_search_empty_query(search_tab):
    """Test search with empty query."""
    search_tab.query_input.setText("")
    
    with patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
        search_tab.perform_search()
        mock_warn.assert_called_once()

def test_perform_search_api_unavailable(search_tab, mock_api_client):
    """Test search when API is unavailable."""
    search_tab.query_input.setText("test")
    mock_api_client.is_api_available.return_value = False
    
    with patch("PySide6.QtWidgets.QMessageBox.critical") as mock_crit:
        search_tab.perform_search()
        mock_crit.assert_called_once()

def test_perform_search_success(search_tab):
    """Test successful search execution."""
    search_tab.query_input.setText("test query")
    search_tab.top_k_spin.setValue(5)
    search_tab.min_score_spin.setValue(0.5)
    search_tab.metric_combo.setCurrentText("cosine")
    
    with patch("desktop_app.ui.search_tab.SearchWorker") as MockWorker:
        mock_worker_instance = MockWorker.return_value
        
        search_tab.perform_search()
        
        MockWorker.assert_called_once()
        # Verify args
        args = MockWorker.call_args
        assert args[0][1] == "test query"
        assert args[0][2] == 5
        assert args[0][3] == 0.5
        assert args[0][4] == "cosine"
        
        mock_worker_instance.start.assert_called_once()
        assert not search_tab.search_btn.isEnabled()

def test_search_finished_success(search_tab):
    """Test handling of successful search results."""
    results = [
        {"score": 0.9, "source_uri": "/path/1", "text_content": "content 1", "chunk_number": 1},
        {"score": 0.8, "source_uri": "/path/2", "text_content": "content 2", "chunk_number": 2}
    ]
    
    search_tab.search_finished(True, results)
    
    assert search_tab.search_btn.isEnabled()
    assert search_tab.results_table.rowCount() == 2
    assert search_tab.results_table.item(0, 0).text() == "0.9000"
    assert search_tab.results_table.item(0, 1).text() == "/path/1"

def test_search_finished_failure(search_tab):
    """Test handling of search failure."""
    with patch("PySide6.QtWidgets.QMessageBox.critical") as mock_crit:
        search_tab.search_finished(False, "Error message")
        
        mock_crit.assert_called_once()
        assert search_tab.search_btn.isEnabled()
        assert "failed" in search_tab.status_label.text()

def test_show_full_content(search_tab):
    """Test showing full content dialog."""
    # Setup table item
    search_tab.results_table.setRowCount(1)
    item = QTableWidgetItem("0.9")
    item.setData(Qt.UserRole, {"text_content": "Full content", "source_uri": "src", "display_score": 0.9, "display_chunk": 1})
    search_tab.results_table.setItem(0, 0, item)
    
    # Create a mock index
    mock_index = MagicMock()
    mock_index.row.return_value = 0
    
    with patch("PySide6.QtWidgets.QMessageBox.exec") as mock_exec:
        search_tab.show_full_content(mock_index)
        mock_exec.assert_called_once()

def test_handle_results_cell_clicked(search_tab, mock_source_manager):
    """Test clicking on results table cell."""
    # Setup table
    search_tab.results_table.setRowCount(1)
    item = QTableWidgetItem("test")
    item.setData(Qt.UserRole, "/path/to/file")
    search_tab.results_table.setItem(0, 1, item)
    
    # Click on source column (1)
    search_tab.handle_results_cell_clicked(0, 1)
    mock_source_manager.open_path.assert_called_with("/path/to/file")
    
    # Click on other column (0)
    mock_source_manager.reset_mock()
    search_tab.handle_results_cell_clicked(0, 0)
    mock_source_manager.open_path.assert_not_called()

def test_context_menu(search_tab, mock_source_manager):
    """Test context menu actions."""
    # Setup table
    search_tab.results_table.setRowCount(1)
    item = QTableWidgetItem("test")
    item.setData(Qt.UserRole, "/path/to/file")
    search_tab.results_table.setItem(0, 1, item)
    
    # Mock finding entry
    mock_entry = MagicMock()
    mock_entry.queued = False
    mock_source_manager.find_entry.return_value = mock_entry
    
    # Mock QMenu class
    with patch("desktop_app.ui.search_tab.QMenu") as MockMenu, \
         patch.object(search_tab.results_table, "indexAt") as mock_index_at, \
         patch.object(search_tab.results_table, "item") as mock_item_method:
        
        # Setup MockMenu instance
        mock_menu_instance = MockMenu.return_value
        
        # Mock indexAt to return a valid index at column 1
        mock_index = MagicMock()
        mock_index.isValid.return_value = True
        mock_index.row.return_value = 0
        mock_index.column.return_value = 1
        mock_index_at.return_value = mock_index
        
        # Mock item return
        mock_item_method.return_value = item
        
        search_tab.show_results_context_menu(QPoint(0, 0))
        
        mock_index_at.assert_called_once()
        mock_item_method.assert_called_once()
        
        mock_source_manager.find_entry.assert_called_with("/path/to/file")
        mock_menu_instance.exec.assert_called_once()

def test_open_source_path_fallback(search_tab):
    """Test open_source_path fallback logic (when source_manager is None)."""
    search_tab.source_manager = None
    
    with patch("pathlib.Path.exists", return_value=True), \
         patch("sys.platform", "linux"), \
         patch("subprocess.Popen") as mock_popen:
        
        search_tab.open_source_path("/path/to/file")
        mock_popen.assert_called_once_with(["xdg-open", "/path/to/file"])
