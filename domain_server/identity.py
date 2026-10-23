"""Verify Waxell end-user tokens (``wax_su_v2_``) — Ed25519 + your workspace JWKS.

Format: ``wax_su_v2_<kid>.<payload_b64url>.<sig_b64url>``. The signature is
raw Ed25519 over the ASCII bytes of ``payload_b64url``. Keys come from
``/api/v1/tenants/<id>/.well-known/waxell-sub-user-jwks.json`` (``kty: OKP``,
``crv: Ed25519``). Public page: https://waxell.ai/docs/runtime/verify-end-user-tokens

``verify_token`` is pure (token + jwks + audience + now). ``verify_header``
fetches and caches the JWKS and refetches once on an unknown ``kid``.
"""

from __future__ import annotations

import base64
import json
import logging
import time
from typing import Any

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

logger = logging.getLogger(__name__)

PREFIX = "wax_su_v2_"
_CACHE: dict[str, tuple[dict[str, Any], float]] = {}
_TTL = 600.0


class TokenError(ValueError):
    pass


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def verify_token(
    token: str,
    jwks: dict[str, Any],
    *,
    expected_aud: str | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Return the verified claims or raise ``TokenError``."""
    if not token or not token.startswith(PREFIX):
        raise TokenError("not a wax_su_v2 token")
    try:
        kid, payload_b64, sig_b64 = token[len(PREFIX) :].split(".", 2)
    except ValueError as exc:
        raise TokenError("malformed token") from exc
    key = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)
    if key is None or key.get("kty") != "OKP" or key.get("crv") != "Ed25519":
        raise TokenError(f"unknown key id {kid!r}")
    try:
        Ed25519PublicKey.from_public_bytes(_b64d(key["x"])).verify(
            _b64d(sig_b64), payload_b64.encode("ascii")
        )
    except (InvalidSignature, ValueError) as exc:
        raise TokenError("bad signature") from exc
    try:
        claims = json.loads(_b64d(payload_b64).decode("utf-8"))
    except ValueError as exc:
        raise TokenError("payload is not JSON") from exc
    t = now if now is not None else time.time()
    if float(claims.get("exp") or 0) < t:
        raise TokenError("expired")
    if expected_aud is not None and claims.get("aud") != expected_aud:
        raise TokenError(f"audience {claims.get('aud')!r} is not {expected_aud!r}")
    return claims


def jwks_url(api_url: str, tenant_id: str) -> str:
    return f"{api_url.rstrip('/')}/api/v1/tenants/{tenant_id}/.well-known/waxell-sub-user-jwks.json"


async def fetch_jwks(url: str, *, force: bool = False) -> dict[str, Any]:
    cached = _CACHE.get(url)
    if cached and not force and time.time() < cached[1]:
        return cached[0]
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url)
    if resp.status_code != 200:
        raise TokenError(f"JWKS fetch failed ({resp.status_code}) from {url}")
    jwks = resp.json()
    _CACHE[url] = (jwks, time.time() + _TTL)
    return jwks


async def verify_header(
    token: str | None, *, url: str, expected_aud: str
) -> dict[str, Any] | None:
    """Claims for ``X-Waxell-Sub-User-Token`` or None when absent."""
    if not token:
        return None
    try:
        return verify_token(token, await fetch_jwks(url), expected_aud=expected_aud)
    except TokenError as exc:
        if "unknown key id" in str(exc):
            return verify_token(
                token, await fetch_jwks(url, force=True), expected_aud=expected_aud
            )
        raise
