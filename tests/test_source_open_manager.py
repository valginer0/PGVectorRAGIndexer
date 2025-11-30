import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from pathlib import Path
import sys
import os

from desktop_app.ui.source_open_manager import SourceOpenManager

@pytest.fixture
def mock_api_client():
    return MagicMock()

@pytest.fixture
def source_manager(mock_api_client):
    # Mock project root
    project_root = Path("/mock/project")
    return SourceOpenManager(mock_api_client, project_root=project_root)

def test_normalize_path_exists(source_manager):
    """Test that existing paths are normalized correctly."""
    with patch("pathlib.Path.exists", return_value=True):
        
        path = "/home/user/file.txt"
        normalized = source_manager._normalize_path(path)
        assert normalized == Path(path)

def test_normalize_path_not_exists_no_resolve(source_manager):
    """Test that non-existent paths return None if resolution fails."""
    with patch("pathlib.Path.exists", return_value=False), \
         patch.object(source_manager, "_resolve_path_mismatch", return_value=None), \
         patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
        
        path = "/home/user/missing.txt"
        normalized = source_manager._normalize_path(path)
        assert normalized is None
        mock_warn.assert_called_once()

def test_resolve_path_mismatch_success(source_manager):
    """Test successful path resolution."""
    original_path = "C:\\Users\\User\\Documents\\resume.pdf"
    expected_path = Path("/mock/project/documents/resume.pdf")
    
    with patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.rglob", return_value=[expected_path]):
        
        resolved = source_manager._resolve_path_mismatch(original_path)
        assert resolved == expected_path

def test_resolve_path_mismatch_failure(source_manager):
    """Test failed path resolution."""
    original_path = "C:\\Users\\User\\Documents\\missing.pdf"
    
    with patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.rglob", return_value=[]):
        
        resolved = source_manager._resolve_path_mismatch(original_path)
        assert resolved is None

def test_is_wsl_true(source_manager):
    """Test WSL detection returns True."""
    with patch("sys.platform", "linux"), \
         patch("builtins.open", new_callable=MagicMock) as mock_open:
        
        mock_file = MagicMock()
        mock_file.read.return_value = "Linux version ... microsoft-standard-WSL2"
        mock_open.return_value.__enter__.return_value = mock_file
        
        assert source_manager._is_wsl() is True

def test_is_wsl_false(source_manager):
    """Test WSL detection returns False."""
    with patch("sys.platform", "linux"), \
         patch("builtins.open", new_callable=MagicMock) as mock_open:
        
        mock_file = MagicMock()
        mock_file.read.return_value = "Linux version ... generic"
        mock_open.return_value.__enter__.return_value = mock_file
        
        assert source_manager._is_wsl() is False

def test_open_in_wsl_success(source_manager):
    """Test opening file in WSL."""
    linux_path = Path("/home/user/doc.txt")
    windows_path = r"\\wsl.localhost\Ubuntu\home\user\doc.txt"
    
    with patch("subprocess.run") as mock_run, \
         patch("subprocess.Popen") as mock_popen:
        
        # Mock wslpath output
        mock_run.return_value.stdout = windows_path
        
        source_manager._open_in_wsl(linux_path)
        
        # Verify wslpath called
        mock_run.assert_called_with(
            ["wslpath", "-w", str(linux_path)],
            capture_output=True,
            text=True,
            check=True
        )
        
        # Verify cmd.exe called
        mock_popen.assert_called_with(
            ["cmd.exe", "/c", "start", "", windows_path]
        )

def test_normalize_path_permission_error(source_manager):
    """Test handling of PermissionError during path existence check."""
    path = "/root/secret.txt"
    with patch("pathlib.Path.exists", side_effect=PermissionError("Permission denied")), \
         patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
        
        # Should return None and show warning (or just return None depending on impl)
        # The current impl doesn't catch PermissionError in _normalize_path, so it might raise.
        # Let's verify if it raises or if we need to update the code.
        # Based on reading the code, it calls .exists() directly.
        with pytest.raises(PermissionError):
            source_manager._normalize_path(path)

def test_resolve_path_mismatch_no_project_root(mock_api_client):
    """Test resolution fails when project root is not set."""
    manager = SourceOpenManager(mock_api_client, project_root=None)
    assert manager._resolve_path_mismatch("foo.txt") is None

def test_resolve_path_mismatch_documents_not_found(source_manager):
    """Test resolution fails when documents directory doesn't exist."""
    with patch("pathlib.Path.exists", return_value=False):
        assert source_manager._resolve_path_mismatch("foo.txt") is None

def test_resolve_path_mismatch_multiple_matches(source_manager):
    """Test resolution logic when multiple files match the filename."""
    original_path = "/old/path/parent_folder/target.txt"
    
    match1 = Path("/mock/project/documents/other_folder/target.txt")
    match2 = Path("/mock/project/documents/parent_folder/target.txt")
    
    # Mock documents dir exists
    with patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.rglob", return_value=[match1, match2]):
        
        resolved = source_manager._resolve_path_mismatch(original_path)
        # Should prefer match2 because parent folder matches
        assert resolved == match2

