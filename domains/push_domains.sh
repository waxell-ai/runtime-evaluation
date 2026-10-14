#!/usr/bin/env bash
# Register the things domain into your Waxell workspace.
#
#   EVAL_DOMAIN_SHARED_SECRET=... EVAL_DOMAIN_BASE_URL=https://<tunnel>.trycloudflare.com/api \
#     ./domains/push_domains.sh eval
#
# Both values come from your .env (scripts/tunnel_url.sh prints the base URL).
# The committed YAML carries placeholders; this substitutes them into a temp
# copy (deleted on exit) so the shared secret never lands in git.
set -euo pipefail

PROFILE="${1:?profile name (e.g. eval)}"
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "${HERE}/.." && pwd)"
[ -f "${ROOT}/.env" ] && set -a && . "${ROOT}/.env" && set +a

TOKEN="${EVAL_DOMAIN_SHARED_SECRET:-}"
BASE_URL="${EVAL_DOMAIN_BASE_URL:-}"
if [ -z "$TOKEN" ] || [ -z "$BASE_URL" ]; then
  echo "ERROR: set EVAL_DOMAIN_SHARED_SECRET and EVAL_DOMAIN_BASE_URL in .env (see env.example)" >&2
  exit 1
fi
case "$BASE_URL" in
  http://localhost*|http://127.0.0.1*)
    echo "ERROR: EVAL_DOMAIN_BASE_URL is a localhost URL — the hosted runtime cannot reach it." >&2
    echo "       Start the tunnel (docker compose up) and run scripts/tunnel_url.sh." >&2
    exit 1;;
esac

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
sed -e "s|__EVAL_DOMAIN_SHARED_SECRET__|${TOKEN}|" \
    -e "s|__EVAL_DOMAIN_BASE_URL__|${BASE_URL}|" \
    "${HERE}/things.yaml" > "${TMP}/things.yaml"

echo "==> registering domain 'things' → ${BASE_URL} (profile=${PROFILE})"
wax -p "${PROFILE}" push-domain "${TMP}/things.yaml" --change-summary "runtime-evaluation things domain"
echo "==> per-user auth: $(wax -p "${PROFILE}" domains show things 2>/dev/null | grep -i 'per_user' || echo 'see wax domains show things')"
echo "Done."
