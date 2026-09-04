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

# Check for untracked files
if [ -n "$(git ls-files --others --exclude-standard)" ]; then
    echo -e "${RED}✗ You have untracked files. Please commit, stash, or .gitignore them first.${NC}"
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
SKIP_CI_GATE=false
while true; do
    case "$1" in
        -y) CONFIRM=false; shift ;;
        # Escape hatch for an emergency release when CI itself is broken.
        # Using it means the tag is published without the default-install
        # check that v2.17.0 shipped past.
        --skip-ci-gate) SKIP_CI_GATE=true; shift ;;
        *) break ;;
    esac
done

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
    echo -e "  ./release.sh [-y] [version|type]"
    echo -e "  ./release.sh          # Auto-bump patch"
    echo -e "  ./release.sh -y       # Auto-bump patch, no confirmation"
    echo -e "  ./release.sh patch    # Bump patch: 2.0.2 → 2.0.3"
    echo -e "  ./release.sh minor    # Bump minor: 2.0.2 → 2.1.0"
    echo -e "  ./release.sh major    # Bump major: 2.0.2 → 3.0.0"
    echo -e "  ./release.sh 2.5.7    # Explicit version"
    exit 1
fi

echo ""
echo -e "${YELLOW}This will:${NC}"

if [ "$NEW_VERSION" != "$CURRENT_VERSION" ]; then
    echo -e "  1. Update VERSION file to ${GREEN}$NEW_VERSION${NC}"
else
    echo -e "  1. Skip VERSION update (already $NEW_VERSION)"
fi
echo -e "  2. Run tests"
echo -e "  3. Create git tag ${GREEN}v$NEW_VERSION${NC}"
echo -e "  4. Push tag to GitHub"
echo -e "  5. Build and publish Docker image to GitHub Container Registry"
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
else
     echo -e "${BLUE}Version matches current. Skipping file updates and commit.${NC}"
fi

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
        python -m pytest tests/ -v -m 'not slow'
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

if [ "$NEW_VERSION" != "$CURRENT_VERSION" ]; then
    # Commit VERSION file and documentation
    echo ""
    # Pragmatic Tradeoff: 'git add -u' stages all tracked modifications made during the script.
    # Since we enforced a clean tree at the start, this safely captures all newly bumped version files
    # without needing a hardcoded list, though it will catch side-effects if any exist.
    git add -u
    git commit -m "chore: Bump version to v$NEW_VERSION"
    echo -e "${GREEN}✓ Committed version bump${NC}"
    
    # Also commit and push website changes if they exist
    WEBSITE_DIR="${WEBSITE_REPO_PATH:-../PGVectorRAGIndexerWebsite}"
    if [ -d "$WEBSITE_DIR/.git" ]; then
        cd "$WEBSITE_DIR"
        
        # Verify we are on main branch
        WEBSITE_BRANCH=$(git branch --show-current)
        if [ "$WEBSITE_BRANCH" != "main" ]; then
            echo -e "${YELLOW}⚠ Website is not on 'main' branch (currently '$WEBSITE_BRANCH'). Skipping website deployment.${NC}"
        elif ! git diff-index --quiet HEAD --; then
            echo -e "${GREEN}Committing and pushing website version bump...${NC}"
            # Ensure we are up to date before committing and pushing
            git pull origin main || {
                echo -e "${RED}✗ Failed to pull latest website changes. Skipping website deployment.${NC}"
            }
            
            git add -u
            git commit -m "chore: release v$NEW_VERSION"
            git push origin main || {
                echo -e "${RED}✗ Failed to push website changes. Deployment skipped.${NC}"
            }
            echo -e "${GREEN}✓ Website updated and deployed${NC}"
        fi
        cd - > /dev/null
    fi
else
    echo -e "${BLUE}Skipping commit (version unchanged)${NC}"
fi

# Create and push tag
git tag -a "v$NEW_VERSION" -m "Release v$NEW_VERSION

