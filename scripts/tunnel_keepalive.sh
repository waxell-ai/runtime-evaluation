#!/usr/bin/env bash
# Keep the quick tunnel usable for the whole evaluation.
#
#   ./scripts/tunnel_keepalive.sh eval        # leave running in a second terminal
#
# Cloudflare quick tunnels (no account) are recycled server-side after a while
# — in our rehearsal about every 25 minutes — and `cloudflared` then retries the
# dead tunnel forever ("Unauthorized: Tunnel not found") instead of requesting a
# new hostname. An agent that calls your domain during that window reports a
# DNS error. This loop probes the public health URL every 20 s and, when it
# stops answering, restarts the tunnel container, writes the new hostname into
# .env and re-pushes the domain contract so the next run routes correctly.
# Recovery takes 60-90 s (the new hostname is registered before the edge resolves it). Stop with Ctrl-C.
#
# Running the whole path inside 25 minutes without interruption works without
# this; it exists so a pause for coffee does not look like a product failure.
set -uo pipefail
PROFILE="${1:?profile name (e.g. eval)}"
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "${HERE}/.." && pwd)"
cd "${ROOT}"

current_url() {
  grep -E '^EVAL_DOMAIN_BASE_URL=' .env 2>/dev/null | cut -d= -f2-
}

echo "tunnel keepalive (profile=${PROFILE}) — Ctrl-C to stop"
while true; do
  URL="$(current_url)"
  if [ -n "$URL" ] && curl -fsS -m 15 -o /dev/null "${URL}/health" 2>/dev/null; then
    sleep 20
    continue
  fi
  echo "$(date -u +%H:%M:%S) tunnel at ${URL:-<unset>} is not answering — restarting"
  docker compose restart tunnel >/dev/null 2>&1 || true
  # the new hostname is the LAST one the container ever printed
  NEW=""
  for _ in $(seq 1 30); do
    NEW="$(docker compose logs tunnel 2>/dev/null | grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' | tail -1 || true)"
    [ -n "$NEW" ] && [ "${NEW}/api" != "$URL" ] && break
    sleep 2
  done
  if [ -z "$NEW" ]; then
    echo "  no new hostname yet; will retry"
    sleep 10
    continue
  fi
  "${HERE}/tunnel_url.sh" --write >/dev/null 2>&1 || true
  # the hostname is registered before Cloudflare's edge resolves it: 30-60 s
  UP=""
  for _ in $(seq 1 30); do
    curl -fsS -m 10 -o /dev/null "${NEW}/api/health" 2>/dev/null && UP=1 && break
    sleep 3
  done
  if [ -n "$UP" ]; then
    echo "  up at ${NEW}/api — re-registering the domain"
    "${ROOT}/domains/push_domains.sh" "${PROFILE}" | grep -E 'Pushed|version' | sed 's/^/  /'
  else
    echo "  ${NEW} registered but not answering yet; next probe will re-check"
  fi
  sleep 20
done
