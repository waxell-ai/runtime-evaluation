#!/usr/bin/env bash
# Print the public base URL of the Cloudflare quick tunnel started by docker
# compose, in the form the domain contract needs (…/api). Waits up to 60 s.
#   ./scripts/tunnel_url.sh            # prints https://xxxx.trycloudflare.com/api
#   ./scripts/tunnel_url.sh --write    # also writes EVAL_DOMAIN_BASE_URL into .env
set -euo pipefail
for _ in $(seq 1 30); do
  URL="$(docker compose logs tunnel 2>/dev/null | grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' | tail -1 || true)"
  [ -n "$URL" ] && break
  sleep 2
done
if [ -z "${URL:-}" ]; then
  echo "no tunnel URL yet — is 'docker compose up -d' running? (docker compose logs tunnel)" >&2
  exit 1
fi
echo "${URL}/api"
if [ "${1:-}" = "--write" ] && [ -f .env ]; then
  python3 - "$URL" <<'PY'
import re, sys
url = sys.argv[1] + "/api"
p = ".env"
s = open(p).read()
s = re.sub(r"^EVAL_DOMAIN_BASE_URL=.*$", f"EVAL_DOMAIN_BASE_URL={url}", s, flags=re.M)
open(p, "w").write(s)
print(f"wrote EVAL_DOMAIN_BASE_URL={url} to .env")
PY
fi
