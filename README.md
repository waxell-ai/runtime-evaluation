# Waxell Runtime — evaluation project

Everything you need to decide whether the Waxell runtime should run your agents,
in about forty minutes at a terminal (plus a few minutes of image build
that runs in the background). You will push the same reviewer agent five
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
| `agents/reviewer_prompt.md` | The one prompt every declarative reviewer shares — including how it uses its memory. |
| `agents/team_seed/` | Writes the `team` graph once, in step 3. The reviewers can only read it: two graphs, two grants, one workspace (step 11). |
| `domains/things.yaml` | The domain contract — how agents reach your system. Every field commented. |
| `domain_server/` | FastAPI + SQLite stand-in for your system of record. Serves the domain, verifies both identity headers, logs every call — and a live page at **http://localhost:8030/** that shows it all happening (one HTML file, no build). |
| `identity/node/` | Zero-dependency Node verifiers for both headers (`node:crypto` only) with tests. |
| `policies/block_publish.py` | A policy as code that blocks `things/publish` before it leaves the runtime (`unblock_publish.py` turns it off again). |
| `scenarios/eval_path.py` | `wax test` scenarios that fire the agents through the real API and assert on the trace. |
| `scripts/` | preflight, tunnel URL, push all, fire all, one verification table, reset. |
| `tests/` | Anti-rot: every `wax` command in this repo exists in the installed CLI; every manifest loads. `make test` runs them against whatever `waxell` you have installed. |

## 0. Setup (5 min)

