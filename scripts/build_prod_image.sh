#!/usr/bin/env bash
# Build the PGVectorRAGIndexer production image from scratch, forcing latest base.
# Usage: ./scripts/build_prod_image.sh [<primary-tag> [additional-tag...]]
# If no tags are supplied, defaults to ghcr.io/valginer0/pgvectorragindexer:<VERSION> and :latest
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker not found in PATH." >&2
  exit 1
fi

DEFAULT_IMAGE_REPO="ghcr.io/valginer0/pgvectorragindexer"
VERSION_FILE="${REPO_ROOT}/VERSION"

is_version_bump_arg=false

if [ $# -eq 0 ]; then
  is_version_bump_arg=true
  BUMP_TYPE="patch"
elif [[ "$1" =~ ^(major|minor|patch)$ || "$1" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  is_version_bump_arg=true
  BUMP_TYPE="$1"
  shift
  if [ $# -gt 0 ]; then
    echo "Too many arguments provided for version bump mode." >&2
    echo "Usage: $0 [major|minor|patch|X.Y.Z]" >&2
    exit 1
  fi
else
  PRIMARY_TAG="$1"
  shift
  ADDITIONAL_TAGS=("$@")
fi

if [ "$is_version_bump_arg" = true ]; then
  if [ -f "${VERSION_FILE}" ]; then
    CURRENT_VERSION=$(tr -d ' \t\r\n' < "${VERSION_FILE}")
  else
    CURRENT_VERSION="0.0.0"
  fi

  IFS='.' read -r CUR_MAJOR CUR_MINOR CUR_PATCH <<< "${CURRENT_VERSION}"

  case "${BUMP_TYPE}" in
    major)
      NEW_VERSION="$((CUR_MAJOR + 1)).0.0"
      ;;
    minor)
      NEW_VERSION="${CUR_MAJOR}.$((CUR_MINOR + 1)).0"
      ;;
    patch)
      NEW_VERSION="${CUR_MAJOR}.${CUR_MINOR}.$((CUR_PATCH + 1))"
      ;;
    *)
      NEW_VERSION="${BUMP_TYPE}"
      ;;
  esac

  echo "${NEW_VERSION}" > "${VERSION_FILE}"

  PRIMARY_TAG="${DEFAULT_IMAGE_REPO}:${NEW_VERSION}"
  ADDITIONAL_TAGS=("${DEFAULT_IMAGE_REPO}:latest")

  echo "Auto versioning: current=${CURRENT_VERSION}, new=${NEW_VERSION}" >&2
  echo "Tags: ${PRIMARY_TAG} ${ADDITIONAL_TAGS[*]}" >&2
fi

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
