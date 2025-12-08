#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

usage() {
    cat <<'EOF'
Usage:
  ./manage.sh update [prod|dev] [--dry-run]
  ./manage.sh run [--dry-run]
  ./manage.sh release [patch|minor|major|<version>] [--dry-run]
  ./manage.sh help

Actions:
  update   Pull/build containers for the selected channel (default: dev)
  run      Launch the desktop application
  release  Forward to release.sh with the given bump keyword (WSL maintainers)
  help     Show this message
EOF
}

DRY_RUN=false
CHANNEL="dev"
ACTION="help"
RELEASE_ARG="patch"

if [[ $# -gt 0 ]]; then
    ACTION="$1"
    shift
fi

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            prod|dev)
                CHANNEL="$1"
                shift
                ;;
            --dry-run)
                DRY_RUN=true
                shift
                ;;
            patch|minor|major)
                RELEASE_ARG="$1"
                shift
                ;;
            help)
                ACTION="help"
                shift
                ;;
            *)
                RELEASE_ARG="$1"
                shift
                ;;
        esac
    done
}

compose_update() {
    local channel="$1"
    local dry_run="$2"
    local env_file="$SCRIPT_DIR/.env.manage.tmp"

    if [[ "$channel" == "dev" ]]; then
        echo "Preparing development environment (docker-compose.dev.yml)"
        if [[ "$dry_run" == true ]]; then
            echo "[DRY RUN] docker compose -f docker-compose.dev.yml down"
            echo "[DRY RUN] docker compose -f docker-compose.dev.yml up -d --build"
            return
        fi
        docker compose -f docker-compose.dev.yml down
        docker compose -f docker-compose.dev.yml up -d --build
    else
        local image="ghcr.io/valginer0/pgvectorragindexer:latest"
        cat <<EOF >"$env_file"
APP_IMAGE=$image
EOF
        echo "Preparing production environment (image: $image)"
        if [[ "$dry_run" == true ]]; then
            echo "[DRY RUN] docker compose --file docker-compose.yml --env-file $env_file pull"
            echo "[DRY RUN] docker compose --file docker-compose.yml --env-file $env_file down"
            echo "[DRY RUN] docker compose --file docker-compose.yml --env-file $env_file up -d"
            rm -f "$env_file"
            return
        fi
        docker compose --file docker-compose.yml --env-file "$env_file" pull
        docker compose --file docker-compose.yml --env-file "$env_file" down
        docker compose --file docker-compose.yml --env-file "$env_file" up -d
        rm -f "$env_file"
    fi

    wait_for_api "http://localhost:8000/health" "$dry_run"
}

wait_for_api() {
    local url="$1"
    local dry_run="$2"
    local max_attempts=30
    local attempt=0

    if [[ "$dry_run" == true ]]; then
        echo "[DRY RUN] Would check API health at $url"
        return
    fi

    echo "Waiting for API to be ready..."
    while (( attempt < max_attempts )); do
        if curl -fs --max-time 2 "$url" >/dev/null; then
            echo "[OK] API is ready!"
            return
        fi
        printf '.'
        sleep 2
        attempt=$((attempt + 1))
    done
    echo
    echo "[WARNING] API health check timed out. Containers may still be initializing."
    echo "  Tip: docker compose logs -f"
}

run_desktop() {
    local dry_run="$1"
    local script="$SCRIPT_DIR/run_desktop_app.sh"
    if [[ ! -f "$script" ]]; then
        echo "run_desktop_app.sh not found at $script" >&2
        exit 1
    fi

    if [[ "$dry_run" == true ]]; then
        echo "[DRY RUN] $script"
    else
        "$script"
    fi
}

invoke_release() {
    local arg="$1"
    local dry_run="$2"
    local script="$SCRIPT_DIR/release.sh"
    if [[ ! -f "$script" ]]; then
        echo "release.sh not found at $script" >&2
        exit 1
    fi

    if [[ "$dry_run" == true ]]; then
        echo "[DRY RUN] $script $arg"
    else
        "$script" "$arg"
    fi
}

case "$ACTION" in
    update)
        parse_args "$@"
        compose_update "$CHANNEL" "$DRY_RUN"
        ;;
    run)
        parse_args "$@"
        run_desktop "$DRY_RUN"
        ;;
    release)
        parse_args "$@"
        invoke_release "$RELEASE_ARG" "$DRY_RUN"
        ;;
    help|*)
        usage
        ;;
 esac
