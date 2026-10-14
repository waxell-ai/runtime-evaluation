"""The evaluation's domain server — a stand-in for YOUR system of record.

One FastAPI process, one SQLite file. It does three jobs:

1. **Serves the `things` domain** at ``POST /api/domains/things/<action>``.
   This is where Waxell delivers every ``things__<action>`` tool call an agent
   makes. Guarded by the shared secret from the domain contract.
2. **Verifies the identity headers** on each call — the end-user token
   (``X-Waxell-Sub-User-Token``) against your workspace's sub-user JWKS and the
   agent identity (``X-Waxell-AXID``) against the AXID JWKS — and refuses the
   call if either is present and invalid, or if the two disagree about which
   run acted for which person.
3. **Logs every call** with its headers and verified claims so you can look at
   what the runtime actually sent: ``GET /api/calls``.

Run it: ``docker compose up`` (starts a Cloudflare quick tunnel too, so the
hosted runtime can reach your laptop), or ``uvicorn app:app --port 8030``.
"""

from __future__ import annotations

import hmac
import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel

import axid as axid_mod
import identity

DB_PATH = Path(os.environ.get("EVAL_DB_PATH", "/data/eval.sqlite"))
SHARED_SECRET = os.environ.get("EVAL_DOMAIN_SHARED_SECRET", "")
WAXELL_API_URL = os.environ.get("WAXELL_API_URL", "").rstrip("/")
WAXELL_TENANT_ID = os.environ.get("WAXELL_TENANT_ID", "")
DOMAIN = "things"

#: Fixed ids so every command in the README pastes.
SEED = [
    (
        "thing-001",
        "Release notes 2.4",
        "Added export to CSV, fixed timezone bug in reports, deprecated the v1 API. "
        "Known issue: the CSV export truncates fields over 32k characters.",
    ),
    (
        "thing-002",
        "Customer email draft",
        "Hi team, as discussed we will ship on Friday regardless of the open P1. "
        "Please tell customers everything is on track.",
    ),
    ("thing-003", "Empty draft", ""),
]

app = FastAPI(title="runtime-evaluation domain server", version="1.0.0")


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


