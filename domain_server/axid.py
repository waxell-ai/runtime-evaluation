"""Verify Waxell Agent Execution Identity (``X-Waxell-AXID``) — EdDSA JWT.

Header ``{"alg": "EdDSA", "typ": "axid+jwt", "kid": ...}``; keys from
``/api/v1/tenants/<id>/.well-known/axid-jwks.json``. The ``sub`` is the run's
durable identity, ``call.id`` is the domain call id Waxell records, ``act`` is
the person the run acts for. Public page:
https://waxell.ai/docs/runtime/verify-agent-identity
"""

from __future__ import annotations

import time
from typing import Any

import httpx
import jwt

_CACHE: dict[str, tuple[dict[str, Any], float]] = {}
_TTL = 600.0


class AxidError(ValueError):
    pass


def jwks_url(api_url: str, tenant_id: str) -> str:
    return (
        f"{api_url.rstrip('/')}/api/v1/tenants/{tenant_id}/.well-known/axid-jwks.json"
    )


def verify_axid(
    token: str,
    jwks: dict[str, Any],
    *,
    tenant_id: str,
    domain: str,
    action: str | None = None,
    leeway: int = 5,
) -> dict[str, Any]:
    """Verified claims or ``AxidError``. Pure: token + jwks + expectations."""
    try:
        header = jwt.get_unverified_header(token)
    except jwt.InvalidTokenError as exc:
        raise AxidError(f"malformed: {exc}") from exc
    if header.get("alg") != "EdDSA" or header.get("typ") != "axid+jwt":
        raise AxidError("not an AXID (alg/typ)")
    key = next(
        (k for k in jwks.get("keys", []) if k.get("kid") == header.get("kid")), None
    )
    if key is None:
        raise AxidError(f"unknown key id {header.get('kid')!r}")
    try:
        claims = jwt.decode(
            token,
            key=jwt.PyJWK(key).key,
            algorithms=["EdDSA"],
            audience=f"domain:{domain}",
            leeway=leeway,
        )
    except jwt.InvalidTokenError as exc:
        raise AxidError(f"invalid: {exc}") from exc
    if claims.get("tenant_id") != tenant_id:
        raise AxidError("wrong tenant")
    if action and (claims.get("call") or {}).get("action") != action:
        raise AxidError("token presented for a different action")
    return claims


async def fetch_jwks(url: str, *, force: bool = False) -> dict[str, Any]:
    cached = _CACHE.get(url)
    if cached and not force and time.time() < cached[1]:
        return cached[0]
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url)
    if resp.status_code != 200:
        raise AxidError(f"JWKS fetch failed ({resp.status_code}) from {url}")
    jwks = resp.json()
    _CACHE[url] = (jwks, time.time() + _TTL)
    return jwks


async def verify_header(
    token: str | None, *, url: str, tenant_id: str, domain: str, action: str
) -> dict[str, Any] | None:
    if not token:
        return None
    try:
        return verify_axid(
            token,
            await fetch_jwks(url),
            tenant_id=tenant_id,
            domain=domain,
            action=action,
        )
    except AxidError as exc:
        if "unknown key id" in str(exc):
            return verify_axid(
                token,
                await fetch_jwks(url, force=True),
                tenant_id=tenant_id,
                domain=domain,
                action=action,
            )
        raise
