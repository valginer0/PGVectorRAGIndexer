# PGVectorRAGIndexer v2.0

A production-ready, modular semantic document search system using PostgreSQL with pgvector extension. Built for RAG (Retrieval-Augmented Generation) applications with enterprise-grade features.

## 🎯 What's New in v2.0

### Major Improvements

- **✅ Modular Architecture**: Clean separation of concerns with dedicated modules for config, database, embeddings, and processing
- **✅ Configuration Management**: Pydantic-based configuration with validation and environment variable support
- **✅ Connection Pooling**: Efficient database connection management with automatic retry and health checks
- **✅ Comprehensive Testing**: Full test suite with unit, integration, and end-to-end tests
- **✅ Document Deduplication**: Automatic detection and prevention of duplicate documents
- **✅ Metadata Support**: Rich metadata storage and filtering capabilities
- **✅ Hybrid Search**: Combine vector similarity with full-text search for better results
- **✅ REST API**: FastAPI-based HTTP API for easy integration
- **✅ Embedding Cache**: In-memory caching for faster repeated queries
- **✅ Batch Processing**: Efficient batch operations for indexing and retrieval
- **✅ Enhanced Schema**: Improved database schema with indexes, triggers, and views
- **✅ Better Error Handling**: Comprehensive error handling with detailed logging
- **✅ CLI Improvements**: Enhanced command-line interface with subcommands

## 📋 Features

### Core Capabilities

- **Multi-Format Support**: PDF, DOCX, XLSX, TXT, HTML, PPTX, CSV, and web URLs
- **Semantic Search**: Vector similarity search using sentence transformers
- **Hybrid Search**: Combine vector and full-text search with configurable weights
- **Document Management**: Full CRUD operations for indexed documents
- **Metadata Filtering**: Filter search results by document properties
- **Connection Pooling**: Efficient database connection management
- **Embedding Cache**: Speed up repeated queries with in-memory cache
- **Batch Operations**: Process multiple documents efficiently
- **Health Monitoring**: Built-in health checks and statistics

### API Features

- **RESTful API**: FastAPI-based HTTP API with automatic OpenAPI documentation
- **CORS Support**: Configurable CORS for web applications
- **Rate Limiting**: Built-in rate limiting support
- **Error Handling**: Comprehensive error responses with detailed messages
- **Async Support**: Asynchronous operations for better performance

## 🚀 Quick Start

### Prerequisites

- **Docker**: Docker Desktop or Rancher Desktop with WSL 2 backend
- **Python**: Python 3.9+ in WSL Ubuntu
- **PostgreSQL**: Runs via Docker container (included)

### Installation

1. **Clone and navigate to project**:
```bash
git clone https://github.com/valginer0/PGVectorRAGIndexer.git
cd PGVectorRAGIndexer
```

2. **Configure environment**:
```bash
# Copy example env file
cp .env.example .env

# Edit .env and update PROJECT_DIR with your absolute path
# Example: PROJECT_DIR=/home/username/projects/PGVectorRAGIndexer
$EDITOR .env  # Use your preferred editor (vi, vim, nano, code, etc.)
```

3. **Create virtual environment**:
```bash
python3 -m venv venv
source venv/bin/activate
```

4. **Install dependencies**:
```bash
pip install -r requirements.txt
```

5. **Start PostgreSQL with pgvector**:
```bash
# Option 1: Using helper script (recommended - auto-initializes database)
./start_database.sh

# Option 2: Direct docker compose (requires manual setup)
cd /path/to/PGVectorRAGIndexer
docker compose up -d
./setup_database.sh  # Run this to initialize schema
```

6. **Verify setup**:
```bash
docker ps  # Check container is running
docker logs vector_rag_db  # View initialization logs
```

## 📖 Usage

### Command-Line Interface

#### Indexing Documents

```bash
# Index a single document
python indexer_v2.py index document.pdf

# Index with Windows path (auto-converted)
python indexer_v2.py index "C:\Users\Name\document.pdf"

# Index a web URL
python indexer_v2.py index https://example.com/article

# Force reindex existing document
python indexer_v2.py index document.pdf --force

# List indexed documents
python indexer_v2.py list

# Show statistics
python indexer_v2.py stats

# Delete a document
python indexer_v2.py delete <document_id>
```

#### Searching Documents

```bash
# Basic search
python retriever_v2.py "What is machine learning?"

# Search with custom parameters
python retriever_v2.py "Python programming" --top-k 10 --min-score 0.8

# Hybrid search (vector + full-text)
python retriever_v2.py "database optimization" --hybrid

# Verbose output (show full text)
python retriever_v2.py "data science" --verbose

# Get context for RAG
python retriever_v2.py "explain transformers" --context

# Filter by document
python retriever_v2.py "query" --filter-doc doc_id_here
```

### REST API

#### Start API Server

```bash
python api.py
```

Or with uvicorn:
```bash
uvicorn api:app --host 0.0.0.0 --port 8000 --reload
```

#### API Documentation

Once running, access:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

