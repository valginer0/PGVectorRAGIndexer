#!/bin/bash

# Lightweight Release Script for PGVectorRAGIndexer
# Creates a new release tag WITHOUT Docker build
# Use this for documentation-only or non-code releases

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     PGVectorRAGIndexer Lightweight Release Script         ║${NC}"
echo -e "${BLUE}║     (No Docker build - for docs/scripts only)             ║${NC}"
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

# Parse arguments
CONFIRM=true
if [ "$1" == "-y" ]; then
    CONFIRM=false
    shift
fi

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
    echo -e "  ./release-lite.sh [-y] [version|type]"
    echo -e "  ./release-lite.sh          # Auto-bump patch"
    echo -e "  ./release-lite.sh -y       # Auto-bump patch, no confirmation"
    echo -e "  ./release-lite.sh 2.5.7    # Explicit version"
    exit 1
fi

echo ""
echo -e "${YELLOW}This will (NO Docker build):${NC}"

if [ "$NEW_VERSION" != "$CURRENT_VERSION" ]; then
    echo -e "  1. Update VERSION file to ${GREEN}$NEW_VERSION${NC}"
else
    echo -e "  1. Skip VERSION update (already $NEW_VERSION)"
fi
echo -e "  2. Create git tag ${GREEN}v$NEW_VERSION${NC}"
echo -e "  3. Push tag to GitHub"
echo ""
echo -e "${YELLOW}⚠ Note: Docker image will NOT be rebuilt.${NC}"
echo -e "${YELLOW}  Use ./release.sh for full releases with Docker.${NC}"
echo ""

if [ "$CONFIRM" = true ]; then
    read -p "Continue? (y/n) " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${YELLOW}Aborted.${NC}"
        exit 0
    fi
fi

if [ "$NEW_VERSION" != "$CURRENT_VERSION" ]; then
    # Update VERSION file
    echo "$NEW_VERSION" > VERSION
    echo -e "${GREEN}✓ Updated VERSION file${NC}"

    # Update documentation headers
    echo -e "${GREEN}Updating documentation version references...${NC}"
    if python3 scripts/update_version_docs.py 2>/dev/null; then
        echo -e "${GREEN}✓ Documentation updated${NC}"
    else
        echo -e "${YELLOW}⚠ Could not update documentation (script missing or failed)${NC}"
    fi

    # Commit VERSION file and documentation
    git add VERSION README.md QUICK_START.md DEPLOYMENT.md
    git commit -m "chore: Bump version to v$NEW_VERSION [skip ci]"
    echo -e "${GREEN}✓ Committed version bump${NC}"
else
    echo -e "${BLUE}Version matches current. Skipping file updates and commit.${NC}"
fi

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
echo -e "${GREEN}║         ✓ Lightweight Release v$NEW_VERSION Created!         ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${BLUE}What was done:${NC}"
echo -e "  1. ✓ VERSION file updated to $NEW_VERSION"
echo -e "  2. ✓ Git tag v$NEW_VERSION created"
echo -e "  3. ✓ Pushed to GitHub"
echo ""
echo -e "${YELLOW}Note: Docker image was NOT rebuilt.${NC}"
echo -e "${YELLOW}      The latest Docker image is still the previous version.${NC}"
echo ""
