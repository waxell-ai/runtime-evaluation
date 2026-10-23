"""The domain server's live page (http://localhost:8030/) stays truthful to the
API it polls and to the README that points at it.

Runs when the domain server's requirements are installed (CI installs them;
locally `pip install -r domain_server/requirements.txt`), skips otherwise.
"""

from __future__ import annotations

import importlib
import os
import re
import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "domain_server"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("EVAL_DB_PATH", str(tmp_path / "eval.sqlite"))
    monkeypatch.setenv("EVAL_DOMAIN_SHARED_SECRET", "test-shared-secret")
    monkeypatch.setenv("WAXELL_API_URL", "https://api.example.test")
    monkeypatch.setenv("WAXELL_TENANT_ID", "00000000-0000-0000-0000-000000000001")
    monkeypatch.setenv("WAXELL_APP_URL", "https://acme.example.test")
    monkeypatch.syspath_prepend(str(SERVER))
    for m in ("app", "identity", "axid"):
        sys.modules.pop(m, None)
    app_mod = importlib.import_module("app")
    from fastapi.testclient import TestClient

    with TestClient(app_mod.app) as c:
        yield c


def test_root_serves_the_live_page(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "Your system of record" in r.text
    assert "blocked in the runtime" in r.text  # the governance strip exists


def test_page_polls_only_endpoints_that_exist(client):
    html = (SERVER / "ui.html").read_text()
    fetched = set(re.findall(r"fetch\('(/api/[a-z/_-]+)", html))
    assert fetched == {"/api/calls", "/api/things", "/api/health"}
    for path in fetched:
        assert client.get(path).status_code == 200, path


def test_health_carries_what_the_header_pills_read(client):
    h = client.get("/api/health").json()
    assert h["domain_armed"] is True
    assert h["identity_verification"] is True
    assert h["app_url"] == "https://acme.example.test"


def test_things_carry_what_the_blocked_strip_derives_from(client):
    things = client.get("/api/things").json()["things"]
    assert [t["thing_id"] for t in things] == [
        "thing-001",
        "thing-002",
        "thing-003",
        "thing-004",
    ]
    t4 = next(t for t in things if t["thing_id"] == "thing-004")
    for key in ("status", "review", "notes", "changed_by_axid"):
        assert key in t4
    assert "thing-001" in t4["body"]  # the cites edge has something real to point at


def test_readme_points_at_the_page():
    readme = (ROOT / "README.md").read_text()
    assert "http://localhost:8030/" in readme
    assert "blocked in the runtime" in readme
    assert "WAXELL_APP_URL" in (ROOT / "env.example").read_text()


def test_docker_image_ships_the_page():
    dockerfile = (SERVER / "Dockerfile").read_text()
    assert "COPY . ." in dockerfile  # ui.html rides along with app.py
    assert (SERVER / "ui.html").exists()
    assert os.path.getsize(SERVER / "ui.html") < 64 * 1024  # one small file, no build
