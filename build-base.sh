#!/bin/bash

# Build Base Image Script
# Builds the base image with all heavy dependencies
# Only run this when requirements.txt changes

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║        Build Base Image (Heavy Dependencies)              ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Check if Docker is available
if ! command -v docker &> /dev/null; then
    echo -e "${RED}✗ Docker not found. Please install Docker first.${NC}"
    exit 1
fi

# Warn user
echo -e "${YELLOW}WARNING: This will build an 8.3GB image with PyTorch/CUDA.${NC}"
echo -e "${YELLOW}This takes ~15 minutes and uploads ~8.3GB to GHCR.${NC}"
echo -e "${YELLOW}Only run this when requirements.txt changes!${NC}"
echo ""
read -p "Continue? (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}Cancelled.${NC}"
    exit 0
fi

# Build base image
echo -e "${GREEN}Building base image...${NC}"
DOCKER_BUILDKIT=1 docker build -f Dockerfile.base -t ghcr.io/valginer0/pgvectorragindexer:base .
BUILD_RESULT=$?
if [ $BUILD_RESULT -ne 0 ]; then
    echo -e "${RED}✗ Docker build failed.${NC}"
    exit 1
fi
echo -e "${GREEN}[OK] Base image built successfully${NC}"

# Push to GHCR
echo -e "${GREEN}Pushing base image to GHCR...${NC}"
docker push ghcr.io/valginer0/pgvectorragindexer:base
PUSH_RESULT=$?
if [ $PUSH_RESULT -ne 0 ]; then
    echo -e "${RED}✗ Failed to push image. Please login to GHCR first:${NC}"
    echo -e "${YELLOW}  docker login ghcr.io -u valginer0${NC}"
    exit 1
fi
echo -e "${GREEN}[OK] Base image pushed to GHCR${NC}"

echo ""
echo -e "${GREEN}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║              [OK] Base Image Ready!                        ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${BLUE}Base image available at:${NC}"
echo -e "  ${YELLOW}ghcr.io/valginer0/pgvectorragindexer:base${NC}"
echo ""
echo -e "${BLUE}Now you can build the app image quickly:${NC}"
echo -e "  ${YELLOW}./push-dev.sh${NC} (takes ~2 minutes instead of ~15 minutes)"
echo ""
