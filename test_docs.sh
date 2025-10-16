#!/bin/bash
# Test the exact commands from documentation

set -e

echo "Testing commands from QUICK_START.md..."
echo ""

# Step 1: Create sample document (from docs)
echo "1. Creating sample document..."
cat > ~/pgvector-rag/documents/sample.txt << 'EOF'
Machine Learning Basics

Machine learning is a method of data analysis that automates 
analytical model building. It uses algorithms that iteratively 
learn from data, allowing computers to find hidden insights.
EOF
echo "✓ Created sample.txt"
echo ""

# Step 2: Index it (from docs)
echo "2. Indexing document..."
response=$(curl -s -X POST "http://localhost:8000/index" \
  -H "Content-Type: application/json" \
  -d '{"source_uri": "/app/documents/sample.txt", "force_reindex": true}')
echo "$response"

if echo "$response" | grep -q -E "success|skipped"; then
    echo "✓ Indexing successful"
else
    echo "✗ Indexing failed"
    exit 1
fi
echo ""

# Step 3: Search (from docs)
echo "3. Searching..."
search_response=$(curl -s -X POST "http://localhost:8000/search" \
  -H "Content-Type: application/json" \
  -d '{"query": "What is machine learning?", "top_k": 5}')
echo "$search_response" | head -c 200
echo "..."

if echo "$search_response" | grep -q "results"; then
    echo "✓ Search successful"
else
    echo "✗ Search failed"
    exit 1
fi
echo ""

echo "✅ All documentation commands work correctly!"
