#!/usr/bin/env bash
# Wipe the domain server's things + call log back to the three seeded things.
set -euo pipefail
curl -fsS -X POST "${EVAL_LOCAL_URL:-http://localhost:8030}/api/reset" && echo
