# PGVectorRAGIndexer Usage Guide

Complete guide for using PGVectorRAGIndexer with Docker-only deployment.

## Table of Contents

- [Getting Started](#getting-started)
- [Indexing Documents](#indexing-documents)
- [Searching](#searching)
- [Managing Documents](#managing-documents)
- [Database Operations](#database-operations)
- [Python Client Examples](#python-client-examples)
- [Advanced Usage](#advanced-usage)
- [Troubleshooting](#troubleshooting)

## Getting Started

### Deploy the System

```bash
curl -fsSL https://raw.githubusercontent.com/valginer0/PGVectorRAGIndexer/main/docker-run.sh | bash
```

### Access the System

**Option 1: Web UI (Recommended for most users)**

Open in your browser: **http://localhost:8000**

The modern web interface provides:
- 🔍 **Search Tab**: Semantic and hybrid search with configurable options
- 📤 **Upload Tab**: Drag & drop file upload with progress tracking
- 📚 **Documents Tab**: Browse and manage indexed documents
- 📊 **Statistics Tab**: System health and metrics dashboard

**Option 2: REST API (For developers and integrations)**

- **API Documentation**: http://localhost:8000/docs (Swagger UI)
- **API Endpoints**: http://localhost:8000/api

### Verify Installation

**Using Web UI:**
- Open http://localhost:8000
- Check the status indicator in the header (should show "System Healthy")

**Using API:**
```bash
curl http://localhost:8000/health

# Should return:
# {
#   "status": "healthy",
#   "database": {"status": "healthy", ...},
#   "embedding_model": {"model_name": "all-MiniLM-L6-v2", ...}
# }
```

---

## Indexing Documents

### Method 1: Using Web UI (Easiest)

1. Open http://localhost:8000
2. Click the **📤 Upload** tab
3. Drag & drop your files or click to browse
4. Watch the progress bars as files are indexed
5. ✅ Done! Files are now searchable

**Supported formats:** TXT, PDF, DOCX, MD

### Method 2: Using API

**Prepare your document:**
```bash
# Create a sample document
cat > ~/pgvector-rag/documents/ai_overview.txt << 'EOF'
Artificial Intelligence and Machine Learning

Machine learning is a subset of artificial intelligence that enables 
computers to learn from data without being explicitly programmed.

Deep learning uses neural networks with multiple layers to process 
complex patterns in data. It has revolutionized computer vision, 
natural language processing, and speech recognition.

Natural language processing (NLP) focuses on the interaction between 
computers and human language, enabling machines to understand, 
interpret, and generate human text.
EOF
```

**Index via API:**
```bash
curl -X POST "http://localhost:8000/index" \
  -H "Content-Type: application/json" \
  -d '{
    "source_uri": "/app/documents/ai_overview.txt"
  }'
```

**Response:**
```json
{
  "status": "success",
  "document_id": "abc123...",
  "chunks_indexed": 3,
  "source_uri": "/app/documents/ai_overview.txt"
}
```

### 2. Index from URL

```bash
curl -X POST "http://localhost:8000/index" \
  -H "Content-Type: application/json" \
  -d '{
    "source_uri": "https://en.wikipedia.org/wiki/Machine_learning"
  }'
```

### 3. Upload and Index from Any Location ⭐ NEW

**Index files from ANY directory on your system** - no need to copy to documents folder!

**From Windows:**
```bash
# Any folder on C: drive
curl -X POST "http://localhost:8000/upload-and-index" \
  -F "file=@C:\Users\YourName\Documents\report.pdf"

# D: drive
curl -X POST "http://localhost:8000/upload-and-index" \
  -F "file=@D:\Projects\analysis.xlsx"

# Network drive
curl -X POST "http://localhost:8000/upload-and-index" \
  -F "file=@\\server\share\document.docx"
```

**From WSL/Linux:**
```bash
curl -X POST "http://localhost:8000/upload-and-index" \
  -F "file=@/home/user/documents/file.txt"
```

**With force reindex:**
```bash
curl -X POST "http://localhost:8000/upload-and-index?force_reindex=true" \
  -F "file=@C:\path\to\file.pdf"
```

**Response:**
```json
{
  "status": "success",
  "document_id": "xyz789...",
  "chunks_indexed": 5,
  "source_uri": "report.pdf"
}
```

### 4. Index Text Directly

```bash
curl -X POST "http://localhost:8000/index" \
  -H "Content-Type: application/json" \
  -d '{
    "source_uri": "text://Quantum computing uses quantum-mechanical phenomena like superposition and entanglement to perform computation.",
    "metadata": {
      "source": "manual_entry",
      "topic": "quantum_computing"
    }
  }'
```

### 5. Batch Index Multiple Files

```bash
# Create multiple documents
for i in {1..5}; do
  echo "Document $i content about topic $i" > ~/pgvector-rag/documents/doc$i.txt
done

# Index them
for i in {1..5}; do
  curl -X POST "http://localhost:8000/index" \
    -H "Content-Type: application/json" \
    -d "{\"source_uri\": \"/app/documents/doc$i.txt\"}"
  echo ""
done
```

---

## Searching

### Method 1: Using Web UI (Easiest)

1. Open http://localhost:8000
2. Click the **🔍 Search** tab (default)
3. Enter your query in the search box
4. Adjust options if needed:
   - **Results**: Number of results to return (1-50)
   - **Similarity Threshold**: Minimum relevance score (0-1)
   - **Search Method**: Semantic or Hybrid
5. Click **Search**
6. View results with similarity scores and source documents

### Method 2: Using API

**Basic Semantic Search:**

```bash
curl -X POST "http://localhost:8000/search" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What is deep learning?",
    "top_k": 5
  }'
```

**Response:**
```json
{
  "results": [
    {
      "chunk_id": 123,
      "document_id": "abc123...",
      "text_content": "Deep learning uses neural networks...",
      "distance": 0.234,
      "source_uri": "/app/documents/ai_overview.txt",
      "chunk_index": 1
    },
    ...
  ],
  "query": "What is deep learning?",
  "total_results": 5
}
```

### 2. Search with Filters

```bash
# Search only in specific document
curl -X POST "http://localhost:8000/search" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "neural networks",
    "top_k": 3,
    "filters": {
      "document_id": "abc123..."
    }
  }'
```

### 3. Search with Different Distance Metrics

```bash
# Cosine similarity (default)
curl -X POST "http://localhost:8000/search" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "machine learning algorithms",
    "top_k": 5,
    "distance_metric": "cosine"
  }'

# L2 distance
curl -X POST "http://localhost:8000/search" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "machine learning algorithms",
    "top_k": 5,
    "distance_metric": "l2"
  }'
```

### 4. Get Context Around Results

```bash
# Search and get surrounding chunks
curl -X POST "http://localhost:8000/search/context" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "neural networks",
    "top_k": 3,
    "context_chunks": 2
  }'
```

---

## Managing Documents

### 1. List All Documents

```bash
curl "http://localhost:8000/documents?limit=50&offset=0"
```

**Response:**

```json
{
  "items": [
    {
      "document_id": "abc123...",
      "source_uri": "/app/documents/ai_overview.txt",
      "chunk_count": 3,
      "indexed_at": "2025-10-15T12:00:00Z",
      "last_updated": "2025-10-18T09:30:00Z",
      "document_type": "policy"
    }
  ],
  "total": 42,
  "limit": 50,
  "offset": 0,
  "sort": {
    "by": "indexed_at",
    "direction": "desc"
  }
}
```

### 2. Get Document Details

```bash
curl "http://localhost:8000/documents/abc123..."
```

### 3. Delete a Document

```bash
curl -X DELETE "http://localhost:8000/documents/abc123..."
```

**Response:**
```json
{
  "status": "success",
  "document_id": "abc123...",
  "chunks_deleted": 3
}
```

### 4. Get Database Statistics

```bash
curl http://localhost:8000/stats
```

**Response:**
```json
{
  "total_documents": 10,
  "total_chunks": 45,
  "database_size": "2.5 MB",
  "oldest_document": "2025-10-01T10:00:00Z",
  "newest_document": "2025-10-15T12:00:00Z"
}
```

---

## Database Operations

### Using the Database Inspector

```bash
cd ~/pgvector-rag

# Download the inspector script
curl -fsSL https://raw.githubusercontent.com/valginer0/PGVectorRAGIndexer/main/inspect_db.sh -o inspect_db.sh
chmod +x inspect_db.sh

# Run it
./inspect_db.sh
```

**Available options:**
1. List all documents
2. Count chunks per document
3. Show recent chunks (last 10)
4. Search for text in chunks
5. Show database statistics
6. List extensions
7. Show table schema
8. Interactive psql session
9. Custom SQL query

### Direct Database Access

```bash
# Connect to PostgreSQL
docker exec -it vector_rag_db psql -U rag_user -d rag_vector_db

# Example queries:
# List all documents
SELECT DISTINCT document_id, source_uri, COUNT(*) as chunks 
FROM document_chunks 
GROUP BY document_id, source_uri;

# Search in text
SELECT document_id, LEFT(text_content, 100) 
FROM document_chunks 
WHERE text_content ILIKE '%machine learning%';

# Exit
\q
```

---

## Python Client Examples

### Install Python Client

```bash
pip install requests
```

### Basic Python Script

```python
import requests
import json

# Base URL
BASE_URL = "http://localhost:8000"

# 1. Check health
response = requests.get(f"{BASE_URL}/health")
print("Health:", response.json())

# 2. Index a document
index_response = requests.post(
    f"{BASE_URL}/index/text",
    json={
        "text": "Python is a high-level programming language known for its simplicity and readability.",
        "metadata": {"language": "python", "topic": "programming"}
    }
)
print("Indexed:", index_response.json())

# 3. Search
search_response = requests.post(
    f"{BASE_URL}/search",
    json={
        "query": "programming language",
        "top_k": 3
    }
)
results = search_response.json()
print(f"\nFound {len(results['results'])} results:")
for result in results['results']:
    print(f"- {result['text_content'][:100]}... (distance: {result['distance']:.3f})")
```

### Advanced Python Client

```python
import requests
from typing import List, Dict, Optional

class RAGClient:
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
    
    def health(self) -> Dict:
        """Check system health."""
        return requests.get(f"{self.base_url}/health").json()
    
    def index_file(self, file_path: str) -> Dict:
        """Index a file."""
        return requests.post(
            f"{self.base_url}/index",
            json={"source_uri": file_path}
        ).json()
    
    def index_text(self, text: str, metadata: Optional[Dict] = None) -> Dict:
        """Index text directly."""
        payload = {"source_uri": f"text://{text}"}
        if metadata:
            payload["metadata"] = metadata
        return requests.post(
            f"{self.base_url}/index",
            json=payload
        ).json()
    
    def search(self, query: str, top_k: int = 5, 
               filters: Optional[Dict] = None) -> List[Dict]:
        """Search for similar content."""
        payload = {"query": query, "top_k": top_k}
        if filters:
            payload["filters"] = filters
        response = requests.post(
            f"{self.base_url}/search",
            json=payload
        ).json()
        return response.get("results", [])
    
    def list_documents(self) -> List[Dict]:
        """List all documents."""
        response = requests.get(f"{self.base_url}/documents")
        payload = response.json()
        return payload.get("items", [])
    
    def delete_document(self, document_id: str) -> Dict:
        """Delete a document."""
        return requests.delete(
            f"{self.base_url}/documents/{document_id}"
        ).json()

# Usage
client = RAGClient()

# Index some content
doc = client.index_file("/app/documents/docker_intro.txt")
print(f"Indexed document: {doc['document_id']}")

# Search
results = client.search("What is Docker?", top_k=3)
for r in results:
    print(f"- {r['text_content'][:80]}...")
```

---

## Advanced Usage

### 1. Custom Embedding Model

Edit `~/pgvector-rag/.env`:
```bash
EMBEDDING_MODEL_NAME=sentence-transformers/all-mpnet-base-v2
EMBEDDING_DIMENSION=768
```

Restart:
```bash
cd ~/pgvector-rag
docker compose restart
```

### 2. Environment Variables

Available configuration options in `.env`:

```bash
# Database
POSTGRES_USER=rag_user
POSTGRES_PASSWORD=rag_password
POSTGRES_DB=rag_vector_db
DB_HOST=db
DB_PORT=5432

# Embedding Model
EMBEDDING_MODEL_NAME=all-MiniLM-L6-v2
EMBEDDING_DIMENSION=384

# API
API_HOST=0.0.0.0
API_PORT=8000

# Chunking
CHUNK_SIZE=500
CHUNK_OVERLAP=50
```

### 3. Backup and Restore

**Backup:**
```bash
cd ~/pgvector-rag
docker exec vector_rag_db pg_dump -U rag_user rag_vector_db > backup.sql
```

**Restore:**
```bash
cat backup.sql | docker exec -i vector_rag_db psql -U rag_user -d rag_vector_db
```

### 4. Update to Latest Version

```bash
cd ~/pgvector-rag
docker compose pull
docker compose up -d
```

---

## Troubleshooting

### Check Logs

```bash
cd ~/pgvector-rag

# All logs
docker compose logs -f

# Just API logs
docker compose logs -f app

# Just database logs
docker compose logs -f db
```

### Common Issues

**1. "Connection refused" error:**
```bash
# Check if containers are running
docker ps | grep vector_rag

# Restart if needed
cd ~/pgvector-rag
docker compose restart
```

**2. "Database not healthy":**
```bash
# Check database logs
docker compose logs db

# Reinitialize database
docker compose down
docker volume rm pgvector-rag_postgres_data
docker compose up -d
```

**3. "Out of memory" error:**
```bash
# Check Docker resources
docker stats

# Increase Docker memory in Docker Desktop settings
```

**4. Port already in use:**
```bash
# Change port in .env
echo "API_PORT=8001" >> ~/pgvector-rag/.env

# Restart
cd ~/pgvector-rag
docker compose down
docker compose up -d
```

### Get Help

- 📚 [README.md](README.md) - Overview and installation
- 🚀 [QUICK_START.md](QUICK_START.md) - 5-minute setup guide
- 🏗️ [DEPLOYMENT.md](DEPLOYMENT.md) - Production deployment
- 🐛 [GitHub Issues](https://github.com/valginer0/PGVectorRAGIndexer/issues) - Report bugs

---

## Next Steps

- Explore the [Interactive API Docs](http://localhost:8000/docs)
- Read about [Production Deployment](DEPLOYMENT.md)
- Check out [Example Use Cases](examples/)
- Join the community discussions

Happy indexing! 🚀
