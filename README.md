# Waxell Runtime — evaluation project

Everything you need to decide whether the Waxell runtime should run your agents,
in about thirty minutes at a terminal. You will push the same reviewer agent five
ways — Claude Agent SDK, CrewAI, AutoGen, and your own LangGraph and pydantic_ai
code running in their own containers — point them at a small domain server on
your laptop, and watch every call arrive with a verifiable end-user identity and
a verifiable agent identity. Then you will block an action with a policy, stand
up evaluations, and export the signed evidence.

Each step says what you should see. If you do not see it, stop and tell us: the
run id is the only thing we need.

```
your terminal ──wax push──▶ Waxell runtime ──signal──▶ governed run (any framework)
                                                            │ things__get / set_review / publish
                                                            ▼
                               Cloudflare tunnel ◀── X-Waxell-Sub-User-Token + X-Waxell-AXID
                                                            │
                                                  domain_server/ on your laptop
                                                  verifies both, logs every call: /api/calls
```

## What is in the box

| Path | What it is |
|---|---|
| `agents/00_hello/` | The first push. One agent, no domains. Push → fire → stream, in a minute. |
| `agents/reviewer_*/` | The same reviewer on `claude_agent_sdk`, `crewai`, `autogen` (declarative) and `langgraph`, `pydantic_ai` (your code, built into an image). See [FRAMEWORKS.md](./FRAMEWORKS.md). |
| `agents/reviewer_prompt.md` | The one prompt every declarative reviewer shares. |
| `domains/things.yaml` | The domain contract — how agents reach your system. Every field commented. |
| `domain_server/` | FastAPI + SQLite stand-in for your system of record. Serves the domain, verifies both identity headers, logs every call. |
| `identity/node/` | Zero-dependency Node verifiers for both headers (`node:crypto` only) with tests. |
| `policies/block_publish.py` | A policy as code that blocks `things/publish` before it leaves the runtime. |
| `scenarios/eval_path.py` | `wax test` scenarios that fire the agents through the real API and assert on the trace. |
| `scripts/` | preflight, tunnel URL, push all, fire all, one verification table, reset. |
| `tests/` | Anti-rot: every `wax` command in this repo exists in the installed CLI; every manifest loads. `make test` runs them against whatever `waxell` you have installed. |

## 0. Setup (5 min)

