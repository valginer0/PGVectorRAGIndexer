#!/bin/bash
# Test REST API directly against running Docker container

set -e

echo "=========================================="
echo "Testing PGVectorRAGIndexer REST API"
echo "=========================================="
echo ""

# Create test file
TEST_FILE="/tmp/rest_api_test_$(date +%s).txt"
echo "The principal software architect designed a scalable microservices architecture for the enterprise application." > "$TEST_FILE"

echo "1. Testing Upload..."
UPLOAD_RESPONSE=$(curl -s -X POST http://localhost:8000/upload-and-index \
  -F "file=@$TEST_FILE" \
  -F "custom_source_uri=C:\\Projects\\Architecture\\design.txt")

echo "$UPLOAD_RESPONSE" | python3 -m json.tool
DOCUMENT_ID=$(echo "$UPLOAD_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin)['document_id'])")
echo "✓ Uploaded document ID: $DOCUMENT_ID"
echo ""

echo "2. Testing Statistics..."
STATS_RESPONSE=$(curl -s http://localhost:8000/statistics)
echo "$STATS_RESPONSE" | python3 -m json.tool
echo ""

echo "3. Testing Documents List..."
DOCS_RESPONSE=$(curl -s http://localhost:8000/documents)
echo "Total documents: $(echo "$DOCS_RESPONSE" | python3 -c "import sys, json; print(len(json.load(sys.stdin)))")"
echo "Our document in list:"
echo "$DOCS_RESPONSE" | python3 -c "import sys, json; docs = json.load(sys.stdin); doc = next((d for d in docs if d['document_id'] == '$DOCUMENT_ID'), None); print(json.dumps(doc, indent=2) if doc else 'NOT FOUND!')"
echo ""

echo "4. Testing Search (min_score=0.0)..."
SEARCH_RESPONSE=$(curl -s -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "principal architect", "top_k": 5, "min_score": 0.0}')
echo "Search results count: $(echo "$SEARCH_RESPONSE" | python3 -c "import sys, json; print(len(json.load(sys.stdin)['results']))")"
echo "First result:"
echo "$SEARCH_RESPONSE" | python3 -c "import sys, json; results = json.load(sys.stdin)['results']; print(json.dumps(results[0], indent=2) if results else 'NO RESULTS!')"
echo ""

echo "5. Verifying in Database..."
docker exec vector_rag_db psql -U rag_user -d rag_vector_db -c \
  "SELECT document_id, source_uri, COUNT(*) as chunks FROM document_chunks WHERE document_id = '$DOCUMENT_ID' GROUP BY document_id, source_uri;"
echo ""

echo "6. Testing Search for our specific document..."
SEARCH_SPECIFIC=$(curl -s -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d "{\"query\": \"software architect\", \"top_k\": 10, \"min_score\": 0.0, \"filters\": {\"document_id\": \"$DOCUMENT_ID\"}}")
echo "Results from our document: $(echo "$SEARCH_SPECIFIC" | python3 -c "import sys, json; print(len(json.load(sys.stdin)['results']))")"
echo ""

echo "7. Cleanup - Deleting test document..."
curl -s -X DELETE "http://localhost:8000/documents/$DOCUMENT_ID"
echo "✓ Deleted"
echo ""

rm "$TEST_FILE"

echo "=========================================="
echo "✓ All REST API tests completed!"
echo "=========================================="
