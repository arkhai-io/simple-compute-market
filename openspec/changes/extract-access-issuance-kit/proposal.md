## Why

After `compose-inference-domain-stack`, the repository carries two copies of the
machinery that turns a verified settlement into an issued bearer credential: the
issuance client and its immutable request/result models, the deterministic
fulfillment identity and request digest, the fulfillment orchestration with its
rollback, and the signed secret-free evidence projection — once in
`domains/apicredits/settlement/` and once in `domains/inference/`. The bearer
gate's outbound client and signing are duplicated the same way.

Goal 4's rule is that an extracted concern leaves no domain-local copy. This
change is that extraction, done now because two consumers exist to show what is
actually shared and what only looked shared.

The earlier framing — "extract the credit ledger" — was too broad and is
rejected here explicitly. Balances, quantities, quota semantics, and the rule
for how a request consumes credits stay inside each domain's authority. API
credits keeps its fixed per-request consumption; inference keeps its rate card.
What moves is access issuance and evidence: the parts that are the same for any
market that sells a bearer credential.

## What Changes

- **Pin API credits first.** Before anything moves, add regression tests that
  record the exact issuance request digest, fulfillment identity, and evidence
  digest bytes the API-credits domain produces today for a fixed input set, so
  the extraction is proven byte-identical rather than believed to be.
- **`kit/access-issuance`** (`market_access_issuance`): issuance request and
  result models parameterized by a domain label; fulfillment-identity derivation
  and request-digest computation taking that label; the typed issuance client;
  fulfillment orchestration with compensating rollback; the issuance evidence
  body, signing, verification, and portable fulfillment reference. API credits
  passes `api-credits`, inference passes `inference`, and every existing
  API-credits digest is unchanged.
- **One digest implementation.** The authority service composes the kit's
  digest and identity functions instead of keeping a mirror copy, so the
  client-side and server-side computations cannot drift. Independent
  *recomputation* is preserved; independent *implementation* is not the point
  and never was.
- **Bearer gate client and signing.** Move the gate's authority client, request
  signing, and configuration into kit in a form the published middleware can
  depend on without acquiring a storefront-client dependency — the packaging
  constraint `apicredits_middleware/signing.py` records. Whether that is the
  same distribution as `market_access_issuance` or a second, dependency-light
  one is decided in `design.md`. The fixed-amount `TokenGate` remains the
  API-credits consumption rule and is not extracted.
- **Delete both copies.** `domains/apicredits/settlement/{credits_client,
  fulfillment,issuance_evidence}.py` and their inference counterparts become
  thin domain-labeled wrappers or tombstones; no domain-local implementation
  survives.
- **Decide the authority packaging.** Whether the inference authority is the
  same kit-composed service distribution as API credits deployed twice with
  different labels, or two distributions sharing the kit, is decided here with
  both consumers in view.

## Capabilities

### New Capabilities

- `access-issuance`: domain-neutral bearer-credential issuance, stable
  fulfillment identity, request digest, evidence projection, and compensating
  rollback for any market that delivers access.

### Modified Capabilities

- `api-credits`: composes the kit; behavior, wire, digests, and data unchanged,
  proven by the pinned regression tests.
- `inference`: composes the kit; its domain-local copy is removed.
- `market-composition`: the extracted-concern rule gains this instance.

## Non-Goals

- No change to any API-credits digest, wire shape, database row, or observable
  behavior. A regression test failure here is a blocking defect, not a
  migration.
- No extraction of balances, quantities, quota, or consumption rules.
- No change to the fixed per-request `TokenGate` beyond relocating what it
  depends on.
- No metering, holds, or usage capture.

## Dependencies and Related Changes

- **Depends on** `compose-inference-domain-stack` having proven its deal, so
  the second consumer is real.
- **Blocks** `meter-inference-usage`: metering mutates the authority and does so
  against the kit-composed authority once this change is accepted; copied
  modules are frozen until then.
- `sign-multi-language-credits-middleware` owns the TypeScript and Rust gates;
  relocating the Python client's signing must keep their conformance fixture
  green and must not move the fixture.

## Impact

- New: `kit/access-issuance/` (and possibly one dependency-light gate-client
  distribution), regression fixtures under `domains/apicredits/tests/`.
- Touched: `domains/apicredits/settlement/`, `domains/apicredits/service/src/models/keys_model.py`,
  `domains/apicredits/middleware/python/`, their inference counterparts,
  `kit/Makefile`, both domains' `pyproject.toml` and `reinit` targets, root
  `dist` ordering.
- Wire: none. Database: none. Packaging: one or two new kit wheels; two domain
  wheels shrink.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — kit layers gain the access-issuance
      capability; the API-credit hosted settlement section cites the kit.
- [x] Existing subsystem specification — `api-credits` and `inference`
      implementation-composition prose; `market-composition`.
- [x] New subsystem specification — `access-issuance`.

## Status

Design phase. `tasks.md` is authored when `compose-inference-domain-stack` has
a green `e2e_inference_deal`.
