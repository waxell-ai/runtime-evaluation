#!/usr/bin/env python3
"""One table for the whole evaluation: per agent, the latest run, where it ran,
what it cost, how many domain calls hit your server and whether the identity
headers verified.

    python3 scripts/verify.py --profile eval
    python3 scripts/verify.py --profile eval --json

Reads runs through the `wax` CLI (JSON output) and calls through the domain
server's /api/calls. Stdlib only.

Where each column comes from:
- run_id / status / cost / tokens: `wax runs list --agent <name> --limit 1`
  (its JSON is ``{"traces": [...]}``; cost and tokens are on the row).
- ran_on: `wax runs show <id>` span tree. The runtime records a
  ``execution.fallback`` span when an agent that asked for its own container
  ran on the shared runtime instead; no such span on an agent with
  ``entrypoint``/``dependencies`` means it ran isolated.
- domain_calls / identity_verified: rows in /api/calls made by this run —
  matched on the verified sub-user token's ``waxell_run_id`` claim (every
  path), else the ``X-Waxell-Workflow-Id`` header. identity_verified counts
  rows whose sub-user token verified against your workspace JWKS.
- axid: the ``X-Waxell-AXID`` subject your server recorded for those calls,
  when the workspace has agent identity on.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.request

AGENTS = [
    "hello",
    "reviewer_claude",
    "reviewer_crewai",
    "reviewer_autogen",
    "reviewer_langgraph",
    "reviewer_pydantic_ai",
]
# Agents the README pushes with their own container (entrypoint + dependencies).
ISOLATED = {"reviewer_langgraph", "reviewer_pydantic_ai"}


def wax_json(profile: str, *args: str) -> dict | list | None:
    try:
        out = subprocess.run(
            ["wax", "-p", profile, *args, "--format", "json"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        text = out.stdout.strip()
        return json.loads(text) if text.startswith(("{", "[")) else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def latest_run(profile: str, agent: str) -> dict:
    data = wax_json(profile, "runs", "list", "--agent", agent, "--limit", "5")
    rows = data.get("traces") or data.get("runs") if isinstance(data, dict) else data
    rows = [
        r for r in (rows or []) if r.get("agent_name") == agent
    ]  # --agent is a substring match
    return rows[0] if rows else {}


def run_detail(profile: str, run_id) -> dict:
    data = wax_json(profile, "runs", "show", str(run_id))
    return data if isinstance(data, dict) else {}


def _walk(node, out):
    out.append(node)
    for child in node.get("children") or []:
        _walk(child, out)


def ran_on(agent: str, detail: dict) -> str:
    spans: list[dict] = []
    tree = detail.get("span_tree")
    for node in tree if isinstance(tree, list) else ([tree] if tree else []):
        _walk(node, spans)
    fallback = next((s for s in spans if s.get("name") == "execution.fallback"), None)
    if fallback:
        reason = (fallback.get("attributes") or {}).get("execution_fallback_reason", "")
        return f"shared (fallback: {reason})" if reason else "shared (fallback)"
    if agent in ISOLATED:
        return "isolated"
    return "shared"


def _call_run_id(call: dict) -> str:
    """Which run made this call. The verified sub-user token carries the run id
    as ``waxell_run_id`` on every execution path; the ``X-Waxell-Workflow-Id``
    header is the run id on the Claude SDK path and the run's workflow UUID on
    the others, so the token claim is the join key and the header the fallback
    (a run fired without ``_sub_user_identity`` sends no token)."""
    end_user = call.get("end_user") or {}
    if isinstance(end_user, dict) and end_user.get("waxell_run_id"):
        return str(end_user["waxell_run_id"])
    return str((call.get("headers") or {}).get("x-waxell-workflow-id", ""))


def calls(local_url: str) -> list[dict]:
    try:
        with urllib.request.urlopen(f"{local_url}/api/calls?limit=500", timeout=5) as r:
            data = json.load(r)
            return data.get("calls", data) if isinstance(data, dict) else data
    except Exception:  # noqa: BLE001
        return []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="eval")
    ap.add_argument(
        "--local-url", default=os.environ.get("EVAL_LOCAL_URL", "http://localhost:8030")
    )
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    all_calls = calls(a.local_url)
    rows = []
    for agent in AGENTS:
        run = latest_run(a.profile, agent)
        run_id = run.get("id") or run.get("run_id") or ""
        detail = run_detail(a.profile, run_id) if run_id else {}
        mine = [c for c in all_calls if _call_run_id(c) == str(run_id)]
        verified = sum(1 for c in mine if c.get("identity_verified"))
        axids = {
            (c.get("axid") or {}).get("sub", "")
            if isinstance(c.get("axid"), dict)
            else (c.get("axid") or "")
            for c in mine
        } - {""}
        axid = next(iter(axids), "")
        rows.append(
            {
                "agent": agent,
                "run_id": run_id,
                "status": run.get("status") or "—",
                "ran_on": ran_on(agent, detail) if run_id else "—",
                "cost_usd": round(float(run.get("total_cost") or 0), 4),
                "tokens": run.get("total_tokens") or 0,
                "domain_calls": len(mine),
                "identity_verified": f"{verified}/{len(mine)}" if mine else "—",
                "axid": (axid[:18] + "…") if len(axid) > 18 else (axid or "—"),
            }
        )

    if a.json:
        print(json.dumps(rows, indent=2))
        return 0
    cols = [
        "agent",
        "run_id",
        "status",
        "ran_on",
        "cost_usd",
        "tokens",
        "domain_calls",
        "identity_verified",
        "axid",
    ]
    widths = {c: max(len(c), *(len(str(r[c])) for r in rows)) for c in cols}
    print("  ".join(c.ljust(widths[c]) for c in cols))
    print("  ".join("-" * widths[c] for c in cols))
    for r in rows:
        print("  ".join(str(r[c]).ljust(widths[c]) for c in cols))
    if not all_calls:
        print(
            "\n(no domain calls logged — is the domain server up and registered? see README step 3)"
        )
    elif not any(r["domain_calls"] for r in rows):
        print(
            "\n(calls were logged but none match these runs — the tunnel hostname may have"
            " changed since the domain was pushed: scripts/tunnel_url.sh --write && domains/push_domains.sh)"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
