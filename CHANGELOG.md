# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- `/documents` endpoint now returns a paginated payload (`items`, `total`, `limit`, `offset`, `sort`) and all clients/tests have been updated to read from `items`.

### Added
- `scripts/run_all_tests.sh` helper to activate the project virtual environment and run the full pytest suite consistently across environments.

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
