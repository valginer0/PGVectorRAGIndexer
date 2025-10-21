#!/bin/bash

# Push Development Build Script
# Builds Docker image locally and pushes to GHCR with :dev tag for testing

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║        Push Development Build to GHCR                     ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Check if Docker is available
if ! command -v docker &> /dev/null; then
    echo -e "${RED}✗ Docker not found. Please install Docker first.${NC}"
    exit 1
fi

# Build Docker image with BuildKit for caching
echo -e "${GREEN}Building Docker image with BuildKit cache...${NC}"
DOCKER_BUILDKIT=1 docker compose -f docker-compose.dev.yml build app
BUILD_RESULT=$?
if [ $BUILD_RESULT -ne 0 ]; then
    echo -e "${RED}✗ Docker build failed.${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Docker image built successfully${NC}"

# Tag for GHCR
echo -e "${GREEN}Tagging image as :dev...${NC}"
docker tag pgvectorragindexer:dev ghcr.io/valginer0/pgvectorragindexer:dev
echo -e "${GREEN}✓ Image tagged${NC}"

# Push to GHCR
echo -e "${GREEN}Pushing to GitHub Container Registry...${NC}"
docker push ghcr.io/valginer0/pgvectorragindexer:dev
PUSH_RESULT=$?
if [ $PUSH_RESULT -ne 0 ]; then
    echo -e "${RED}✗ Failed to push image. Please login to GHCR first:${NC}"
    echo -e "${YELLOW}  docker login ghcr.io -u valginer0${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Image pushed to GHCR${NC}"

echo ""
echo -e "${GREEN}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║              ✓ Dev Build Pushed!                           ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${BLUE}Image available at:${NC}"
echo -e "  ${YELLOW}ghcr.io/valginer0/pgvectorragindexer:dev${NC}"
echo ""
echo -e "${BLUE}Test on Windows:${NC}"
echo -e "  ${YELLOW}cd C:\\Users\\v_ale\\PGVectorRAGIndexer${NC}"
echo -e "  ${YELLOW}.\\update-dev.ps1${NC}"
echo -e "  ${YELLOW}.\\run_desktop_app.ps1${NC}"
echo ""