def test_open_path_show_in_folder(source_manager):
    """Test open_path with 'show_in_folder' mode."""
    path = "/home/user/file.txt"
    with patch.object(source_manager, "_normalize_path", return_value=Path(path)), \
         patch.object(source_manager, "_show_in_folder") as mock_show:
        
        source_manager.open_path(path, mode="show_in_folder")
        mock_show.assert_called_once_with(Path(path))

def test_open_path_copy_path(source_manager):
    """Test open_path with 'copy_path' mode."""
    path = "/home/user/file.txt"
    with patch.object(source_manager, "_normalize_path", return_value=Path(path)), \
         patch.object(source_manager, "_copy_to_clipboard") as mock_copy:
        
        source_manager.open_path(path, mode="copy_path")
        mock_copy.assert_called_once_with(Path(path))

def test_launch_default_linux_fallback(source_manager):
    """Test fallback to webbrowser on Linux if xdg-open fails."""
    path = Path("/home/user/file.txt")
    with patch("sys.platform", "linux"), \
         patch.object(source_manager, "_is_wsl", return_value=False), \
         patch("subprocess.Popen", side_effect=FileNotFoundError), \
         patch("webbrowser.open") as mock_web_open:
        
        source_manager._launch_default(path)
        mock_web_open.assert_called_once_with(path.as_uri())

def test_launch_default_macos(source_manager):
    """Test launching on macOS."""
    path = Path("/Users/user/file.txt")
    with patch("sys.platform", "darwin"), \
         patch("subprocess.Popen") as mock_popen:
        
        source_manager._launch_default(path)
        mock_popen.assert_called_once_with(["open", str(path)])

def test_launch_open_with_dialog_linux(source_manager):
    """Test 'Open With' dialog on Linux."""
    path = Path("/home/user/file.txt")
    selected_app = "/usr/bin/gedit"
    
    with patch("sys.platform", "linux"), \
         patch("PySide6.QtWidgets.QFileDialog.getOpenFileName", return_value=(selected_app, "")), \
         patch("subprocess.Popen") as mock_popen:
        
        source_manager._launch_open_with_dialog(path)
        mock_popen.assert_called_once_with([selected_app, str(path)])

def test_launch_open_with_dialog_macos(source_manager):
    """Test 'Open With' dialog on macOS."""
    path = Path("/Users/user/file.txt")
    selected_app = "/Applications/TextEdit.app"
    
    with patch("sys.platform", "darwin"), \
         patch("PySide6.QtWidgets.QFileDialog.getOpenFileName", return_value=(selected_app, "")), \
         patch("subprocess.Popen") as mock_popen:
        
        source_manager._launch_open_with_dialog(path)
        mock_popen.assert_called_once_with(["open", str(path), "-a", selected_app])

def test_launch_open_with_dialog_windows(source_manager):
    """Test 'Open With' dialog on Windows."""
    path = Path("C:\\file.txt")
    
    with patch("sys.platform", "win32"), \
         patch("subprocess.Popen") as mock_popen:
        
        source_manager._launch_open_with_dialog(path)
        mock_popen.assert_called_once_with(["rundll32", "shell32.dll,OpenAs_RunDLL", str(path)])

def test_show_in_folder_windows(source_manager):
    """Test show in folder on Windows."""
    path = Path("C:\\folder\\file.txt")
    with patch("sys.platform", "win32"), \
         patch("os.startfile", create=True) as mock_startfile:
        
        source_manager._show_in_folder(path)
        mock_startfile.assert_called_once_with(str(path.parent))

def test_get_recent_entries(source_manager):
    """Test retrieving recent entries."""
    source_manager._track_recent("file1")
    source_manager._track_recent("file2")
    
    entries = source_manager.get_recent_entries()
    assert len(entries) == 2
    assert entries[0].path == "file2"
    assert entries[1].path == "file1"
    
    # Verify it returns a copy
    entries.pop()
    assert len(source_manager._recent_entries) == 2

def test_track_recent_add_new(source_manager):
    """Test adding a new recent entry."""
    path = "/home/user/new_file.txt"
    with patch.object(source_manager, "entry_added") as mock_signal:
        entry = source_manager._track_recent(path)
        
        assert entry.path == path
        assert len(source_manager._recent_entries) == 1
        assert source_manager._recent_entries[0] == entry
        mock_signal.emit.assert_called_once_with(entry)

def test_track_recent_update_existing(source_manager):
    """Test updating an existing recent entry moves it to top."""
    path1 = "/home/user/file1.txt"
    path2 = "/home/user/file2.txt"
    
    source_manager._track_recent(path1)
    source_manager._track_recent(path2)
    
    # file2 should be at index 0, file1 at index 1
    assert source_manager._recent_entries[0].path == path2
    
    # Access file1 again
    with patch.object(source_manager, "entry_updated") as mock_signal:
        source_manager._track_recent(path1)
        
        # file1 should now be at index 0
        assert source_manager._recent_entries[0].path == path1
        assert source_manager._recent_entries[1].path == path2
        mock_signal.emit.assert_called_once()

