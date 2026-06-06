#!/usr/bin/env bash
# Build and download an unsigned Windows MSI artifact for branch/tag testing.
#
# This is intentionally separate from release.sh:
# - no VERSION bump
# - no release tag
# - no signing
# - no website update
#
# Usage:
#   ./scripts/build_dev_msi_artifact.sh [branch-or-tag]
#   ./scripts/build_dev_msi_artifact.sh dev/v2 --app-image ghcr.io/valginer0/pgvectorragindexer:dev

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
WORKFLOW_FILE="build-windows-installer.yml"
WORKFLOW_NAME="Build Windows Installer"
REPO="valginer0/PGVectorRAGIndexer"
REF=""
APP_IMAGE_OVERRIDE="${APP_IMAGE:-}"
TIMEOUT_SECONDS=3600
POLL_SECONDS=15

default_output_root() {
  if [ -d "/mnt/c/Users/v_ale" ]; then
    printf '%s\n' "/mnt/c/Users/v_ale/.codex/validation/PGVectorRAGIndexer/dev-msi"
  else
    printf '%s\n' "${HOME}/.codex/validation/PGVectorRAGIndexer/dev-msi"
  fi
}

OUTPUT_ROOT="${PGVECTOR_DEV_MSI_OUTPUT_DIR:-$(default_output_root)}"

usage() {
  cat <<'EOF'
Usage: ./scripts/build_dev_msi_artifact.sh [branch-or-tag] [options]

Build and download an unsigned MSI artifact using the existing GitHub Actions
"Build Windows Installer" workflow.

Arguments:
  branch-or-tag              Remote branch or tag to build. Defaults to current branch.

Options:
  --app-image IMAGE          Write APP_IMAGE into the generated install helper.
  --output-root DIR          Persistent root for downloaded artifacts.
  --timeout-seconds N        Workflow wait timeout. Default: 3600.
  --poll-seconds N           Poll interval. Default: 15.
  -h, --help                 Show this help.

Environment:
  APP_IMAGE                  Default value for --app-image.
  PGVECTOR_DEV_MSI_OUTPUT_DIR
                             Default output root override.

Output:
  <output-root>/<safe-ref>/<run-id>/PGVectorRAGIndexer.msi
  <output-root>/<safe-ref>/<run-id>/install-dev-msi.ps1

Notes:
  - This script does not sign the MSI.
  - This script does not update ragvault.net.
  - For branch/tag behavior, run the generated install-dev-msi.ps1 helper so
    the MSI installer process receives PGVECTOR_REPO_REF and, optionally,
    APP_IMAGE.
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --app-image)
      APP_IMAGE_OVERRIDE="${2:-}"
      if [ -z "$APP_IMAGE_OVERRIDE" ]; then
        echo "ERROR: --app-image requires a value" >&2
        exit 1
      fi
      shift 2
      ;;
    --output-root)
      OUTPUT_ROOT="${2:-}"
      if [ -z "$OUTPUT_ROOT" ]; then
        echo "ERROR: --output-root requires a value" >&2
        exit 1
      fi
      shift 2
      ;;
    --timeout-seconds)
      TIMEOUT_SECONDS="${2:-}"
      shift 2
      ;;
    --poll-seconds)
      POLL_SECONDS="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    -*)
      echo "ERROR: Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
    *)
      if [ -n "$REF" ]; then
        echo "ERROR: Only one branch-or-tag argument is allowed" >&2
        exit 1
      fi
      REF="$1"
      shift
      ;;
  esac
done

cd "${REPO_ROOT}"

if [ -z "$REF" ]; then
  REF="$(git branch --show-current)"
fi

if [ -z "$REF" ]; then
  echo "ERROR: Could not infer current branch; pass a branch or tag explicitly." >&2
  exit 1
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "ERROR: GitHub CLI (gh) is required." >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 is required for run polling." >&2
  exit 1
fi

resolve_remote_ref_sha() {
  local ref="$1"
  local sha=""

  sha="$(git ls-remote origin "refs/heads/${ref}" | awk 'NR == 1 {print $1}')"
  if [ -n "$sha" ]; then
    printf '%s\n' "$sha"
    return 0
  fi

  # Annotated tags need to be peeled to the commit SHA; lightweight tags are
  # already stored as the commit SHA.
  sha="$(git ls-remote origin "refs/tags/${ref}^{}" | awk 'NR == 1 {print $1}')"
  if [ -z "$sha" ]; then
    sha="$(git ls-remote origin "refs/tags/${ref}" | awk 'NR == 1 {print $1}')"
  fi

  if [ -n "$sha" ]; then
    printf '%s\n' "$sha"
    return 0
  fi

  return 1
}

REF_SHA="$(resolve_remote_ref_sha "$REF" || true)"
if [ -z "$REF_SHA" ]; then
  echo "ERROR: origin does not have branch or tag '$REF'." >&2
  echo "Push the branch/tag first, then rerun this script." >&2
  exit 1
fi

safe_ref="$(printf '%s' "$REF" | tr '/: ' '---')"
started_epoch="$(date -u +%s)"

echo "Triggering '${WORKFLOW_NAME}' for ref '${REF}' (${REF_SHA})..."
gh workflow run "$WORKFLOW_FILE" --repo "$REPO" --ref "$REF"

