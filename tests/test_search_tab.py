import pytest

# Mark all tests in this file as slow (UI tests with QApplication)
pytestmark = pytest.mark.slow
from unittest.mock import MagicMock, patch
from pathlib import Path
from PySide6.QtWidgets import QApplication, QMessageBox, QTableWidgetItem
from PySide6.QtCore import Qt, QPoint

from desktop_app.ui.search_tab import SearchTab
from desktop_app.ui.workers import format_lancedb_search_results

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
    client.get_health.return_value = {"status": "ok"}
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
    mock_api_client.get_health.return_value = {"status": "unreachable"}
    
    with patch("desktop_app.ui.search_tab.app_config.get_local_lancedb_search_enabled", return_value=False), \
         patch("PySide6.QtWidgets.QMessageBox.critical") as mock_crit:
        search_tab.perform_search()
        mock_crit.assert_called_once()

def test_perform_search_success(search_tab):
    """Test successful search execution."""
    search_tab.query_input.setText("test query")
    search_tab.top_k_spin.setValue(5)
    search_tab.min_score_spin.setValue(0.5)
    search_tab.metric_combo.setCurrentText("cosine")
    
    with patch("desktop_app.ui.search_tab.app_config.get_local_lancedb_search_enabled", return_value=False), \
         patch("desktop_app.ui.search_tab.SearchWorker") as MockWorker:
        mock_worker_instance = MockWorker.return_value
        
        search_tab.perform_search()
        
        MockWorker.assert_called_once()
        # Verify args
        args = MockWorker.call_args
        assert args[0][1] == "test query"
        assert args[0][2] == 100
        assert args[0][3] == 0.5
        assert args[0][4] == "cosine"
        
        mock_worker_instance.start.assert_called_once()
        assert not search_tab.search_btn.isEnabled()


def test_perform_search_can_use_document_level_backend_option(search_tab):
    """Experimental document-level search sends a visible-limit request to the API."""
    search_tab.query_input.setText("EV6")
    search_tab.top_k_spin.setValue(5)
    search_tab.min_score_spin.setValue(0.3)
    search_tab.metric_combo.setCurrentText("cosine")

    with patch("desktop_app.ui.search_tab.app_config.get_document_level_search_enabled", return_value=True), \
         patch("desktop_app.ui.search_tab.app_config.get_local_lancedb_search_enabled", return_value=False), \
         patch("desktop_app.ui.search_tab.SearchWorker") as MockWorker:
        search_tab.perform_search()

        args = MockWorker.call_args
        assert args[0][1] == "EV6"
        assert args[0][2] == 5
        assert args.kwargs["group_by_document"] is True
        assert args.kwargs["literal_tail_suppression"] == "identifier-token"


def test_perform_search_can_use_local_lancedb_option(search_tab, mock_api_client):
    search_tab.query_input.setText("EV6")
    search_tab.top_k_spin.setValue(5)

    with patch("desktop_app.ui.search_tab.app_config.get_local_lancedb_search_enabled", return_value=True), \
         patch("desktop_app.ui.search_tab.app_config.get_local_lancedb_db_path", return_value="/tmp/local-lancedb"), \
         patch("desktop_app.ui.search_tab.LocalLanceDBSearchWorker") as MockWorker:
        worker = MockWorker.return_value

        search_tab.perform_search()

        MockWorker.assert_called_once_with("EV6", 5, "/tmp/local-lancedb")
        worker.start.assert_called_once()
        mock_api_client.get_health.assert_not_called()


def test_local_lancedb_search_rejects_filters(search_tab):
    search_tab.query_input.setText("EV6")
    search_tab.type_filter.setCurrentText("policy")

    with patch("desktop_app.ui.search_tab.app_config.get_local_lancedb_search_enabled", return_value=True), \
         patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn, \
         patch("desktop_app.ui.search_tab.LocalLanceDBSearchWorker") as MockWorker:
        search_tab.perform_search()

        mock_warn.assert_called_once()
        MockWorker.assert_not_called()


def test_format_lancedb_search_results_matches_table_shape():
    result = MagicMock(
        score=0.75,
        source_uri="/docs/ev6.txt",
        text="EV6 local chunk",
        chunk_index=3,
        score_label="Cosine similarity: 0.7500",
        parent_rank=1,
    )

    formatted = format_lancedb_search_results([result])

    assert formatted == [
        {
            "score": 0.75,
            "source_uri": "/docs/ev6.txt",
            "text_content": "EV6 local chunk",
            "chunk_index": 3,
            "metadata": {
                "search_backend": "local_lancedb",
                "score_label": "Cosine similarity: 0.7500",
                "parent_rank": 1,
            },
        }
    ]


def test_load_extensions_defaults_to_select_all(search_tab, mock_api_client):
    """Loading extensions should show '*' (all) selected, with no active filter."""
    mock_api_client.get_extensions.return_value = [".txt", ".pdf"]

    search_tab.load_extensions()

    assert search_tab.ext_filter.currentText() == "*"
    # checked_items() returns [] when only '*' is selected (means no filter)
    assert search_tab.ext_filter.checked_items() == []

