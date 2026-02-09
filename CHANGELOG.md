# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.4.5] - 2026-02-09

### Added
- **Virtualization Help Dialog**: When virtualization is disabled, the installer now shows a prominent GUI dialog with manufacturer-specific BIOS instructions and a clickable "Open Step-by-Step Guide" button (instead of log-only messages).

### Fixed
- **Skip Docker image download when cached**: Installer now checks both app and database images locally before running `docker compose pull`, avoiding unnecessary multi-minute downloads on re-runs.

## [2.4.4] - 2026-02-08

### Added
- **Docker Detection Improvements**: Installer now detects Docker Desktop, Rancher Desktop, and Podman before attempting installation.
  - Docker Desktop detection via file paths and Windows Registry
  - Podman detection with full `docker compose` compatibility validation
  - Virtualization check using PowerShell (`Get-CimInstance`) with `systeminfo` fallback
  - ARM64 architecture detection with Rancher Desktop compatibility warning
  - Manufacturer-specific inline BIOS instructions (Dell, HP, Lenovo, ASUS, Acer, Microsoft Surface, Samsung, LG, Huawei, MSI)
  - WSL2 auto-detection and installation before Rancher Desktop download
  - Skips WSL2 check when Docker Desktop is found (supports Hyper-V backend)

### Changed
- **Installer detection order**: Now checks existing runtimes before attempting downloads, preventing unnecessary 700MB Rancher Desktop downloads.
- **Replaced deprecated `wmic`** with PowerShell `Get-CimInstance` for manufacturer detection (wmic removed since Windows 10 21H1).
- **Replaced slow `systeminfo`** with PowerShell `Get-CimInstance` for virtualization check (<1s vs 10-30s).

### Fixed
- Podman compatibility no longer relies on a fragile `.bat` alias — validates actual `docker compose` support.

## [2.4.0] - 2026-01-12

### Added
- **Windows Installer Parity**: Full feature parity with legacy PowerShell scripts.
- **Rancher Auto-Start**: Installer automatically starts Rancher Desktop/Docker if not running.
- **Rancher Installation**: Automatically installs Rancher Desktop if Docker is not found.
- **Improved Detection**: Added direct binary check for Rancher Desktop `rdctl.exe` to support non-standard PATHs.
- **Reboot & Resume**: Installer triggers system reboot if needed and resumes automatically via Scheduled Task.
- **Image Pre-Pulling**: Installer pulls Docker images during setup to reduce first-run wait time.
- **Self-Healing Installer**: Detects timeouts (300s) and offers reboot to fix stuck Docker daemons.

## [2.3.0] - 2025-12-30

### Added
- **MCP Server** - Model Context Protocol integration for AI agents
  - New `mcp_server.py` exposing `search_documents`, `index_document`, `list_documents`
  - Works with Claude CLI, Claude Desktop, Cursor, and other MCP clients
  - Zero network exposure — uses stdio transport
  - 10 new tests in `tests/test_mcp_server.py`
- **Security Documentation**
  - New `SECURITY.md` with network configuration guidance
  - Friendly security notes added to README, QUICK_START, INSTALL_DESKTOP_APP
- **AI Agent Section in README** - Configuration examples for Claude CLI/Desktop

### Dependencies
- Added `mcp>=1.0.0` to requirements.txt

## [2.2.9] - 2025-12-27

### Fixed
- **Load Common Patterns** - Now merges with existing patterns instead of replacing them
  - Patterns from `.pgvector-ignore` are preserved when loading defaults

## [2.2.8] - 2025-12-27

### Added
- **Global .pgvector-ignore** - Support for home directory ignore file
  - Linux/Mac: `~/.pgvector-ignore`
  - Windows: `C:\Users\YourName\.pgvector-ignore`
  - Patterns from both global and local files are merged automatically

## [2.2.7] - 2025-12-27

### Fixed
- **Manage Tab Filter Bug** - Selecting `*` as Document Type now correctly matches all types
  - Previously treated `*` as a literal value, returning no results
  - Fixed in both client-side (manage_tab.py) and server-side (database.py)

## [2.2.6] - 2025-12-27

### Added
- **Persistent Exclusions (.pgvector-ignore)** - Create a `.pgvector-ignore` file in your project
  - Works like `.gitignore` — patterns auto-loaded when indexing folder
  - Searches parent directories for ignore files
  - 3 new tests for ignore file loading

## [2.2.5] - 2025-12-26

