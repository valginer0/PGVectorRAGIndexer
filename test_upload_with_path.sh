#!/bin/bash
# Test script demonstrating REST API upload with custom source URI (full path)
# This shows how to preserve file paths when uploading via REST API
# The desktop app will use the same approach

echo "Creating test file..."
echo "The principal architect designed the system." > /tmp/test_principal.txt

echo ""
echo "Uploading with custom path..."
RESPONSE=$(curl -s -X POST http://localhost:8000/upload-and-index \
  -F "file=@/tmp/test_principal.txt" \
  -F "custom_source_uri=C:\\Projects\\Architecture\\test_principal.txt")

echo "$RESPONSE" | python3 -m json.tool

DOC_ID=$(echo "$RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('document_id', ''))")

echo ""
echo "Checking in documents list..."
curl -s http://localhost:8000/documents | python3 -c "import sys, json; docs = json.load(sys.stdin); doc = next((d for d in docs if d['document_id'] == '$DOC_ID'), None); print(json.dumps(doc, indent=2) if doc else 'NOT FOUND')"

echo ""
echo "Searching for 'principal architect'..."
curl -s -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "principal architect", "top_k": 5, "min_score": 0.0}' | python3 -c "import sys, json; results = json.load(sys.stdin)['results']; print(f'Found {len(results)} results'); [print(f\"  - {r['source_uri']}: {r['text_content'][:50]}...\") for r in results[:3]]"

echo ""
echo "Cleaning up..."
curl -s -X DELETE "http://localhost:8000/documents/$DOC_ID" > /dev/null
echo "✓ Done"