find_run_json() {
  gh run list \
    --repo "$REPO" \
    --workflow "$WORKFLOW_NAME" \
    --event workflow_dispatch \
    --limit 30 \
    --json databaseId,headBranch,headSha,status,conclusion,createdAt,url \
  | python3 -c '
import datetime
import json
import sys

ref = sys.argv[1]
ref_sha = sys.argv[2]
started_epoch = int(sys.argv[3])
runs = json.load(sys.stdin)

def parse_epoch(value: str) -> int:
    value = value.replace("Z", "+00:00")
    return int(datetime.datetime.fromisoformat(value).timestamp())

for run in runs:
    # Branch-triggered runs are easy to identify by headBranch. Tag-triggered
    # runs can report the target branch instead, so also match the resolved SHA.
    if run.get("headBranch") != ref and run.get("headSha") != ref_sha:
        continue
    if parse_epoch(run["createdAt"]) < started_epoch - 5:
        continue
    print(json.dumps(run))
    break
' "$REF" "$REF_SHA" "$started_epoch"
}

deadline=$((started_epoch + TIMEOUT_SECONDS))
run_json=""

while [ "$(date -u +%s)" -lt "$deadline" ]; do
  run_json="$(find_run_json || true)"
  if [ -n "$run_json" ]; then
    status="$(printf '%s' "$run_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])')"
    conclusion="$(printf '%s' "$run_json" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("conclusion") or "")')"
    run_id="$(printf '%s' "$run_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["databaseId"])')"
    url="$(printf '%s' "$run_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["url"])')"
    echo "Run ${run_id}: status=${status}${conclusion:+ conclusion=${conclusion}}"
    if [ "$status" = "completed" ]; then
      if [ "$conclusion" != "success" ]; then
        echo "ERROR: Workflow run failed: $url" >&2
        exit 1
      fi
      break
    fi
  else
    echo "Waiting for workflow run to appear..."
  fi
  sleep "$POLL_SECONDS"
done

if [ -z "${run_id:-}" ] || [ "${status:-}" != "completed" ]; then
  echo "ERROR: Timed out waiting for '${WORKFLOW_NAME}' on ref '${REF}'." >&2
  exit 1
fi

output_dir="${OUTPUT_ROOT}/${safe_ref}/${run_id}"
rm -rf "$output_dir"
mkdir -p "$output_dir"

echo "Downloading unsigned MSI artifact to ${output_dir}..."
gh run download "$run_id" \
  --repo "$REPO" \
  --name "PGVectorRAGIndexer.msi" \
  --dir "$output_dir"

msi_path="$(find "$output_dir" -maxdepth 2 -type f -name 'PGVectorRAGIndexer.msi' | head -n 1)"
if [ -z "$msi_path" ]; then
  echo "ERROR: Download completed, but PGVectorRAGIndexer.msi was not found." >&2
  find "$output_dir" -maxdepth 3 -print >&2
  exit 1
fi

canonical_msi="${output_dir}/PGVectorRAGIndexer.msi"
if [ "$msi_path" != "$canonical_msi" ]; then
  cp "$msi_path" "$canonical_msi"
fi

if command -v wslpath >/dev/null 2>&1; then
  windows_msi_path="$(wslpath -w "$canonical_msi")"
else
  windows_msi_path="$canonical_msi"
fi

helper_path="${output_dir}/install-dev-msi.ps1"
cat > "$helper_path" <<EOF
# Generated by scripts/build_dev_msi_artifact.sh
# Installs the unsigned dev MSI with branch/test overrides in this PowerShell process.

\$ErrorActionPreference = "Stop"
\$env:PGVECTOR_REPO_REF = "$REF"
EOF

if [ -n "$APP_IMAGE_OVERRIDE" ]; then
  cat >> "$helper_path" <<EOF
\$env:APP_IMAGE = "$APP_IMAGE_OVERRIDE"
EOF
else
  cat >> "$helper_path" <<'EOF'
# Optional backend image override for Local Docker tests:
# $env:APP_IMAGE = "ghcr.io/valginer0/pgvectorragindexer:your-debug-tag"
EOF
fi

cat >> "$helper_path" <<EOF

\$msiPath = "$windows_msi_path"
Write-Host "Installing dev MSI: \$msiPath"
Write-Host "PGVECTOR_REPO_REF=\$env:PGVECTOR_REPO_REF"
if (\$env:APP_IMAGE) { Write-Host "APP_IMAGE=\$env:APP_IMAGE" }
Start-Process -FilePath "msiexec.exe" -ArgumentList @("/i", \$msiPath) -Wait

\$setupPath = Join-Path \$env:ProgramFiles "PGVectorRAGIndexer\\PGVectorRAGIndexer-Setup.exe"
if (Test-Path -LiteralPath \$setupPath) {
    Write-Host "Launching Setup Wizard with the same branch/test overrides: \$setupPath"
    Start-Process -FilePath \$setupPath -Wait
} else {
    Write-Warning "Setup Wizard was not found at \$setupPath"
    Write-Warning "Launch PGVectorRAGIndexer-Setup.exe from the MSI install location using this same PowerShell session."
}
EOF

echo ""
echo "✓ Dev MSI artifact is ready:"
echo "  WSL:     $canonical_msi"
echo "  Windows: $windows_msi_path"
echo ""
echo "Install helper:"
if command -v wslpath >/dev/null 2>&1; then
  echo "  $(wslpath -w "$helper_path")"
else
  echo "  $helper_path"
fi
echo ""
echo "This artifact is unsigned and intended for testing only."
