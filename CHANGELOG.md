# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.3] - 2025-10-16

### Added
- **Windows native support** - PowerShell deployment script (`docker-run.ps1`)
- **WINDOWS_SETUP.md** - Comprehensive Windows setup guide
- **DEPLOYMENT_OPTIONS.md** - Comparison of all deployment methods
- **Docker Desktop and Rancher Desktop** support documented
- **DOCUMENTATION_STRUCTURE.md** - Documentation roadmap

### Changed
- Updated QUICK_START.md with Windows installation option
- Updated README.md with Windows deployment instructions
- Updated DEPLOYMENT.md with note pointing to simpler Docker-only guides
- Improved PowerShell script with better error handling and output suppression

### Fixed
- PowerShell script syntax errors (Unicode characters, here-string format)
- Container cleanup logic in PowerShell script
- PostgreSQL notice output suppression

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
