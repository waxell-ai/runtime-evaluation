#!/usr/bin/env node
// Verify a header value from the command line.
//
//   WAXELL_API_URL=https://api.waxell.dev WAXELL_TENANT_ID=<uuid> \
//     node cli.mjs sub-user "<X-Waxell-Sub-User-Token value>" --audience things
//   node cli.mjs axid "<X-Waxell-AXID value>" --domain things --action publish
//
// Reads the JWKS from your workspace (cached nowhere — this is a CLI), verifies
// with node:crypto only, prints the claims as JSON. Exit 0 = valid.

import { readFileSync } from "node:fs";
import { axidJwksUrl, subUserJwksUrl, verifyAxid, verifySubUserToken } from "./verify.mjs";

const [, , kind, rawToken, ...rest] = process.argv;
const opts = {};
for (let i = 0; i < rest.length; i += 2) opts[rest[i].replace(/^--/, "")] = rest[i + 1];

if (!kind || !rawToken || !["sub-user", "axid"].includes(kind)) {
  console.error("usage: cli.mjs <sub-user|axid> <token|@file> [--audience D] [--domain D] [--action A] [--jwks-url URL]");
  process.exit(2);
}
const token = rawToken.startsWith("@") ? readFileSync(rawToken.slice(1), "utf8").trim() : rawToken;
const apiUrl = process.env.WAXELL_API_URL || "https://api.waxell.dev";
const tenantId = process.env.WAXELL_TENANT_ID || "";
const url = opts["jwks-url"] || (kind === "axid" ? axidJwksUrl(apiUrl, tenantId) : subUserJwksUrl(apiUrl, tenantId));
if (!tenantId && !opts["jwks-url"]) {
  console.error("set WAXELL_TENANT_ID (wax axid show prints it) or pass --jwks-url");
  process.exit(2);
}

const res = await fetch(url);
if (!res.ok) {
  console.error(`JWKS fetch failed: ${res.status} ${url}`);
  process.exit(1);
}
const jwks = await res.json();
try {
  const claims =
    kind === "axid"
      ? verifyAxid(token, jwks, { tenantId, domain: opts.domain, action: opts.action })
      : verifySubUserToken(token, jwks, { audience: opts.audience });
  console.log(JSON.stringify({ valid: true, kind, jwks_url: url, claims }, null, 2));
} catch (err) {
  console.log(JSON.stringify({ valid: false, kind, jwks_url: url, error: String(err.message || err) }, null, 2));
  process.exit(1);
}
