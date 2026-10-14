"""Anti-rot: every `wax …` command this repo tells you to run must exist in
the installed `wax` CLI, with the options it uses. A README that teaches a
command the CLI does not have is the failure this file exists to catch.

Runs against whatever `waxell` is installed — a development build in Waxell's
own CI, or the PyPI release on your machine via `make test`.
"""

from __future__ import annotations

import pathlib
import re
import shlex

import click
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCES = [
    ROOT / "README.md",
    ROOT / "FRAMEWORKS.md",
    ROOT / "Makefile",
    *sorted((ROOT / "scripts").glob("*.sh")),
    *sorted((ROOT / "domains").glob("*.sh")),
    *sorted((ROOT / "agents").rglob("waxell.yaml")),
    *sorted((ROOT / "policies").glob("*.py")),
    *sorted((ROOT / "scenarios").glob("*.py")),
]

#: Commands and flags that appeared in earlier docs and do not exist.
BANNED = [
    r"\bwax\s+signals\s+send\b",
    r"\bwax\s+run\b",
    r"\bwax\s+agent\s+deploy\b",
    r"\bwax\s+profile\s+add\b",
    r"\bwax\s+metrics\b",
    r"\bwax\s+usage\s+show\b",
    r"--data\s",
    r"/tenants/<[^>]+>/\.well-known",  # root form 404s in prod; use /api/v1/
]

_PLACEHOLDER = re.compile(r"^<[^>]+>$|^\$\{?[A-Z_][A-Z0-9_]*\}?$|^\"\$|^'\$")


#: A `wax …` mention ends at a shell separator, a closing backtick/quote, or
#: a diagram glyph — so prose like "`wax push` uploads src/" yields "wax push".
_WAX_MENTION = re.compile(r"(?<![\w./-])wax\s+[^|;&)>#`\"'─▶\n]*")


def _wax_lines():
    for src in SOURCES:
        if not src.exists():
            continue
        for lineno, line in enumerate(src.read_text(encoding="utf-8").splitlines(), 1):
            for m in _WAX_MENTION.finditer(line):
                text = m.group(0).strip()
                if len(text.split()) >= 2:
                    yield src.name, lineno, text


def _cli():
    from waxell_sdk.cli import cli

    return cli


def _resolve(cli: click.Group, tokens: list[str]):
    """Walk the click tree; return (command, remaining tokens)."""
    cmd: click.Command = cli
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.startswith("-"):
            # global options like -p/--profile take a value
            if tok in ("-p", "--profile") and i + 1 < len(tokens):
                i += 2
                continue
            i += 1
            continue
        if isinstance(cmd, click.Group):
            sub = cmd.get_command(click.Context(cmd), tok)
            if sub is None:
                raise AssertionError(f"unknown subcommand {tok!r} under {cmd.name!r}")
            cmd = sub
            i += 1
            continue
        break
    return cmd, tokens[i:]


def test_sources_exist():
    assert (ROOT / "README.md").exists()


@pytest.mark.parametrize("src,lineno,text", list(_wax_lines()))
def test_every_wax_command_exists(src, lineno, text):
    try:
        tokens = shlex.split(text.replace("…", ""))
    except ValueError:
        tokens = text.split()
    tokens = [t for t in tokens[1:] if t and not t.startswith("$(")]
    if not tokens or tokens[0] in ("--version", "--help"):
        return
    cmd, rest = _resolve(_cli(), tokens)
    assert not isinstance(cmd, click.Group) or not rest, (
        f"{src}:{lineno}: {text!r} stops at a group"
    )
    valid_opts = {
        opt
        for p in cmd.params
        for opt in getattr(p, "opts", []) + getattr(p, "secondary_opts", [])
    }
    for tok in rest:
        if tok.startswith("--") and not _PLACEHOLDER.match(tok):
            name = tok.split("=", 1)[0]
            assert name in valid_opts, (
                f"{src}:{lineno}: {cmd.name!r} has no option {name!r} ({text!r})"
            )


def test_no_banned_commands():
    hits = []
    for src in SOURCES:
        if not src.exists():
            continue
        text = src.read_text(encoding="utf-8")
        for pat in BANNED:
            for m in re.finditer(pat, text):
                hits.append(f"{src.name}: {m.group(0)!r}")
    assert not hits, "\n".join(hits)
