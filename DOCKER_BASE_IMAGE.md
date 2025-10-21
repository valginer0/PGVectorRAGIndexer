# Docker Base Image Strategy

## Overview

To speed up development iterations, we use a **two-layer Docker image strategy**:

1. **Base Image** (`ghcr.io/valginer0/pgvectorragindexer:base`) - ~8.3GB
   - Contains Python 3.12 + all heavy dependencies (PyTorch, CUDA, transformers, etc.)
   - Rebuilt only when `requirements.txt` changes (rarely)
   - Takes ~15 minutes to build and push

2. **App Image** (`ghcr.io/valginer0/pgvectorragindexer:dev` or `:latest`) - ~50MB
   - Built on top of base image
   - Contains only application code (Python files, static files, etc.)
   - Rebuilt frequently during development
   - Takes ~2 minutes to build and push

## Benefits

- **Fast iterations**: Dev builds go from 15 minutes → 2 minutes
- **Smaller uploads**: Push 50MB instead of 8.3GB per iteration
- **Faster downloads**: Windows pulls 50MB instead of 8.3GB
- **Same final image**: No difference in functionality

## When to Rebuild Base Image

Rebuild the base image only when:
- Adding/removing packages in `requirements.txt`
- Updating package versions in `requirements.txt`
- Changing system dependencies (gcc, postgresql-client, etc.)

Typically: Once a month or less

## How to Rebuild Base Image

```bash
# In WSL
cd /home/valginer0/projects/PGVectorRAGIndexer
./build-base.sh
```

This will:
1. Build the base image with all dependencies (~15 minutes)
2. Push to GHCR (~10 minutes depending on upload speed)
3. Make it available for app builds

## Normal Development Workflow

```bash
# In WSL - Build and push app image (fast!)
./push-dev.sh  # Now takes ~2 minutes instead of ~15 minutes

# In Windows - Pull and test
.\update-dev.ps1
.\run_desktop_app.ps1
```

## Files

- `Dockerfile.base` - Defines the base image with dependencies
- `Dockerfile` - Defines the app image (uses base)
- `build-base.sh` - Script to build and push base image
- `push-dev.sh` - Script to build and push app image (uses base)

## Image Tags

- `ghcr.io/valginer0/pgvectorragindexer:base` - Base image (rarely changes)
- `ghcr.io/valginer0/pgvectorragindexer:dev` - Development app image
- `ghcr.io/valginer0/pgvectorragindexer:latest` - Production app image
- `ghcr.io/valginer0/pgvectorragindexer:x.y.z` - Versioned releases

## First Time Setup

If you're setting up a new machine or the base image doesn't exist yet:

```bash
# Build base image first (one time, ~25 minutes total)
./build-base.sh

# Then build app image (fast from now on)
./push-dev.sh
```

## Troubleshooting

**Error: "failed to solve: ghcr.io/valginer0/pgvectorragindexer:base: not found"**
- The base image hasn't been built yet
- Run `./build-base.sh` first

**Base image is outdated**
- Check if `requirements.txt` changed
- Rebuild base with `./build-base.sh`

**Want to force rebuild everything**
```bash
# Rebuild base
./build-base.sh

# Rebuild app
./push-dev.sh
```
