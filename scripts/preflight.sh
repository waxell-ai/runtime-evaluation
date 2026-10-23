#!/usr/bin/env bash
# Everything the 30-minute path needs, checked up front.
#   ./scripts/preflight.sh eval
set -uo pipefail
PROFILE="${1:-eval}"
ok=0; bad=0
pass() { echo "  ✓ $1"; ok=$((ok+1)); }
fail() { echo "  ✗ $1"; bad=$((bad+1)); }

echo "preflight (profile=${PROFILE})"
MIN_WAX="0.1.9"   # needed for: the claude-haiku judge, and --wait / wax test ending on a blocked run
if command -v wax >/dev/null 2>&1; then
  WAX_V="$(wax --version 2>/dev/null | head -1 | awk '{print $NF}')"
  if python3 -c "import sys; a=tuple(map(int,'${WAX_V}'.split('.')[:3])); b=tuple(map(int,'${MIN_WAX}'.split('.'))); sys.exit(0 if a>=b else 1)" 2>/dev/null; then
    pass "CLI ${WAX_V}"
  else
    fail "CLI ${WAX_V:-?} is older than ${MIN_WAX} — pip install -U waxell"
  fi
else
  fail "CLI not installed — pip install waxell"
fi
command -v docker >/dev/null 2>&1 && pass "docker" || fail "docker not found (needed for the domain server + tunnel)"
command -v node >/dev/null 2>&1 && pass "node $(node --version 2>/dev/null)" || fail "node not found (needed for identity/node; Node 18+)"
command -v python3 >/dev/null 2>&1 && pass "python3 $(python3 --version 2>/dev/null | cut -d' ' -f2)" || fail "python3 not found"

if wax -p "${PROFILE}" whoami >/dev/null 2>&1; then
  # --json: the table form is a Rich panel whose first line is blank.
  WORKSPACE="$(wax -p "${PROFILE}" whoami --json 2>/dev/null | python3 -c 'import sys,json; t=json.load(sys.stdin).get("tenant",{}); print(t.get("slug") or t.get("name") or "")' 2>/dev/null)"
  pass "profile '${PROFILE}' authenticates (workspace: ${WORKSPACE:-?})"
else
  fail "profile '${PROFILE}' cannot authenticate — wax config init --profile ${PROFILE}"
fi

if [ -f .env ]; then
  pass ".env present"
  grep -q '^EVAL_DOMAIN_SHARED_SECRET=change-me' .env && fail "EVAL_DOMAIN_SHARED_SECRET still the placeholder" || pass "EVAL_DOMAIN_SHARED_SECRET set"
  grep -q 'REPLACE-ME' .env && echo "  · EVAL_DOMAIN_BASE_URL not set yet (run scripts/tunnel_url.sh after docker compose up)" || pass "EVAL_DOMAIN_BASE_URL set"
else
  echo "  · .env not created yet — that happens in step 3 (cp env.example .env)"
fi

# --format json: the table truncates long keys ("ANTHROPIC_A…"), so a grep on
# the table form fails on a correctly configured workspace.
if wax -p "${PROFILE}" secrets list --format json 2>/dev/null | grep -q '"key": *"ANTHROPIC_API_KEY"'; then
  pass "ANTHROPIC_API_KEY is a workspace secret"
else
  fail "ANTHROPIC_API_KEY not set — wax -p ${PROFILE} secrets set ANTHROPIC_API_KEY <your key>"
fi

echo
echo "${ok} ok, ${bad} to fix"
[ "$bad" -eq 0 ]