### Added
- **Folder Exclusion Patterns** - Exclude files/folders when indexing directories
  - Wildcard patterns: `**/node_modules/**`, `**/.git/**`, `*.log`, etc.
  - "Load Common Patterns" button for quick setup
  - Live file count updates as you edit patterns
  - Documented in `desktop_app/README.md`

## [2.2.4] - 2025-12-25

### Added
- **Optimized Hybrid Search for Large Databases**
  - Uses UNION approach: top 1000 vector results + ALL fulltext matches
  - Scales to 150K+ chunks without performance degradation
  - Hybrid search now enabled by default in desktop app
- **Improved Search Result Display**
  - Comprehensive null-safety handling
  - Better logging for debugging edge cases

### Fixed
- **Desktop App Search Crashes** - Fixed AttributeError when displaying search results
- **Checkbox Visibility** - Fixed invisible checkbox on dark theme

### Changed
- **RRF Formula Restored** - Reverted to proper Reciprocal Rank Fusion (1/text_rank)

## [2.2.3] - 2025-12-25

### Added
- **Improved Hybrid Search** - Better ranking for full-text matches
  - **Exact-Match Boost**: Documents containing search terms rank higher (+10.0 boost)
  - **Phrase Support**: Quoted phrases use `phraseto_tsquery` for adjacent word matching
  - Fixes issue where low vector similarity would hide relevant exact matches
- **Force Reindex Checkbox** - Upload tab now has option to reprocess existing documents
- **Reindex Script** - `scripts/reindex_all.py` to re-process all documents
  - Useful when changing chunk size or other processing settings
  - Supports `--dry-run` mode to preview affected documents
- **Query Parsing Tests** - 9 new tests for search query parsing
- **Hybrid Search Tests** - 5 new tests for SQL generation and boost logic

### Changed
- **Default Chunk Size** - Reduced from 500 to 250 characters
  - Improves semantic search quality for mixed-content documents
  - Overlap reduced proportionally (50 → 25 characters)
  - Existing documents retain old chunking until reindexed

## [2.2.2] - 2025-12-22

### Added
- **macOS/Linux One-Line Install** - New `bootstrap_desktop_app.sh` script
  - Mirrors the Windows `bootstrap_desktop_app.ps1` functionality
  - Auto-detects macOS Catalina and uses compatible PySide6 version (6.4.3)
  - Works without `ensurepip` (uses `--without-pip` + get-pip.py)
  - Tested on macOS Catalina and Ubuntu (WSL)
  - Usage: `curl -fsSL https://raw.githubusercontent.com/valginer0/PGVectorRAGIndexer/main/bootstrap_desktop_app.sh | bash`

### Improved
- **Documentation** updated to support all container runtimes
  - Docker Desktop, Rancher Desktop, Podman Desktop, Docker in WSL
  - `DESKTOP_APP_WINDOWS.md` and `INSTALL_DESKTOP_APP.md` updated
- **Website** quickstart section reorganized with clearer cross-platform messaging
  - New "macOS / Linux (Desktop App)" tab added
  - "What this command does" and "Features" sections for clarity

## [2.2.1] - 2025-12-20

### Added
- **Encrypted PDF Detection** - Password-protected PDFs are now detected and handled gracefully
  - `EncryptedPDFError` raised when attempting to index encrypted PDFs
  - API returns 403 with `error_type: encrypted_pdf` for password-protected PDFs
  - `GET /documents/encrypted` endpoint to list all encrypted PDFs encountered
  - CLI (`indexer_v2.py`) logs encrypted PDFs to `encrypted_pdfs.log` for headless mode tracking
  - Desktop app shows "🔒 Encrypted PDFs (N)" button with filterable dialog
  - 8 new tests for encrypted PDF handling
- **Improved Error Panel** - Replaced small popup with resizable dialog
  - Minimum size 700x500, resizable
  - Scrollable table with File, Error Type, and Details columns
  - Filter tabs: All | 🔒 Encrypted | ⚠️ Other Errors
  - Export to CSV button for error reports
- **Office Temp File Filter** - `~$*` files (Office temporary/lock files) now filtered from uploads
- **Per-file Timing** - Upload log now shows processing time for each file
- `scripts/run_all_tests.sh` helper to activate the project virtual environment and run the full pytest suite consistently across environments

