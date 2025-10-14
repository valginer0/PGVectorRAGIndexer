#!/bin/bash

# PGVectorRAGIndexer - Complete Setup Script
# Single command to set up everything automatically

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║         PGVectorRAGIndexer - Automated Setup              ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Export PROJECT_DIR for docker-compose
export PROJECT_DIR="$SCRIPT_DIR"

# Step 1: Check prerequisites
echo -e "${GREEN}[1/6] Checking prerequisites...${NC}"
if ! command -v docker &> /dev/null; then
    echo -e "${RED}✗ Docker not found. Please install Docker Desktop or Rancher Desktop.${NC}"
    exit 1
fi
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}✗ Python3 not found. Please install Python 3.9+${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Prerequisites met${NC}"
echo ""

# Step 2: Set up environment file
echo -e "${GREEN}[2/6] Configuring environment...${NC}"
if [ ! -f ".env" ]; then
    cp .env.example .env
    # Update PROJECT_DIR in .env
    sed -i "s|PROJECT_DIR=.*|PROJECT_DIR=$SCRIPT_DIR|g" .env
    echo -e "${GREEN}✓ Created .env file${NC}"
else
    echo -e "${YELLOW}⚠ .env already exists, skipping${NC}"
fi
echo ""

# Step 3: Create Python virtual environment
echo -e "${GREEN}[3/6] Setting up Python environment...${NC}"
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo -e "${GREEN}✓ Virtual environment created${NC}"
else
    echo -e "${YELLOW}⚠ Virtual environment already exists${NC}"
fi

# Activate venv and install dependencies
source venv/bin/activate
pip install --upgrade pip > /dev/null 2>&1
pip install -r requirements.txt > /dev/null 2>&1
echo -e "${GREEN}✓ Dependencies installed${NC}"
echo ""

# Step 4: Start database
echo -e "${GREEN}[4/6] Starting PostgreSQL database...${NC}"
if docker ps --format '{{.Names}}' | grep -q "^vector_rag_db$"; then
    echo -e "${YELLOW}⚠ Database already running${NC}"
else
    docker compose up -d
    echo -e "${GREEN}✓ Database container started${NC}"
fi
echo ""

# Step 5: Wait for database and initialize
echo -e "${GREEN}[5/6] Initializing database schema...${NC}"
echo "Waiting for PostgreSQL to be ready..."
sleep 5

# Check if database is ready
max_attempts=30
attempt=0
until docker exec vector_rag_db pg_isready -U rag_user -d rag_vector_db > /dev/null 2>&1; do
    attempt=$((attempt + 1))
    if [ $attempt -eq $max_attempts ]; then
        echo -e "${RED}✗ Database failed to start${NC}"
        exit 1
    fi
    echo -n "."
    sleep 1
done
echo ""

# Run initialization script
docker exec -i vector_rag_db psql -U rag_user -d rag_vector_db < init-db.sql > /dev/null 2>&1
echo -e "${GREEN}✓ Database schema initialized${NC}"
echo ""

# Step 6: Verify setup
echo -e "${GREEN}[6/6] Verifying installation...${NC}"
echo ""

# Check extensions
echo "Installed PostgreSQL extensions:"
docker exec vector_rag_db psql -U rag_user -d rag_vector_db -c "\dx" | grep -E "vector|pg_trgm"

echo ""
echo -e "${GREEN}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║              ✓ Setup Complete!                             ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${BLUE}Next steps:${NC}"
echo ""
echo -e "  ${GREEN}1.${NC} Activate Python environment:"
echo -e "     ${YELLOW}source venv/bin/activate${NC}"
echo ""
echo -e "  ${GREEN}2.${NC} Index a document:"
echo -e "     ${YELLOW}python indexer_v2.py index document.pdf${NC}"
echo ""
echo -e "  ${GREEN}3.${NC} Search documents:"
echo -e "     ${YELLOW}python retriever_v2.py \"your query\"${NC}"
echo ""
echo -e "  ${GREEN}4.${NC} Start API server:"
echo -e "     ${YELLOW}python api.py${NC}"
echo ""
echo -e "${BLUE}Useful commands:${NC}"
echo -e "  View logs:       ${YELLOW}docker logs vector_rag_db${NC}"
echo -e "  Stop database:   ${YELLOW}docker compose down${NC}"
echo -e "  Restart:         ${YELLOW}docker compose restart${NC}"
echo ""
