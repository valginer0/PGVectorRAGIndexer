# Release Instructions

> **Audience:** Project maintainer only. Not relevant for end users.

## Quick Release

To create a new release, simply run:

```bash
./release.sh patch  # or: minor, major, or explicit version like 2.0.3
```

This will:
1. ✅ Check you're on main branch with no uncommitted changes
2. ✅ Pull latest changes
3. ✅ Bump version number (patch/minor/major)
4. ✅ Run all tests
5. ✅ **Build Docker image locally** (~15 minutes)
6. ✅ **Push image to GHCR** (with version tag and `:latest`)
7. ✅ Update VERSION file
8. ✅ Create git tag
9. ✅ Push to GitHub (with `[skip ci]` to avoid duplicate build)

**Note:** This builds the Docker image locally and pushes it directly to GHCR, skipping GitHub Actions (~20 minutes faster).

## Prerequisites

Before releasing, ensure you're logged into GitHub Container Registry:

```bash
# Login to GHCR (one-time setup)
docker login ghcr.io -u valginer0
# Enter your GitHub Personal Access Token when prompted
```

## Manual Release Process

If you prefer to do it manually:

### 1. Run Tests

```bash
source venv/bin/activate
pytest tests/ -v
```

### 2. Build Docker Image

```bash
docker compose -f docker-compose.dev.yml build app
```

### 3. Tag Docker Image

```bash
# Replace 2.0.3 with your version
docker tag pgvectorragindexer:dev ghcr.io/valginer0/pgvectorragindexer:2.0.3
docker tag pgvectorragindexer:dev ghcr.io/valginer0/pgvectorragindexer:latest
```

**Why two tags?**
- `:2.0.3` - Specific version (immutable, users can pin to this)
- `:latest` - Always points to newest version (auto-updates)

### 4. Push to GHCR

```bash
docker push ghcr.io/valginer0/pgvectorragindexer:2.0.3
docker push ghcr.io/valginer0/pgvectorragindexer:latest
```

### 5. Update Version and Tag

```bash
echo "2.0.3" > VERSION
git add VERSION
git commit -m "chore: Bump version to v2.0.3 [skip ci]"
git tag -a v2.0.3 -m "Release v2.0.3"
```

### 6. Push to GitHub

```bash
git push origin main
git push origin v2.0.3
```

**Note:** The `[skip ci]` in the commit message prevents GitHub Actions from rebuilding the Docker image (since we already built and pushed it).

## Development Workflow

### Local Development (WSL)

For rapid iteration during development:

```bash
# Build and run with development config
docker compose -f docker-compose.dev.yml up -d

# Run tests
source venv/bin/activate
pytest tests/ -v

# Make changes, rebuild, and push for Windows testing
./push-dev.sh
```

The `push-dev.sh` script will:
1. Build Docker image with `:dev` tag
2. Push to GHCR as `ghcr.io/valginer0/pgvectorragindexer:dev`
3. Ready for Windows testing

**Key differences:**
- `docker-compose.dev.yml` - Builds locally with `:dev` tag
- `docker-compose.yml` - Pulls from GHCR with `:latest` tag (production)
- `:dev` tag - For testing before release
- `:latest` tag - For production use

### Testing on Windows (Development Build)

After pushing dev build, test on Windows:

```powershell
# Pull and run latest dev build
.\update-dev.ps1

# Run desktop app
.\run_desktop_app.ps1
```

The `update-dev.ps1` script will:
- Pull latest `:dev` image from GHCR
- Restart containers with dev image
- Check API health

### Testing on Windows (Production Build)

After releasing, test the production build:

```powershell
# Update to latest production version
.\update.ps1

# Run desktop app
.\run_desktop_app.ps1
```

The `update.ps1` script will:
- Pull latest code from GitHub
- Pull latest `:latest` image from GHCR
- Update desktop app dependencies

## First Release (v2.0.0)

For the first release, run:

```bash
./release.sh
```

When prompted, enter: `2.0.0`

## Testing the Release

After the Docker image is published, test the deployment:

```bash
# Create a test directory
mkdir -p ~/test-pgvector && cd ~/test-pgvector

# Run the deployment script
curl -fsSL https://raw.githubusercontent.com/valginer0/PGVectorRAGIndexer/main/docker-run.sh | bash

# Verify services are running
docker ps

# Check API
curl http://localhost:8000/health

# View logs
docker compose logs -f
```

## Versioning Guidelines

We follow [Semantic Versioning](https://semver.org/):

- **MAJOR** (x.0.0): Breaking changes
- **MINOR** (2.x.0): New features, backwards compatible
- **PATCH** (2.0.x): Bug fixes, backwards compatible

Examples:
- `2.0.0` → First stable release
- `2.1.0` → Added new search features
- `2.0.1` → Fixed bug in vector search
- `3.0.0` → Changed API (breaking change)

## GitHub Container Registry

Images are published to:
- `ghcr.io/valginer0/pgvectorragindexer:2.0.0` (specific version)
- `ghcr.io/valginer0/pgvectorragindexer:2.0` (minor version)
- `ghcr.io/valginer0/pgvectorragindexer:2` (major version)
- `ghcr.io/valginer0/pgvectorragindexer:latest` (latest release)

## Rollback

If you need to rollback a release:

```bash
# Delete local tag
git tag -d v2.0.0

# Delete remote tag
git push origin :refs/tags/v2.0.0

# Revert VERSION file
git revert <commit-hash>
git push origin main
```

## Troubleshooting

### Build Failed

Check GitHub Actions logs:
https://github.com/valginer0/PGVectorRAGIndexer/actions

Common issues:
- Tests failing → Fix tests before releasing
- Docker build error → Check Dockerfile syntax
- Permission denied → Check GitHub token permissions

### Image Not Found

Wait a few minutes for the build to complete. Check:
```bash
# List available tags
curl -H "Authorization: Bearer $GITHUB_TOKEN" \
  https://ghcr.io/v2/valginer0/pgvectorragindexer/tags/list
```

### Deployment Script Fails

Test locally first:
```bash
# Clone repo
git clone https://github.com/valginer0/PGVectorRAGIndexer.git
cd PGVectorRAGIndexer

# Run docker-compose
docker compose -f docker-compose.full.yml up -d
```