### Fixed
- **Hash Check Not Working** - API `GET /documents/{id}` now returns `metadata` field with `file_hash`, fixing incremental indexing skip logic
- **Upload Tab Layout** - Removed scroll area, proper element heights, all content visible without scrolling
- **OCR Mode Label** - Changed "Only (OCR files only)" to clearer "Only OCR (scanned docs)"

### Changed
- `/documents` endpoint now returns a paginated payload (`items`, `total`, `limit`, `offset`, `sort`) and all clients/tests have been updated to read from `items`
- API timeout increased from 5 minutes to 2 hours for large OCR files
- Minimum window height increased to 950px to fit all Upload tab content

## [2.2.0] - 2025-12-08

### Added
- **Incremental Indexing** - Smartly detects changed files
  - Calculates file hashes (`xxHash`) to detect content changes efficiently
  - Skips re-indexing unchanged files, saving significant processing time and DB IO
  - Automatically updates modified files
  - O(1) existence checks using ID-based lookup for faster client-side scans
- **Wildcard Search Support**
  - Search Tab now supports `*` wildcard for Document Type to query all types
  - Search results now display the document type (e.g., `[Resume] ...`)
- **Dynamic Upload UI**
  - Upload Tab document type dropdown is now dynamic, populating from the database
  - Added "Refresh" button to update available types
- **Demo Script**
  - `scripts/demo_incremental.sh` for verifying the incremental indexing workflow

## [2.1.0] - 2025-10-20

### Added
- **Document Type/Metadata System** - Organize documents with custom types
  - Upload documents with `document_type` parameter (policy, resume, report, etc.)
  - Store metadata in PostgreSQL JSONB column
  - Filter search results by document type
  - Display document type in documents list
- **Generic Metadata Filtering** - Filter by ANY metadata field
  - Use `metadata.*` syntax for custom fields (e.g., `metadata.author`)
  - Backward compatible with shortcuts (type, namespace, category)
  - Future-proof - works with any metadata you add later
- **Metadata Discovery API** - Discover available metadata dynamically
  - `GET /metadata/keys` - List all metadata keys (with pattern support)
  - `GET /metadata/values?key=X` - Get all values for a specific key
  - Useful for building dynamic UI filters
- **Bulk Delete with Preview** - Safely delete multiple documents
  - `POST /documents/bulk-delete` with `preview: true` for dry-run
  - `POST /documents/bulk-delete` with `preview: false` to actually delete
  - Safety check: Cannot delete all documents without filters
  - Supports multiple filter criteria
- **Export/Backup System** - Create restorable backups
  - `POST /documents/export` - Export documents as JSON backup
  - Includes all chunks, embeddings, and metadata
  - Use before bulk delete for safety