#### Example API Calls

**Index a document**:
```bash
curl -X POST "http://localhost:8000/index" \
  -H "Content-Type: application/json" \
  -d '{
    "source_uri": "/path/to/document.pdf",
    "force_reindex": false
  }'
```

**Search documents**:
```bash
curl -X POST "http://localhost:8000/search" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "machine learning",
    "top_k": 5,
    "use_hybrid": false
  }'
```

**List documents**:
```bash
curl "http://localhost:8000/documents?limit=10"
```

**Get statistics**:
```bash
curl "http://localhost:8000/stats"
```

**Health check**:
```bash
curl "http://localhost:8000/health"
```

## ⚙️ Configuration

Configuration is managed through environment variables and the `.env` file. All settings have sensible defaults.

### Environment Variables

```bash
# Database
DB_HOST=localhost
DB_PORT=5432
POSTGRES_DB=rag_vector_db
POSTGRES_USER=rag_user
POSTGRES_PASSWORD=rag_password

# Embedding Model
EMBEDDING_MODEL_NAME=all-MiniLM-L6-v2
EMBEDDING_DIMENSION=384
EMBEDDING_BATCH_SIZE=32

# Chunking
CHUNK_SIZE=500
CHUNK_OVERLAP=50

# Retrieval
RETRIEVAL_TOP_K=5
RETRIEVAL_SIMILARITY_THRESHOLD=0.7
RETRIEVAL_DISTANCE_METRIC=cosine
RETRIEVAL_ENABLE_HYBRID_SEARCH=false

# API
API_HOST=0.0.0.0
API_PORT=8000
API_WORKERS=4
API_LOG_LEVEL=info

# Application
ENVIRONMENT=development
DEBUG=false
MAX_FILE_SIZE_MB=50
CACHE_EMBEDDINGS=true
ENABLE_DEDUPLICATION=true
```

### Configuration Validation

The system uses Pydantic for configuration validation. Invalid configurations will raise clear error messages at startup.

## 🧪 Testing

### Run All Tests

```bash
pytest
```

### Run Specific Test Categories

```bash
# Unit tests only
pytest -m unit

# Integration tests
pytest -m integration

# With coverage
pytest --cov=. --cov-report=html
```

### Test Structure

```
tests/
├── __init__.py
├── conftest.py           # Shared fixtures
├── test_config.py        # Configuration tests
├── test_database.py      # Database tests
└── test_embeddings.py    # Embedding tests
```

## 🏗️ Architecture

### Module Overview

```
PGVectorRAGIndexer/
├── config.py              # Configuration management
├── database.py            # Database operations & pooling
├── embeddings.py          # Embedding service
├── document_processor.py  # Document loading & chunking
├── indexer_v2.py         # Indexing CLI
├── retriever_v2.py       # Search CLI
├── api.py                # REST API
├── init-db.sql           # Database schema
├── requirements.txt      # Dependencies
└── tests/                # Test suite
```

### Database Schema

```sql
-- Main table with enhanced features
CREATE TABLE document_chunks (
    chunk_id BIGSERIAL PRIMARY KEY,
    document_id TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    text_content TEXT NOT NULL,
    source_uri TEXT NOT NULL,
    embedding VECTOR(384),
    metadata JSONB DEFAULT '{}',
    indexed_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(document_id, chunk_index)
);

-- Indexes for performance
CREATE INDEX idx_chunks_embedding_hnsw ON document_chunks 
    USING hnsw (embedding vector_cosine_ops);
CREATE INDEX idx_chunks_text_search ON document_chunks 
    USING gin(to_tsvector('english', text_content));
CREATE INDEX idx_chunks_metadata ON document_chunks 
    USING gin(metadata);
```

### Key Design Patterns

- **Repository Pattern**: Clean data access layer
- **Service Layer**: Business logic separation
- **Factory Pattern**: Service instantiation
- **Singleton Pattern**: Global configuration and services
- **Strategy Pattern**: Pluggable document loaders

## 🔍 Advanced Features

### Hybrid Search

Combine vector similarity with full-text search for better results:

```python
# CLI
python retriever_v2.py "query" --hybrid --alpha 0.7

# API
{
  "query": "machine learning",
  "use_hybrid": true,
  "alpha": 0.7  # 0.7 vector + 0.3 full-text
}
```

### Metadata Filtering

Add and filter by custom metadata:

```python
# Index with metadata
{
  "source_uri": "/path/to/doc.pdf",
  "metadata": {
    "author": "John Doe",
    "category": "research",
    "year": 2024
  }
}

# Search with filters
{
  "query": "neural networks",
  "filters": {
    "document_id": "abc123"
  }
}
```

### Batch Processing

Process multiple documents efficiently:

```python
from indexer_v2 import DocumentIndexer

indexer = DocumentIndexer()
results = indexer.index_batch([
    "/path/to/doc1.pdf",
    "/path/to/doc2.pdf",
    "https://example.com/article"
])
```

## 📊 Performance Optimization

### Database Tuning

