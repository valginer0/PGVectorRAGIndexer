#!/usr/bin/env bash
#
# smoke_team_setup.sh — one-command setup for the two-account Team-mode smoke test.
#
# Brings up the backend with enforced auth, installs a DISPOSABLE Team license,
# creates an admin account and a regular-user account, and prints both API keys
# so you can drive the desktop-app validation described in
# docs/ACCESS_CONTROL_GUIDE.md (§ Validating Team mode).
#
# This is a LOCAL VALIDATION tool, not CI or production:
#   - the license is a throwaway HS256 token signed with a random secret
#     (never your production RS256 signing key);
#   - auth is forced even for loopback so the on-box desktop app is treated
#     like a real remote client.
#
# Usage:
#   scripts/smoke_team_setup.sh            # set up
#   scripts/smoke_team_setup.sh --down     # tear down + wipe volumes
#
# Requirements: docker compose, and the project's venv for license generation
# (falls back to system python3 with PyJWT installed).

set -euo pipefail

cd "$(dirname "$0")/.."
PROJECT_DIR="$(pwd)"
# Isolated compose project + host ports so this never collides with a dev
# stack you may already be running (which uses :8000 / :5432).
SMOKE_API_PORT="${SMOKE_API_PORT:-8001}"
SMOKE_DB_PORT="${SMOKE_DB_PORT:-5433}"
export SMOKE_API_PORT SMOKE_DB_PORT
COMPOSE=(docker compose -p pgvrag_smoke -f docker-compose.yml -f docker-compose.smoke-team.yml)
BASE_URL="http://localhost:${SMOKE_API_PORT}"
LICENSE_DIR="${HOME}/.pgvector-license"

# Disposable secret reused across teardown/setup runs so a regenerated license
# still verifies against an already-running container if you re-run setup.
SECRET_FILE="${LICENSE_DIR}/.smoke_signing_secret"

log()  { printf '\033[1;34m[smoke]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[smoke]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[smoke] ERROR:\033[0m %s\n' "$*" >&2; exit 1; }

if [[ "${1:-}" == "--down" ]]; then
    log "Tearing down the isolated smoke stack and wiping its volumes..."
    LICENSE_SIGNING_SECRET="teardown" APP_IMAGE="${APP_IMAGE:-scratch}" \
        "${COMPOSE[@]}" down -v || true
    log "Done. (Left ${LICENSE_DIR} in place; delete it manually if you want.)"
    exit 0
fi

command -v docker >/dev/null || die "docker not found"

# --- 0. image to test ----------------------------------------------------
# The visibility/access-control fixes live on this branch, so released images
# won't have them. Build from the checkout unless the caller points APP_IMAGE
# at an image they already built from this branch.
if [[ -n "${APP_IMAGE:-}" ]]; then
    log "Using provided APP_IMAGE=${APP_IMAGE}"
else
    APP_IMAGE="pgvector-smoke:dev-v2"
    log "Building app image from the current checkout as ${APP_IMAGE} (one-time, can take several minutes)..."
    docker build -t "$APP_IMAGE" -f Dockerfile . \
        || die "docker build failed; fix the build or pass APP_IMAGE=<your dev/v2 image>"
fi
export APP_IMAGE

# --- python for license generation ---------------------------------------
PY="python3"
if [[ -x "${PROJECT_DIR}/venv/bin/python" ]]; then
    PY="${PROJECT_DIR}/venv/bin/python"
fi
"$PY" -c "import jwt" 2>/dev/null || die "PyJWT not available to ${PY}; activate the venv or 'pip install PyJWT'."

# --- 1. disposable signing secret + Team license -------------------------
mkdir -p "$LICENSE_DIR"
if [[ -f "$SECRET_FILE" ]]; then
    SECRET="$(cat "$SECRET_FILE")"
else
    SECRET="$("$PY" -c 'import secrets; print(secrets.token_hex(32))')"
    printf '%s' "$SECRET" > "$SECRET_FILE"
fi
export LICENSE_SIGNING_SECRET="$SECRET"

log "Generating a disposable Team license (HS256, 7 days, 5 seats)..."
"$PY" generate_license_key.py --secret "$SECRET" --edition team \
    --org "Smoke Test" --seats 5 --days 7 > "${LICENSE_DIR}/license.key"
[[ -s "${LICENSE_DIR}/license.key" ]] || die "license generation produced no token"

# --- 2. bring up the stack with enforced auth ----------------------------
log "Starting backend (auth enforced for all connections)..."
"${COMPOSE[@]}" up -d

log "Running database migrations..."
"${COMPOSE[@]}" run --rm app alembic upgrade head

# Install the license into the DB (server_settings) rather than relying on the
# file mount. On Rancher Desktop + WSL, bind-mounting a file from the Linux home
# into the container is unreliable, so the file-based license often doesn't load
# and the edition silently falls back to Community. Storing it in the DB is
# mount-independent and is how the in-app "Install license" flow persists it.
log "Installing Team license into the DB (mount-independent)..."
LICENSE_TOKEN="$(cat "${LICENSE_DIR}/license.key")"
"${COMPOSE[@]}" run --rm -T app python - "$LICENSE_TOKEN" <<'PY' || warn "License DB install failed; edition may be Community."
import sys
from license import validate_license_key, resolve_verification_context, load_all_licenses, reset_license, set_current_license
from server_settings_store import set_server_license_key
token = sys.argv[1]
secret, algs = resolve_verification_context()
validate_license_key(token, secret, algs)  # raises if invalid
set_server_license_key(token)
reset_license()
set_current_license(load_all_licenses())
PY

