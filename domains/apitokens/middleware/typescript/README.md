# @arkhai/apitokens-middleware (TypeScript)

Seller-side gating middleware for the API-tokens domain — the
TypeScript sibling of the Python reference
(`../python`). It extracts the bearer key from the `Authorization`
header, verifies it against the tokens service (short-TTL cache), meters
each request by consuming credits (synchronously near exhaustion,
optionally batched above a low-balance threshold), and maps a drained
key to a 402 whose body carries a `purchase` pointer (the re-purchase
loop). All verification and accounting authority stays in the service.

The behavioral contract — status codes, machine-readable bodies, and
per-step service-call counts — is shared with the Python and Rust
middlewares and pinned by `../conformance/session.json`.

## Install

```sh
npm install @arkhai/apitokens-middleware
```

Requires Node ≥ 22.6 (per `engines`). The package is published with
[provenance](https://docs.npmjs.com/generating-provenance-statements).

## Use

Two framework-neutral bindings ship from the package root. Both gate
every request before it reaches the app and return a `402` with a
`purchase` pointer once a key is drained; `excludePaths` defaults to
`["/health"]`.

Connect/Express:

```ts
import express from "express";
import { tokenGateMiddleware, gateConfigFromEnv } from "@arkhai/apitokens-middleware";

const app = express();
app.use(tokenGateMiddleware({ config: gateConfigFromEnv() }));
// ... your routes
```

Web `fetch` handler (Workers, Deno, Bun, …):

```ts
import { withTokenGate, gateConfig } from "@arkhai/apitokens-middleware";

const fetchHandler = withTokenGate(
  { config: gateConfig({ serviceUrl: "http://localhost:8082", adminKey: process.env.ADMIN_KEY }) },
  async (_req) => Response.json({ ok: true }),
);
export default { fetch: fetchHandler };
```

`gateConfigFromEnv()` reads `APITOKENS_MIDDLEWARE_*` variables
(`SERVICE_URL`, `ADMIN_KEY`, `AMOUNT_PER_REQUEST`, the `PURCHASE_*`
pointer fields, …); `gateConfig({ serviceUrl, … })` takes the same
fields inline. All verification and accounting authority stays in the
tokens service — the gate only caches and meters.

## Layout

- `src/config.ts` — `GateConfig` / `PurchasePointer` (+ `gateConfigFromEnv`).
- `src/client.ts` — `TokensClient` over `fetch`, and the `TokensApi`
  interface the gate depends on.
- `src/gate.ts` — framework-neutral `TokenGate` (verify cache, balance
  estimate, batched-charge accumulator), `parseBearer`,
  `keyIdFromSecret`.
- `src/adapter.ts` — two bindings: a Connect/Express middleware
  (`tokenGateMiddleware`) and a Web `fetch` wrapper (`withTokenGate`).
  Neither imports a framework.

## Develop

Requires Node ≥ 22.6 (native TypeScript type-stripping; tests run `.ts`
directly).

```sh
npm install
npm run typecheck      # tsc --noEmit
npm test               # node --test over the conformance + gate suites
npm run check          # typecheck + test
npm run build          # emit dist/ (.js + .d.ts) for publishing
```

`test/conformanceRunner.ts` is the reference harness: it stands up an
in-process scripted tokens service (`test/scriptedService.ts`) and
drives the **real** `fetch` client against it, replaying
`../conformance/session.json` step for step and asserting the decision
plus the per-step verify/consume call counts — mirroring the Python
runner at the HTTP layer.
