"""Every manifest loads, projects, and keeps the promises the README makes."""

from __future__ import annotations

import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFESTS = sorted((ROOT / "agents").glob("*/waxell.yaml"))
EXPECTED_FRAMEWORKS = {
    "claude_agent_sdk",
    "crewai",
    "autogen",
    "langgraph",
    "pydantic_ai",
}


def _load(path):
    from waxell_sdk.manifest import load_manifest, to_registry_artifacts

    m = load_manifest(path)
    return m, to_registry_artifacts(m, root_dir=path.parent)


def test_seven_agents_five_frameworks():
    assert len(MANIFESTS) == 7, [
        p.parent.name for p in MANIFESTS
    ]  # six agents + team_seed
    frameworks = set()
    for p in MANIFESTS:
        m, _ = _load(p)
        for a in m.agents:
            frameworks.add(a.framework)
    assert frameworks == EXPECTED_FRAMEWORKS


def test_signals_are_unique_across_agents():
    seen = {}
    for p in MANIFESTS:
        _, arts = _load(p)
        for art in arts:
            for sig in art["spec"].get("signals") or []:
                name = sig["name"]
                assert name not in seen, (
                    f"signal {name} declared by {seen[name]} and {p.parent.name}"
                )
                seen[name] = p.parent.name


@pytest.mark.parametrize("path", MANIFESTS, ids=[p.parent.name for p in MANIFESTS])
def test_manifest_shape(path):
    m, arts = _load(path)
    [art] = arts
    spec = art["spec"]
    agent = m.agents[0]
    is_code = bool(agent.entrypoint and ":" in agent.entrypoint)
    # Declarative agents name their model in the manifest, provider-prefixed and
    # Anthropic; code agents name it in code (and go through the Anthropic proxy).
    model = spec.get("model") or next(
        (a.get("model") for a in (spec.get("agents") or []) if isinstance(a, dict)), ""
    )
    if not is_code:
        assert model.startswith("anthropic:"), (
            f"{path}: model {model!r} must be anthropic:<id>"
        )
    # prompt file resolves
    if agent.system_prompt_file:
        assert (path.parent / agent.system_prompt_file).resolve().exists()
        assert spec.get("system_prompt"), "system_prompt_file did not load"
    # python pin, when present, is the published base
    deps = spec.get("dependencies") or {}
    if deps.get("python"):
        assert deps["python"] == "3.11"
    # code agents: entrypoint has a colon, source dir exists and has the module
    if is_code:
        assert spec["execution"]["mode"] == "isolated"
        module = agent.entrypoint.split(":")[0].replace(".", "/") + ".py"
        assert (path.parent / agent.source / module).exists(), (
            f"{module} missing under {agent.source}"
        )
        files = art["framework_extension"]["waxell"]["source_files"]
        assert module in files
        assert deps.get("pip"), "a code agent must declare its pip dependencies"
    # every agent declares at least one signal with a schema
    assert spec.get("signals"), f"{path}: no signals"


REVIEWERS_WITH_MEMORY = ("reviewer_claude", "reviewer_crewai", "reviewer_autogen")


def test_memory_slots_tell_the_story_the_readme_tells():
    """Three declarative reviewers, the SAME four slots: episodic recent_reviews,
    semantic style_rules, graph things (read_write), graph team (read). team_seed
    is the only writer of team. The code agents (langgraph / pydantic_ai) carry
    none — their source never calls a tool, by design."""
    specs = {}
    for p in MANIFESTS:
        _, arts = _load(p)
        for art in arts:
            specs[art["name"]] = art["spec"]
    expected = {
        "recent_reviews": ("episodic", None, None),
        "style_rules": ("semantic", None, None),
        "things": ("graph", "things", "read_write"),
        "team": ("graph", "team", "read"),
    }
    for name in REVIEWERS_WITH_MEMORY:
        mem = specs[name].get("memory") or {}
        assert set(mem) == set(expected), (name, sorted(mem))
        for slot, (tier, graph, access) in expected.items():
            assert mem[slot]["tier"] == tier, (name, slot)
            if graph:
                assert mem[slot]["graph_name"] == graph, (name, slot)
                assert mem[slot]["graph_access"] == access, (name, slot)
    seed = specs["team_seed"]["memory"]
    assert set(seed) == {"team"} and seed["team"]["graph_access"] == "write"
    for name in ("reviewer_langgraph", "reviewer_pydantic_ai", "hello"):
        assert not specs[name].get("memory"), name
