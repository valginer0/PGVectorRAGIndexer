import pytest

# Mark all tests in this file as slow (UI tests with QApplication)
pytestmark = pytest.mark.slow
from unittest.mock import MagicMock, patch
from pathlib import Path
from PySide6.QtWidgets import QApplication, QPushButton, QLabel, QMessageBox
from PySide6.QtCore import Qt

from desktop_app.ui.upload_tab import UploadTab

@pytest.fixture(scope="session")
def qapp():
    """Create the QApplication instance for the test session."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app

@pytest.fixture
def mock_api_client():
    return MagicMock()

@pytest.fixture
def upload_tab(qapp, mock_api_client):
    tab = UploadTab(mock_api_client)
    # Force show to ensure visibility checks work as expected in some environments
    tab.show() 
    return tab

def test_initialization(upload_tab):
    """Test that UI components are initialized correctly."""
    assert upload_tab.api_client is not None
    assert upload_tab.failed_uploads == []
    
    # Check for key widgets
    assert hasattr(upload_tab, "select_files_btn")
    assert hasattr(upload_tab, "upload_btn")
    assert hasattr(upload_tab, "view_errors_btn")
    
    # Check initial state of error button
    # It is explicitly hidden in setup_ui
    assert not upload_tab.view_errors_btn.isVisible()

def test_upload_workflow(upload_tab, mock_api_client):
    """Test the upload workflow."""
    # Mock file selection
    files = [Path("/path/to/file1.txt"), Path("/path/to/file2.pdf")]
    upload_tab.selected_files = files
    
    # Mock UploadWorker
    with patch("desktop_app.ui.upload_tab.UploadWorker") as MockWorker:
        mock_worker_instance = MockWorker.return_value
        
        # Trigger upload
        upload_tab.upload_file()
        
        # Verify worker started
        MockWorker.assert_called_once()
        mock_worker_instance.start.assert_called_once()
        
        # Verify UI state during upload
        assert not upload_tab.upload_btn.isEnabled()

def test_upload_failure_handling(upload_tab):
    """Test that failed uploads are recorded and error button appears."""
    # Reset state
    upload_tab.failed_uploads = []
    upload_tab.view_errors_btn.hide()
    upload_tab.selected_files = [Path("bad_file.txt")]
    
    # Simulate a failed upload
    # on_file_finished(index, success, message)
    error_msg = "Connection timed out"
    upload_tab.on_file_finished(0, False, error_msg)
    
    # Verify failure recorded
    assert len(upload_tab.failed_uploads) == 1
    assert upload_tab.failed_uploads[0]["file"] == "bad_file.txt"
    assert upload_tab.failed_uploads[0]["error"] is not None
    assert "Hint" in upload_tab.failed_uploads[0]["error"]
    
    # Verify button visibility
    assert upload_tab.view_errors_btn.isVisible()

def test_upload_success_handling(upload_tab):
    """Test that successful uploads do not trigger error handling."""
    # Reset state
    upload_tab.failed_uploads = []
    upload_tab.view_errors_btn.hide()
    upload_tab.selected_files = [Path("good_file.txt")]
    
    # Simulate a successful upload
    upload_tab.on_file_finished(0, True, "Success")
    
    # Verify no failure recorded
    assert len(upload_tab.failed_uploads) == 0
    assert not upload_tab.view_errors_btn.isVisible()

def test_clear_failures_on_new_upload(upload_tab):
    """Test that previous failures are cleared when starting a new upload."""
    # Setup previous failures
    upload_tab.failed_uploads = [{"file": "old.txt", "error": "old error"}]
    upload_tab.view_errors_btn.show()
    upload_tab.selected_files = [Path("/path/to/new.txt")]
    
    # Mock UploadWorker
    with patch("desktop_app.ui.upload_tab.UploadWorker"):
        # Start new upload
        upload_tab.upload_file()
        
        # Verify failures cleared
        assert upload_tab.failed_uploads == []
        assert not upload_tab.view_errors_btn.isVisible()

def test_select_files(upload_tab):
    """Test file selection dialog."""
    with patch("desktop_app.ui.shared.pick_open_files", return_value=["/path/to/file1.txt", "/path/to/file2.pdf"]):
        upload_tab.select_files()

        assert len(upload_tab.selected_files) == 2
        assert upload_tab.selected_files[0] == Path("/path/to/file1.txt")
        assert upload_tab.upload_btn.isEnabled()

def test_select_folder(upload_tab):
    """Test folder selection dialog."""
    mock_folder_dialog = MagicMock()
    mock_folder_dialog.exec.return_value = True
    mock_folder_dialog.get_filtered_files.return_value = [Path("/path/to/folder/file1.txt")]

    with patch("desktop_app.ui.shared.pick_directory", return_value="/path/to/folder"), \
         patch.object(upload_tab, "_find_supported_files", return_value=[Path("/path/to/folder/file1.txt")]), \
         patch("desktop_app.ui.upload_tab.FolderIndexDialog", return_value=mock_folder_dialog):

        upload_tab.select_folder()

        assert len(upload_tab.selected_files) == 1
        assert upload_tab.selected_files[0] == Path("/path/to/folder/file1.txt")
        assert upload_tab.upload_btn.isEnabled()

def test_find_supported_files(upload_tab):
    """Test finding supported files in a directory."""
    # Create a mock directory structure
    with patch("pathlib.Path.rglob") as mock_rglob:
        file1 = MagicMock(spec=Path)
        file1.is_file.return_value = True
        file1.suffix = ".txt"
        file1.name = "file1.txt"
        
        file2 = MagicMock(spec=Path)
        file2.is_file.return_value = True
        file2.suffix = ".pdf"
        file2.name = "file2.pdf"
        
        file3 = MagicMock(spec=Path)
        file3.is_file.return_value = True
        file3.suffix = ".exe" # Unsupported
        file3.name = "file3.exe"
        
        file4 = MagicMock(spec=Path)
        file4.is_file.return_value = True
        file4.suffix = ".doc"
        file4.name = "~$temp.doc" # Ignored
        
        mock_rglob.return_value = [file1, file2, file3, file4]
        
        files = upload_tab._find_supported_files(Path("/mock/folder"))
        
        assert len(files) == 2
        assert file1 in files
        assert file2 in files
        assert file3 not in files
        assert file4 not in files

def test_show_errors_dialog(upload_tab):
    """Test error dialog display."""
    upload_tab.failed_uploads = [{"file": "test.txt", "error": "failed"}]
    
    with patch("desktop_app.ui.upload_tab.UploadResultsDialog") as mock_dialog:
        upload_tab.show_errors_dialog()
        mock_dialog.assert_called_once()

def test_on_file_finished_hints(upload_tab):
    """Test error hints generation."""
    upload_tab.selected_files = [Path("test.txt")]
    
    # Test timeout hint
    upload_tab.on_file_finished(0, False, "Connection timed out")
    assert "Hint: File might be too large" in upload_tab.failed_uploads[-1]["error"]
    
    # Test 413 hint
    upload_tab.on_file_finished(0, False, "Error 413")
    assert "Hint: File exceeds server size limit" in upload_tab.failed_uploads[-1]["error"]

def test_on_all_finished(upload_tab):
    """Test UI reset after all uploads finished."""
    upload_tab.upload_started_at = 100.0
    upload_tab.selected_files = [Path("test.txt")]
    upload_tab.upload_btn.setEnabled(False)
    
    with patch("time.perf_counter", return_value=110.0):
        upload_tab.on_all_finished()
        
        assert upload_tab.upload_started_at is None
        assert upload_tab.selected_files == []
        assert not upload_tab.upload_btn.isEnabled()
        assert upload_tab.select_files_btn.isEnabled()

def test_format_elapsed(upload_tab):
    """Test elapsed time formatting."""
    assert upload_tab._format_elapsed(65.5) == "00:01:05 (65.50s)"
    assert upload_tab._format_elapsed(3661.0) == "01:01:01 (3661.00s)"

def test_build_documents_filter(upload_tab):
    """Test document filter string construction."""
    filter_str = upload_tab._build_documents_filter()
    assert "Documents (" in filter_str
    assert "*.txt" in filter_str
    assert "*.pdf" in filter_str

# Tests for FolderIndexDialog pattern matching
class TestFolderIndexDialogPatternMatching:
    """Tests for the exclusion pattern matching in FolderIndexDialog."""
    
    def test_matches_simple_extension_pattern(self, qapp):
        """Test matching simple extension patterns like *.log."""
        from desktop_app.ui.folder_index_dialog import FolderIndexDialog
        
        path = Path("/project/logs/debug.log")
        assert FolderIndexDialog._matches_any_pattern(path, ["*.log"]) == True
        assert FolderIndexDialog._matches_any_pattern(path, ["*.txt"]) == False
    
    def test_matches_folder_pattern(self, qapp):
        """Test matching folder patterns like **/node_modules/**."""
        from desktop_app.ui.folder_index_dialog import FolderIndexDialog
        
        path = Path("/project/node_modules/package/index.js")
        assert FolderIndexDialog._matches_any_pattern(path, ["**/node_modules/**"]) == True
        
        path2 = Path("/project/src/index.js")
        assert FolderIndexDialog._matches_any_pattern(path2, ["**/node_modules/**"]) == False
    
    def test_matches_git_folder(self, qapp):
        """Test matching .git folder."""
        from desktop_app.ui.folder_index_dialog import FolderIndexDialog
        
        path = Path("/project/.git/config")
        assert FolderIndexDialog._matches_any_pattern(path, ["**/.git/**"]) == True
        
        path2 = Path("/project/src/main.py")
        assert FolderIndexDialog._matches_any_pattern(path2, ["**/.git/**"]) == False
    
    def test_no_match_returns_false(self, qapp):
        """Test that non-matching paths return False."""
        from desktop_app.ui.folder_index_dialog import FolderIndexDialog
        
        path = Path("/project/src/main.py")
        patterns = ["*.log", "**/node_modules/**", "**/.git/**"]
        assert FolderIndexDialog._matches_any_pattern(path, patterns) == False
    
    def test_empty_patterns_returns_false(self, qapp):
        """Test that empty pattern list returns False."""
        from desktop_app.ui.folder_index_dialog import FolderIndexDialog
        
        path = Path("/project/src/main.py")
        assert FolderIndexDialog._matches_any_pattern(path, []) == False

# Tests for .pgvector-ignore file loading
class TestPgvectorIgnoreFile:
    """Tests for loading patterns from .pgvector-ignore files."""
    
    def test_load_ignore_patterns_from_file(self, qapp, tmp_path):
        """Test loading patterns from a .pgvector-ignore file."""
        from desktop_app.ui.folder_index_dialog import FolderIndexDialog
        
        # Create a .pgvector-ignore file
        ignore_file = tmp_path / ".pgvector-ignore"
        ignore_file.write_text("""
# Comment line (should be ignored)
*.log
**/node_modules/**
secret_folder/

# Another comment
*.tmp
""")
        
        patterns, paths = FolderIndexDialog.load_ignore_patterns(tmp_path)
        
        assert ignore_file in paths
        assert len(patterns) == 4
        assert "*.log" in patterns
        assert "**/node_modules/**" in patterns
        assert "secret_folder/" in patterns
        assert "*.tmp" in patterns
        # Comments should be excluded
        assert "# Comment line (should be ignored)" not in patterns
    
    def test_load_ignore_patterns_file_not_found(self, qapp, tmp_path):
        """Test that missing .pgvector-ignore returns empty list."""
        from desktop_app.ui.folder_index_dialog import FolderIndexDialog
        
        patterns, paths = FolderIndexDialog.load_ignore_patterns(tmp_path)
        
        assert patterns == []
        assert paths == []
    
    def test_load_ignore_patterns_searches_parent_dirs(self, qapp, tmp_path):
        """Test that .pgvector-ignore is found in parent directories."""
        from desktop_app.ui.folder_index_dialog import FolderIndexDialog
        
        # Create nested folder structure
        nested_folder = tmp_path / "level1" / "level2" / "level3"
        nested_folder.mkdir(parents=True)
        
        # Create .pgvector-ignore in parent
        ignore_file = tmp_path / ".pgvector-ignore"
        ignore_file.write_text("*.log\n*.tmp")
        
        # Search from deeply nested folder should find parent's ignore file
        patterns, paths = FolderIndexDialog.load_ignore_patterns(nested_folder)
        
        assert ignore_file in paths
        assert len(patterns) == 2
        assert "*.log" in patterns
