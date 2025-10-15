#!/bin/bash

# Release Script for PGVectorRAGIndexer
# Creates a new release tag and triggers Docker build

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║        PGVectorRAGIndexer Release Script                  ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Check if on main branch
CURRENT_BRANCH=$(git branch --show-current)
if [ "$CURRENT_BRANCH" != "main" ]; then
    echo -e "${RED}✗ Not on main branch. Please switch to main first.${NC}"
    exit 1
fi

# Check for uncommitted changes
if ! git diff-index --quiet HEAD --; then
    echo -e "${RED}✗ You have uncommitted changes. Please commit or stash them first.${NC}"
    exit 1
fi

# Pull latest changes
echo -e "${GREEN}Pulling latest changes...${NC}"
git pull origin main

# Get current version
if [ -f "VERSION" ]; then
    CURRENT_VERSION=$(cat VERSION)
    echo -e "${BLUE}Current version: ${YELLOW}v$CURRENT_VERSION${NC}"
else
    CURRENT_VERSION="1.0.0"
    echo -e "${YELLOW}No VERSION file found. Starting from v1.0.0${NC}"
fi

# Ask for new version
echo ""
echo -e "${GREEN}Enter new version (e.g., 2.0.0, 2.1.0, 2.0.1):${NC}"
read -p "> " NEW_VERSION

# Validate version format
if ! [[ $NEW_VERSION =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo -e "${RED}✗ Invalid version format. Use semantic versioning (e.g., 2.0.0)${NC}"
    exit 1
fi

# Confirm
echo ""
echo -e "${YELLOW}This will:${NC}"
echo -e "  1. Update VERSION file to ${GREEN}$NEW_VERSION${NC}"
echo -e "  2. Create git tag ${GREEN}v$NEW_VERSION${NC}"
echo -e "  3. Push tag to GitHub"
echo -e "  4. Trigger Docker build and publish to GitHub Container Registry"
echo ""
read -p "Continue? (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}Release cancelled.${NC}"
    exit 0
fi

# Update VERSION file
echo "$NEW_VERSION" > VERSION
echo -e "${GREEN}✓ Updated VERSION file${NC}"

# Run tests
echo -e "${GREEN}Running tests...${NC}"
if command -v python3 &> /dev/null; then
    if [ -d "venv" ]; then
        source venv/bin/activate
        python -m pytest tests/test_integration.py -v
        if [ $? -ne 0 ]; then
            echo -e "${RED}✗ Tests failed. Please fix before releasing.${NC}"
            exit 1
        fi
        echo -e "${GREEN}✓ All tests passed${NC}"
    else
        echo -e "${YELLOW}⚠ No venv found, skipping tests${NC}"
    fi
else
    echo -e "${YELLOW}⚠ Python not found, skipping tests${NC}"
fi

# Commit VERSION file
git add VERSION
git commit -m "chore: Bump version to v$NEW_VERSION"
echo -e "${GREEN}✓ Committed version bump${NC}"

# Create and push tag
git tag -a "v$NEW_VERSION" -m "Release v$NEW_VERSION

See CHANGELOG.md for details."
echo -e "${GREEN}✓ Created tag v$NEW_VERSION${NC}"

# Push changes and tag
git push origin main
git push origin "v$NEW_VERSION"
echo -e "${GREEN}✓ Pushed to GitHub${NC}"

echo ""
echo -e "${GREEN}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║              ✓ Release v$NEW_VERSION Created!                  ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${BLUE}Next steps:${NC}"
echo -e "  1. GitHub Actions will build and publish Docker image"
echo -e "  2. Monitor: ${YELLOW}https://github.com/valginer0/PGVectorRAGIndexer/actions${NC}"
echo -e "  3. Image will be available at:"
echo -e "     ${YELLOW}ghcr.io/valginer0/pgvectorragindexer:$NEW_VERSION${NC}"
echo -e "     ${YELLOW}ghcr.io/valginer0/pgvectorragindexer:latest${NC}"
echo ""
echo -e "${BLUE}Test the deployment:${NC}"
echo -e "  ${YELLOW}curl -fsSL https://raw.githubusercontent.com/valginer0/PGVectorRAGIndexer/main/docker-run.sh | bash${NC}"
echo ""
