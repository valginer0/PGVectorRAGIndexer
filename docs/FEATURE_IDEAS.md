# Feature Ideas & Roadmap

This document tracks feature ideas for future development. Ideas here are not yet scheduled—they're collected for consideration and planning.

When ready to implement, items should be moved to a feature branch with a proper implementation plan.

---

## 🔮 Ideas Under Consideration

### 1. Remote Backend Support
**Status**: Idea  
**Priority**: TBD  
**Branch**: (not yet created)

**Description**:  
Allow the desktop app to connect to a Docker backend running on a different machine on the local network, rather than requiring Docker to run on the same machine as the UI.

**Current State**:
- `APIClient` already accepts a configurable `base_url` parameter
- Currently hardcoded to `http://localhost:8000` in `main_window.py`
- Docker management (start/stop) is tightly coupled with the UI

**Proposed Changes**:
1. Add a "Backend URL" setting in the Settings tab
2. Add a toggle for "Local Docker" vs "Remote Server" mode
3. Hide Docker control buttons when in Remote mode (can't start/stop remote containers)
4. Persist the user's preference (e.g., `QSettings` or config file)
5. Validate connection on URL change

**Use Cases**:
- Run heavy Docker backend on a powerful server/NAS
- Multiple workstations sharing one indexed database
- Separate the UI from resource-intensive embedding/indexing

**Technical Notes**:
- The FastAPI backend already binds to `0.0.0.0:8000` (accessible from network)
- May need firewall/port configuration guidance for users
- Consider security implications (authentication?) for network exposure

---

### 2. Split Deployment Support
**Status**: Idea  
**Priority**: TBD  
**Branch**: (not yet created)  
**Depends on**: #1 Remote Backend Support

**Description**:  
Enable a deployment model where the Docker backend runs on a dedicated server (Linux/Windows/macOS) while the lightweight desktop UI runs on user workstations. This separates resource-intensive indexing/embedding from the UI.

**Architecture**:
```
[Server Host]                      [Desktop Workstations]
├── Docker Engine                  ├── Desktop UI only (no Docker)
├── vector_rag_db                  └── Connects to http://server:8000
├── vector_rag_app
└── Port 8000 exposed
```

**Proposed Implementation**:

#### Tier 1: Server Setup Script (Linux/macOS/WSL)
Create `server-setup.sh` that:
1. Detects OS (Linux distro, macOS, WSL)
2. Installs Docker Engine (not Rancher Desktop—servers don't need GUI)
3. Pulls and starts containers via docker-compose
4. Configures firewall (ufw, firewalld, etc.)
5. Prints connection URL: `http://<server-ip>:8000`

```bash
# User SSHs into server, then runs:
curl -fsSL https://raw.githubusercontent.com/.../server-setup.sh | bash
```

**Effort**: ~2-4 hours (mostly testing across distros)

#### Tier 2: Desktop Installer Flag
Modify `bootstrap_desktop_app.sh` to accept:
```bash
./bootstrap_desktop_app.sh --remote-backend http://192.168.1.50:8000
```
This would:
1. Skip Docker/Rancher installation
2. Install only Python + PySide6 + dependencies
3. Configure app to use remote URL
4. Launch UI

#### Tier 3: Windows Server Support (Complex)
Windows as a server host is more challenging:

| Approach | Cost | Viability |
|----------|------|-----------|
| **WSL2 + Docker Engine** | ✅ Free | ✅ Best option — scriptable, uses Linux script inside WSL |
| **Rancher Desktop** | ✅ Free | ⚠️ Requires GUI session, user must be logged in |
| **Podman Desktop** | ✅ Free | ⚠️ Alternative to Rancher, daemonless architecture |
| **Docker Desktop** | ⚠️ Paid for enterprise | ⚠️ Requires GUI session, licensing restrictions |
| **Windows Container Mode** | N/A | ❌ Cannot run our Linux images (see note below) |

> **Note on Windows Container Mode**: Windows supports TWO container types:
> - **Linux containers** (via WSL2): Runs Linux images like our `pgvector/pgvector:pg16` ✅
> - **Windows containers** (native): Runs Windows Server images only ❌
>
> Our app uses Linux-based containers. "Windows container mode" in Docker/Rancher is for 
> running Windows Server images (.NET Framework, IIS, etc.) and cannot run our images.
> Always use **Linux container mode** (the default in Rancher/Docker Desktop).

**Recommended Windows path**:
```powershell
# Step 1: Install WSL (one-time, requires reboot)
wsl --install -d Ubuntu

# Step 2: Run Linux server script inside WSL
wsl -d Ubuntu -- bash -c "curl -fsSL .../server-setup.sh | bash"
```

**Use Cases**:
- NAS or home server running containers 24/7 (most NAS devices run Linux—see below)
- Office server shared by multiple workstations
- Keeping laptops lightweight (no Docker overhead)
- Centralized document index for a team

**NAS/Home Server OS Notes**:
Most consumer NAS devices run Linux-based operating systems with native Docker support:
| Device | OS | Docker Support |
|--------|-----|----------------|
| Synology | DSM (Linux) | ✅ Native Docker package |
| QNAP | QTS (Linux) | ✅ Container Station |
| TrueNAS | FreeBSD/Linux | ✅ Docker or jails |
| Unraid | Linux | ✅ Docker built-in |
| Raspberry Pi | Raspberry Pi OS | ✅ Docker Engine (ARM) |

These would use the **Tier 1 Linux script** with minimal modification.

**Technical Notes**:
- Requires #1 (Remote Backend Support) to be implemented first
- Consider adding health check / connection test in UI
- May need documentation for router/firewall port forwarding
- Security: Consider future authentication for network-exposed API

---

### 3. Multi-User Support
**Status**: Idea  
**Priority**: TBD  
**Branch**: (not yet created)  
**Depends on**: #1 Remote Backend Support, #2 Split Deployment Support

**Description**:  
Enable multiple desktop UI clients to connect to a shared backend server simultaneously. This allows teams to share a centralized document index.

**Current State (Good News)**:
The architecture is **already mostly multi-user compatible**:
- FastAPI handles concurrent HTTP requests natively
- PostgreSQL manages transaction isolation
- Source ID deduplication is deterministic (same file = same ID)
- All search/list/view operations are read-only and stateless

**What Already Works (No Changes Needed)**:
| Operation | Multi-User Safe? | Reason |
|-----------|------------------|--------|
| Search | ✅ Yes | Read-only, stateless |
| List documents | ✅ Yes | Read-only query |
| View document | ✅ Yes | Read-only query |
| Get statistics | ✅ Yes | Read-only query |
| Upload same file | ✅ Yes | Deduplication by source_id |

**Potential Issues & Solutions**:
| Scenario | Risk | Solution |
|----------|------|----------|
| User A deletes while User B views | Low | Handle 404s gracefully in UI |
| Bulk delete affects other users | Medium | Warning dialog with affected count |
| Stale document list | Low | Add "Last refreshed" indicator |
| No authentication | Security | Optional: API key or basic auth |

**Implementation Tiers**:

| Tier | Scope | Effort |
|------|-------|--------|
| **Minimal** | Just point multiple UIs at same backend | ~0 hours (works today) |
| **Polished** | Better error handling, refresh hints | ~4-6 hours |
| **Secure** | Add API key authentication | +4-8 hours |
| **Enterprise** | User accounts, permissions, audit logs | +20-40 hours |

**Recommended Starting Point**: Polished tier
1. Robust error handling for concurrent modifications
2. "Last refreshed" timestamp in document list
3. Graceful 404 handling when documents disappear
4. Multi-user setup documentation

**Technical Notes**:
- No queue needed — synchronous HTTP is sufficient
- PostgreSQL handles write conflicts at transaction level
- Consider WebSocket for real-time updates (future enhancement)

---

### 4. Run-Level Status / Indexing Health Dashboard
**Status**: Idea  
**Priority**: TBD  
**Branch**: (not yet created)  
**Depends on**: None (independent feature)

**Description**:  
Provide users with a simple, clear answer to: "Is my knowledge up to date?"

Currently, the system has excellent **file-level correctness** (file hashing, deduplication, incremental updates), but users can't easily see the **system-level health**. This feature exposes run-level status so users trust the "set it and forget it" promise.

**The Mental Model**:
| Level | Question | Currently |
|-------|----------|-----------|
| File-level | "Is `report.pdf` indexed?" | ✅ Yes (file hash) |
| Folder-scan | "What changed in `/Docs`?" | ⚠️ Implicit |
| **Run-level** | "Is my knowledge up to date?" | ❌ Not visible |

**What Users See (Target UX)**:
```
✅ All indexed folders are up to date
Last sync: Jan 8, 2:03 AM | 4,812 files | 9 updated, 3 new | 12 skipped (see details)
```
Or in partial state:
```
⚠️ Last sync completed with warnings
Jan 8, 2:03 AM | 4,812 files | 9 updated | 12 warnings (click to view)
```

**Data Model (stored in PostgreSQL)**:
```sql
CREATE TABLE indexing_runs (
    id UUID PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    status TEXT NOT NULL,  -- 'running', 'success', 'partial', 'failed'
    roots JSONB,           -- list of indexed folders
    files_scanned INT,
    files_added INT,
    files_updated INT,
    files_skipped INT,
    files_unchanged INT,
    errors JSONB           -- categorized error list
);
```

> **Why DB, not file?** Storing in PostgreSQL ensures:
> - Available from any client (multi-user, remote UI)
> - Persistent across restarts
> - Can track history of runs (not just last run)

**Error Categorization**:
Real-world indexing encounters various issues. All problematic files are **skipped** and **accumulated into categorized lists** for user review:

| Category | Example | Severity | Behavior |
|----------|---------|----------|----------|
| `empty_file` | Zero-byte files | ⚠️ Warning | Skipped, listed |
| `encrypted_pdf` | Password-protected PDFs | ⚠️ Warning | Skipped, listed at end |
| `parse_error` | Corrupted/malformed files | ⚠️ Warning | Skipped, listed |
| `permission_denied` | File system access issues | ❌ Error | Skipped, listed |
| `timeout` | OCR or processing timeout | ❌ Error | Skipped, listed |
| `disk_full` | Write failures | ❌ Critical | Run aborts |

**Known Limitations**:
- Cannot detect external file changes without running a scan
- "Last indexed" timestamp reflects when *we* last scanned, not when files changed
- The Recent tab tracks files *opened from the app*, not external edits

**UI Display Options**:

| Surface | What to Show |
|---------|--------------|
| Desktop: Settings tab | Add status section (run summary, history) |
| CLI: `ragvault status` | Text summary |
| API: `/status` endpoint | JSON run metadata |

**Implementation Effort**:
| Step | Effort |
|------|--------|
| DB schema + migration | ~1 hour |
| Backend: write run records | ~2 hours |
| API: `/status` endpoint | ~1 hour |
| Desktop UI: status display | ~2-3 hours |
| CLI: `status` command | ~1 hour |
| **Total** | **~7-9 hours** |

**Technical Notes**:
- This is foundational for scheduled/headless indexing trust
- Consider pruning old runs (keep last N or last 30 days)
- Could add email/webhook notifications on failure (future)

---

### 5. Upload Tab UI Streamlining
**Status**: Idea  
**Priority**: TBD  
**Branch**: (not yet created)  
**Depends on**: None (independent feature)

**Description**:  
Simplify the Upload tab by consolidating actions and adding "last indexed" visibility per folder.

**Current State**:
- Two separate buttons: "Index File" and "Index Folder"
- No visible "last indexed" timestamp for folders
- File selection requires separate flow from folder browsing

**Proposed Changes**:

1. **Make "Index Folder" the primary action**
   - Users can select individual files within the folder picker tree
   - Folder picker already supports file selection

2. **Remove or minimize "Index File" button**
   - Keep as secondary option (small "+" or menu item) for power users
   - Frees UI real estate

3. **Add "Last Indexed" timestamp per folder**
   - Display next to currently selected folder
   - Subfolders inherit timestamp from topmost indexed ancestor
   - Example: `Last indexed: Jan 8, 2:03 AM (via /Docs)`

4. **Folder hierarchy inheritance**
   - When `/Docs` is indexed, all subfolders show same timestamp
   - UI indicates "inherited from parent" vs "directly indexed"

**Trade-offs**:
| Concern | Mitigation |
|---------|------------|
| Indexing single file now takes 3 clicks | Rare use case; keep secondary option |
| Users expect separate buttons | Folder picker is intuitive for file selection |

**Implementation Effort**: ~3-5 hours

**Technical Notes**:
- Requires tracking which root folder was indexed (for inheritance)
- May want to store per-folder metadata in DB for timestamp lookup
- Consider: should "last indexed" show per-folder or per-run?

---

### 6. Scheduled Automatic Indexing
**Status**: Idea  
**Priority**: TBD  
**Branch**: (not yet created)  
**Depends on**: None (standalone), synergizes with #2, #4, #6

**Description**:  
Enable automatic periodic indexing of "watched folders." Users register root folders they want to keep indexed, and the system periodically scans for changes and re-indexes.

**Core Concept**:
- **Watched Folders List**: Stored in DB, managed via UI (add/remove folders)
- **Scheduled Scans**: Hourly, daily, or custom intervals
- **Incremental Updates**: Only process changed files (existing hash-based detection)

**Where Does Scanning Run?**:

| Deployment | Scheduler Location | Why |
|------------|-------------------|-----|
| Desktop-only | Desktop app | Server can't see local files |
| Split (#2) | Desktop client | Files are on client machine |
| Server-hosted files | Server (cron/APScheduler) | Files accessible to server |

> **Key insight**: The scheduler must run where the files are. Even with a remote backend, local files require the desktop client to perform scans.

**Data Model**:
```sql
CREATE TABLE watched_folders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    root_path TEXT NOT NULL,
    client_id TEXT,                    -- identifies which desktop registered this
    schedule TEXT DEFAULT 'daily',     -- 'hourly', 'daily', 'weekly', 'manual'
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_scanned_at TIMESTAMPTZ,
    last_scan_status TEXT,             -- 'success', 'partial', 'failed'
    exclusion_patterns TEXT[]          -- inherited from folder dialog
);
```

**UI Requirements**:

1. **Watched Folders Manager** (new panel or tab section)
   - List of registered folders with status
   - Add folder (reuse existing folder picker)
   - Remove folder (with confirmation)
   - Enable/disable per folder
   - Edit schedule per folder

2. **Per-folder controls**:
   | Action | Description |
   |--------|-------------|
   | ➕ Add | Register new folder to watch |
   | 🗑️ Remove | Delete from watch list (keeps indexed data) |
   | ⏸️ Disable | Pause automatic scans |
   | 🔄 Scan Now | Trigger immediate scan |
   | ⚙️ Settings | Edit schedule, exclusions |

3. **Status indicators**:
   - Last scanned: timestamp
   - Next scan: scheduled time
   - Status: ✅ Up to date / ⚠️ Pending / ❌ Failed

**Desktop Scheduler Options**:

| Approach | Pros | Cons |
|----------|------|------|
| **Background thread** | Simple, works while app runs | App must be open |
| **System tray mode** | App can minimize to tray | Still requires app running |
| **OS scheduled task** | Runs even when app closed | Complex setup, platform-specific |

**Recommended**: Start with background thread + tray mode. Add OS-level scheduling later.

**Implementation Effort**:
| Step | Effort |
|------|--------|
| DB schema + API endpoints | ~2-3 hours |
| UI: watched folders list | ~3-4 hours |
| Background scheduler (desktop) | ~3-4 hours |
| Integration with existing indexer | ~2 hours |
| Tray mode (minimize to tray) | ~2 hours |
| **Total** | **~12-15 hours** |

**Technical Notes**:
- Reuse `FolderIndexDialog` logic for scanning
- Store exclusion patterns per watched folder
- Synergizes with #4 (run history/status dashboard)
- Synergizes with #6 (tree view shows watched roots)
- Consider: what happens if folder is deleted/moved?

---

### 7. Hierarchical Document Browser
**Status**: Idea  
**Priority**: TBD  
**Branch**: (not yet created)  
**Depends on**: None (independent, but synergizes with #4)

**Description**:  
Replace the flat document list in the Documents tab with a hierarchical folder tree. With 2,500+ indexed files, the current flat list is difficult to navigate even with sorting. A tree view allows users to drill down by folder structure.

**Current State**:
- Documents tab shows flat list of all indexed files
- Each row has: Source URI, Type, Chunks, Created, Updated, Delete
- Pagination helps but doesn't solve navigation problem
- Users can't easily find a specific file without knowing its exact path

**Proposed UX**:
```
📁 C:\Users\v_ale\My Drive\home_connections (1,234 files)
   ├── 📁 Fla (456 files, Last updated: Jan 7)
   │   ├── 📁 home (234 files)
   │   │   ├── 📁 cars (12 files)
   │   │   │   ├── 📄 KiaEV6_2.txt     Jan 2    Jan 9
   │   │   │   └── 📄 TeslaModel3.pdf  Dec 15   Dec 15
   │   │   └── 📁 taxes (89 files)
   │   └── 📁 insurance (122 files)
   └── 📁 CA (778 files, Last updated: Jan 5)
📁 C:\Projects (322 files, Last updated: Dec 28)
```

**Proposed Implementation**:

1. **Backend: Group documents by path prefix**
   - New API endpoint: `GET /documents/tree?root=<path>`
   - Returns folder structure with aggregated counts and timestamps
   - Lazy-loading: only fetch children when folder is expanded

2. **Frontend: Tree widget**
   - Use `QTreeWidget` or `QTreeView` instead of `QTableWidget`
   - Expand/collapse folders
   - Show file count and last-updated per folder (aggregated from children)
   - Click file row to see full details / open context menu

3. **Aggregated metadata per folder**
   - `file_count`: count of indexed files in folder (recursive)
   - `last_updated`: MAX(last_updated) of all files in folder
   - `created`: MIN(indexed_at) of all files in folder

**Data Model**:
No schema change required—derive folder structure from existing `source_uri` paths:
```sql
-- Example: count files per root folder
SELECT 
    split_part(source_uri, '/', 4) as root_folder,
    COUNT(DISTINCT document_id) as file_count,
    MAX(last_updated) as last_updated
FROM document_chunks
GROUP BY root_folder;
```

**UI Modes** (optional):
| Mode | Description |
|------|-------------|
| Tree View | Hierarchical folder browser (proposed) |
| List View | Current flat list (keep as option) |

**Implementation Effort**:
| Step | Effort |
|------|--------|
| Backend: tree structure API | ~3-4 hours |
| Frontend: tree widget | ~4-6 hours |
| Folder aggregation (counts, timestamps) | ~2 hours |
| Toggle between tree/list view | ~1 hour |
| **Total** | **~10-13 hours** |

**Technical Notes**:
- Path parsing must handle both Windows (`\`) and Unix (`/`) paths
- Consider caching folder aggregates for large indexes
- Synergizes with #4 (Health Dashboard) for timestamp data
- Could add search/filter within tree view

---

## ✅ Implemented Features
(Move features here after they ship)

---

## 🗑️ Rejected/Deferred Ideas
(Move ideas here that are explicitly not planned)

---

*Last updated: 2026-01-08*
