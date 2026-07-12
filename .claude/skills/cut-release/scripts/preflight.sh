#!/usr/bin/env bash
# Release preflight: fails loudly on anything release.sh would choke on.
# Usage: preflight.sh
set -u

MAIN=/home/valginer0/projects/PGVectorRAGIndexer
WEB=/home/valginer0/projects/PGVectorRAGIndexerWebsite
FAIL=0

check() { # check <ok|FAIL|WARN> <message>
    local level="$1"; shift
    echo "[$level] $*"
    if [ "$level" = "FAIL" ]; then FAIL=1; fi
    return 0  # must not leak a falsy status into callers' `&& ... || ...`
}

# --- main repo -------------------------------------------------------------
BR=$(git -C "$MAIN" branch --show-current)
[ "$BR" = "main" ] && check ok "main repo on main" \
                   || check FAIL "main repo on '$BR', not main"

git -C "$MAIN" fetch origin main -q
LR=$(git -C "$MAIN" rev-list --left-right --count origin/main...main)
[ "$LR" = "0	0" ] && check ok "main in sync with origin/main" \
                   || check FAIL "main vs origin/main (behind/ahead): $LR"

DIRTY=$(git -C "$MAIN" status --porcelain)
if [ -z "$DIRTY" ]; then
    check ok "main repo working tree clean"
else
    check FAIL "main repo not clean — release.sh will refuse:"
    echo "$DIRTY" | sed 's/^/        /'
fi

# --- website repo ------------------------------------------------------------
if [ -d "$WEB/.git" ]; then
    WBR=$(git -C "$WEB" branch --show-current)
    [ "$WBR" = "main" ] && check ok "website repo on main" \
                        || check FAIL "website repo on '$WBR' — release.sh silently skips website bump"
    WDIRTY=$(git -C "$WEB" status --porcelain)
    [ -z "$WDIRTY" ] && check ok "website repo clean" \
                     || { check FAIL "website repo not clean:"; echo "$WDIRTY" | sed 's/^/        /'; }
else
    check FAIL "website repo not found at $WEB"
fi

# --- docs/internal repo (separate private repo) -------------------------------
# SKILL.md later runs `git add -A` here for the version-bump side-effect commit;
# a dirty tree now would sweep unrelated internal changes into that commit.
DOCSINT="$MAIN/docs/internal"
if [ -d "$DOCSINT/.git" ]; then
    IDIRTY=$(git -C "$DOCSINT" status --porcelain)
    [ -z "$IDIRTY" ] && check ok "docs/internal repo clean" \
                     || { check FAIL "docs/internal repo not clean — 'git add -A' in the release side-effect commit would sweep these in:"; echo "$IDIRTY" | sed 's/^/        /'; }
else
    check FAIL "docs/internal repo not found at $DOCSINT"
fi

# --- tooling -----------------------------------------------------------------
gh auth status >/dev/null 2>&1 && check ok "gh authenticated" \
                               || check FAIL "gh auth status failed"
docker info >/dev/null 2>&1 && check ok "docker daemon reachable" \
                            || check FAIL "docker daemon not reachable (release.sh builds+pushes the image)"

# --- context ------------------------------------------------------------------
echo "[info] VERSION file : $(cat "$MAIN/VERSION")"
echo "[info] last tag     : $(git -C "$MAIN" describe --tags --abbrev=0 2>/dev/null || echo none)"

exit $FAIL
