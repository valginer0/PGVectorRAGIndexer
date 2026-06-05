#!/bin/bash
# Run full pytest suite inside project virtual environment.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PATH="$PROJECT_ROOT/venv/bin/activate"

if [[ ! -f "$VENV_PATH" ]]; then
  echo "Virtual environment not found at $VENV_PATH" >&2
  exit 1
fi

source "$VENV_PATH"
cd "$PROJECT_ROOT"

pytest "$@"
