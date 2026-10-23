// Verify the two identity headers Waxell sends your domain endpoint, with
// nothing but node:crypto (Node 18+). No jose, no jsonwebtoken.
//
//   X-Waxell-Sub-User-Token  wax_su_v2_<kid>.<payload_b64url>.<sig_b64url>
//                            raw Ed25519 over the ASCII bytes of payload_b64url
//                            (NOT a JWS — a JWT library will reject it)
//   X-Waxell-AXID            a compact JWS: EdDSA over "<header_b64url>.<payload_b64url>",
//                            header {alg: "EdDSA", typ: "axid+jwt", kid}
//
// Both key sets are Ed25519 JWKs ({kty: "OKP", crv: "Ed25519", x, kid}).
// Docs: https://waxell.ai/docs/runtime/verify-end-user-tokens
//       https://waxell.ai/docs/runtime/verify-agent-identity

import { createPublicKey, verify as cryptoVerify } from "node:crypto";

const SUB_USER_PREFIX = "wax_su_v2_";

export class IdentityError extends Error {}

function b64urlDecode(s) {
  return Buffer.from(s.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (s.length % 4)) % 4), "base64");
}

function keyFor(jwks, kid) {
  const jwk = (jwks.keys || []).find((k) => k.kid === kid);
  if (!jwk || jwk.kty !== "OKP" || jwk.crv !== "Ed25519") {
    throw new IdentityError(`unknown key id ${JSON.stringify(kid)}`);
  }
  return createPublicKey({ key: { kty: "OKP", crv: "Ed25519", x: jwk.x }, format: "jwk" });
}

/**
 * Verify an end-user token. Returns the claims or throws IdentityError.
 * @param {string} token      X-Waxell-Sub-User-Token
 * @param {object} jwks       the sub-user JWKS document
 * @param {object} [opts]     { audience: "things", now: seconds }
 */
export function verifySubUserToken(token, jwks, opts = {}) {
  if (!token || !token.startsWith(SUB_USER_PREFIX)) throw new IdentityError("not a wax_su_v2 token");
  const parts = token.slice(SUB_USER_PREFIX.length).split(".");
  if (parts.length !== 3) throw new IdentityError("malformed token");
  const [kid, payloadB64, sigB64] = parts;
  const key = keyFor(jwks, kid);
  const ok = cryptoVerify(null, Buffer.from(payloadB64, "ascii"), key, b64urlDecode(sigB64));
  if (!ok) throw new IdentityError("bad signature");
  let claims;
  try {
    claims = JSON.parse(b64urlDecode(payloadB64).toString("utf8"));
  } catch {
    throw new IdentityError("payload is not JSON");
  }
  const now = opts.now ?? Date.now() / 1000;
  if (Number(claims.exp || 0) < now) throw new IdentityError("expired");
  if (opts.audience !== undefined && claims.aud !== opts.audience) {
    throw new IdentityError(`audience ${JSON.stringify(claims.aud)} is not ${JSON.stringify(opts.audience)}`);
  }
  return claims;
}

/**
 * Verify an AXID (agent identity) header. Returns the claims or throws.
 * @param {string} token      X-Waxell-AXID
 * @param {object} jwks       the AXID JWKS document
 * @param {object} [opts]     { tenantId, domain: "things", action: "publish", now, leeway: 5 }
 */
export function verifyAxid(token, jwks, opts = {}) {
  const parts = (token || "").split(".");
  if (parts.length !== 3) throw new IdentityError("malformed AXID");
  const [headerB64, payloadB64, sigB64] = parts;
  let header;
  try {
    header = JSON.parse(b64urlDecode(headerB64).toString("utf8"));
  } catch {
    throw new IdentityError("header is not JSON");
  }
  if (header.alg !== "EdDSA" || header.typ !== "axid+jwt") throw new IdentityError("not an AXID (alg/typ)");
  const key = keyFor(jwks, header.kid);
  const ok = cryptoVerify(null, Buffer.from(`${headerB64}.${payloadB64}`, "ascii"), key, b64urlDecode(sigB64));
  if (!ok) throw new IdentityError("bad signature");
  const claims = JSON.parse(b64urlDecode(payloadB64).toString("utf8"));
  const now = opts.now ?? Date.now() / 1000;
  const leeway = opts.leeway ?? 5;
  if (Number(claims.exp || 0) + leeway < now) throw new IdentityError("expired");
  if (Number(claims.iat || 0) - leeway > now) throw new IdentityError("issued in the future");
  if (opts.tenantId && claims.tenant_id !== opts.tenantId) throw new IdentityError("wrong tenant");
  if (opts.domain) {
    const aud = Array.isArray(claims.aud) ? claims.aud : [claims.aud];
    if (!aud.includes(`domain:${opts.domain}`)) throw new IdentityError(`audience ${JSON.stringify(claims.aud)} lacks domain:${opts.domain}`);
  }
  if (opts.action && claims.call?.action !== opts.action) throw new IdentityError("token presented for a different action");
  return claims;
}

/**
 * The two headers must agree: the person in the AXID is the token's subject,
 * and the run in the token is the AXID's subject. Throws when they disagree.
 */
export function assertConsistent(subUserClaims, axidClaims) {
  if (!subUserClaims || !axidClaims) return;
  const personInAxid = axidClaims.act?.sub;
  if (personInAxid && personInAxid !== subUserClaims.sub) {
    throw new IdentityError("AXID act.sub does not match the end-user token sub");
  }
  if (subUserClaims.axid && subUserClaims.axid !== axidClaims.sub) {
    throw new IdentityError("end-user token axid does not match the AXID sub");
  }
}

export function subUserJwksUrl(apiUrl, tenantId) {
  return `${apiUrl.replace(/\/$/, "")}/api/v1/tenants/${tenantId}/.well-known/waxell-sub-user-jwks.json`;
}

export function axidJwksUrl(apiUrl, tenantId) {
  return `${apiUrl.replace(/\/$/, "")}/api/v1/tenants/${tenantId}/.well-known/axid-jwks.json`;
}