- **Undo/Restore Functionality** - Restore deleted documents
  - `POST /documents/restore` - Restore from backup
  - Safe: Uses ON CONFLICT DO NOTHING (won't overwrite existing)
  - One-click undo in desktop app
- **Desktop App Manage Tab** - Full GUI for bulk operations
  - Filter by document type or custom metadata (JSON)
  - Preview what will be deleted before taking action
  - Export backup button (saves JSON file)
  - Delete button with confirmation dialog
  - Undo button (restore from last backup or file)
  - Results table showing affected documents
- **Legacy Word Support** - Added .doc (Office 97-2003) file support
  - Works with existing `unstructured` library
  - No additional dependencies required
  - Updated desktop app file picker and folder indexing
- **26 new comprehensive tests** covering all new features
  - 9 tests for metadata filtering and discovery
  - 9 tests for bulk delete operations
  - 3 tests for backup/restore functionality
  - 5 tests for legacy Word support

### Changed
- Enhanced `search_similar()` to support `metadata.*` syntax
- Updated `DocumentInfo` model to include `document_type` field
- Updated desktop app Upload tab with Document Type dropdown
- Updated supported file formats list to include .doc
- All 143 tests passing (98.6% pass rate)

### Fixed
- Metadata now correctly stored and retrieved from JSONB column
- List documents endpoint now returns document_type field
- Search filtering now works with generic metadata fields

## [2.0.3] - 2025-10-16

### Added
- **Windows native support** - PowerShell deployment script (`docker-run.ps1`)
- **WINDOWS_SETUP.md** - Comprehensive Windows setup guide
- **DEPLOYMENT_OPTIONS.md** - Comparison of all deployment methods
- **Docker Desktop and Rancher Desktop** support documented
- **DOCUMENTATION_STRUCTURE.md** - Documentation roadmap
- **Automated release script** with smart version bumping (patch/minor/major)
- Database startup in release script for comprehensive testing

### Changed
- Updated QUICK_START.md with Windows installation option
- Updated README.md with Windows deployment instructions
- Updated DEPLOYMENT.md with note pointing to simpler Docker-only guides
- Improved PowerShell script with better error handling and output suppression
- Release script now runs ALL tests (not selective)
- Release script auto-bumps version without manual input

### Fixed
- **Critical**: Upload endpoint now stores original filename instead of temp path
- PowerShell script syntax errors (Unicode characters, here-string format)
- Container cleanup logic in PowerShell script
- PostgreSQL notice output suppression
- Docker Compose obsolete `version` field warning
- Container removal errors during cleanup
- Test failures: Pydantic config validation, exception type expectations

### Removed
- Deleted obsolete v1 documentation (README_v1_legacy.md)
- Deleted one-time migration docs (IMPROVEMENTS_SUMMARY.md)
- Deleted redundant licensing summary (LICENSING_SUMMARY.md)
- Deleted internal ownership notes (OWNERSHIP_NOTES.md)

## [2.0.2] - 2025-10-16

### Added
- **Upload-and-index endpoint** (`/upload-and-index`) for indexing files from ANY location
- Upload files directly from Windows (C:, D:, network drives) without copying
- Upload files from any Linux/macOS directory
- 7 comprehensive unit tests for upload endpoint
- Documentation updates with upload examples in README, QUICK_START, USAGE_GUIDE

### Fixed
- **Flaky integration tests** - Fixed `encode()` calls to use single string instead of `[string][0]`
- Better test isolation with `indexed_document` fixture
- Improved error messages in tests

### Changed
- All tests now pass consistently (37 tests: 11 integration + 19 embedding + 7 upload)

## [2.0.1] - 2025-10-15

### Fixed
- **Critical embedding dimension bug** - Single text embeddings now return 1D list instead of 2D
- Fixed "invalid input syntax for type vector" PostgreSQL error
- Added regression test `test_single_text_returns_1d_list`

## [2.0.0] - 2025-10-14

### Added
- **Docker-only deployment** - Single-command deployment without repository clone
- **GitHub Container Registry** support for pre-built Docker images
- **Comprehensive integration tests** (11/11 passing)
  - Document indexing and retrieval
  - Vector similarity search with multiple metrics
  - Database operations and statistics
  - Embedding consistency tests
- **Database inspection tool** (`inspect_db.sh`) with 9 interactive options
- **Automated setup script** (`setup.sh`) for one-command installation
- **GitHub Actions workflow** for automated Docker builds and publishing
- **Database management documentation** in README
- **Health checks** for Docker containers

### Fixed
- **Critical bug**: Vector type casting in `database.py` and `retriever.py`
  - Fixed `operator does not exist: vector <=> numeric[]` error
  - Proper pgvector format string conversion
  - Added `::vector` type cast in SQL queries
- **Documentation**: Removed hardcoded personal paths from all docs
- **Tests**: Fixed all API mismatches and scope issues

### Changed
- Upgraded to modular v2 architecture
- Improved error handling and logging
- Enhanced configuration management with Pydantic
- Better connection pooling for database operations
- Optimized Docker images with multi-stage builds

### Documentation
- Complete rewrite of README.md with quick start guide
- Added DEPLOYMENT.md with production deployment strategies
- Added BACKUP_GUIDE.md for database backup procedures
- Added QUICK_START.md for 5-minute setup
- Updated all documentation to be user-agnostic

## [1.0.0] - 2024-XX-XX

### Added
- Initial release
- Basic RAG indexing and retrieval
- PostgreSQL with pgvector integration
- Sentence transformers for embeddings
- Simple CLI interface

---

## Release Notes

### v2.0.0 - Major Overhaul

This is a major release with significant improvements:

**🚀 Easy Deployment**
```bash
curl -fsSL https://raw.githubusercontent.com/valginer0/PGVectorRAGIndexer/main/docker-run.sh | bash
```

**✅ Production Ready**
- All integration tests passing
- Docker images published to GitHub Container Registry
- Automated CI/CD pipeline
- Comprehensive documentation

**🐛 Bug Fixes**
- Fixed critical vector search bug affecting all similarity queries
- Improved database connection handling
- Better error messages and logging

**📚 Documentation**
- Complete documentation overhaul
- Step-by-step guides for all deployment scenarios
- Database management and backup procedures