You need: Python 3.11+, Docker with Compose v2 (`docker compose`), Node 18+,
port 8030 free, and a Waxell workspace with the Runtime product enabled (sign
up at https://waxell.ai, or use the one you were given). Create an API key in
the app under **Settings → API Keys**; the API URL is `https://api.waxell.dev`
unless you were given another.

```bash
pip install 'waxell>=0.1.9'
wax config init --profile eval          # prompts for the API URL and key; nothing stored in this repo
wax -p eval whoami
./scripts/preflight.sh eval
```

The agents call Anthropic models through Waxell's governed proxy. Store your key
once as a workspace secret; it never appears in a manifest or a container:

```bash
wax -p eval secrets set ANTHROPIC_API_KEY <your Anthropic key>
```

**You should see:** `whoami` prints your workspace; preflight is all ✓, with one
informational line saying `.env` is not created yet (that's step 3). Every
command in this walkthrough passes `-p eval`; run `wax config use eval` once and
you can drop it.

## 1. First agent: push, fire, stream (3 min)

```bash
cd agents/00_hello
wax -p eval push
wax -p eval signals fire hello_run --payload '{"prompt": "Say hello to the evaluator in one sentence."}' --stream
cd ../..
```

**You should see:** `Registered 1/1 artifact(s)`, then a `202` with a `run_id`,
then the run's events streaming live — a governance evaluation, the model call,
the result — and the run ends with the sentence (`success` in `wax -p eval runs`). Open the run in the app:
the span tree, tokens, cost, and the policy evaluations are all there.

This is also what `wax init` scaffolds for a new project. Push is idempotent;
re-pushing the same content is a no-op, changing content with the same
`version:` is a 409 that lists what changed.

## 2. The same thing over HTTP (2 min)

Signals are a plain `POST`. The 202 tells you where the run is.

```bash
export WAXELL_API_URL="$(wax -p eval axid show --format json | python3 -c 'import sys,json; print(json.load(sys.stdin)["jwks_url"].split("/api/")[0])')"
curl -sS -X POST "$WAXELL_API_URL/api/v1/signals/hello_run/" \
  -H "X-Wax-Key: <the API key from step 0>" -H "Content-Type: application/json" \
  -d '{"prompt": "Reply with exactly: READY"}' | python3 -m json.tool
```

**You should see:** a `202` with `{"status": "matched", "run_id": "5969", "poll_url": "/api/v1/observe/query/traces/detail/?trace_id=5969", "events_url": "/api/v1/runs/5969/events/", …}`.
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
wax -p eval axid show --format json      # jwks_url is https://<API host>/api/v1/tenants/<tenant id>/… — copy both into .env (WAXELL_API_URL, WAXELL_TENANT_ID)
docker compose up -d --build
open http://localhost:8030/              # the live page (xdg-open on Linux) — keep it on a second screen
./scripts/tunnel_url.sh --write          # prints https://<random>.trycloudflare.com/api and writes it into .env
./domains/push_domains.sh eval
./scripts/tunnel_keepalive.sh eval       # in a SECOND terminal; leave it running (see below)
```

Push every agent now — the two code agents start their image builds (ready by
step 6) — and seed the `team` graph the reviewers read from:

```bash
./scripts/push_all.sh eval
wax -p eval signals fire team_seed --payload '{}' --wait
```

**You should see:** the live page's header pills read `server armed · verifying`
(`curl -s localhost:8030/api/health` says the same as JSON); `push_domains.sh` prints
`==> actions: get, list, set_review, add_note, publish` and
`==> per_user_auth_enabled: True`, then `Done.` (`"action": "updated"` instead of
`"created"` on a re-run). The agent pushes print `container image building` for
`reviewer_langgraph` and `reviewer_pydantic_ai`. `team_seed` finishes with
`graph.remember_batch · +7 entities, +4 relationships` and the **Graph Memory**
page (`/graph-memory`, graph `team`) shows three people owning four things.

**About the tunnel.** Cloudflare quick tunnels need no account, which is why
this uses one, but Cloudflare recycles them after roughly 25 minutes — shorter than this
walkthrough — and
`cloudflared` then retries the dead hostname instead of asking for a new one.
An agent that calls your domain in that state reports a DNS error.
`tunnel_keepalive.sh` probes the public URL every 20 s and, when it stops
answering, restarts the tunnel, writes the new hostname into `.env` and
re-pushes the domain (60 to 90 s; the new hostname is registered before the edge resolves it). If you would rather not run it, re-run
`tunnel_url.sh --write` and `push_domains.sh` yourself whenever a run reports
`Name or service not known`. If you have your own public endpoint or a named
tunnel, set `EVAL_DOMAIN_BASE_URL` to it and skip the quick tunnel entirely.

## 4. A reviewer that calls your system (3 min)

```bash
wax -p eval signals fire review_claude --payload '{"thing_id": "thing-001"}' --stream
curl -s localhost:8030/api/calls | python3 -m json.tool | head -60
curl -s localhost:8030/api/things/thing-001 | python3 -m json.tool
```

**You should see:** in the stream, the reviewer *remembers first* —
`memory.recall · 0 in recent_reviews`, `memory.search · 0 match in style_rules`,
`graph.recall · 1 in team` (the owner, Grace Hopper) — then `things__get`,
`things__set_review`, `things__add_note` (addressed to Grace) and, if it
recommends publishing, `things__publish`, each preceded by a governance
evaluation. At the end it *records*: `memory.remember · recent_reviews`,
`memory.remember · style_rules`, and `graph.remember_batch` into the
`things` graph — the thing itself; the person and the `reviewed_by` edge only
appear once a run acts for an end user (step 7). On the live page, three rows appear
as they happen — `things.get`, `things.set_review`, `things.add_note`, each
`by reviewer_claude` with a `run ↗` link into the app — and the thing-001 card
fills with the review and the note addressed to Grace. (`/api/calls` and
`/api/things/thing-001` are the same data as JSON.) Nothing in the payload asked for any of the memory
work; the agent's manifest declares four memory slots and its prompt says when
to use them (step 11 opens them up).

## 5. Five frameworks, one domain (3 min)

```bash
./scripts/fire_all.sh eval
python3 scripts/verify.py --profile eval
```

**You should see** (captured 2026-10-16, about 60 s after `fire_all.sh`):

```
agent                 run_id  status   ran_on    cost_usd  tokens  domain_calls  identity_verified  axid
--------------------  ------  -------  --------  --------  ------  ------------  -----------------  ----
hello                 5970    success  shared    0.0047    1036    0             —                  —
reviewer_claude       6006    success  shared    0.018     1202    3             3/3                …
reviewer_crewai       6007    success  shared    0.0213    4788    3             3/3                …
reviewer_autogen      6008    success  shared    0.0262    6578    3             3/3                …
reviewer_langgraph    6009    success  isolated  0.0035    340     0             —                  —
reviewer_pydantic_ai  6010    success  isolated  0.0054    1025    0             —                  —
```

The three declarative reviewers each made three calls to your server
(`things__get`, `things__set_review`, `things__add_note`), every one carrying
a sub-user token that verified against your workspace JWKS (`3/3`). Open
`reviewer_claude`'s run: its first event is `memory.recall · 1 in
recent_reviews` — it found the step-4 review of thing-001 and says so in its
summary — and `memory.search` now returns the style rule it saved then. All
three reviewers share the `things` graph (one graph, three writers) and read
the same `team` graph. The two
code agents ran in their own containers (`isolated`) and reviewed the text
they were handed; their source never calls the domain — that is the point of
step 6. If a code agent shows `shared (fallback: …)` its image is still
building; re-run after step 6. `axid` fills in once the workspace has agent
identity on (step 7). [FRAMEWORKS.md](./FRAMEWORKS.md) says exactly what
each framework honours.

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

**You should see:** on the live page every new row carries two green tags,
`✓ end user u_42` and `✓ AXID …`, the header pill's verified count matches its
call count (`12/12` if you ran step 5 — the pill counts every call so far),
and the **Acting for** panel decodes both: the person (`u_42 ada@example.com ·
reviewer`, audience `things`, bound to this run) and the agent identity
(`reviewer_autogen v1.x`, its `axid:` subject, `acting for u_42
(tenant_asserted)`, scope `domain:things.*`, and this call's `call.id` — a 60 s
token minted fresh per call). The note on the thing card is stamped with Ada's
email and the AXID. In JSON: `"end_user": {"sub": "u_42", …}`, `"axid": {"sub":
"axid:…", "agent": {…}, "act": {"sub": "u_42", …}, "call": {…}}`,
`"identity_verified": true`. The server also refused nothing — try it: edit
one character of a header value in a replayed request and it answers `401`.

Verify a header yourself, with Node and no dependencies. The server never
stores raw tokens; it keeps only the newest call's in memory and returns them
as `raw_headers` on `/api/calls/latest` (both expire within minutes):

```bash
cd identity/node && node --test && cd ../..
set -a; . ./.env; set +a                     # WAXELL_API_URL + WAXELL_TENANT_ID
curl -s localhost:8030/api/calls/latest | python3 -c 'import sys,json; print(json.load(sys.stdin)["raw_headers"]["x-waxell-sub-user-token"])' > /tmp/su.txt
node identity/node/cli.mjs sub-user @/tmp/su.txt --audience things
curl -s localhost:8030/api/calls/latest | python3 -c 'import sys,json; print(json.load(sys.stdin)["raw_headers"]["x-waxell-axid"])' > /tmp/axid.txt
node identity/node/cli.mjs axid @/tmp/axid.txt --domain things --action add_note
rm -f /tmp/su.txt /tmp/axid.txt
```

**You should see** (captured 2026-10-16) for the sub-user token:

```
{
  "valid": true,
  "kind": "sub-user",
  "jwks_url": "https://api.waxell.dev/api/v1/tenants/<tenant id>/.well-known/waxell-sub-user-jwks.json",
  "claims": {
    "sub": "u_42",
    "email": "ada@example.com",
    "roles": ["reviewer"],
    "aud": "things",
    "iat": 1792174402, "exp": 1792174702,
    "waxell_run_id": 6014,
    ...
  }
}
```

and `"valid": true, "kind": "axid"` with the `agent`, `act` and `call` claims
for the agent identity.

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

`thing-004` is a clean maintenance notice: a careful reviewer recommends
publishing it and so calls `things.publish`. The policy says reviewers never
publish.

```bash
wax -p eval policies push policies/block_publish.py --dry-run
wax -p eval policies push policies/block_publish.py
./scripts/reset.sh
wax -p eval signals fire review_autogen --payload '{"thing_id": "thing-004"}' --stream
curl -s 'localhost:8030/api/calls?limit=20' | python3 -c 'import sys,json; print([c["action"] for c in json.load(sys.stdin)["calls"]])'
```

**You should see:** the dry run lists `eval_block_publish (domain-governance)`
scoped to the three reviewers; the push prints `✓ Created: eval_block_publish`.
In the stream, `[governance] eval_block_publish` runs before every tool call
(`allow` for `things__get`, `things__set_review`, `things__add_note`), then the
model calls `things__publish` and the policy answers **block**: the run ends
`policy_blocked` (finish reason `policy_blocked_domain`) and your server's call list is
`['add_note', 'set_review', 'get']` — no `publish`. The block happened inside
the runtime; your endpoint was never asked. The live page says it plainly on
the thing-004 card: `publish` recommended at 0.82 confidence, then a red
**blocked in the runtime** strip — the one call that never arrived. `wax -p eval policies list` shows
the policy; the run's Governance tab shows the evaluation. Thing 001–003 are
deliberately flawed and get `revise`, so a reviewer never reaches `publish` on
them — use them to see the policy evaluate and allow.

## 9. Evaluations (2 min)

```bash
wax -p eval eval bootstrap --pack quality --agent reviewer_claude --judge-model claude-haiku
wax -p eval test scenarios/ --list
wax -p eval test scenarios/ --tag smoke
```

**You should see** (captured 2026-10-17):

```
Bootstrap 'quality'
Warn on low helpfulness, relevance, and format compliance.

Judge: Claude Haiku — key present

  evaluator Helpfulness  (created)
  evaluator Answer relevance  (created)
  evaluator Format compliance  (created)
  guardrail Guardrail: helpfulness  action=warn  (created, staged)
  guardrail Guardrail: relevance  action=warn  (created, staged)
  guardrail Guardrail: format_ok  action=warn  (created, staged)
! Guardrails are staged (disabled). Review the counterfactual, then re-run with --arm.
```

then four scenarios listed, and:

```
running 1 scenario(s) → /tmp/waxell-eval/20261017-143001/report.md
  (profile: eval)
  ▸ hello_answers  (autonomous)  → PASS · ✓ · 13.0s

1/1 scenarios passed
report: /tmp/waxell-eval/20261017-143001/report.md
uploaded → /api/v1/evals/runs/<id>/
```

The scenario fires `hello_run` through the real API, waits for the run and
asserts `run_completed_ok` and `latency<=120s`; the report names the run and
trace. Drop `--tag smoke` to run the reviewer scenarios too (a few minutes).
The upload puts the run on the workspace's Evaluations page. `wax test` honours
`-p eval` the same as every other command. `--judge-model claude-haiku` uses the
`ANTHROPIC_API_KEY` you stored in step 0; the default judge (`gpt-4o-mini`)
needs an `OPENAI_API_KEY` workspace secret instead.

## 10. Evidence (2 min)

```bash
wax -p eval compliance attest --period last_7_days -o attestation.json
wax -p eval compliance verify attestation.json
wax -p eval compliance pack --framework nist_ai_rmf --period last_7_days
wax -p eval compliance verify waxell-pack-nist_ai_rmf-last_7_days.zip
```

**You should see** (captured 2026-10-17): `✓ Wrote attestation.json (24,621
bytes)`; verify prints the computed and claimed SHA-256, `hash matches`, and
`Signer: att_… (EdDSA)` — the signature checked against your workspace's
attestation JWKS. The
pack is a zip of what an auditor asks for:

```
report.json  report.pdf  policies.jsonl  events.jsonl  framework-controls.csv
endpoint-decisions.jsonl  gateway-decisions.jsonl  redaction-proof.json
README.txt  manifest.json
```

and its `manifest.json` carries the same hash and signature. Everything you
just did is in it. Frameworks for `pack` are the governance catalog slugs
(`owasp_llm`, `nist_ai_rmf`, `iso_42001`, `eu_ai_act`, `hipaa`, `gdpr`, `sox`);
SOC 2 and ISO 27001 are control mappings on the Compliance page, not pack
frameworks.

## 11. Memory: four tiers, two graphs, one agent (4 min)

Every declarative reviewer declares four memory slots in its `waxell.yaml`
(`agents/reviewer_claude/waxell.yaml`, the block is commented) and has been
using them since step 4:

| Slot | Tier | Backing | What the reviewer keeps there |
|---|---|---|---|
| `recent_reviews` | episodic, list, 30 d | Postgres | thing, recommendation, reason — newest first |
| `style_rules` | semantic | pgvector | house rules it learned, found later **by meaning** — embedded by Waxell's bundled open-source model unless you point the slot at your own provider |
| `things` | graph, `read_write` | graph store | thing → `reviewed_by` → person, thing → `cites` → thing |
| `team` | graph, `read` | graph store | who owns what — written by `team_seed`, read-only here |

The runtime turns each slot into tools (`memory__recall__<slot>`,
`memory__remember__<slot>`, `memory__search__<slot>` for semantic,
`graph__recall__<slot>` / `graph__remember_*__<slot>` for graphs) and enforces
the grant before the backend is reached. Same tools on every framework; the
prompt decides when they are used. A graph is (workspace, name): declare as
many as you like, give each agent the grant it needs.

The semantic slot needs no key: with nothing configured the runtime embeds
with `BAAI/bge-small-en-v1.5` (MIT, 384 dims) on its own CPU, so nothing
about your facts leaves Waxell. To use your own embedding provider instead,
add it as a provider instance (`wax -p eval provider add openai_main
--from-catalog openai` — or `ollama`, `vllm`, `azure_openai`, …) and either leave it as the
workspace default or pin it on the slot with `embedding_provider: <instance_id>`
and `embedding_model:`. Each fact records which model embedded it, so a switch
never ranks vectors from two models together.

Step 8's policy is still on, and it ends any run that reaches `publish` before
the reviewer records its memory. Turn it off first, then fire the reviewer that
learned a rule in step 4 (`reviewer_claude`; each agent's semantic facts are
its own) at the one thing that cites another:

```bash
wax -p eval policies push policies/unblock_publish.py
wax -p eval signals fire review_claude --payload '{"thing_id": "thing-004", "_sub_user_identity": {"sub_user_id": "u_42", "email": "ada@example.com", "roles": ["reviewer"]}}' --stream
wax -p eval memory show reviewer_claude --slot recent_reviews
wax -p eval memory search reviewer_claude --slot style_rules --query "what makes a deprecation notice complete"
wax -p eval graph show things
wax -p eval graph show team
```

**You should see:** the stream opens with the three recalls (the search now
*finds* "a deprecation must name an end-of-life date and a migration path",
learned on thing-001, and the review of thing-004 cites it); `graph.recall · 1
in team` names Grace Hopper as the owner and the hand-off note is addressed to
her; the batch write records thing-004 `cites` thing-001 and `reviewed_by` Ada.
`memory show` lists the reviews newest first with the run that wrote each and
says what embeds `style_rules` (`embeds with bundled local model ·
BAAI/bge-small-en-v1.5 · 384 dims`); `memory search` ranks the deprecation
rule first with its similarity;
`graph show things` has every reviewed thing, the people, and the edges, each
node carrying provenance (which agent, which run, acting for whom);
`graph show team` is unchanged — and if you edit the reviewer's `team` slot to
`graph_access: read_write` and push, the next run *can* write it, which is the
point: the grant is the control, per agent, per graph. The Graph Memory page
shows both graphs with the provenance panel; `wax -p eval graph show things --format json`
is the same data for your own tooling.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `wax push` says `feature_gated` | The workspace does not have the Runtime product yet | Tell us; it is a flag on our side |
| A run fails with `SecretNotConfiguredError` / `No ANTHROPIC_API_KEY` | No model key in the workspace | `wax -p eval secrets set ANTHROPIC_API_KEY …` |
| `/api/calls` is empty after step 4 | Runtime cannot reach the tunnel, or the domain is registered with the old tunnel URL | `./scripts/tunnel_url.sh --write && ./domains/push_domains.sh eval` |
| A run's result says `Name or service not known` / `Connection error` for the domain | The quick tunnel was recycled by Cloudflare (about every 25 min) and the container is retrying the dead hostname | Keep `./scripts/tunnel_keepalive.sh eval` running (step 3); or `docker compose restart tunnel`, then `tunnel_url.sh --write` and `push_domains.sh eval` |
| Step 8 ends `error` with `messages.N.tool_calls: Extra inputs are not permitted` instead of `policy_blocked` | A workspace on a runtime older than 2026-10-17 | Tell us; the block still happened (no `publish` on your server) — only the run's final status is wrong |
| Step 11's stream ends at `things__publish` with no `memory.remember` | Step 8's policy is still on | `wax -p eval policies push policies/unblock_publish.py` |
| `"identity_verified": false` with a note about `WAXELL_TENANT_ID` | `.env` lacks the tenant id / API host | `wax -p eval axid show`, fill `.env`, `docker compose up -d` |
| Code agent run stays `pending` | Its image is still building | `wax -p eval agents builds <name>`; the run starts itself when ready |
| Code agent run `failed: custom_image_unavailable` | The build failed | `wax -p eval agents builds <name>` shows the error (usually a pip name); fix, bump `version:`, push |
| Push returns `409` | Same `version:`, different content | Bump `version:` in `waxell.yaml` |
| Push returns `400 invalid_agent_bundle` | A path, package name or python pin the runtime refuses | The response lists every problem |

## Reset

```bash
./scripts/reset.sh                 # the domain server back to the four seeded things, empty call log
./scripts/reset.sh eval --memory   # also every reviewer's memory slots and both graphs (operator action)
wax -p eval signals fire team_seed --payload '{}' --wait   # re-seed the team graph after --memory
```

Clearing memory is something you do (`wax memory forget`, `wax graph clear`);
no agent can wipe a graph — the reviewers hold read/write grants, not delete.

## License

MIT — see [LICENSE](./LICENSE).
