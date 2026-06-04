#!/usr/bin/env bash
# Inspect image for LibreOffice/soffice presence and report version.
# Usage: ./scripts/inspect_image.sh <image>
set -euo pipefail

if [ $# -ne 1 ]; then
  echo "Usage: $0 <image>" >&2
  exit 1
fi

IMAGE="$1"

docker run --rm "$IMAGE" bash -lc '
set -e
if command -v soffice >/dev/null 2>&1; then
  BIN=soffice
elif command -v libreoffice >/dev/null 2>&1; then
  BIN=libreoffice
else
  echo "LibreOffice binary not found in PATH" >&2
  echo "Searching for soffice/libreoffice binaries..." >&2
  find / -maxdepth 4 -type f \( -name soffice -o -name libreoffice \) 2>/dev/null | head -n 20 >&2
  exit 1
fi
command -v "$BIN"
"$BIN" --version
'
