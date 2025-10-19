# Testing the Desktop Application

## Quick Start Testing

### 1. Run from Windows PowerShell

```powershell
# Navigate to project (using WSL path)
cd \\wsl.localhost\Ubuntu\home\valginer0\projects\PGVectorRAGIndexer

# Launch the app (use .ps1 for UNC paths)
.\run_desktop_app.ps1
```

**Note:** Use `run_desktop_app.ps1` (PowerShell script) when accessing via UNC path (`\\wsl.localhost\...`). The `.bat` file doesn't work with UNC paths.

**What should happen:**
- A window opens showing "PGVectorRAGIndexer - Document Management"
- Status bar shows Docker and API status
- Four tabs: Upload, Search, Documents, Settings

### 2. Test Upload with Windows Path

**Steps:**
1. Click **Upload** tab
2. Click **📁 Select File** button
3. Windows file picker opens - navigate to any Windows location (C:\Users\..., D:\, etc.)
4. Select a `.txt`, `.md`, `.pdf`, or `.docx` file
5. Click **📤 Upload and Index**

**Expected Result:**
- Progress bar shows
- Log shows "Uploading..." then "✓ Uploaded successfully!"
- Full Windows path is preserved (e.g., `C:\Users\YourName\Documents\file.txt`)

**Verify:**
- Go to **Documents** tab
- Click **🔄 Refresh**
- Your file should appear with the FULL Windows path in the "Source URI" column

### 3. Test Search

**Steps:**
1. Click **Search** tab
2. Enter a search query (e.g., "test" or any word from your uploaded document)
3. Click **🔍 Search**

**Expected Result:**
- Results table populates with matching chunks
- Shows score, source (with full path), chunk number, and content preview
- Double-click a result to see full content

### 4. Test Documents Management

**Steps:**
1. Click **Documents** tab
2. Click **🔄 Refresh** if not already loaded
3. Select a document and click **🗑️ Delete**
4. Confirm deletion

**Expected Result:**
- Confirmation dialog appears
- After confirming, document is deleted
- List refreshes automatically

### 5. Test Settings

**Steps:**
1. Click **Settings** tab
2. Check database statistics (should show counts)
3. Click **📋 View Application Logs**

**Expected Result:**
- Statistics show total documents, chunks, and database size
- Logs appear in the text area

## Automated Tests

### Run Unit Tests (from WSL)

```bash
cd /home/valginer0/projects/PGVectorRAGIndexer
source venv/bin/activate
pytest tests/test_desktop_app.py -v
```

**What these test:**
- Desktop app modules can be imported
- API client initializes correctly
- Docker manager initializes correctly
- Windows detection works
- Required files exist
- Directory structure is correct

**Note:** These are smoke tests only. Full GUI testing requires a display server and GUI testing framework (like pytest-qt), which is beyond current scope.

## Platform-Specific Testing

### Windows Testing (Primary)

**Why:** Desktop app is designed for Windows to access Windows file paths.

**Test:**
```powershell
cd \\wsl.localhost\Ubuntu\home\valginer0\projects\PGVectorRAGIndexer
.\run_desktop_app.bat
```

**Verify:**
- File picker shows Windows drives (C:\, D:\, etc.)
- Can navigate to Windows folders
- Full paths are captured and stored

### WSL Testing (Secondary)

**Why:** Verify it works but shows WSL files only.

**Test:**
```bash
cd /home/valginer0/projects/PGVectorRAGIndexer
./run_desktop_app.sh
```

**Expected:**
- App runs but file picker shows WSL filesystem only
- Paths like `/home/user/...` instead of `C:\...`

## Docker Integration Testing

### Test Docker Status Detection

**Steps:**
1. Stop Docker containers: `docker compose down`
2. Launch desktop app
3. Check status bar

**Expected:**
- Shows "🔴 Docker: Stopped"
- Shows "🔴 API: Not Available"
- Offers to start containers

### Test Container Start from App

**Steps:**
1. With containers stopped, click **Start Containers** button
2. Wait for startup

**Expected:**
- Status changes to "🟢 Docker: Running"
- After ~5 seconds, "🟢 API: Ready"
- Can now upload/search/manage documents

## Troubleshooting Tests

### Test: "Python is not installed"

**Simulate:**
```powershell
# Temporarily rename python.exe or run from environment without Python
.\run_desktop_app.bat
```

**Expected:**
- Error message: "Python is not installed on Windows or not in PATH"
- Instructions to install Python

### Test: "Docker is not available"

**Simulate:**
1. Stop Docker Desktop/Rancher Desktop
2. Launch app

**Expected:**
- Status shows "🔴 Docker: Not Available"
- Error message when trying to start containers

### Test: "Can't see Windows files"

**Simulate:**
```bash
# Run from WSL instead of Windows
cd /home/valginer0/projects/PGVectorRAGIndexer
python -m desktop_app.main
```

**Expected:**
- File picker shows WSL filesystem only
- No access to C:\ drives

## Success Criteria

✅ **Upload Tab:**
- Can select files from any Windows location
- Full paths are preserved (e.g., `C:\Projects\file.txt`)
- Upload completes successfully
- Progress is shown

✅ **Search Tab:**
- Can search indexed documents
- Results show with scores
- Can view full content

✅ **Documents Tab:**
- Lists all documents with full paths
- Can delete documents
- Auto-refreshes after operations

✅ **Settings Tab:**
- Shows database statistics
- Can restart containers
- Can view logs

✅ **Docker Integration:**
- Detects container status
- Can start/stop containers from app
- Status indicators update correctly

## Known Limitations

1. **WSL File Access:** When run from WSL, only shows WSL files (by design)
2. **GUI Testing:** No automated GUI tests (would require pytest-qt and display server)
3. **Windows Only:** Full path preservation only works when run from Windows

## Next Steps

After manual testing confirms everything works:

1. **Create test data:** Upload a few sample documents
2. **Test search:** Verify search works across all documents
3. **Test delete:** Verify deletion works and refreshes
4. **Test restart:** Verify Docker restart works
5. **Document any issues:** Report bugs if found

## Reporting Issues

If you find issues, please note:
- What you were doing (which tab, which button)
- What you expected to happen
- What actually happened
- Any error messages
- Screenshots if applicable
