# Release Instructions

## Quick Release

To create a new release, simply run:

```bash
./release.sh
```

This will:
1. ✅ Check you're on main branch with no uncommitted changes
2. ✅ Pull latest changes
3. ✅ Ask for new version number
4. ✅ Run all tests
5. ✅ Update VERSION file
6. ✅ Create git tag
7. ✅ Push to GitHub
8. ✅ Trigger automated Docker build

## Manual Release Process

If you prefer to do it manually:

### 1. Update Version

```bash
echo "2.0.0" > VERSION
git add VERSION
git commit -m "chore: Bump version to v2.0.0"
```

### 2. Create Tag

```bash
git tag -a v2.0.0 -m "Release v2.0.0"
```

### 3. Push

```bash
git push origin main
git push origin v2.0.0
```

### 4. Monitor Build

GitHub Actions will automatically:
- Build Docker image
- Run tests
- Publish to `ghcr.io/valginer0/pgvectorragindexer:2.0.0`
- Publish to `ghcr.io/valginer0/pgvectorragindexer:latest`

Monitor at: https://github.com/valginer0/PGVectorRAGIndexer/actions

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
