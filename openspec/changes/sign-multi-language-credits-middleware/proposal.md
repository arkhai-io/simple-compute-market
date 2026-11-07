## Why

The API-credits service authenticates every non-health route against a signed
marketplace identity v2 envelope and signs every response. That was enabled on
2026-09-14 by `repair-storefront-alkahest-configuration` task `3ax.8`, which
also taught the Python middleware to sign as the `service` role.

The TypeScript (`domains/apicredits/middleware/typescript`) and Rust
(`domains/apicredits/middleware/rust`) middlewares still send only the legacy
`X-Admin-Key` shared secret. A service with signed authentication enabled
accepts signed requests **or** the shared secret and never both — `main.py`
composes `SiteAuthMiddleware` or `AdminKeyAuthMiddleware`, not both — so both
clients are refused on every route by the configuration this repository now
ships and runs in compose.

They are not broken in the sense of having regressed: they still reproduce
`conformance/session.json` exactly, because that fixture pins the *inbound*
contract — the end user's `Authorization` header, the gate's allow/deny
decision, the deny body, and the verify/consume call counts — and says nothing
about how a middleware authenticates itself outbound. So all three
implementations remain behaviourally identical in everything the shared
fixture asserts, and are no longer interchangeable deployments. That gap is
recorded as `3ax.10`.

## Why This Is Its Own Change

Two reasons, and the second is the binding one.

Implementing ed25519 signing, RFC 8785 canonical JSON, and the request
envelope in two more languages is a substantial piece of work in its own
right, with no shared implementation to lean on: `market_identity` is Python.

More importantly, **neither implementation has a validation path.** There is
no e2e scenario exercising the TypeScript or Rust middleware against a live
credits service. The Python middleware is the reference and the only one in
the compose topology (`arkhai:apicredits-sample-app`), so it is the only one a
run can prove. Signing code written for the other two could be merged, pass
its own language's unit tests, satisfy the shared conformance fixture, and
still be refused by a real service — which is exactly the failure mode that
fixture cannot see, and exactly what happened to the Python client's request
signing before the authority learned to canonicalize query input.

So this change owes its validation layer before, or alongside, its signing
work. Not after.

## What This Change Covers

### Validation first

- A gated-app scenario per implementation, driving the real middleware against
  a real credits service with signed authentication enabled, in the compose
  topology. The Python sample app's path through the e2e is the shape to
  follow: buy credits, call the metered endpoint, exhaust the key, observe the
  402 and the purchase pointer, top up, call again.
- A test layer for each implementation consistent with
  `docs/development/TESTING.md`: unit tests owning the signing envelope,
  integration tests owning the client against a real service surface, and the
  scenario above owning the cross-service contract. The Rust and TypeScript
  trees currently have conformance harnesses and little else.

### Then signing

- Request signing in the `service` role for the three gated operations,
  agreeing with `CREDITS_ROUTE_CONTRACTS` on operation name and signed
  resource: `credits_key_consume` and `credits_key_verify` keyed by `key_id`,
  `credits_key_consume_batch` by the empty resource.
- Response verification against the authority's trusted principal, including
  refusals. A 402 for an exhausted key is an authority decision the gate acts
  on, so it has to be established as the authority's before it is acted on.
- The canonical body for a GET with query input, if either client grows one.
  The Python/authority pair disagreed about this and produced `invalid_proof`
  on a route that worked for every other caller; the canonical form is in
  `market_site.auth.canonical_site_request_body` and
  `canonical_provisioning_request_body`.

### And the conformance contract

- Decide whether outbound authentication enters `session.json` or stays out of
  it. It is currently out, which is why the fixture could not see this gap.
  Extending it means every harness must drive a signer; leaving it out means
  the fixture's "identical behaviour across three languages" claim continues
  to exclude authentication, which should then be stated in
  `conformance/README.md` rather than inferred.

## What This Change Does Not Cover

- The Python middleware, which already signs.
- Reverting the service to the shared-secret gate. The signed boundary is the
  intended configuration and the e2e depends on it.

## Interim Position

Until this change lands, the TypeScript and Rust middlewares work only
against a credits service that has not enabled signed authentication.
`conformance/README.md` says so, so a third-party user discovers it from
documentation rather than from a 401.
