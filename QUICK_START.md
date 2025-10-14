# Quick Start Guide - PGVectorRAGIndexer v2.0

Get up and running in 5 minutes!

## ⚡ Installation (2 minutes)

```bash
# 1. Navigate to project
cd ~/projects/PGVectorRAGIndexer

# 2. Create virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Start database
docker compose up -d

# 5. Verify
python indexer_v2.py stats
```

## 📝 Basic Usage (3 minutes)

### Index Your First Document

```bash
# Index a PDF
python indexer_v2.py index /path/to/document.pdf

# Index from Windows path (auto-converted)
python indexer_v2.py index "C:\Users\YourName\Documents\report.pdf"

# Index a web page
python indexer_v2.py index https://en.wikipedia.org/wiki/Machine_learning
```

### Search Your Documents

```bash
# Basic search
python retriever_v2.py "What is machine learning?"

# Get more results
python retriever_v2.py "Python programming" --top-k 10

# Hybrid search (better results)
python retriever_v2.py "database optimization" --hybrid
```

### Manage Documents

```bash
# List all indexed documents
python indexer_v2.py list

# Show statistics
python indexer_v2.py stats

# Delete a document
python indexer_v2.py delete <document_id>
```

## 🌐 API Usage (Optional)

### Start API Server

```bash
python api.py
```

Visit http://localhost:8000/docs for interactive API documentation!

### Example API Calls

```bash
# Index a document
curl -X POST "http://localhost:8000/index" \
  -H "Content-Type: application/json" \
  -d '{"source_uri": "/path/to/doc.pdf"}'

# Search
curl -X POST "http://localhost:8000/search" \
  -H "Content-Type: application/json" \
  -d '{"query": "machine learning", "top_k": 5}'

# Health check
curl "http://localhost:8000/health"
```

## 🎯 Common Tasks

### Index Multiple Documents

```bash
# Create a script
for file in /path/to/documents/*.pdf; do
    python indexer_v2.py index "$file"
done
```

### Search with Filters

```bash
# Search within specific document
python retriever_v2.py "query" --filter-doc <document_id>

# Set minimum relevance score
python retriever_v2.py "query" --min-score 0.8
```

### Get Context for RAG

```bash
# Get formatted context for LLM
python retriever_v2.py "explain neural networks" --context
```

## 🔧 Configuration

Edit `.env` file to customize:

```bash
# Database
DB_HOST=localhost
DB_PORT=5432

# Embedding Model
EMBEDDING_MODEL_NAME=all-MiniLM-L6-v2
EMBEDDING_DIMENSION=384

# Search
RETRIEVAL_TOP_K=5
RETRIEVAL_SIMILARITY_THRESHOLD=0.7

# API
API_PORT=8000
```

## 🧪 Testing

```bash
# Run all tests
pytest

# Run specific tests
pytest tests/test_config.py

# With coverage
pytest --cov
```

## 📚 Next Steps

- Read [README.md](README.md) for detailed documentation
- Check [DEPLOYMENT.md](DEPLOYMENT.md) for production deployment
- Review [IMPROVEMENTS_SUMMARY.md](IMPROVEMENTS_SUMMARY.md) for all features
- Explore API docs at http://localhost:8000/docs

## 🆘 Troubleshooting

### Database Connection Error
```bash
# Check if container is running
docker ps

# Restart container
docker compose restart
```

### Import Errors
```bash
# Activate virtual environment
source venv/bin/activate

# Reinstall dependencies
pip install -r requirements.txt
```

### Slow Performance
```bash
# Clear embedding cache
python -c "from embeddings import get_embedding_service; get_embedding_service().clear_cache()"

# Check database indexes
python indexer_v2.py stats
```

## 💡 Tips

1. **Use hybrid search** for better results: `--hybrid`
2. **Adjust top_k** based on your needs: `--top-k 10`
3. **Set score threshold** to filter results: `--min-score 0.8`
4. **Use verbose mode** to see full text: `--verbose`
5. **Check stats regularly** to monitor system: `indexer_v2.py stats`

## 🎉 You're Ready!

Start indexing and searching your documents with semantic search powered by PostgreSQL and pgvector!

For questions or issues, check the documentation or review the logs.

---

**Happy Searching! 🚀**