def test_track_recent_max_entries(source_manager):
    """Test that max entries limit is respected."""
    source_manager.max_entries = 2
    
    source_manager._track_recent("file1")
    source_manager._track_recent("file2")
    source_manager._track_recent("file3")
    
    assert len(source_manager._recent_entries) == 2
    assert source_manager._recent_entries[0].path == "file3"
    assert source_manager._recent_entries[1].path == "file2"
    # file1 should be gone

def test_remove_entry(source_manager):
    """Test removing an entry."""
    path = "/home/user/file.txt"
    source_manager._track_recent(path)
    
    with patch.object(source_manager, "entry_removed") as mock_signal:
        result = source_manager.remove_entry(path)
        
        assert result is True
        assert len(source_manager._recent_entries) == 0
        mock_signal.emit.assert_called_once()

def test_remove_entry_not_found(source_manager):
    """Test removing a non-existent entry."""
    result = source_manager.remove_entry("/missing.txt")
    assert result is False

def test_clear_entries(source_manager):
    """Test clearing all entries."""
    source_manager._track_recent("file1")
    source_manager._track_recent("file2")
    
    with patch.object(source_manager, "entries_cleared") as mock_signal:
        source_manager.clear_entries()
        
        assert len(source_manager._recent_entries) == 0
        mock_signal.emit.assert_called_once()

def test_queue_entry(source_manager):
    """Test queuing an entry."""
    path = "/home/user/file.txt"
    with patch("pathlib.Path.exists", return_value=True), \
         patch.object(source_manager, "entry_updated") as mock_signal:
        
        entry = source_manager.queue_entry(path, queued=True)
        
        assert entry.queued is True
        assert entry.reindexed is False
        mock_signal.emit.assert_called()

def test_process_queue_success(source_manager, mock_api_client):
    """Test processing the queue with successful reindexing."""
    path = "/home/user/file.txt"
    entry = source_manager._track_recent(path)
    source_manager._set_entry_queued(entry, True)
    
    mock_api_client.upload_document.return_value = {"status": "success"}
    
    success, failures = source_manager.process_queue()
    
    assert success == 1
    assert failures == 0
    assert entry.queued is False
    assert entry.reindexed is True
    assert entry.last_error is None
    mock_api_client.upload_document.assert_called_once()

def test_process_queue_failure(source_manager, mock_api_client):
    """Test processing the queue with failed reindexing."""
    path = "/home/user/file.txt"
    entry = source_manager._track_recent(path)
    source_manager._set_entry_queued(entry, True)
    
    mock_api_client.upload_document.side_effect = Exception("API Error")
    
    success, failures = source_manager.process_queue()
    
    assert success == 0
    assert failures == 1
    assert entry.queued is True
    assert entry.reindexed is False
    assert entry.last_error == "API Error"

def test_trigger_reindex_path(source_manager, mock_api_client):
    """Test triggering reindex for a specific path."""
    path = "/home/user/file.txt"
    with patch("pathlib.Path.exists", return_value=True):
        mock_api_client.upload_document.return_value = {"status": "success"}
        
        result = source_manager.trigger_reindex_path(path)
        
        assert result is True
        mock_api_client.upload_document.assert_called_once()

def test_clear_queue(source_manager):
    """Test clearing the queue status."""
    path = "/home/user/file.txt"
    entry = source_manager._track_recent(path)
    source_manager._set_entry_queued(entry, True)
    
    changed = source_manager.clear_queue()
    
    assert changed is True
    assert entry.queued is False

def test_find_entry(source_manager):
    """Test finding an entry."""
    path = "/home/user/file.txt"
    source_manager._track_recent(path)
    
    entry = source_manager.find_entry(path)
    assert entry is not None
    assert entry.path == path
    
    assert source_manager.find_entry("/other.txt") is None

def test_resolve_path_mismatch_exception(source_manager):
    """Test exception handling in resolve_path_mismatch."""
    with patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.rglob", side_effect=Exception("Disk Error")):
        
        resolved = source_manager._resolve_path_mismatch("foo.txt")
        assert resolved is None

def test_open_path_invalid(source_manager):
    """Test open_path with invalid path."""
    with patch.object(source_manager, "_normalize_path", return_value=None):
        source_manager.open_path("invalid")
        # Should just return without error

def test_process_queue_empty(source_manager):
    """Test processing an empty queue."""
    source_manager.clear_entries()
    success, failures = source_manager.process_queue()
    assert success == 0
    assert failures == 0

def test_set_entry_queued_no_change(source_manager):
    """Test _set_entry_queued when state doesn't change."""
    path = "/home/user/file.txt"
    entry = source_manager._track_recent(path)
    entry.queued = True
    
    with patch.object(source_manager, "entry_updated") as mock_signal:
        source_manager._set_entry_queued(entry, True)
        mock_signal.emit.assert_not_called()

def test_launch_default_exception(source_manager):
    """Test exception handling in _launch_default."""
    path = Path("/home/user/file.txt")
    with patch("sys.platform", "linux"), \
         patch.object(source_manager, "_is_wsl", return_value=False), \
         patch("subprocess.Popen", side_effect=Exception("Launch Failed")):
        
        with pytest.raises(Exception):
            source_manager._launch_default(path)


