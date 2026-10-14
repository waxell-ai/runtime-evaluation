#!/usr/bin/env python3
"""One table for the whole evaluation: per agent, the latest run, where it ran,
what it cost, how many domain calls hit your server and whether the identity
headers verified.

    python3 scripts/verify.py --profile eval
    python3 scripts/verify.py --profile eval --json

Reads runs through the `wax` CLI (JSON output) and calls through the domain
server's /api/calls. Stdlib only.
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


def wax_json(profile: str, *args: str) -> dict | list | None:
    try:
        out = subprocess.run(
            ["wax", "-p", profile, *args, "--format", "json"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        return (
            json.loads(out.stdout)
            if out.stdout.strip().startswith(("{", "["))
            else None
        )
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def latest_run(profile: str, agent: str) -> dict:
    data = wax_json(profile, "runs", "list", "--agent", agent, "--limit", "1")
    runs = data.get("runs") if isinstance(data, dict) else data
    return (runs or [{}])[0] if isinstance(runs, list) else {}


def calls(local_url: str) -> list[dict]:
    try:
        with urllib.request.urlopen(f"{local_url}/api/calls?limit=200", timeout=5) as r:
            return json.load(r).get("calls", [])
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
        run = latest_run(a.profile, agent) or {}
        ctx = run.get("context") or {}
        meta = run.get("metadata") or {}
        axid = (meta.get("axid") or {}).get("sub", "")
        mine = (
            [c for c in all_calls if (c.get("axid") or {}).get("sub") == axid]
            if axid
            else []
        )
        verified = sum(1 for c in mine if c.get("identity_verified"))
        rows.append(
            {
                "agent": agent,
                "run_id": run.get("id") or run.get("run_id") or "",
                "status": run.get("status") or "—",
                "ran_on": ctx.get("execution")
                or meta.get("runtime_disposition")
                or ("shared" if run else "—"),
                "cost_usd": ctx.get("rollup_cost") or 0,
                "tokens": ctx.get("rollup_tokens") or 0,
                "domain_calls": len(mine),
                "identity_verified": f"{verified}/{len(mine)}" if mine else "—",
                "axid": axid[:18] + ("…" if len(axid) > 18 else ""),
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
