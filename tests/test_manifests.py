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


def test_six_agents_five_frameworks():
    assert len(MANIFESTS) == 6, [p.parent.name for p in MANIFESTS]
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
