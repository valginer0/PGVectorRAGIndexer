#!/bin/bash

# Database Startup Script
# Ensures docker-compose runs from the correct directory

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}=== Starting PGVectorRAGIndexer Database ===${NC}"
echo ""

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Change to script directory
cd "$SCRIPT_DIR"

echo "Working directory: $SCRIPT_DIR"
echo ""

# Export PROJECT_DIR for docker-compose
export PROJECT_DIR="$SCRIPT_DIR"
echo "PROJECT_DIR set to: $PROJECT_DIR"
echo ""

# Check if init-db.sql exists
if [ ! -f "init-db.sql" ]; then
    echo -e "${RED}Error: init-db.sql not found in $SCRIPT_DIR${NC}"
    exit 1
fi

# Check if docker-compose.yml exists
if [ ! -f "docker-compose.yml" ]; then
    echo -e "${RED}Error: docker-compose.yml not found in $SCRIPT_DIR${NC}"
    exit 1
fi

# Start docker compose
echo -e "${GREEN}Starting Docker containers...${NC}"
docker compose up -d

if [ $? -eq 0 ]; then
    echo ""
    echo -e "${GREEN}✓ Database container started!${NC}"
    echo ""
    
    # Wait for database to be ready
    echo "Waiting for database to be ready..."
    sleep 3
    
    # Run database initialization
    echo ""
    echo -e "${GREEN}Initializing database schema...${NC}"
    if [ -f "setup_database.sh" ]; then
        bash setup_database.sh
    else
        # Fallback: run init-db.sql directly
        docker exec -i vector_rag_db psql -U rag_user -d rag_vector_db < init-db.sql
        echo -e "${GREEN}✓ Database initialized!${NC}"
    fi
    
    echo ""
    echo "Container status:"
    docker ps --filter "name=vector_rag_db" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
    echo ""
    echo "To view logs:"
    echo "  docker logs vector_rag_db"
    echo ""
    echo "To stop:"
    echo "  docker compose down"
else
    echo -e "${RED}✗ Failed to start database${NC}"
    exit 1
fi
