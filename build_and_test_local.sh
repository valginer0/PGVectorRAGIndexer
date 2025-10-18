#!/bin/bash
# Build Docker image locally and test before releasing

set -e

echo "=========================================="
echo "Local Docker Build and Test"
echo "=========================================="
echo ""

echo "Step 1: Building Docker image locally..."
docker build -t pgvectorragindexer:local .
echo "✓ Build complete"
echo ""

echo "Step 2: Stopping and removing current containers..."
docker compose down
docker rm -f vector_rag_db vector_rag_app 2>/dev/null || true
echo "✓ Containers stopped and removed"
echo ""

echo "Step 3: Updating docker-compose to use local image..."
# Backup original
cp docker-compose.yml docker-compose.yml.backup

# Replace image with local
sed -i 's|image: ghcr.io/valginer0/pgvectorragindexer:latest|image: pgvectorragindexer:local|' docker-compose.yml
echo "✓ Updated docker-compose.yml"
echo ""

echo "Step 4: Starting containers with local image..."
docker compose up -d
echo "✓ Containers started"
echo ""

echo "Step 5: Waiting for services to be ready..."
sleep 10
echo "✓ Services ready"
echo ""

echo "Step 6: Running REST API tests..."
./test_rest_api.sh
echo ""

echo "Step 7: Restoring original docker-compose.yml..."
mv docker-compose.yml.backup docker-compose.yml
echo "✓ Restored"
echo ""

echo "=========================================="
echo "✓ Local build and test complete!"
echo "=========================================="
echo ""
echo "If tests passed, you can now:"
echo "  1. Commit changes"
echo "  2. Run: ./release.sh patch"
echo "  3. Wait for GitHub Actions to build"
