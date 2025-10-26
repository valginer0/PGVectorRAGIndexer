#!/usr/bin/env bash
# Build the PGVectorRAGIndexer dev image from scratch, forcing latest base.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "Pulling latest base image..." >&2
docker pull ghcr.io/valginer0/pgvectorragindexer:base >&2

echo "Building dev image with --pull --no-cache..." >&2
DOCKER_BUILDKIT=1 docker build --pull --no-cache \
  -t ghcr.io/valginer0/pgvectorragindexer:dev \
  -f Dockerfile .

echo "Dev image built: ghcr.io/valginer0/pgvectorragindexer:dev" >&2