For production, consider these PostgreSQL settings:

```sql
-- Increase work memory for vector operations
SET work_mem = '256MB';

-- Tune HNSW index parameters
CREATE INDEX ON document_chunks USING hnsw (embedding vector_cosine_ops)
WITH (m = 32, ef_construction = 128);  -- Higher values = better recall, slower build
```

### Embedding Cache

The system caches embeddings in memory. Monitor cache size:

```python
from embeddings import get_embedding_service

service = get_embedding_service()
print(f"Cache size: {service.get_cache_size()}")
service.clear_cache()  # Clear if needed
```

### Connection Pooling

Adjust pool size based on workload:

```bash
DB_POOL_SIZE=20
DB_MAX_OVERFLOW=40
```

## 🔒 Security Considerations

1. **Database Credentials**: Store in `.env` file (gitignored)
2. **API Authentication**: Add authentication middleware for production
3. **Input Validation**: All inputs validated via Pydantic
4. **SQL Injection**: Protected via parameterized queries
5. **File Upload**: Validate file types and sizes

## 🐛 Troubleshooting

### Database Connection Issues

```bash
# Check container status
docker ps

# Check logs
docker logs vector_rag_db

# Restart container
docker compose restart
```

### Import Errors

```bash
# Ensure virtual environment is activated
source venv/bin/activate

# Reinstall dependencies
pip install -r requirements.txt --upgrade
```

### Memory Issues

```bash
# Clear embedding cache
python -c "from embeddings import get_embedding_service; get_embedding_service().clear_cache()"

# Reduce batch size
export EMBEDDING_BATCH_SIZE=16
```

## 📈 Monitoring

### Health Checks

```bash
# CLI
python indexer_v2.py stats

# API
curl http://localhost:8000/health
```

### Database Statistics

```sql
-- View document statistics
SELECT * FROM document_stats;

-- Check index usage
SELECT * FROM pg_stat_user_indexes WHERE schemaname = 'public';

-- Database size
SELECT pg_size_pretty(pg_database_size(current_database()));
```

## 🔄 Migration from v1

The v2 system is backward compatible with v1 data. To migrate:

1. **Backup existing data**:
```bash
docker exec vector_rag_db pg_dump -U rag_user rag_vector_db > backup.sql
```

2. **Update schema**:
```bash
docker exec -i vector_rag_db psql -U rag_user -d rag_vector_db < init-db.sql
```

3. **Use new CLI**:
```bash
# Old: python indexer.py document.pdf
# New: python indexer_v2.py index document.pdf
```

## 📝 Development

### Code Style

```bash
# Format code
black .

# Lint code
ruff check .

# Type checking
mypy .
```

### Adding New Document Loaders

Extend `DocumentLoader` class in `document_processor.py`:

```python
class CustomLoader(DocumentLoader):
    def can_load(self, source_uri: str) -> bool:
        return source_uri.endswith('.custom')
    
    def load(self, source_uri: str) -> List[Document]:
        # Your loading logic
        pass
```

## 💬 Feedback & Suggestions

**This project does not accept pull requests or code contributions.**

We welcome:
- 🐛 **Bug reports** - Create an issue with details
- 💡 **Feature suggestions** - Share your ideas via issues
- 📝 **Feedback** - Let us know what could be better
- 📧 **Direct contact** - valginer0@gmail.com for specific inquiries

See [CONTRIBUTING.md](CONTRIBUTING.md) for details on how to provide feedback.

All development is maintained exclusively by the copyright holder to ensure code quality and full ownership.

## 🙏 Acknowledgments

- PostgreSQL and pgvector teams
- Sentence Transformers library
- LangChain community
- FastAPI framework

## 📞 Support

For issues and questions:
- Check documentation
- Review test examples
- Check API docs at `/docs`
- Review logs for error details

---

**Version**: 2.0.0  
**Last Updated**: 2024  
**Status**: Production Ready ✅

## 📜 License

**PGVectorRAGIndexer** is dual-licensed under two options:

- 🟩 **Community License (default)** – Free for personal, educational, and research use.  
  You may fork for personal use, but redistribution or commercial use requires permission.  
  See [LICENSE_COMMUNITY.txt](LICENSE_COMMUNITY.txt).

- **Commercial License** – Required for companies or individuals integrating  
  PGVectorRAGIndexer into commercial products or paid services.  
  See [LICENSE_COMMERCIAL.txt](LICENSE_COMMERCIAL.txt) for details and contact  
  Valery Giner at valginer0@gmail.com to discuss terms.

This software is provided **"AS IS"**, without warranty of any kind.  
Voluntary contributions or sponsorships are welcome 

### Support

If you find this tool useful, consider supporting its development:

- **[Star this repo](https://github.com/valginer0/PGVectorRAGIndexer)** - Help others discover it!
- **[Sponsor on GitHub](https://github.com/sponsors/valginer0)** - Support ongoing development
- **Share it** - Tell others who might find it useful

Your support helps maintain and improve this project. Thank you! 