def test_select_all_is_sticky(search_tab, mock_api_client):
    """'*' must never disappear: unchecking it or the last specific ext reverts to '*'."""
    mock_api_client.get_extensions.return_value = [".txt"]
    search_tab.load_extensions()
    box = search_tab.ext_filter

    # Simulate unchecking '*' directly
    star_index = box._model.index(0, 0)
    box._toggle_item(star_index)
    assert box.currentText() == "*", "unchecking '*' alone should re-check it"
    assert box.checked_items() == []

    # Check .txt (unchecks '*'), then uncheck .txt → should revert to '*'
    txt_index = box._model.index(1, 0)
    box._toggle_item(txt_index)   # check .txt, uncheck *
    assert box.currentText() == ".txt"
    box._toggle_item(txt_index)   # uncheck .txt → nothing left → revert to *
    assert box.currentText() == "*", "unchecking last specific ext should revert to '*'"
    assert box.checked_items() == []


def test_display_results_deduplicates_chunks_by_source(search_tab):
    """Multiple chunk matches from the same file should display as one row."""
    results = [
        {
            "relevance_score": 0.95,
            "source_uri": "/docs/ev6.txt",
            "text_content": "EV6 charging notes",
            "chunk_index": 2,
        },
        {
            "relevance_score": 0.85,
            "source_uri": "/docs/ev6.txt",
            "text_content": "EV6 warranty notes",
            "chunk_index": 5,
        },
        {
            "relevance_score": 0.75,
            "source_uri": "/docs/other.txt",
            "text_content": "Other notes",
            "chunk_index": 1,
        },
    ]

    search_tab.display_results(results)

    assert search_tab.results_table.rowCount() == 2
    assert search_tab.results_table.item(0, 2).text() == "/docs/ev6.txt"
    assert search_tab.results_table.item(0, 3).text() == "2"
    assert search_tab.results_table.item(1, 2).text() == "/docs/other.txt"

def test_display_results_respects_visible_limit_after_deduping(search_tab):
    search_tab._display_result_limit = 2
    results = [
        {
            "relevance_score": 1.0 - (i * 0.01),
            "source_uri": f"/docs/file-{i}.txt",
            "text_content": f"EV6 note {i}",
            "chunk_index": i,
        }
        for i in range(5)
    ]

    search_tab.display_results(results)

    assert search_tab.results_table.rowCount() == 2
    assert search_tab.results_table.item(0, 2).text() == "/docs/file-0.txt"
    assert search_tab.results_table.item(1, 2).text() == "/docs/file-1.txt"

def test_search_finished_success(search_tab):
    """Test handling of successful search results."""
    results = [
        {"score": 0.9, "source_uri": "/path/1", "text_content": "content 1", "chunk_number": 1},
        {"score": 0.8, "source_uri": "/path/2", "text_content": "content 2", "chunk_number": 2}
    ]
    
    search_tab.search_finished(True, results)
    
    assert search_tab.search_btn.isEnabled()
    assert search_tab.results_table.rowCount() == 2
    assert search_tab.results_table.item(0, 0).text() == "0.9000"  # Score
    assert search_tab.results_table.item(0, 2).text() == "/path/1"  # Source (column 2 now)
    assert search_tab.status_label.text() == "Found 2 results"


def test_search_finished_marks_local_results_one_per_file(search_tab):
    search_tab.search_worker = MagicMock()
    search_tab.search_worker.property.return_value = True

    search_tab.search_finished(
        True,
        [{"score": 0.9, "source_uri": "/path/1", "text_content": "content 1", "chunk_index": 1}],
    )

    assert search_tab.status_label.text() == "Found 1 result (1 per file)"

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
    # Setup table - Source is in column 2 now (0=Score, 1=Type, 2=Source)
    search_tab.results_table.setRowCount(1)
    item = QTableWidgetItem("test")
    item.setData(Qt.UserRole, "/path/to/file")
    search_tab.results_table.setItem(0, 2, item)  # Column 2 for Source
    
    # Click on source column (2)
    search_tab.handle_results_cell_clicked(0, 2)
    mock_source_manager.open_path.assert_called_with("/path/to/file")
    
    # Click on other column (0)
    mock_source_manager.reset_mock()
    search_tab.handle_results_cell_clicked(0, 0)
    mock_source_manager.open_path.assert_not_called()

def test_context_menu(search_tab, mock_source_manager):
    """Test context menu actions."""
    # Setup table - Source is in column 2 now
    search_tab.results_table.setRowCount(1)
    item = QTableWidgetItem("test")
    item.setData(Qt.UserRole, "/path/to/file")
    search_tab.results_table.setItem(0, 2, item)  # Column 2 for Source
    
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
        
        # Mock indexAt to return a valid index at column 2 (Source)
        mock_index = MagicMock()
        mock_index.isValid.return_value = True
        mock_index.row.return_value = 0
        mock_index.column.return_value = 2
        mock_index_at.return_value = mock_index
        
        # Mock item return
        mock_item_method.return_value = item
        
        search_tab.show_results_context_menu(QPoint(0, 0))
        
        mock_index_at.assert_called_once()
        mock_item_method.assert_called_once()
        
        mock_source_manager.find_entry.assert_called_with("/path/to/file")
        mock_menu_instance.exec.assert_called_once()

# NOTE: open_source_path method was moved to source_manager, these tests are obsolete
