#!/usr/bin/env bash
# Fire every reviewer once, as the same end user, and print the run ids.
#   ./scripts/fire_all.sh eval
# Then: python3 scripts/verify.py --profile eval
set -euo pipefail
PROFILE="${1:?profile name (e.g. eval)}"
USER_JSON='{"sub_user_id": "u_42", "email": "ada@example.com", "display_name": "Ada", "roles": ["reviewer"]}'
BODY='Added export to CSV, fixed timezone bug in reports, deprecated the v1 API. Known issue: the CSV export truncates fields over 32k characters.'

fire() {  # signal, payload
  echo "==> $1"
  wax -p "${PROFILE}" signals fire "$1" --payload "$2" || true
  echo
}

fire review_claude      "{\"thing_id\": \"thing-001\", \"_sub_user_identity\": ${USER_JSON}}"
fire review_crewai      "{\"thing_id\": \"thing-002\", \"_sub_user_identity\": ${USER_JSON}}"
fire review_autogen     "{\"thing_id\": \"thing-003\", \"_sub_user_identity\": ${USER_JSON}}"
fire review_langgraph   "{\"thing_id\": \"thing-001\", \"title\": \"Release notes 2.4\", \"body\": \"${BODY}\", \"_sub_user_identity\": ${USER_JSON}}"
fire review_pydantic_ai "{\"prompt\": \"Title: Release notes 2.4\\nBody: ${BODY}\", \"_sub_user_identity\": ${USER_JSON}}"

echo "Follow any run:  wax -p ${PROFILE} runs show <run_id>"
echo "All of them:     python3 scripts/verify.py --profile ${PROFILE}"
