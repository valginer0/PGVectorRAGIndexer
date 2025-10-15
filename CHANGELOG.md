# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
