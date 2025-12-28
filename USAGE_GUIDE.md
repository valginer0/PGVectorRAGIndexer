# Reference Manual & API Guide

> **Note:** For installation and getting started, see [QUICK_START.md](QUICK_START.md) or [INSTALL_DESKTOP_APP.md](INSTALL_DESKTOP_APP.md).

This guide provides detailed reference documentation for API usage, advanced configuration, and database operations.

## Table of Contents

- [Python Client Examples](#python-client-examples)
- [Advanced Usage](#advanced-usage)
- [Database Operations](#database-operations)
- [Troubleshooting](#troubleshooting)


### 5. Advanced Filtering & Metadata

> **Note:** This section describes advanced filtering capabilities available in the Desktop App and API.

**Overview**
All three tabs (Upload, Search, Manage) support comprehensive filtering with metadata discovery.

**Search Tab Filters:**
1. **Document Type**: Dropdown with dynamic refresh
2. **Custom Metadata**: Key-value pair (e.g., `author=John`)
3. All filters combined with AND logic

**Manage Tab (Bulk Operations):**
- **Document Type**: Loads actual types from your database
- **Path/Name Filter**: Supports wildcards (e.g., `*resume*`, `C:\Projects\*`)
- **Metadata Filters**: Filter by arbitrary key-value pairs (e.g., `status=obsolete`)

**Backend API Support:**
- `type` - shortcut for `metadata.type`
- `source_uri_like` - SQL LIKE pattern for path/filename
- `metadata.*` - Any custom metadata field
- `GET /metadata/keys` - List all metadata keys
- `GET /metadata/values?key=type` - Get values for a specific key

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