# Restart so the app loads the license + migrated schema cleanly.
log "Restarting app to load license + schema..."
"${COMPOSE[@]}" restart app

# Wait for the API to answer.
log "Waiting for the API to come up..."
for _ in $(seq 1 30); do
    if curl -fsS "${BASE_URL}/license" >/dev/null 2>&1; then break; fi
    sleep 2
done
curl -fsS "${BASE_URL}/license" >/dev/null 2>&1 || die "API did not come up at ${BASE_URL}"

# --- 3. create admin + regular user accounts (direct DB, no auth gating) --
log "Creating or refreshing admin and regular-user accounts..."
RESULT="$("${COMPOSE[@]}" run --rm -T app python - <<'PY'
import json
import auth
import users
from database import get_db_manager

admin_key = auth.create_api_key_record("smoke-admin")
alice_key = auth.create_api_key_record("smoke-alice")

def _role_or_user(role: str) -> str:
    return role if role in users._get_valid_roles() else "user"

def _upsert_smoke_user(email: str, role: str, api_key_id: int):
    """Create or relink a smoke user so rerunning this script prints usable keys."""
    with get_db_manager().get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO users (email, display_name, role, auth_provider, api_key_id, is_active)
            VALUES (%s, %s, %s, 'api_key', %s, true)
            ON CONFLICT (email) DO UPDATE SET
                display_name = COALESCE(users.display_name, EXCLUDED.display_name),
                role = EXCLUDED.role,
                auth_provider = 'api_key',
                api_key_id = EXCLUDED.api_key_id,
                is_active = true,
                updated_at = now()
            RETURNING id, email, role, api_key_id, is_active
            """,
            (email, email.split("@", 1)[0], _role_or_user(role), api_key_id),
        )
        row = cursor.fetchone()
        conn.commit()
        if not row:
            return None
        return {
            "id": row[0],
            "email": row[1],
            "role": row[2],
            "api_key_id": row[3],
            "is_active": row[4],
        }


admin_user = _upsert_smoke_user("admin@smoke.local", "admin", admin_key["id"])
# researcher: read + write + visibility, no admin. Fall back to the always-present
# system "user" role if a custom role isn't seeded in this environment.
alice_user = _upsert_smoke_user("alice@smoke.local", "researcher", alice_key["id"])

print("SMOKE_RESULT " + json.dumps({
    "admin_key": admin_key["key"],
    "alice_key": alice_key["key"],
    "admin_user_ok": bool(admin_user),
    "alice_user_ok": bool(alice_user),
}))
PY
)"

LINE="$(printf '%s\n' "$RESULT" | grep '^SMOKE_RESULT ' | tail -1 || true)"
[[ -n "$LINE" ]] || { printf '%s\n' "$RESULT"; die "account creation did not report a result"; }
JSON="${LINE#SMOKE_RESULT }"

ADMIN_KEY="$("$PY" -c "import sys,json;print(json.loads(sys.argv[1])['admin_key'])" "$JSON")"
ALICE_KEY="$("$PY" -c "import sys,json;print(json.loads(sys.argv[1])['alice_key'])" "$JSON")"
ADMIN_OK="$("$PY" -c "import sys,json;print(json.loads(sys.argv[1])['admin_user_ok'])" "$JSON")"
ALICE_OK="$("$PY" -c "import sys,json;print(json.loads(sys.argv[1])['alice_user_ok'])" "$JSON")"

[[ "$ADMIN_OK" == "True" ]] || warn "admin user was NOT linked — the admin key may not have admin rights."
[[ "$ALICE_OK" == "True" ]] || warn "regular user was NOT created — check valid roles."

# --- 4. confirm Team edition is active -----------------------------------
EDITION="$(curl -fsS "${BASE_URL}/license" 2>/dev/null || echo '{}')"
if printf '%s' "$EDITION" | grep -qi 'team'; then
    LICENSE_STATE="Team edition active ✔"
else
    LICENSE_STATE="WARNING: license did not register as Team — response: ${EDITION}"
fi

# --- 5. summary ----------------------------------------------------------
cat <<EOF

============================================================
  Team-mode smoke environment is ready.
============================================================
  Server URL : ${BASE_URL}
  License    : ${LICENSE_STATE}

  ADMIN key  : ${ADMIN_KEY}
  ALICE key  : ${ALICE_KEY}   (regular user — read/write/visibility, not admin)

  Next: open the desktop app, set the server URL above, and run the
  two-account checks in docs/ACCESS_CONTROL_GUIDE.md (§ Validating Team mode):
    1. Log in as ALICE  → upload a file → right-click → Make Private.
    2. Switch to ADMIN  → confirm you can see Alice's private doc;
       upload your own file → Make Private.
    3. Switch back to ALICE → confirm the admin's private doc is absent
       from Search, the Documents list, and the Tree; Alice's own is still there.

  Tear down when finished:
    scripts/smoke_team_setup.sh --down
============================================================
EOF
