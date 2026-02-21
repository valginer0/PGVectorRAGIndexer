# PGVectorRAGIndexer v2.4
![MCP Compatible](https://img.shields.io/badge/MCP-compatible-blue)

> **Start here:**
> - 🟢 **Most Users (Desktop App)**: [INSTALL_DESKTOP_APP.md](INSTALL_DESKTOP_APP.md)
> - ⚡ **Quick 5-Minute Setup (Docker)**: [QUICK_START.md](QUICK_START.md)
> - 🟡 **Advanced / Server Deployment**: [DEPLOYMENT.md](DEPLOYMENT.md)
> - 🔵 **Usage & API Reference**: [USAGE_GUIDE.md](USAGE_GUIDE.md)

> **Commercial use?**  
> PGVectorRAGIndexer is free for personal use, education, research, and evaluation.  
> Production, CI/CD, or ongoing internal company use requires a commercial license.  
> See [COMMERCIAL.md](./COMMERCIAL.md).

---

### 🤔 In Plain English (What does this actually do?)

> **Imagine a magic bookshelf** that reads and understands every book, document, and note you put on it. When you have a question, you don't have to search for keywords yourself—you just ask the bookshelf in plain English (like "How do I fix the printer?" or "What was our revenue last year?"), and it instantly hands you the exact page with the answer.
>
> **Best of all? It lives 100% on your computer.** Your documents never get sent to the "cloud" or some stranger's server. It's your personal librarian that keeps your secrets safe.

Most search bars are dumb—they only find exact word matches. If you search for **"dog"**, they won't find **"puppy"**.

**This system is smart.** It reads your documents, understands the _meaning_ behind the text, and lets you search using natural language.

---

### 🔒 Designed for Trust, Not the Cloud

What this system does **not** do is just as important as what it does.

PGVectorRAGIndexer does **not** upload your documents, open a public server, or rely on any external AI service.  
Everything runs locally on your computer, using local models and a local database.

This design is intentional. It means:
- Your files never leave your machine
- There are no accounts, subscriptions, or hidden data flows
- You can use it safely with personal, private, or sensitive documents

**Policy:** PGVectorRAGIndexer is local-only by design — your data stays on your hardware, and we do not offer hosted indexing or storage.

Unlike chat-based tools, this app focuses on **search and discovery**, not conversation.  
It helps you *find and rediscover* documents by meaning — even when you don’t remember the exact words.

---

### 🖥️ Two Ways to Deploy

> **💡 Most users only need the Desktop App.** The rest of the docs are for advanced scenarios.

| Feature | **Desktop App** (Recommended) | **Docker / Server** |
|-------|-------------------------------|---------------------|
| **Best For** | Personal use, everyday search | Teams, servers, NAS, automation |
| **Interface** | Native GUI (Windows/Mac/Linux) | Web UI + REST API |
| **Setup** | One-line installer / executable | Docker Compose |
| **File Access** | Native file picker | Mounted volumes only |
| **Privacy** | 100% Local | 100% Local |

Both modes run **entirely on your hardware** — no cloud, no external services.

> **💡 CLI is also available** in both modes for power users:
> - Batch processing
> - Scripting and automation
> - Headless usage  
>
> CLI requires the backend running (via Docker or Desktop App).

---

## 🋹 What's New in v2.4

### 🆕 Latest Features (v2.4)

- **✅ Windows Installer Parity**: Full feature parity with legacy PowerShell scripts
  - Rancher Desktop auto-installation via winget if Docker is missing
  - Automatic runtime start with `rdctl start --container-engine moby`
  - Reboot & resume logic via Scheduled Tasks for seamless installation
  - Docker image pre-pulling during setup
- **✅ Self-Healing Installer**: Detects timeouts and offers system reboot to fix stuck Docker daemons

### Previous Releases (v2.3)

- **✅ MCP Server**: AI agents (Claude CLI, Claude Desktop, Cursor) can connect directly to your local database
  - Uses `stdio` transport — zero network exposure, no open ports
  - Exposes `search_documents`, `index_document`, `list_documents` tools
  - See [AI Agent Integration (MCP)](#-ai-agent-integration-mcp) for setup
- **✅ Security Documentation**: New `SECURITY.md` with network config guidance + friendly notes in docs
- **✅ Encrypted PDF Detection**: Password-protected PDFs are gracefully detected and skipped
  - Returns 403 with `error_type: encrypted_pdf` for clear error handling
  - `GET /documents/encrypted` endpoint to list all skipped encrypted PDFs
  - CLI logs encrypted PDFs to `encrypted_pdfs.log` for headless mode tracking
- **✅ Improved Error Panel**: Desktop app now shows a resizable dialog with filter tabs (All/Encrypted/Other) and CSV export
- **✅ Incremental Indexing**: Smart content change detection using `xxHash`. Skips unchanged files, saving bandwidth and processing time.
- **✅ Wildcard Search**: Document type filter now supports `*` for "All Types".
- **✅ Dynamic UI**: Upload tab automatically fetches available document types from the database.

### Previous Releases (v2.1)

- **✅ Document Type System**: Organize documents with custom types (policy, resume, report, etc.)
- **✅ Bulk Delete with Preview**: Safely delete multiple documents with preview before action
- **✅ Export/Backup System**: Export documents as JSON backup before deletion
- **✅ Undo/Restore Functionality**: Restore deleted documents from backup
- **✅ Desktop App Manage Tab**: Full GUI for bulk operations with backup/restore
- **✅ Legacy Word Support**: Added .doc (Office 97-2003) file support

> ℹ️ **Legacy .doc conversion**: Automatic conversion relies on LibreOffice. **Docker users (recommended) have this pre-installed.** Manual/Local developers must install it and expose the `soffice` binary (e.g., `export LIBREOFFICE_PATH` in `.env`).

### Major Improvements (v2.0)

- **✅ Modern Web UI**: User-friendly web interface for search, upload, and document management
- **✅ Modular Architecture**: Clean separation of concerns with dedicated modules for config, database, embeddings, and processing
- **✅ Configuration Management**: Pydantic-based configuration with validation and environment variable support
- **✅ Connection Pooling**: Efficient database connection management with automatic retry and health checks
- **✅ Comprehensive Testing**: Full test suite with unit, integration, and end-to-end tests (143 tests!)
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

- **Multi-Format Support**: PDF, DOC, DOCX, XLSX, TXT, HTML, PPTX, CSV, and web URLs
- **OCR Support**: Extract text from scanned PDFs and images (PNG, JPG, TIFF, BMP) using Tesseract
- **Semantic Search**: Vector similarity search using sentence transformers
- **Hybrid Search**: Combine vector and full-text search with configurable weights
- **Document Management**: Full CRUD operations for indexed documents
- **Bulk Operations**: Preview, export, delete, and restore multiple documents
- **Backup/Restore**: Export documents as JSON and restore with undo functionality
- **Connection Pooling**: Efficient database connection management
- **Embedding Cache**: Speed up repeated queries with in-memory cache
- **Health Monitoring**: Built-in health checks and statistics

### User Interface


- **Search Interface**: Intuitive search with semantic and hybrid options
- **Drag & Drop Upload**: Easy file upload with progress tracking
- **Document Browser**: View and manage all indexed documents
- **Statistics Dashboard**: Real-time system health and metrics

### API Features

- **RESTful API**: FastAPI-based HTTP API with automatic OpenAPI documentation
- **CORS Support**: Configurable CORS for web applications
- **Rate Limiting**: Built-in rate limiting support
- **Error Handling**: Comprehensive error responses with detailed messages
- **Async Support**: Asynchronous operations for better performance

### 🔐 Encrypted PDF Handling

Password-protected PDFs cannot be indexed without decryption. Instead of crashing or failing silently, PGVectorRAGIndexer handles them gracefully:

**How it works:**
1. When a password-protected PDF is encountered during upload, it's detected immediately
2. The file is skipped (not indexed) and added to a special "encrypted PDFs" list
3. Processing continues with the remaining files — one encrypted file won't stop your batch
4. You can review all encrypted PDFs after the upload completes

**Desktop App:**
- After upload, an **"🔒 Encrypted PDFs (N)"** button appears if any were detected
- Click to see a filterable list of all encrypted files with their paths
- You can copy paths or open the folder to manually decrypt files
- Re-upload the decrypted versions when ready

**API:**
- `GET /documents/encrypted` — List all encrypted PDFs encountered
- Upload returns `403` with `error_type: encrypted_pdf` for individual encrypted files

**CLI (Headless Mode):**
- Encrypted PDFs are logged to `encrypted_pdfs.log` for later review
- Processing continues without interruption

> **Note:** The app cannot decrypt PDFs for you — you'll need the password and a PDF tool to unlock them first.

## 🚀 Getting Started (Desktop App)
**This is the recommended way to use the app.** It gives you the full experience with the native interface.

> 🛡️ **Security note (public Wi-Fi)**
> If you use the app on public or shared Wi-Fi (cafés, airports, hotels), we recommend using a trusted network or a VPN.
> On a private home network, no special setup is needed.

> **Most users only need this guide.** The additional documents are for advanced deployment, customization, or maintenance scenarios.

### 📘 [Read the Full Installation Guide](INSTALL_DESKTOP_APP.md)
*(Includes detailed steps for Windows, macOS, and Linux)*

**Windows Quick Install:**
1. Download [`PGVectorRAGIndexer-Setup.exe`](https://github.com/valginer0/PGVectorRAGIndexer/releases/latest/download/PGVectorRAGIndexer-Setup.exe)
2. Double-click to install
3. Done!

---

### 🤖 AI Agent Integration (MCP)
**New in v2.3+**: You can connect desktop AI agents (Claude Desktop, Cursor, etc.) directly to your local database using the Model Context Protocol (MCP).

PGVectorRAGIndexer acts as a **local MCP tool provider** — it does not run an LLM,
but exposes your indexed documents as searchable tools to compatible AI agents.

**Why use this?**
- 🔒 **Zero network exposure**: Uses `stdio` pipes, so no ports are opened.
- 🧠 **Context-aware AI**: Your AI assistant can fuzzy-search your private documents to answer questions.

**Other compatible clients**
- Cursor (agent mode)
- Claude CLI
- Custom MCP-compatible agents

**Exposed MCP tools**
- `search_documents` — semantic / hybrid search over indexed files
- `index_document` — add or re-index documents
- `list_documents` — enumerate indexed sources

**Setup for Claude Desktop:**
1.  Add this to your `claude_desktop_config.json`:
    ```json
    {
      "mcpServers": {
        "local-rag": {
          "command": "/path/to/your/venv/bin/python",
          "args": ["/path/to/PGVectorRAGIndexer/mcp_server.py"]
        }
      }
    }
    ```
2.  Restart Claude. You will see a 🔌 icon indicating the connection.
3.  Ask: *"Search my documents for 'financial report' and summarize the key points."*

---

### 🛠️ Technical Capability: Web Server Mode (Advanced)
**NOTE**: Use this ONLY if you want to run the application as a headless server or strictly use the Web UI. For the normal desktop experience, see the section above.

### Prerequisites
- **Docker** (required)

### One-line Command (Linux/macOS/WSL)
```bash
curl -fsSL https://raw.githubusercontent.com/valginer0/PGVectorRAGIndexer/main/docker-run.sh | bash
```

**Services will be available at:**
- 🌐 **Web UI**: `http://localhost:8000`
- 📚 **API Docs**: `http://localhost:8000/docs`

### Basic Usage

**1. Check system health:**
```bash
curl http://localhost:8000/health
```

**2. Index a document:**
```bash
# Create a text document in the documents directory
cat > ~/pgvector-rag/documents/sample.txt << 'EOF'
Artificial Intelligence and Machine Learning

Machine learning is a subset of AI that enables computers to learn from data.
Deep learning uses neural networks to process complex patterns.
EOF

# Index it via API
curl -X POST "http://localhost:8000/index" \
  -H "Content-Type: application/json" \
  -d '{"source_uri": "/app/documents/sample.txt"}'
```

**3. Or upload from ANY location:**
```bash
# Index files from any Windows directory - no copying needed!
curl -X POST "http://localhost:8000/upload-and-index" \
  -F "file=@C:\Users\YourName\Documents\report.pdf"
```

**4. Search for similar content:**
```bash
curl -X POST "http://localhost:8000/search" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "your search query",
    "top_k": 5
  }'
```

**5. View logs and manage:**
```bash
cd ~/pgvector-rag

# View logs
docker compose logs -f

# Stop services
docker compose down

# Restart services
docker compose restart

# Update to latest version
docker compose pull && docker compose up -d
```

See [USAGE_GUIDE.md](USAGE_GUIDE.md) for more examples and [QUICK_START.md](QUICK_START.md) for detailed setup.

---

### Alternative: Developer Setup (For Contributing)

**If you want to modify the code:**
```bash
git clone https://github.com/valginer0/PGVectorRAGIndexer.git
cd PGVectorRAGIndexer
./setup.sh
```

This sets up a local development environment with Python virtual environment.

**Benefits of Docker-only:**
- ✅ No repository clone needed
- ✅ No Python environment setup
- ✅ Everything in containers
- ✅ Easy updates: `docker compose pull && docker compose up -d`

#### Manual Setup (Advanced)

<details>
<summary>Click to expand manual installation steps</summary>

1. **Clone and navigate to project**:
```bash
git clone https://github.com/valginer0/PGVectorRAGIndexer.git
cd PGVectorRAGIndexer
```

2. **Configure environment**:
```bash
cp .env.example .env
$EDITOR .env  # Update PROJECT_DIR with your absolute path
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

5. **Start database**:
```bash
./start_database.sh  # Auto-initializes pgvector
```

6. **Verify setup**:
```bash
docker ps
docker logs vector_rag_db
```

</details>

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

# Index with OCR mode (for scanned documents)
python indexer_v2.py index scanned_doc.pdf --ocr-mode auto  # Smart fallback (default)
python indexer_v2.py index native_doc.pdf --ocr-mode skip   # Skip OCR (fastest)
python indexer_v2.py index image.jpg --ocr-mode only        # OCR-only files

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

#### New Metadata & Bulk Operations API (v2.1)

**Upload with document type**:
```bash
curl -X POST "http://localhost:8000/upload-and-index" \
  -F "file=@document.pdf" \
  -F "document_type=policy"
```

**Upload with OCR mode** (for scanned documents/images):
```bash
# Auto mode (default) - uses OCR only when native text extraction fails
curl -X POST "http://localhost:8000/upload-and-index" \
  -F "file=@scanned_contract.pdf" \
  -F "ocr_mode=auto"

# Skip mode - faster, never uses OCR (skips scanned docs)
curl -X POST "http://localhost:8000/upload-and-index" \
  -F "file=@native_doc.pdf" \
  -F "ocr_mode=skip"

# Only mode - process only files that require OCR
curl -X POST "http://localhost:8000/upload-and-index" \
  -F "file=@photo_of_text.jpg" \
  -F "ocr_mode=only"
```

**Discover metadata keys**:
```bash
curl "http://localhost:8000/metadata/keys"
# Returns: ["type", "author", "file_type", "upload_method", ...]
```

**Get values for a metadata key**:
```bash
curl "http://localhost:8000/metadata/values?key=type"
# Returns: ["policy", "resume", "report", ...]
```

**Search with metadata filter**:
```bash
curl -X POST "http://localhost:8000/search" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "security requirements",
    "top_k": 5,
    "filters": {"type": "policy"}
  }'
```

**Preview bulk delete**:
```bash
curl -X POST "http://localhost:8000/documents/bulk-delete" \
  -H "Content-Type: application/json" \
  -d '{
    "filters": {"type": "draft"},
    "preview": true
  }'
```

**Export backup before delete**:
```bash
curl -X POST "http://localhost:8000/documents/export" \
  -H "Content-Type: application/json" \
  -d '{"filters": {"type": "draft"}}' > backup.json
```

**Bulk delete documents**:
```bash
curl -X POST "http://localhost:8000/documents/bulk-delete" \
  -H "Content-Type: application/json" \
  -d '{
    "filters": {"type": "draft"},
    "preview": false
  }'
