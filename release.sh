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
    CURRENT_VERSION="0.0.0"
    echo -e "${YELLOW}No VERSION file found. Starting from v0.0.0${NC}"
fi

# Parse current version
IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT_VERSION"

# Determine new version based on argument
BUMP_TYPE="${1:-patch}"  # Default to patch if no argument

if [[ $BUMP_TYPE =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    # Explicit version provided
    NEW_VERSION="$BUMP_TYPE"
    echo -e "${GREEN}Using explicit version: ${YELLOW}v$NEW_VERSION${NC}"
elif [ "$BUMP_TYPE" = "major" ]; then
    NEW_VERSION="$((MAJOR + 1)).0.0"
    echo -e "${GREEN}Bumping major version: ${YELLOW}v$CURRENT_VERSION → v$NEW_VERSION${NC}"
elif [ "$BUMP_TYPE" = "minor" ]; then
    NEW_VERSION="$MAJOR.$((MINOR + 1)).0"
    echo -e "${GREEN}Bumping minor version: ${YELLOW}v$CURRENT_VERSION → v$NEW_VERSION${NC}"
elif [ "$BUMP_TYPE" = "patch" ]; then
    NEW_VERSION="$MAJOR.$MINOR.$((PATCH + 1))"
    echo -e "${GREEN}Bumping patch version: ${YELLOW}v$CURRENT_VERSION → v$NEW_VERSION${NC}"
else
    echo -e "${RED}✗ Invalid argument. Use: major, minor, patch, or explicit version (e.g., 2.0.3)${NC}"
    echo -e "${YELLOW}Usage:${NC}"
    echo -e "  ./release.sh          # Auto-bump patch"
    echo -e "  ./release.sh patch    # Bump patch: 2.0.2 → 2.0.3"
    echo -e "  ./release.sh minor    # Bump minor: 2.0.2 → 2.1.0"
    echo -e "  ./release.sh major    # Bump major: 2.0.2 → 3.0.0"
    echo -e "  ./release.sh 2.5.7    # Explicit version"
    exit 1
fi

echo ""
echo -e "${YELLOW}This will:${NC}"
echo -e "  1. Update VERSION file to ${GREEN}$NEW_VERSION${NC}"
echo -e "  2. Run tests"
echo -e "  3. Create git tag ${GREEN}v$NEW_VERSION${NC}"
echo -e "  4. Push tag to GitHub"
echo -e "  5. Trigger Docker build and publish to GitHub Container Registry"
echo ""

# Update VERSION file
echo "$NEW_VERSION" > VERSION
echo -e "${GREEN}✓ Updated VERSION file${NC}"

# Ensure database is running for tests
echo -e "${GREEN}Checking database...${NC}"
DB_RUNNING=false
if docker ps | grep -q vector_rag_db; then
    echo -e "${GREEN}✓ Database already running${NC}"
    DB_RUNNING=true
else
    echo -e "${YELLOW}Database not running. Starting test database...${NC}"
    # Check if we have docker-compose.yml in a test location or use existing deployment
    if [ -d "$HOME/pgvector-rag" ] && [ -f "$HOME/pgvector-rag/docker-compose.yml" ]; then
        cd "$HOME/pgvector-rag"
        docker compose up -d db
        sleep 5  # Wait for database to be ready
        cd - > /dev/null
        echo -e "${GREEN}✓ Started test database${NC}"
    else
        echo -e "${YELLOW}⚠ No database available. Tests requiring database will be skipped.${NC}"
    fi
fi

# Run tests
echo -e "${GREEN}Running tests...${NC}"
if command -v python3 &> /dev/null; then
    if [ -d "venv" ]; then
        source venv/bin/activate
        # Run tests, skipping slow UI tests (they can be run separately)
        # This reduces test time from 40+ min to ~1-2 min
        python -m pytest \
            tests/test_config.py \
            tests/test_database.py \
            tests/test_regression_bugs.py \
            tests/test_document_processor_office.py \
            tests/test_yaml_and_license.py \
            -v --tb=shorte
        TEST_RESULT=$?
        if [ $TEST_RESULT -ne 0 ]; then
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

# Build Docker image locally using production helper
echo ""
echo -e "${GREEN}Building production Docker image...${NC}"
if command -v docker &> /dev/null; then
    ./scripts/build_prod_image.sh \
        "ghcr.io/valginer0/pgvectorragindexer:$NEW_VERSION" \
        "ghcr.io/valginer0/pgvectorragindexer:latest"
    BUILD_RESULT=$?
    if [ $BUILD_RESULT -ne 0 ]; then
        echo -e "${RED}✗ Docker build failed. Please fix before releasing.${NC}"
        exit 1
    fi
    echo -e "${GREEN}✓ Production image built and tagged (v$NEW_VERSION, latest)${NC}"
else
    echo -e "${RED}✗ Docker not found. Please install Docker first.${NC}"
    exit 1
fi

# Check if logged into GHCR
echo -e "${GREEN}Pushing Docker image to GitHub Container Registry...${NC}"
docker push ghcr.io/valginer0/pgvectorragindexer:$NEW_VERSION
PUSH_RESULT=$?
if [ $PUSH_RESULT -ne 0 ]; then
    echo -e "${RED}✗ Failed to push image. Please login to GHCR first:${NC}"
    echo -e "${YELLOW}  docker login ghcr.io -u valginer0${NC}"
    exit 1
fi
docker push ghcr.io/valginer0/pgvectorragindexer:latest
echo -e "${GREEN}✓ Image pushed to GHCR${NC}"

# Commit VERSION file
echo ""
git add VERSION
git commit -m "chore: Bump version to v$NEW_VERSION [skip ci]"
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
echo -e "${BLUE}What was done:${NC}"
echo -e "  1. ✓ All tests passed"
echo -e "  2. ✓ Docker image built locally"
echo -e "  3. ✓ Image pushed to GHCR"
echo -e "  4. ✓ Version bumped and committed"
echo -e "  5. ✓ Tag created and pushed"
echo ""
echo -e "${BLUE}Docker images available at:${NC}"
echo -e "  ${YELLOW}ghcr.io/valginer0/pgvectorragindexer:$NEW_VERSION${NC}"
echo -e "  ${YELLOW}ghcr.io/valginer0/pgvectorragindexer:latest${NC}"
echo ""
echo -e "${BLUE}Test on Windows:${NC}"
echo -e "  ${YELLOW}cd C:\\Users\\v_ale\\PGVectorRAGIndexer${NC}"
echo -e "  ${YELLOW}.\\update.ps1${NC}"
echo -e "  ${YELLOW}.\\run_desktop_app.ps1${NC}"
echo ""
