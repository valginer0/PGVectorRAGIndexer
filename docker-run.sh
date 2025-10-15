#!/bin/bash

# Standalone Docker Deployment Script
# Run PGVectorRAGIndexer without cloning the repository
# Pulls pre-built image from GitHub Container Registry

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     PGVectorRAGIndexer - Docker-Only Deployment           ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Check Docker
if ! command -v docker &> /dev/null; then
    echo -e "${RED}✗ Docker not found. Please install Docker first.${NC}"
    exit 1
fi

# Create deployment directory
DEPLOY_DIR="$HOME/pgvector-rag"
mkdir -p "$DEPLOY_DIR"
cd "$DEPLOY_DIR"

echo -e "${GREEN}Deployment directory: $DEPLOY_DIR${NC}"
echo ""

# Check for existing containers
if docker ps -a | grep -q "vector_rag_"; then
    echo -e "${YELLOW}⚠ Existing containers found${NC}"
    
    # Check if running interactively
    if [ -t 0 ]; then
        # Interactive mode - ask user
        read -p "Stop and remove existing containers? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo -e "${RED}✗ Cannot proceed with existing containers. Exiting.${NC}"
            exit 1
        fi
    else
        # Non-interactive mode (piped) - auto cleanup
        echo -e "${GREEN}Running in non-interactive mode - automatically cleaning up...${NC}"
    fi
    
    echo -e "${GREEN}Stopping and removing existing containers...${NC}"
    docker compose down 2>/dev/null || true
    docker rm -f vector_rag_db vector_rag_app 2>/dev/null || true
    echo -e "${GREEN}✓ Cleanup complete${NC}"
fi
echo ""

# Create .env file if it doesn't exist
if [ ! -f ".env" ]; then
    echo -e "${GREEN}Creating .env file...${NC}"
    cat > .env << 'EOF'
# Database Configuration
POSTGRES_USER=rag_user
POSTGRES_PASSWORD=rag_password
POSTGRES_DB=rag_vector_db
DB_HOST=db
DB_PORT=5432

# Embedding Model
EMBEDDING_MODEL_NAME=all-MiniLM-L6-v2
EMBEDDING_DIMENSION=384

# API Configuration
API_HOST=0.0.0.0
API_PORT=8000

# Project Directory (for volume mounts)
PROJECT_DIR=${PWD}
EOF
    echo -e "${GREEN}✓ Created .env file${NC}"
else
    echo -e "${YELLOW}⚠ .env file already exists${NC}"
fi

# Create docker-compose.yml
echo -e "${GREEN}Creating docker-compose.yml...${NC}"
cat > docker-compose.yml << 'EOF'
version: '3.8'

services:
  db:
    image: pgvector/pgvector:pg16
    container_name: vector_rag_db
    restart: always
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - rag_network

  app:
    image: ghcr.io/valginer0/pgvectorragindexer:latest
    container_name: vector_rag_app
    restart: always
    environment:
      DB_HOST: db
      DB_PORT: 5432
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
      API_HOST: ${API_HOST}
      API_PORT: ${API_PORT}
    ports:
      - "${API_PORT}:8000"
    volumes:
      - ./documents:/app/documents
      - model_cache:/root/.cache/huggingface
    depends_on:
      db:
        condition: service_healthy
    networks:
      - rag_network

volumes:
  postgres_data:
  model_cache:

networks:
  rag_network:
    driver: bridge
EOF

# Download init-db.sql
echo -e "${GREEN}Downloading database initialization script...${NC}"
curl -fsSL https://raw.githubusercontent.com/valginer0/PGVectorRAGIndexer/main/init-db.sql -o init-db.sql

# Create documents directory
mkdir -p documents

echo -e "${GREEN}✓ Configuration complete${NC}"
echo ""

# Start services
echo -e "${GREEN}Starting services...${NC}"
docker compose up -d

# Wait for database to be ready
echo -e "${GREEN}Waiting for database to initialize...${NC}"
sleep 5

# Initialize database schema
echo -e "${GREEN}Initializing database schema...${NC}"
cat init-db.sql | docker exec -i vector_rag_db psql -U rag_user -d rag_vector_db > /dev/null 2>&1 || true
echo -e "${GREEN}✓ Database ready${NC}"

echo ""
echo -e "${GREEN}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║              ✓ Deployment Complete!                       ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${BLUE}Services:${NC}"
echo -e "  API:      ${YELLOW}http://localhost:8000${NC}"
echo -e "  Docs:     ${YELLOW}http://localhost:8000/docs${NC}"
echo -e "  Database: ${YELLOW}localhost:5432${NC}"
echo ""
echo -e "${BLUE}Directories:${NC}"
echo -e "  Config:    ${YELLOW}$DEPLOY_DIR${NC}"
echo -e "  Documents: ${YELLOW}$DEPLOY_DIR/documents${NC}"
echo ""
echo -e "${BLUE}Commands:${NC}"
echo -e "  View logs:    ${YELLOW}docker compose logs -f${NC}"
echo -e "  Stop:         ${YELLOW}docker compose down${NC}"
echo -e "  Restart:      ${YELLOW}docker compose restart${NC}"
echo -e "  Update image: ${YELLOW}docker compose pull && docker compose up -d${NC}"
echo ""
echo -e "${BLUE}Place documents in:${NC} ${YELLOW}$DEPLOY_DIR/documents/${NC}"
echo ""
