#!/usr/bin/env bash
# Push every agent directory. Code agents start their image build on push.
#   ./scripts/push_all.sh eval
set -euo pipefail
PROFILE="${1:?profile name (e.g. eval)}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
AGENTS=(00_hello reviewer_claude reviewer_crewai reviewer_autogen reviewer_langgraph reviewer_pydantic_ai)
for a in "${AGENTS[@]}"; do
  echo "==> ${a}"
  ( cd "${ROOT}/agents/${a}" && wax -p "${PROFILE}" push )
done
echo
echo "Builds (code agents): wax -p ${PROFILE} agents builds reviewer_langgraph ; wax -p ${PROFILE} agents builds reviewer_pydantic_ai"