```

**Restore from backup (undo)**:
```bash
curl -X POST "http://localhost:8000/documents/restore" \
  -H "Content-Type: application/json" \
  -d @backup.json
```

### Database Management

#### Manual Database Inspection

Use the interactive database inspection tool:
```bash
./inspect_db.sh
```

Options include:
- List all documents
- Count chunks per document
- Show recent chunks
- Search for text in chunks
- Show database statistics
- List extensions
- Show table schema
- Interactive psql session
- Custom SQL query

#### Direct Database Access

```bash
# View all documents
docker exec vector_rag_db psql -U rag_user -d rag_vector_db -c \
  "SELECT DISTINCT document_id, source_uri, COUNT(*) as chunks 
   FROM document_chunks GROUP BY document_id, source_uri;"

# Search for text
docker exec vector_rag_db psql -U rag_user -d rag_vector_db -c \
  "SELECT document_id, LEFT(text_content, 100) 
   FROM document_chunks WHERE text_content ILIKE '%search_term%';"

# Get statistics
docker exec vector_rag_db psql -U rag_user -d rag_vector_db -c \
  "SELECT COUNT(DISTINCT document_id) as docs, COUNT(*) as chunks 
   FROM document_chunks;"
```

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

**v2.2.4+ Improvements:**
- **Optimized for Large Databases**: Scales to 150K+ chunks efficiently
- **Exact-Match Boost**: Full-text matches are automatically boosted to top of results
- **Phrase Support**: Mix quoted and unquoted terms in your search:
  ```
  Master Card "Simplicity 9112"
  ```
  Quoted subphrases (`"Simplicity 9112"`) must match as adjacent words; other terms (`Master Card`) are matched individually.

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

## 🧪 Testing

### Run All Tests

```bash
bash scripts/run_all_tests.sh
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

