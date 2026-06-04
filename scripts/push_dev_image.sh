#!/usr/bin/env bash
# Push the current dev image to GHCR without rebuilding.
set -euo pipefail

echo "Pushing ghcr.io/valginer0/pgvectorragindexer:dev to GHCR..." >&2

docker push ghcr.io/valginer0/pgvectorragindexer:dev

echo "Push complete." >&2
