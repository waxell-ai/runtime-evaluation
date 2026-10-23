# What each framework gets on the hosted runtime

Every agent in this repo is the same reviewer. The `framework:` value in its
`waxell.yaml` decides **how** it executes. There are two modes.

## Declarative — the runtime drives the agent from the manifest

`reviewer_claude`, `reviewer_crewai`, `reviewer_autogen`.

| Agent | `framework:` | What runs | Tools | Caps honoured |
|---|---|---|---|---|
| `reviewer_claude` | `claude_agent_sdk` | The **Claude Agent SDK** in its own container per run, driven by the manifest's prompt, model and caps. Waxell governs it from outside: every tool call is policy-checked before it executes. | Claude Code built-ins you list, plus every action of `domains: [things]` as `things__<action>` | `max_turns`, `max_budget_usd`, `timeout_seconds`, budget policies |
| `reviewer_crewai` | `crewai` | One **governed model ↔ tool loop** the runtime runs itself. The system prompt is built from the first agent's `role`/`goal`/`backstory` and the first task's `description`; the model comes from that agent. | `things__<action>` | budget policies, `timeout_seconds`, 8 model/tool rounds |
| `reviewer_autogen` | `autogen` | The same governed loop, from top-level `system_prompt` + `model`. | `things__<action>` | budget policies, `timeout_seconds`, 8 model/tool rounds |

What this means for an evaluation: the CrewAI and AutoGen manifests are
**descriptions** of the agent that the runtime honours — one agent, one task,
the declared tools. Multi-agent crews, graph edges and framework-specific
settings in those manifests are recorded, but the first agent/node is what
runs. A note in the run's event stream says so.

## From your code — the runtime runs your program in its own container

`reviewer_langgraph`, `reviewer_pydantic_ai`.

Add `source:` (your code) and `entrypoint: module:attr`. On push the runtime
copies the source, builds an image from `dependencies`, and each run executes
your entrypoint inside it as a child process with a minimal environment.

| Agent | Entrypoint resolves to | The runtime calls | Result |
|---|---|---|---|
| `reviewer_langgraph` | a compiled `StateGraph` (`app`) | `app.invoke(payload)` | the final state; the last message is the run's text |
| `reviewer_pydantic_ai` | a `pydantic_ai.Agent` (`reviewer`) | `reviewer.run_sync(payload["prompt"])` | `.output` (the `Review` model) |

The framework value is provenance here; dispatch follows what the entrypoint
*is*. A CrewAI `Crew` (`kickoff(inputs=…)`) or any callable works the same way.

Model calls: the container's `ANTHROPIC_BASE_URL` and `ANTHROPIC_API_KEY` point
at the run's governed proxy. `langchain-anthropic` and `pydantic-ai` go through
the official `anthropic` client, so they pick this up with no code change —
policy checks on the real prompts, tokens and cost on the run page, your real
key never in the container. **Code agents use Anthropic models**; the proxy
serves the Anthropic API.

Code agents do not call domains through the runtime in this release — they
show "your code, governed and observed". The domain and identity steps of the
README use the declarative agents.

While a code agent's image builds, a fired run **waits** (its event stream
says so) and starts when the build completes. If the build fails, the run
fails with the build error; it never silently runs something else.

## Shared by every agent

- **Signals** start runs: `POST /api/v1/signals/<name>/` with your workspace
  key, or `wax signals fire`. The 202 carries `run_id`, `poll_url`, `events_url`.
- **Events and trace**: `wax runs show <id>`, the live event stream, the span
  tree on the run page.
- **Identity**: a run started with `_sub_user_identity` carries the person;
  every domain call then presents the end-user token and the agent identity
  (AXID) — see the README's identity step.
- **Governance**: `before_workflow` / `after_workflow` policies evaluate on
  every run; domain-governance policies block domain actions before they leave
  the runtime (declarative agents).
- **Caps**: `timeout_seconds` (default 300, max 3600) on every run.

Reference: https://waxell.ai/docs/runtime/framework-support
