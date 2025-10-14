#!/bin/bash

# Database Setup Script
# Ensures pgvector extension and schema are properly initialized

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}=== Database Setup ===${NC}"
echo ""

# Check if container is running
if ! docker ps --format '{{.Names}}' | grep -q "^vector_rag_db$"; then
    echo -e "${RED}Error: Container 'vector_rag_db' is not running!${NC}"
    echo "Start it with: docker compose up -d"
    exit 1
fi

echo "Running database initialization..."
echo ""

# Run the init-db.sql script
docker exec -i vector_rag_db psql -U rag_user -d rag_vector_db < init-db.sql

if [ $? -eq 0 ]; then
    echo ""
    echo -e "${GREEN}✓ Database setup complete!${NC}"
    echo ""
    
    # Verify extensions
    echo "Installed extensions:"
    docker exec vector_rag_db psql -U rag_user -d rag_vector_db -c "\dx"
    
    echo ""
    echo "Tables:"
    docker exec vector_rag_db psql -U rag_user -d rag_vector_db -c "\dt"
    
else
    echo -e "${RED}✗ Database setup failed!${NC}"
    exit 1
fi

echo ""
echo -e "${GREEN}=== Setup Complete ===${NC}"
echo ""
echo "You can now index documents:"
echo "  python indexer_v2.py index document.pdf"
