#!/usr/bin/env bash
# Build, verify, and push the PGVectorRAGIndexer dev image.
# Usage: ./scripts/build_and_push_dev.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

echo "[1/3] Building dev image (pull + no cache)..." >&2
"${SCRIPT_DIR}/build_dev_image.sh"

echo "[2/3] Verifying LibreOffice availability in dev image..." >&2
"${REPO_ROOT}/check_libreoffice.sh" ghcr.io/valginer0/pgvectorragindexer:dev

echo "[3/3] Pushing dev image to GHCR..." >&2
"${SCRIPT_DIR}/push_dev_image.sh"

echo "✓ Dev image rebuilt, verified, and pushed." >&2
