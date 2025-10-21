# Quick Start Guide - PGVectorRAGIndexer v2.1

Get up and running in 5 minutes with Docker-only deployment!

## 🆕 What's New in v2.1

- **Document Types**: Organize documents with custom types (policy, resume, report, etc.)
- **Bulk Delete**: Preview, export backup, delete, and undo multiple documents
- **Metadata Discovery**: Dynamically discover available metadata fields
- **Legacy Word Support**: Added .doc (Office 97-2003) file support
- **Desktop App Manage Tab**: Full GUI for bulk operations with backup/restore

## ⚡ Installation (1 minute)

### For Linux/macOS/WSL:

```bash
curl -fsSL https://raw.githubusercontent.com/valginer0/PGVectorRAGIndexer/main/docker-run.sh | bash
```

### For Windows (Native - No WSL):

Open **PowerShell** and run:

```powershell
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/valginer0/PGVectorRAGIndexer/main/docker-run.ps1" -OutFile "$env:TEMP\docker-run.ps1"
PowerShell -ExecutionPolicy Bypass -File "$env:TEMP\docker-run.ps1"
```

📖 **See [WINDOWS_SETUP.md](WINDOWS_SETUP.md) for detailed Windows instructions**

---

That's it! The script will:
- ✅ Pull pre-built Docker image
- ✅ Set up PostgreSQL with pgvector
- ✅ Initialize database schema
- ✅ Start API server
- ✅ Configure everything automatically

**Services available at:**
- 🌐 **Web UI**: http://localhost:8000 (Start here!)
- 📚 **API Docs**: http://localhost:8000/docs
- 🔧 **API**: http://localhost:8000/api
- 🗄️ **Database**: localhost:5432

## ✅ Verify Installation (30 seconds)

**Option 1: Use the Web UI (Easiest)**

Open http://localhost:8000 in your browser - you'll see a modern interface where you can:
- 🔍 Search documents
- 📤 Upload files (drag & drop)
- 📚 Browse indexed documents
- 📊 View system statistics

**Option 2: Use the API**

```bash
# Check system health
curl http://localhost:8000/health

# Should show: "status": "healthy"
```

For API integration, visit http://localhost:8000/docs for interactive documentation!

## 📝 Basic Usage (3 minutes)

### 1. Index Your First Document

**Create a sample document:**
```bash
cat > ~/pgvector-rag/documents/sample.txt << 'EOF'
Machine Learning Basics

Machine learning is a method of data analysis that automates 
analytical model building. It uses algorithms that iteratively 
learn from data, allowing computers to find hidden insights.
EOF
```

**Index it via API:**
```bash
curl -X POST "http://localhost:8000/index" \
  -H "Content-Type: application/json" \
  -d '{"source_uri": "/app/documents/sample.txt"}'
```

**Or index from URL:**
```bash
curl -X POST "http://localhost:8000/index" \
  -H "Content-Type: application/json" \
  -d '{"source_uri": "https://en.wikipedia.org/wiki/Machine_learning"}'
```

**Or upload from ANY location (Windows/Linux):**
```bash
# From any Windows directory
curl -X POST "http://localhost:8000/upload-and-index" \
  -F "file=@C:\Users\YourName\Documents\myfile.pdf"

# From any WSL/Linux directory
curl -X POST "http://localhost:8000/upload-and-index" \
  -F "file=@/home/user/documents/file.txt"
```

### 2. Search Your Documents

```bash
curl -X POST "http://localhost:8000/search" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What is machine learning?",
    "top_k": 5
  }'
```

**Response:**
```json
{
  "results": [
    {
      "text_content": "Machine learning is a method of data analysis...",
      "distance": 0.234,
      "source_uri": "/app/documents/sample.txt"
    }
  ]
}
```

### 3. Manage Documents

```bash
# List all documents
curl http://localhost:8000/documents

# Get statistics
curl http://localhost:8000/stats

# Delete a document
curl -X DELETE "http://localhost:8000/documents/<document_id>"
```

## 🎯 Common Tasks

