## Why

Every authority that accepts version 2 authenticated requests keeps replay state,
and none of them ever removes any of it:

- the storefront (`core_storefront`'s `auth_replay_reservations`) and the registry
  (`publisher_replay_reservations`) keep a reservation per request *and* the full
  response body, durably and indefinitely;
- the provisioning service keeps durable reservations indefinitely;
- the site middleware's default store keeps reservations in memory for the life of
  the process.

Two consequences follow, and neither is local to one route.

**Unbounded growth.** Every authenticated request adds a row that is never deleted.
State grows with total traffic, not with anything the system is doing now.

**Indefinite retention of whatever a response carried.** The storefront records the
body of every authenticated response, reads included. An introduction reveal or read
therefore leaves a copy of a counterparty's contact in the replay store each time it
is answered, outside anything a retention policy can reach. `contact-payload-retention`
bounds the introduction record and scopes its disclosure to that record for exactly
this reason.

Meanwhile much of what the stored bodies exist to provide is already provided
elsewhere, and provided better. The response body is only needed to answer an exact
retry of a mutation that cannot safely be run again. Most mutations in this system are
idempotent in their own domain — an introduction start, a settlement submission, a
contact redaction, a credits consume keyed by an idempotency key — and for those,
running the handler again on an exact retry gives the right answer, including the
*current* answer after something has changed. A stored body can only give the answer
from the moment it was recorded.

`retain-authenticated-request-outcomes` would extend outcome retention to the site
authorities' stores. Built on the present design, it would add a third body-retaining
store with the same two problems. It is blocked on this change so the two are not
designed in the wrong order.

*Expanded 2026-10-27, by `resolve-compute-family-findings`' design (its decision D3), to
the shared `kit/identity` request contract, and renamed from
`redesign-authenticated-replay-state` to match.* The direction is independently operated
sites and storefronts, and one storefront serving several sites, and the version 2
request envelope does not carry what that needs:

- **It binds no audience.** `RequestEnvelope` (`kit/identity/src/market_identity/models.py`)
  signs role, principal, method, operation, resource, request identity, timestamp, and
  body hash, and nothing naming the authority the request is addressed to. Replay is
  reserved per authority. Once one storefront principal is trusted by several sites, a
  request it signed for site A verifies at site B, whose store has never seen it, and
  for an operation whose resource is not site-specific — a reservation against a pool
  both sites name, a projection read — the replay acts. That makes audience binding a
  replay question as much as an envelope one.
- **A request does not state its operation.** The signature binds the operation, but the
  request does not name it, so an authority that cannot route a request cannot sign its
  answer (`resolve-compute-family-findings` keeps those answers unsigned, by status), and
  cannot tell a caller whose route table differs from its own that it signed operation X
  where this service binds Y; it answers 403. A stated operation lets an authority sign
  "operation not served" over the caller's own claim, report version skew as skew, give
  a newer storefront evidence to degrade against an older site, and match and authorize
  on the operation rather than on how a proxy spelled the path. It also lets every replay
  row record its operation, which today's rows cannot.

Before 1.0 the envelope may change incompatibly (`docs/development/RELEASING.md`,
"Versioning policy"): a version 3 protocol identifier is defined beside version 2, and
the release that introduces it may stop accepting version 2.

`service-identity-signing` was found delivered by `add-nonchain-marketplace-identities`
and later changes, its requirements already in the permanent specifications. What its
tasks left undone moves here:

- the API-credits service's shared-secret fallback (`storefront_admin_key`,
  `AdminKeyAuthMiddleware`) and the `X-Admin-Key` the Python credits client still sends,
  removed only after `sign-multi-language-credits-middleware` signs the TypeScript and
  Rust middlewares, whose interim position relies on the fallback;
- the API-credits service's trusted principals, read from the environment with no
  durable rotation;
- one site-registry interface returning `(site_id, url, principal)`, where principals
  come through `ServicePeerTrust` and URLs straight from configuration;
- provisioning-side explicit principal retirement and disablement, which
  `physical-provisioning` requires and the service lacks, and an operator route to the
  storefront's existing disablement;
- the VM storefront's callback middleware's unsigned authentication refusals, contrary
  to `marketplace-identity`;
- a runtime protocol-capability check, and exact `arkhai-kit-identity` pins in
  `kit/site` and `kit/arkhai-payments`.

## What changes

This change is in design. Its direction, to be settled by the decisions in
`design.md`:

- **One replay contract, with each concern bounded separately.** Reservation (refusing
  a replayed or changed request), exactly-once resolution of a lost acknowledgement,
  and in-flight leasing are three jobs with three different lifetimes. Each is kept
  only as long as its job needs.
- **Every row has a bound.** Reservations can be pruned once a captured request would
  fail its timestamp check anyway. Nothing is kept indefinitely by default.
- **Routes declare how an exact retry is resolved.** A route idempotent in its own
  domain re-runs on an exact retry and records no body. A read records no body. Only a
  route that genuinely cannot be re-run retains an outcome, for a stated period.
- **One implementation.** The storefront, registry, provisioning service, and site
  middleware converge on one shared store and contract, so the bound and the
  declarations are the same everywhere.
- **The requirement is restated.** `marketplace-identity`'s "an exact reuse MUST
  resolve to the recorded operation outcome" is revised to say how each kind of route
  resolves one, and for how long.
- **A version 3 request envelope** states its operation and binds its audience, and
  every authority's middleware and typed client moves to it; an authority signs its
  answer to a request it cannot route, over the operation the request states.
- **What `service-identity-signing` left undone**, listed under Why.

## Design questions this owes

See `design.md`. In short: where the shared contract lives; how a route declares its
retry resolution and who checks the declaration is true; the reservation horizon and
how it relates to clock skew and leases; how long a retained outcome lives and what an
exact retry after it receives; how existing rows are migrated or dropped; and what
becomes of `retain-authenticated-request-outcomes`.

## What this change does not cover

- Skew enforcement on first use, which conforms and is unchanged.
- The introduction record's retention, which `contact-payload-retention` owns.
- A signed answer to a route that raises after authentication, which
  `unbacked-bare-metal-listings` owns.

If design finds that bounded replay state and the version 3 envelope can land
separately, it may split them again; what argues for one change is that both rewrite
every authority's middleware.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — the identity paragraph's replay
      reservation, and the authenticated service-to-service call description
- [x] Existing subsystem specification — `marketplace-identity`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- The three replay jobs, each one's lifetime, and the reservation horizon →
  `openspec/specs/marketplace-identity/spec.md`
- Route declaration of exact-retry resolution → `marketplace-identity`, and the
  storefront and site route contracts that carry it
- Where the shared replay store lives in the package layers →
  `docs/development/ARCHITECTURE.md`
- Any operator-configurable horizon → `docs/development/DEPLOYMENT_AND_CONFIG.md`
- The version 3 envelope, its audience binding, and signed answers to unroutable
  requests → `openspec/specs/marketplace-identity/spec.md` and `architecture.md`;
  `docs/development/ARCHITECTURE.md`, "Authenticated service boundaries"