### Testing Rules

- **Write tests first**: For each bug or feature, add or update tests before changing code.
- **Separate test database**: Tests run against `rag_vector_db_test` to avoid polluting development data. This is configured in `tests/conftest.py`.
- **No manual installs**: Do not run `pip install <pkg>`. Always add dependencies to `requirements.txt` and install via `pip install -r requirements.txt` for reproducibility.

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
├── api.py                # REST API (Orchestrator)
├── api_models.py         # Pydantic models for API
├── routers/              # Modular API router package
├── services.py           # API service layer / factories
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



**Version**: 2.4.3  
**Last Updated**: 2026  
**Status**: Production Ready ✅


---

## License

PGVectorRAGIndexer is **dual-licensed**.

### Community License
Free for personal use, education, research, and non-commercial evaluation.  
Evaluation within a company is permitted for testing and assessment purposes.

### Commercial License
A commercial license is required for:
- production use
- CI/CD or automated workflows
- ongoing internal company use
- use as part of a paid, hosted, or client-facing service

See [COMMERCIAL.md](./COMMERCIAL.md) for details on when a commercial license is required
and how to obtain one.

If you are unsure whether your use case requires a commercial license, feel free to reach out.

---

## Supporting the project

If you use PGVectorRAGIndexer personally or for learning and would like to support
ongoing development, you can sponsor the project via GitHub Sponsors.

Sponsorships are optional and **do not grant commercial usage rights**.

- ⭐ Star the repository
- ❤️ Sponsor on GitHub
- 📢 Share it with others who may find it useful

Thank you for supporting independent open-source development.
