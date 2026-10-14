#!/usr/bin/env bash
# Everything the 30-minute path needs, checked up front.
#   ./scripts/preflight.sh eval
set -uo pipefail
PROFILE="${1:-eval}"
ok=0; bad=0
pass() { echo "  ✓ $1"; ok=$((ok+1)); }
fail() { echo "  ✗ $1"; bad=$((bad+1)); }

echo "preflight (profile=${PROFILE})"
command -v wax >/dev/null 2>&1 && pass "wax $(wax --version 2>/dev/null | head -1)" || fail "CLI not installed — pip install waxell"
command -v docker >/dev/null 2>&1 && pass "docker" || fail "docker not found (needed for the domain server + tunnel)"
command -v node >/dev/null 2>&1 && pass "node $(node --version 2>/dev/null)" || fail "node not found (needed for identity/node; Node 18+)"
command -v python3 >/dev/null 2>&1 && pass "python3 $(python3 --version 2>/dev/null | cut -d' ' -f2)" || fail "python3 not found"

if wax -p "${PROFILE}" whoami >/dev/null 2>&1; then
  pass "profile '${PROFILE}' authenticates ($(wax -p "${PROFILE}" whoami 2>/dev/null | head -1))"
else
  fail "profile '${PROFILE}' cannot authenticate — wax config init --profile ${PROFILE}"
fi

if [ -f .env ]; then
  pass ".env present"
  grep -q '^EVAL_DOMAIN_SHARED_SECRET=change-me' .env && fail "EVAL_DOMAIN_SHARED_SECRET still the placeholder" || pass "EVAL_DOMAIN_SHARED_SECRET set"
  grep -q 'REPLACE-ME' .env && echo "  · EVAL_DOMAIN_BASE_URL not set yet (run scripts/tunnel_url.sh after docker compose up)" || pass "EVAL_DOMAIN_BASE_URL set"
else
  fail ".env missing — cp env.example .env"
fi

if wax -p "${PROFILE}" secrets list 2>/dev/null | grep -q ANTHROPIC_API_KEY; then
  pass "ANTHROPIC_API_KEY is a workspace secret"
else
  fail "ANTHROPIC_API_KEY not set — wax -p ${PROFILE} secrets set ANTHROPIC_API_KEY <your key>"
fi

echo
echo "${ok} ok, ${bad} to fix"
[ "$bad" -eq 0 ]
