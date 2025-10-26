#!/usr/bin/env bash
# Verify LibreOffice/soffice is available inside the PGVectorRAGIndexer image.
# Usage: ./check_libreoffice.sh [image]
set -euo pipefail

IMAGE="${1:-ghcr.io/valginer0/pgvectorragindexer:dev}"

if [ $# -gt 1 ]; then
  echo "Usage: $0 [image]" >&2
  exit 1
fi

echo "Checking LibreOffice availability inside image: ${IMAGE}" >&2

docker run --rm -e CHECK_IMAGE="${IMAGE}" "${IMAGE}" bash -lc "
set -e
if command -v soffice >/dev/null 2>&1; then
  BIN=soffice
elif command -v libreoffice >/dev/null 2>&1; then
  BIN=libreoffice
else
  echo 'LibreOffice binary not found in image' >&2
  exit 1
fi
PATH_TO_BIN=\"\$(command -v \${BIN})\"
echo \"Found \${BIN} at \${PATH_TO_BIN}\"
\${BIN} --version || true
"
