# Release Instructions

> **Audience:** Project maintainer only. Not relevant for end users.

## Release Process (CI-based)

### 1. Run Tests

```bash
source venv/bin/activate
python -m pytest tests/ --ignore=tests/test_slow* --ignore=tests/test_search_tab_open.py \
  --ignore=tests/test_upload_endpoint.py --ignore=tests/test_web_ui.py \
  --ignore=tests/test_web_ui_integration.py -q
```

### 2. Bump Version

Update all version references (single source of truth is `VERSION` file):

```bash
echo "X.Y.Z" > VERSION
```

Also update:
- `CHANGELOG.md` — add new version section
- Website `index.html` — hero badge (line ~72), footer (line ~1201), download links (lines ~165, ~187, ~202)
- Website `package.json` — version field

### 3. Commit, Tag, and Push

```bash
git add VERSION CHANGELOG.md
git commit -m "chore: bump version to vX.Y.Z"
git tag vX.Y.Z
git push origin main --tags
```

This triggers 5 CI workflows:
- **Docker Build and Publish** — builds and pushes Docker image to GHCR
- **Build Windows Installer** — builds unsigned `.msi` via PyInstaller + WiX
- **Build Base Image** — builds tagged Docker base image
- **Verify Installers** — validates installer scripts
- **macOS Compatibility Check** — validates macOS support

### 4. Sign the Windows Installer

After CI completes, download the unsigned MSI and sign it:

```bash
# Download from CI artifacts
gh run download <run-id> --name PGVectorRAGIndexer.msi \
  --dir /mnt/c/Users/v_ale/Desktop/ToSign/PGVectorRAGIndexer-unsigned
```

Sign with the code-signing certificate:
```powershell
PS C:\Users\v_ale\Desktop\ToSign> .\signtool.exe sign `
  /sha1 c72170b0d48e4ea6a3a64739795f2952a0aac06d `
  /tr http://time.certum.pl /td sha256 /fd sha256 `
  /d "PGVectorRAGIndexer" `
  PGVectorRAGIndexer-unsigned\PGVectorRAGIndexer.msi
```

### 5. Upload Signed MSI to Release

```bash
gh release upload vX.Y.Z /mnt/c/Users/v_ale/Desktop/ToSign/PGVectorRAGIndexer-unsigned/PGVectorRAGIndexer.msi \
  --clobber
```

### 6. Push Website Updates

```bash
cd /path/to/PGVectorRAGIndexerWebsite
git add index.html package.json
git commit -m "chore: bump version to vX.Y.Z, update download links"
git push origin main
```

## Prerequisites

Ensure you're logged into GitHub Container Registry:

```bash
# Login to GHCR (one-time setup)
docker login ghcr.io -u valginer0
# Enter your GitHub Personal Access Token when prompted
```

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
