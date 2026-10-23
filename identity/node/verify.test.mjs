// node --test  (Node 18+). Generates an Ed25519 pair, mints both header
// shapes the way Waxell does, and checks the verifier accepts the real thing
// and rejects the tampered, expired, wrong-audience and wrong-key cases.

import assert from "node:assert/strict";
import { generateKeyPairSync, sign as cryptoSign } from "node:crypto";
import { test } from "node:test";
import { assertConsistent, verifyAxid, verifySubUserToken } from "./verify.mjs";

function b64url(buf) {
  return Buffer.from(buf).toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function keypair(kid) {
  const { publicKey, privateKey } = generateKeyPairSync("ed25519");
  const jwk = { ...publicKey.export({ format: "jwk" }), kid, alg: "EdDSA", use: "sig" };
  return { privateKey, jwks: { keys: [jwk] } };
}

function mintSubUser(privateKey, kid, claims) {
  const payloadB64 = b64url(JSON.stringify(claims));
  const sig = cryptoSign(null, Buffer.from(payloadB64, "ascii"), privateKey);
  return `wax_su_v2_${kid}.${payloadB64}.${b64url(sig)}`;
}

function mintAxid(privateKey, kid, claims, typ = "axid+jwt") {
  const h = b64url(JSON.stringify({ alg: "EdDSA", typ, kid }));
  const p = b64url(JSON.stringify(claims));
  const sig = cryptoSign(null, Buffer.from(`${h}.${p}`, "ascii"), privateKey);
  return `${h}.${p}.${b64url(sig)}`;
}

const now = Math.floor(Date.now() / 1000);

test("end-user token: valid, audience checked, expiry checked, tamper rejected", () => {
  const { privateKey, jwks } = keypair("su-1");
  const claims = { sub: "u_42", email: "ada@example.com", aud: "things", exp: now + 300, axid: "axid:abc" };
  const t = mintSubUser(privateKey, "su-1", claims);
  assert.deepEqual(verifySubUserToken(t, jwks, { audience: "things" }).sub, "u_42");
  assert.throws(() => verifySubUserToken(t, jwks, { audience: "other" }), /audience/);
  assert.throws(() => verifySubUserToken(mintSubUser(privateKey, "su-1", { ...claims, exp: now - 1 }), jwks), /expired/);
  const tampered = t.slice(0, -2) + (t.endsWith("A") ? "B" : "A") + t.slice(-1);
  assert.throws(() => verifySubUserToken(tampered, jwks), /bad signature|malformed/);
  assert.throws(() => verifySubUserToken(t, keypair("su-1").jwks), /bad signature/);
  assert.throws(() => verifySubUserToken(t, { keys: [] }), /unknown key id/);
  assert.throws(() => verifySubUserToken("eyJ.not.a.wax.token", jwks), /not a wax_su_v2/);
});

test("AXID: valid, typ/alg enforced, domain audience, action, tenant, wrong key", () => {
  const { privateKey, jwks } = keypair("axid-1");
  const claims = {
    iss: "https://api.example/tenants/t1",
    aud: ["domain:things"],
    sub: "axid:abc",
    jti: "j1",
    iat: now,
    exp: now + 60,
    tenant_id: "t1",
    agent: { name: "reviewer", version: "1.0.0" },
    run: { id: "4471" },
    act: { sub: "u_42", assurance: "tenant_asserted" },
    call: { id: "call-1", domain: "things", action: "publish" },
    chain_depth: 1,
  };
  const t = mintAxid(privateKey, "axid-1", claims);
  const got = verifyAxid(t, jwks, { tenantId: "t1", domain: "things", action: "publish" });
  assert.equal(got.sub, "axid:abc");
  assert.equal(got.call.id, "call-1");
  assert.throws(() => verifyAxid(t, jwks, { tenantId: "t2" }), /wrong tenant/);
  assert.throws(() => verifyAxid(t, jwks, { domain: "crm" }), /lacks domain:crm/);
  assert.throws(() => verifyAxid(t, jwks, { action: "get" }), /different action/);
  assert.throws(() => verifyAxid(mintAxid(privateKey, "axid-1", claims, "JWT"), jwks), /not an AXID/);
  assert.throws(() => verifyAxid(mintAxid(privateKey, "axid-1", { ...claims, exp: now - 60 }), jwks), /expired/);
  assert.throws(() => verifyAxid(t, keypair("axid-1").jwks), /bad signature/);
});

test("the two headers must agree", () => {
  assertConsistent({ sub: "u_42", axid: "axid:abc" }, { sub: "axid:abc", act: { sub: "u_42" } });
  assert.throws(() => assertConsistent({ sub: "u_42", axid: "axid:abc" }, { sub: "axid:abc", act: { sub: "u_99" } }), /act.sub/);
  assert.throws(() => assertConsistent({ sub: "u_42", axid: "axid:zzz" }, { sub: "axid:abc", act: { sub: "u_42" } }), /axid does not match/);
  assertConsistent(null, { sub: "axid:abc" }); // one header alone is fine
});
