#!/usr/bin/env bash
# Build the PGVectorRAGIndexer production image from scratch, forcing latest base.
# Usage: ./scripts/build_prod_image.sh <primary-tag> [additional-tag...]
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "Usage: $0 <primary-tag> [additional-tag...]" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker not found in PATH." >&2
  exit 1
fi

PRIMARY_TAG="$1"
shift
ADDITIONAL_TAGS=("$@")

BASE_IMAGE="ghcr.io/valginer0/pgvectorragindexer:base"

echo "Pulling latest base image (${BASE_IMAGE})..." >&2
docker pull "${BASE_IMAGE}" >&2

echo "Building production image with --pull --no-cache..." >&2
DOCKER_BUILDKIT=1 docker build --pull --no-cache \
  -t "${PRIMARY_TAG}" \
  -f Dockerfile .

echo "Production image built: ${PRIMARY_TAG}" >&2

if [ ${#ADDITIONAL_TAGS[@]} -gt 0 ]; then
  for tag in "${ADDITIONAL_TAGS[@]}"; do
    echo "Tagging additional image: ${tag}" >&2
    docker tag "${PRIMARY_TAG}" "${tag}"
  done
  echo "Additional tags applied: ${ADDITIONAL_TAGS[*]}" >&2
fi
