#!/usr/bin/env bash
# Back to the start: the domain server's four seeded things and an empty call
# log; optionally the agents' memory too.
#
#   ./scripts/reset.sh                 # domain server only (what steps 4–8 need between runs)
#   ./scripts/reset.sh eval --memory   # also clear every reviewer's memory slots and both graphs
#
# Clearing memory is an operator action (`wax memory forget`, `wax graph clear`),
# never something an agent can do to itself — the reviewers hold read/write
# grants, not wipe. After --memory, fire team_seed again so the team graph is
# back before the next review.
set -euo pipefail
PROFILE="${1:-}"
curl -fsS -X POST "${EVAL_LOCAL_URL:-http://localhost:8030}/api/reset" && echo
if [ "${2:-}" = "--memory" ]; then
  [ -n "$PROFILE" ] || { echo "usage: reset.sh <profile> --memory" >&2; exit 1; }
  # needs the memory and graph commands (waxell 0.1.6+). Fail loudly, not silently.
  wax memory --help >/dev/null 2>&1 || { echo "this CLI has no memory commands — pip install -U waxell (0.1.6+)" >&2; exit 1; }
  for agent in reviewer_claude reviewer_crewai reviewer_autogen; do
    for slot in recent_reviews style_rules; do
      wax -p "$PROFILE" memory forget "$agent" --slot "$slot" --yes
    done
  done
  wax -p "$PROFILE" graph clear things --yes
  wax -p "$PROFILE" graph clear team --yes
  echo "memory cleared — run: wax -p $PROFILE signals fire team_seed --payload '{}' --wait"
fi