You need: Python 3.11+, Docker, Node 18+, and a Waxell workspace with the
Runtime product (sign up at https://waxell.ai, or use the one you were given)
plus an API key for it.

```bash
pip install waxell
wax config init --profile eval          # prompts for the API URL and key; nothing stored in this repo
wax -p eval whoami
./scripts/preflight.sh eval
```

The agents call Anthropic models through Waxell's governed proxy. Store your key
once as a workspace secret; it never appears in a manifest or a container:

```bash
wax -p eval secrets set ANTHROPIC_API_KEY <your Anthropic key>
```

**You should see:** `whoami` prints your workspace; preflight is all ✓ except the
two `.env` lines (next step).

## 1. First agent: push, fire, stream (3 min)

```bash
cd agents/00_hello
wax -p eval push
wax -p eval signals fire hello_run --payload '{"prompt": "Say hello to the evaluator in one sentence."}' --stream
cd ../..
```

**You should see:** `Registered 1/1 artifact(s)`, then a `202` with a `run_id`,
then the run's events streaming live — a governance evaluation, the model call,
the result — and `status: completed` with the sentence. Open the run in the app:
the span tree, tokens, cost, and the policy evaluations are all there.

This is also what `wax init` scaffolds for a new project. Push is idempotent;
re-pushing the same content is a no-op, changing content with the same
`version:` is a 409 that lists what changed.

## 2. The same thing over HTTP (2 min)

Signals are a plain `POST`. The 202 tells you where the run is.

```bash
export WAXELL_API_URL="$(wax -p eval axid show --format json | python3 -c 'import sys,json; print(json.load(sys.stdin)["jwks_url"].split("/api/")[0])')"
curl -sS -X POST "$WAXELL_API_URL/api/v1/signals/hello_run/" \
  -H "X-Wax-Key: <your workspace key>" -H "Content-Type: application/json" \
  -d '{"prompt": "Reply with exactly: READY"}' | python3 -m json.tool
```

**You should see:** `{"status": "accepted", "run_id": …, "poll_url": …, "events_url": …}`.
`curl` the `events_url` (same key) for the event list; add `/stream/` for SSE.
Send the same body twice with an `X-Idempotency-Key` header and the second
call returns `"status": "duplicate"` pointing at the first run.

## 3. Your system of record: the domain server + tunnel (5 min)

A **domain** is how an agent reaches your system: you register a contract
(`domains/things.yaml`), the runtime turns each action into a tool
(`things__get`, `things__set_review`, …), and every call is an HTTP POST from
Waxell to your endpoint. For the evaluation the endpoint runs on your laptop
behind a Cloudflare quick tunnel (no account needed).

```bash
cp env.example .env                      # set EVAL_DOMAIN_SHARED_SECRET to any long random string
wax -p eval axid show                    # copy the tenant id + API host into .env (WAXELL_TENANT_ID, WAXELL_API_URL)
docker compose up -d --build
./scripts/tunnel_url.sh --write          # prints https://<random>.trycloudflare.com/api and writes it into .env
./domains/push_domains.sh eval
```

Start the two code agents' image builds now so they are ready by step 6:

```bash
./scripts/push_all.sh eval
```

**You should see:** `curl -s localhost:8030/api/health` → `"domain_armed": true,
"identity_verification": true`; `wax -p eval domains show things` lists five
actions with per-user auth on; the pushes print `container image building` for
`reviewer_langgraph` and `reviewer_pydantic_ai`.

The tunnel hostname changes when the tunnel container restarts: re-run
`tunnel_url.sh --write` and `push_domains.sh` after a restart.

## 4. A reviewer that calls your system (3 min)

```bash
wax -p eval signals fire review_claude --payload '{"thing_id": "thing-001"}' --stream
curl -s localhost:8030/api/calls | python3 -m json.tool | head -60
curl -s localhost:8030/api/things/thing-001 | python3 -m json.tool
```

**You should see:** in the stream, `things__get`, `things__set_review`,
`things__add_note` and (if it recommends publishing) `things__publish`, each
preceded by a governance evaluation. On your server, one row per call in
`/api/calls` with the `X-Waxell-*` headers it received, and `thing-001` now
carries a review and a note.

## 5. Five frameworks, one domain (3 min)

```bash
./scripts/fire_all.sh eval
python3 scripts/verify.py --profile eval
```

**You should see:** a table with one row per agent — run id, status, where it
ran (`shared`, the SDK container, or `code` for your own containers), cost,
tokens, how many domain calls hit your server and how many verified. The two
code agents may show `pending` until their images finish building (step 6).
[FRAMEWORKS.md](./FRAMEWORKS.md) says exactly what each framework honours.

## 6. Your own code, in its own container (3 min)

`reviewer_langgraph` is a compiled `StateGraph` in `agents/reviewer_langgraph/src/graph.py`;
`reviewer_pydantic_ai` is a `pydantic_ai.Agent` in `agents/reviewer_pydantic_ai/src/agent.py`.
Neither imports anything from Waxell. `source:` + `entrypoint:` in their
manifests is the whole integration.

```bash
wax -p eval agents builds reviewer_langgraph
wax -p eval signals fire review_langgraph --payload '{"thing_id": "thing-001", "title": "Release notes 2.4", "body": "Added export to CSV, fixed timezone bug in reports, deprecated the v1 API."}' --stream
```

**You should see:** the build as `success` with its image; the run's events
`Running graph:app from the agent's image`, then `Entrypoint resolved to a
langgraph`, then the model call recorded by the proxy (tokens, cost), then the
review JSON as the result. If you fire before the build finishes, the run says
`Waiting for this agent's custom image…` and starts by itself when the image is
ready. Edit `graph.py`, bump `version:`, push again: the image rebuilds and the
next run executes your change.

## 7. Identity: who the person is, and what acted for them (4 min)

Start a run on behalf of a person by adding `_sub_user_identity` to the signal.
Every domain call then carries two signed headers your server verifies offline
against your workspace's public keys — no shared secret involved:

| Header | Says | Verify against |
|---|---|---|
| `X-Waxell-Sub-User-Token` | **who the person is** (`sub`, email, roles, `aud` = your domain) | `…/.well-known/waxell-sub-user-jwks.json` |
| `X-Waxell-AXID` | **what acted** — agent, version, run, the person (`act`), the parent run, and `call.id` for this exact request | `…/.well-known/axid-jwks.json` |

```bash
wax -p eval signals fire review_autogen --payload '{"thing_id": "thing-002", "_sub_user_identity": {"sub_user_id": "u_42", "email": "ada@example.com", "roles": ["reviewer"]}}' --stream
curl -s localhost:8030/api/calls/latest | python3 -m json.tool
```

**You should see:** `"end_user": {"sub": "u_42", "email": "ada@example.com", "aud": "things", "axid": "axid:…"}`,
`"axid": {"sub": "axid:…", "agent": {"name": "reviewer_autogen", …}, "act": {"sub": "u_42", …}, "call": {"id": …, "action": …}}`
and `"identity_verified": true`. The server also refused nothing — try it: edit
one character of a header value in a replayed request and it answers `401`.

Verify a header yourself, with Node and no dependencies:

```bash
cd identity/node && node --test && cd ../..
WAXELL_TENANT_ID=<tenant id> node identity/node/cli.mjs axid "<X-Waxell-AXID value from the server log>" --domain things --action get
```

And walk the agent identity back to everything it touched:

```bash
wax -p eval axid trace axid:<hex from the call>
```

**You should see:** the person, the agent and version, the run, every domain
call that presented this identity (with the `call_id` your server logged), the
lineage edge, and the person's activity entries. The same `sub` is on the run's
spans in the app. Docs: [end-user tokens](https://waxell.ai/docs/runtime/verify-end-user-tokens),
[agent identity](https://waxell.ai/docs/runtime/verify-agent-identity).

## 8. Governance: block an action before it happens (3 min)

```bash
wax -p eval policies push policies/block_publish.py --dry-run
wax -p eval policies push policies/block_publish.py
./scripts/reset.sh
wax -p eval signals fire review_autogen --payload '{"thing_id": "thing-001"}' --stream
curl -s 'localhost:8030/api/calls?limit=20' | python3 -c 'import sys,json; print([c["action"] for c in json.load(sys.stdin)["calls"]])'
```

**You should see:** the stream shows `things__get`, `things__set_review`,
`things__add_note`, then a `[governance]` event: `things/publish` **blocked** by
`eval_block_publish` — and your server's call list has no `publish`. The block
happened inside the runtime; your endpoint was never asked. `wax -p eval policies list`
shows the policy; the Governance page shows the evaluation.

## 9. Evaluations (2 min)

```bash
wax -p eval eval bootstrap --pack quality --agent reviewer_claude
wax -p eval test scenarios/ --list
wax -p eval test scenarios/ --profile eval --tag smoke
```

**You should see:** the bootstrap creates a quality evaluator and the guardrail
policies that go with it (staged, not armed); the scenario run fires
`hello_run` through the real API, waits for the run and asserts on the result.
Drop `--tag smoke` to run the reviewer scenarios too (they take a few minutes).

## 10. Evidence (2 min)

```bash
wax -p eval compliance attest --period last_7_days -o attestation.json
wax -p eval compliance verify attestation.json
wax -p eval compliance pack --framework soc2 --period last_7_days
```

**You should see:** a signed attestation of this window's runs and policy
evaluations, verified against your workspace's attestation JWKS, and a zip of the
evidence an auditor would ask for. Everything you just did is in it.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `wax push` says `feature_gated` | The workspace does not have the Runtime product yet | Tell us; it is a flag on our side |
| A run fails with `SecretNotConfiguredError` / `No ANTHROPIC_API_KEY` | No model key in the workspace | `wax -p eval secrets set ANTHROPIC_API_KEY …` |
| `/api/calls` is empty after step 4 | Runtime cannot reach the tunnel, or the domain is registered with the old tunnel URL | `./scripts/tunnel_url.sh --write && ./domains/push_domains.sh eval` |
| `"identity_verified": false` with a note about `WAXELL_TENANT_ID` | `.env` lacks the tenant id / API host | `wax -p eval axid show`, fill `.env`, `docker compose up -d` |
| Code agent run stays `pending` | Its image is still building | `wax -p eval agents builds <name>`; the run starts itself when ready |
| Code agent run `failed: custom_image_unavailable` | The build failed | `wax -p eval agents builds <name>` shows the error (usually a pip name); fix, bump `version:`, push |
| Push returns `409` | Same `version:`, different content | Bump `version:` in `waxell.yaml` |
| Push returns `400 invalid_agent_bundle` | A path, package name or python pin the runtime refuses | The response lists every problem |

## Reset

```bash
./scripts/reset.sh            # the domain server back to three seeded things, empty call log
```

## License

MIT — see [LICENSE](./LICENSE).