@contextmanager
def db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS things (
              id TEXT PRIMARY KEY, title TEXT, body TEXT, status TEXT,
              review_json TEXT DEFAULT '{}', notes_json TEXT DEFAULT '[]',
              changed_by_axid TEXT DEFAULT '', changed_by_call TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS calls (
              id TEXT PRIMARY KEY, ts REAL, domain TEXT, action TEXT,
              request_json TEXT, headers_json TEXT, status INTEGER,
              sub_user_json TEXT, axid_json TEXT, identity_ok INTEGER, identity_error TEXT
            );
            """
        )
        seed(conn)


def seed(conn: sqlite3.Connection) -> None:
    for tid, title, body in SEED:
        conn.execute(
            "INSERT OR IGNORE INTO things(id,title,body,status) VALUES (?,?,?,'draft')",
            (tid, title, body),
        )


def thing_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "thing_id": row["id"],
        "title": row["title"],
        "body": row["body"],
        "status": row["status"],
        "review": json.loads(row["review_json"] or "{}"),
        "notes": json.loads(row["notes_json"] or "[]"),
        "changed_by_axid": row["changed_by_axid"],
        "changed_by_call": row["changed_by_call"],
    }


@app.on_event("startup")
def _startup() -> None:
    init_db()


# ---------------------------------------------------------------------------
# Guards: shared secret (transport) + identity headers (who)
# ---------------------------------------------------------------------------


async def require_shared_secret(authorization: str = Header(default="")) -> None:
    if not SHARED_SECRET:
        raise HTTPException(503, "EVAL_DOMAIN_SHARED_SECRET unset — domain not armed")
    if not hmac.compare_digest(authorization or "", f"Bearer {SHARED_SECRET}"):
        raise HTTPException(401, "invalid domain credential")


WAXELL_HEADERS = (
    "x-waxell-workflow-id",
    "x-waxell-agent-name",
    "x-waxell-tenant-id",
    "x-waxell-sub-user-id",
    "x-waxell-sub-user-email",
    "x-waxell-sub-user-token",
    "x-waxell-axid",
    "x-correlation-id",
)


async def verify_identity(request: Request, action: str) -> dict[str, Any]:
    """Verify whichever identity headers are present. Returns what was found;
    raises 401 when a header is present but invalid, or the two disagree."""
    out: dict[str, Any] = {"sub_user": None, "axid": None, "ok": True, "error": ""}
    if not (WAXELL_API_URL and WAXELL_TENANT_ID):
        out["error"] = (
            "WAXELL_API_URL/WAXELL_TENANT_ID unset — headers logged, not verified"
        )
        out["ok"] = False
        return out
    su = request.headers.get("x-waxell-sub-user-token")
    ax = request.headers.get("x-waxell-axid")
    try:
        if su:
            out["sub_user"] = await identity.verify_header(
                su,
                url=identity.jwks_url(WAXELL_API_URL, WAXELL_TENANT_ID),
                expected_aud=DOMAIN,
            )
        if ax:
            out["axid"] = await axid_mod.verify_header(
                ax,
                url=axid_mod.jwks_url(WAXELL_API_URL, WAXELL_TENANT_ID),
                tenant_id=WAXELL_TENANT_ID,
                domain=DOMAIN,
                action=action,
            )
    except (identity.TokenError, axid_mod.AxidError) as exc:
        raise HTTPException(401, f"identity header rejected: {exc}") from exc
    # The two headers must tell the same story.
    if out["sub_user"] and out["axid"]:
        person_in_axid = ((out["axid"].get("act") or {}).get("sub")) or ""
        run_in_token = out["sub_user"].get("axid") or ""
        if person_in_axid and person_in_axid != out["sub_user"].get("sub"):
            raise HTTPException(
                401, "AXID act.sub does not match the end-user token sub"
            )
        if run_in_token and run_in_token != out["axid"].get("sub"):
            raise HTTPException(401, "end-user token axid does not match the AXID sub")
    return out


async def log_call(
    request: Request, action: str, body: dict, status: int, ident: dict
) -> str:
    call_id = ((ident.get("axid") or {}).get("call") or {}).get("id") or str(
        uuid.uuid4()
    )
    headers = {k: v for k, v in request.headers.items() if k.lower() in WAXELL_HEADERS}
    # never store the raw tokens
    for k in ("x-waxell-sub-user-token", "x-waxell-axid"):
        if k in headers:
            headers[k] = (
                f"<{len(headers[k])} chars, verified={bool(ident.get('sub_user' if 'sub' in k else 'axid'))}>"
            )
    with db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO calls VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                call_id,
                time.time(),
                DOMAIN,
                action,
                json.dumps(body),
                json.dumps(headers),
                status,
                json.dumps(ident.get("sub_user")),
                json.dumps(ident.get("axid")),
                1 if ident.get("ok") else 0,
                ident.get("error") or "",
            ),
        )
    return call_id


# ---------------------------------------------------------------------------
# The domain: POST /api/domains/things/<action>
# ---------------------------------------------------------------------------


class GetReq(BaseModel):
    thing_id: str


class ListReq(BaseModel):
    status: str | None = None
    limit: int = 100


class SetReviewReq(BaseModel):
    thing_id: str
    review: Any = None
    review_json: str | None = None


class AddNoteReq(BaseModel):
    thing_id: str
    text: str


class PublishReq(BaseModel):
    thing_id: str
    summary: str | None = None


def _load(conn: sqlite3.Connection, thing_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM things WHERE id=?", (thing_id,)).fetchone()
    if row is None:
        raise HTTPException(404, f"no thing {thing_id!r}")
    return row


def _stamp(ident: dict) -> tuple[str, str]:
    ax = ident.get("axid") or {}
    return str(ax.get("sub") or ""), str((ax.get("call") or {}).get("id") or "")


@app.post("/api/domains/things/get", dependencies=[Depends(require_shared_secret)])
async def things_get(req: GetReq, request: Request) -> dict:
    ident = await verify_identity(request, "get")
    with db() as conn:
        out = thing_dict(_load(conn, req.thing_id))
    await log_call(request, "get", req.model_dump(), 200, ident)
    return out


@app.post("/api/domains/things/list", dependencies=[Depends(require_shared_secret)])
async def things_list(req: ListReq, request: Request) -> dict:
    ident = await verify_identity(request, "list")
    with db() as conn:
        q = (
            "SELECT * FROM things"
            + (" WHERE status=?" if req.status else "")
            + " LIMIT ?"
        )
        args = (req.status, req.limit) if req.status else (req.limit,)
        rows = [thing_dict(r) for r in conn.execute(q, args).fetchall()]
    await log_call(request, "list", req.model_dump(), 200, ident)
    return {"count": len(rows), "things": rows}


@app.post(
    "/api/domains/things/set_review", dependencies=[Depends(require_shared_secret)]
)
async def things_set_review(req: SetReviewReq, request: Request) -> dict:
    ident = await verify_identity(request, "set_review")
    review = req.review if isinstance(req.review, dict) and req.review else None
    if review is None and req.review_json:
        try:
            review = json.loads(req.review_json)
        except ValueError:
            review = {"summary": req.review_json}
    review = review or {}
    by_axid, by_call = _stamp(ident)
    with db() as conn:
        _load(conn, req.thing_id)
        conn.execute(
            "UPDATE things SET review_json=?, status='in_review', changed_by_axid=?, changed_by_call=? WHERE id=?",
            (json.dumps(review), by_axid, by_call, req.thing_id),
        )
    await log_call(request, "set_review", req.model_dump(), 200, ident)
    return {"success": True, "thing_id": req.thing_id, "status": "in_review"}


@app.post("/api/domains/things/add_note", dependencies=[Depends(require_shared_secret)])
async def things_add_note(req: AddNoteReq, request: Request) -> dict:
    ident = await verify_identity(request, "add_note")
    by_axid, by_call = _stamp(ident)
    with db() as conn:
        row = _load(conn, req.thing_id)
        notes = json.loads(row["notes_json"] or "[]")
        notes.append(
            {
                "text": req.text,
                "by": ((ident.get("sub_user") or {}).get("email")) or "agent",
                "axid": by_axid,
                "ts": time.time(),
            }
        )
        conn.execute(
            "UPDATE things SET notes_json=?, changed_by_axid=?, changed_by_call=? WHERE id=?",
            (json.dumps(notes), by_axid, by_call, req.thing_id),
        )
    await log_call(request, "add_note", req.model_dump(), 200, ident)
    return {"success": True, "thing_id": req.thing_id, "notes": len(notes)}


@app.post("/api/domains/things/publish", dependencies=[Depends(require_shared_secret)])
async def things_publish(req: PublishReq, request: Request) -> dict:
    ident = await verify_identity(request, "publish")
    by_axid, by_call = _stamp(ident)
    with db() as conn:
        _load(conn, req.thing_id)
        conn.execute(
            "UPDATE things SET status='awaiting_approval', changed_by_axid=?, changed_by_call=? WHERE id=?",
            (by_axid, by_call, req.thing_id),
        )
    await log_call(request, "publish", req.model_dump(), 200, ident)
    return {"status": "awaiting_approval", "thing_id": req.thing_id}


# ---------------------------------------------------------------------------
# Evidence surface (no auth — it is your laptop)
# ---------------------------------------------------------------------------


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "domain_armed": bool(SHARED_SECRET),
        "identity_verification": bool(WAXELL_API_URL and WAXELL_TENANT_ID),
        "db": str(DB_PATH),
    }


@app.get("/api/things")
def list_things() -> dict:
    with db() as conn:
        rows = [thing_dict(r) for r in conn.execute("SELECT * FROM things").fetchall()]
    return {"count": len(rows), "things": rows}


@app.get("/api/things/{thing_id}")
def get_thing(thing_id: str) -> dict:
    with db() as conn:
        return thing_dict(_load(conn, thing_id))


def _call_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "call_id": row["id"],
        "ts": row["ts"],
        "domain": row["domain"],
        "action": row["action"],
        "request": json.loads(row["request_json"] or "{}"),
        "headers": json.loads(row["headers_json"] or "{}"),
        "status": row["status"],
        "end_user": json.loads(row["sub_user_json"] or "null"),
        "axid": json.loads(row["axid_json"] or "null"),
        "identity_verified": bool(row["identity_ok"]),
        "identity_note": row["identity_error"],
    }


@app.get("/api/calls")
def list_calls(limit: int = 50) -> dict:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM calls ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
    return {"count": len(rows), "calls": [_call_dict(r) for r in rows]}


@app.get("/api/calls/latest")
def latest_call() -> dict:
    with db() as conn:
        row = conn.execute("SELECT * FROM calls ORDER BY ts DESC LIMIT 1").fetchone()
    if row is None:
        raise HTTPException(
            404, "no calls yet — fire an agent that uses the things domain"
        )
    return _call_dict(row)


@app.post("/api/reset")
def reset() -> dict:
    with db() as conn:
        conn.execute("DELETE FROM calls")
        conn.execute("DELETE FROM things")
        seed(conn)
    return {"ok": True, "things": len(SEED)}