### Index Multiple Documents

```bash
# Create multiple documents
for i in {1..5}; do
  echo "Document $i about topic $i" > ~/pgvector-rag/documents/doc$i.txt
done

# Index them all
for i in {1..5}; do
  curl -X POST "http://localhost:8000/index" \
    -H "Content-Type: application/json" \
    -d "{\"source_uri\": \"/app/documents/doc$i.txt\"}"
done
```

### Search with Filters

```bash
# Search only in specific document
curl -X POST "http://localhost:8000/search" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "machine learning",
    "top_k": 3,
    "filters": {"document_id": "abc123..."}
  }'
```

### Supported File Types

The system supports these file formats:
- `.txt` - Plain text
- `.pdf` - PDF documents
- `.docx` - Word documents
- `.xlsx`, `.csv` - Spreadsheets
- `.html` - HTML files
- `.pptx` - PowerPoint presentations

### Use Interactive API Docs

Open http://localhost:8000/docs and try the API interactively!

## 🔧 Configuration

Edit `~/pgvector-rag/.env` to customize:

```bash
# Database
POSTGRES_USER=rag_user
POSTGRES_PASSWORD=rag_password
POSTGRES_DB=rag_vector_db

# Embedding Model
EMBEDDING_MODEL_NAME=all-MiniLM-L6-v2
EMBEDDING_DIMENSION=384

# API
API_PORT=8000
```

**Restart after changes:**
```bash
cd ~/pgvector-rag
docker compose restart
```

## 🔍 Database Inspector

```bash
cd ~/pgvector-rag

# Download inspector
curl -fsSL https://raw.githubusercontent.com/valginer0/PGVectorRAGIndexer/main/inspect_db.sh -o inspect_db.sh
chmod +x inspect_db.sh

# Run it
./inspect_db.sh
```

**Available options:**
1. List all documents
2. Count chunks per document
3. Show recent chunks
4. Search for text
5. Show statistics
6. List extensions
7. Show table schema
8. Interactive psql session
9. Custom SQL query

## 📚 Next Steps

- Read [README.md](README.md) for detailed documentation
- Check [DEPLOYMENT.md](DEPLOYMENT.md) for production deployment
- Review [IMPROVEMENTS_SUMMARY.md](IMPROVEMENTS_SUMMARY.md) for all features
- Explore API docs at http://localhost:8000/docs

## 🆘 Troubleshooting

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

**1. "Connection refused":**
```bash
# Check containers
docker ps | grep vector_rag

# Restart
cd ~/pgvector-rag
docker compose restart
```

**2. "Port already in use":**
```bash
# Change port in .env
echo "API_PORT=8001" >> ~/pgvector-rag/.env

# Restart
cd ~/pgvector-rag
docker compose down
docker compose up -d
```

**3. Update to latest version:**
```bash
cd ~/pgvector-rag
docker compose pull
docker compose up -d
```

## 💡 Tips

1. **Use Interactive Docs**: http://localhost:8000/docs - Try all endpoints visually
2. **Check Health**: `curl http://localhost:8000/health` - Verify system status
3. **Monitor Logs**: `docker compose logs -f` - See what's happening
4. **Inspect Database**: Use `./inspect_db.sh` - View indexed content
5. **Backup Data**: Database persists in Docker volumes - Safe across restarts

## 📖 More Resources

- 📘 [USAGE_GUIDE.md](USAGE_GUIDE.md) - Complete usage examples
- 🚀 [README.md](README.md) - Full documentation
- 🏗️ [DEPLOYMENT.md](DEPLOYMENT.md) - Production deployment
- 🐛 [GitHub Issues](https://github.com/valginer0/PGVectorRAGIndexer/issues) - Get help

## 🎉 You're Ready!

Start indexing and searching your documents with semantic search powered by PostgreSQL and pgvector!

**Your deployment directory:** `~/pgvector-rag/`
**API endpoint:** http://localhost:8000
**Interactive docs:** http://localhost:8000/docs

---

**Happy Searching! 🚀**
