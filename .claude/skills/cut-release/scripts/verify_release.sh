#!/usr/bin/env bash
# Verify a cut release end-to-end: website repo, live site, and that the
# GitHub asset the website button serves is byte-identical in size to the
# locally signed MSI.
# Usage: verify_release.sh vX.Y.Z
set -u

TAG="${1:?usage: verify_release.sh vX.Y.Z}"
VER="${TAG#v}"
WEB=/home/valginer0/projects/PGVectorRAGIndexerWebsite
MSI=/mnt/c/Users/v_ale/Desktop/ToSign/PGVectorRAGIndexer-unsigned/PGVectorRAGIndexer.msi
FAIL=0

check() { # check <ok|FAIL|WARN> <message>
    local level="$1"; shift
    echo "[$level] $*"
    if [ "$level" = "FAIL" ]; then FAIL=1; fi
    return 0  # must not leak a falsy status into callers' `&& ... || ...`
}

# --- 1. website repo ---------------------------------------------------------
grep -q "releases/download/$TAG/PGVectorRAGIndexer\.msi" "$WEB/index.html" \
    && check ok "repo: MSI button href is $TAG" \
    || check FAIL "repo: index.html MSI href is NOT $TAG"

grep -q "Production Ready · $TAG" "$WEB/index.html" \
    && check ok "repo: hero shows $TAG" \
    || check FAIL "repo: hero 'Production Ready' badge is NOT $TAG"

grep -q "\"version\": \"$VER\"" "$WEB/package.json" \
    && check ok "repo: package.json is $VER" \
    || check FAIL "repo: package.json version is NOT $VER"

# Drift guard: any other x.y.z version strings in index.html that aren't $VER
STALE=$(grep -oE "v[0-9]+\.[0-9]+\.[0-9]+" "$WEB/index.html" | grep -v "^$TAG$" | sort -u)
[ -z "$STALE" ] && check ok "repo: no stale version strings in index.html" \
                || check WARN "repo: other version strings present (check hero/footer drift): $STALE"

# --- 2. live site --------------------------------------------------------------
LIVE=$(curl -fsSL --max-time 30 https://www.ragvault.net 2>/dev/null || true)
if [ -z "$LIVE" ]; then
    check FAIL "live: could not fetch https://www.ragvault.net"
else
    echo "$LIVE" | grep -q "releases/download/$TAG/PGVectorRAGIndexer\.msi" \
        && check ok "live: MSI button points at $TAG" \
        || check FAIL "live: MSI button NOT $TAG yet (deploy may still be running — recheck in a few minutes)"
    echo "$LIVE" | grep -q "$TAG" \
        && check ok "live: page shows $TAG" \
        || check FAIL "live: version string $TAG not on page yet"
fi

# --- 3. release asset vs signed file -------------------------------------------
if [ -f "$MSI" ]; then
    LOCAL_SIZE=$(stat -c%s "$MSI")
    CL=$(curl -sIL --max-time 60 \
        "https://github.com/valginer0/PGVectorRAGIndexer/releases/download/$TAG/PGVectorRAGIndexer.msi" \
        | tr -d '\r' | awk 'tolower($1)=="content-length:" {v=$2} END {print v}')
    if [ "$CL" = "$LOCAL_SIZE" ]; then
        check ok "asset: served Content-Length ($CL) == local signed MSI size"
    else
        check FAIL "asset: served Content-Length=$CL != local signed size=$LOCAL_SIZE (unsigned/stale asset?)"
    fi
else
    check FAIL "asset: signed MSI not found at $MSI"
fi

exit $FAIL