See CHANGELOG.md for details."
echo -e "${GREEN}✓ Created tag v$NEW_VERSION${NC}"

# Push the release commit first, WITHOUT the tag. The tag is what publishes a
# release (it triggers the installer build and becomes the version users get),
# so it must not go out until CI has judged this exact commit.
git push origin main

# ── CI gate ─────────────────────────────────────────────────────────────────
# v2.17.0 shipped a default install that returned 401 against its own machine.
# Nothing stopped it: the tag was pushed seconds after the commit, long before
# any workflow finished. The install-defaults job now covers that path, but a
# passing job only helps if the release waits for it.
if [ "$SKIP_CI_GATE" = true ]; then
    echo -e "${YELLOW}⚠ Skipping the CI gate (--skip-ci-gate).${NC}"
    echo -e "${YELLOW}  The tag will publish without CI having judged this commit.${NC}"
elif ! command -v gh &> /dev/null; then
    echo -e "${RED}✗ gh CLI not found - cannot verify CI before tagging.${NC}"
    echo -e "${YELLOW}  Install gh, or re-run with --skip-ci-gate to publish anyway.${NC}"
    echo -e "${YELLOW}  The local tag v$NEW_VERSION exists but was NOT pushed.${NC}"
    exit 1
else
    RELEASE_SHA=$(git rev-parse HEAD)
    echo ""
    echo -e "${GREEN}Waiting for CI on the release commit before publishing the tag...${NC}"
    echo -e "${BLUE}  commit: $RELEASE_SHA${NC}"

    # Give the workflows time to be registered before concluding anything.
    for _ in $(seq 1 24); do
        [ -n "$(gh run list --commit "$RELEASE_SHA" --limit 25 --json databaseId -q '.[].databaseId' 2>/dev/null)" ] && break
        sleep 5
    done
    if [ -z "$(gh run list --commit "$RELEASE_SHA" --limit 25 --json databaseId -q '.[].databaseId' 2>/dev/null)" ]; then
        echo -e "${RED}✗ No workflow runs appeared for this commit after 2 minutes.${NC}"
        echo -e "${YELLOW}  The local tag v$NEW_VERSION exists but was NOT pushed.${NC}"
        exit 1
    fi

    # Poll until every run on this commit has finished (40 min ceiling).
    GATE_DEADLINE=$(( $(date +%s) + 2400 ))
    while [ -n "$(gh run list --commit "$RELEASE_SHA" --limit 25 --json status -q '.[]|select(.status!="completed")' 2>/dev/null)" ]; do
        if [ "$(date +%s)" -gt "$GATE_DEADLINE" ]; then
            echo -e "${RED}✗ CI did not finish within 40 minutes.${NC}"
            echo -e "${YELLOW}  The local tag v$NEW_VERSION exists but was NOT pushed.${NC}"
            exit 1
        fi
        sleep 20
    done

    FAILED=$(gh run list --commit "$RELEASE_SHA" --limit 25 \
        --json conclusion,name -q '.[]|select(.conclusion!="success")|.name' 2>/dev/null | sort -u)
    if [ -n "$FAILED" ]; then
        echo -e "${RED}✗ CI is not green on the release commit. Tag NOT pushed.${NC}"
        echo -e "${RED}  Failing: $(echo "$FAILED" | tr '\n' ' ')${NC}"
        echo ""
        echo -e "${YELLOW}  The version bump is already on main, and the local tag exists.${NC}"
        echo -e "${YELLOW}  Fix the failure, then either:${NC}"
        echo -e "${YELLOW}    git tag -d v$NEW_VERSION && ./release.sh -y $NEW_VERSION   (re-tag the fixed commit)${NC}"
        echo -e "${YELLOW}    git push origin v$NEW_VERSION                              (publish anyway)${NC}"
        exit 1
    fi
    echo -e "${GREEN}✓ CI green on the release commit${NC}"
fi

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
