# Redesign authenticated requests

## Why

Every authority that accepts version 2 authenticated requests keeps replay state,
and none of them ever removes any of it:

- the storefront (`core_storefront`'s `auth_replay_reservations`), the registry
  (`publisher_replay_reservations`) and the provisioning service
  (`provisioning_replay_reservations`) keep a reservation per request *and* the full
  response body, durably and indefinitely;
- the site middleware's default store keeps reservations in memory for the life of
  the process, so a replay across a restart is accepted;
- the deal-lifecycle routes keep no reservation at all.

Two consequences follow, and neither is local to one route.

**Unbounded growth.** Every authenticated request adds a row that is never deleted.
State grows with total traffic, not with anything the system is doing now.

It has been observed (2026-11-24). Before its upgrade to marketplace 0.4.0, a
provisioning service running in mock mode behind a long-running bare-metal seller held
a 508 MB database, of which `provisioning_replay_reservations` was 401 MB and that
table's index 107 MB. On its 1 GiB volume this left too little free space for a
consistent snapshot beside the database, so the pre-upgrade backup refused until the
snapshot was written elsewhere.

**Indefinite retention of whatever a response carried.** The storefronts record the
body of every authenticated response, reads included. An introduction reveal or read
therefore leaves a copy of a counterparty's contact in the replay store each time it
is answered, outside anything a retention policy can reach. `contact-payload-retention`
bounds the introduction record and scopes its disclosure to that record for exactly
this reason.

Much of what the stored bodies exist to provide is already provided better in the
domain. The response body is only needed to answer an exact retry of a mutation that
cannot safely be run again. Most mutations here converge in their own domain, and for
those, running the handler again on an exact retry gives the right answer, including
the *current* answer after something has changed.

The authorities also authenticate requests by seven separate arrangements, each
deciding for itself what an exact retry receives, so no bound or per-route rule can
be applied in one place.

*Expanded 2026-10-27, by `resolve-compute-family-findings`' design (its decision D3),
to the shared `kit/identity` request contract, and renamed from
`redesign-authenticated-replay-state` to match.* The direction is independently
operated sites and storefronts, and the version 2 request envelope binds no audience:
a request one storefront principal signed for site A verifies at site B, whose replay
store has never seen it. It does not state its operation either, so an authority that
cannot route a request cannot sign its answer, and a caller whose route table differs
cannot tell version skew from tampering. Before 1.0 a versioned contract's introducing
release may stop accepting the version before
(`docs/guidance/engineering/versioning.md`).

## What Changes

- **One authenticated-request layer for every authority.** A standalone replay
  component under `tools/` (reserve, lease, renew, resolve, conclude, record, expire, sweep, with
  `sqlite3` and SQLAlchemy stores) and a thin foundation kit,
  `kit/authenticated-requests`, over it: version 3 verification, audience, trust,
  signed refusals and 500s, a signed-outcome hook, a fallback that signs answers to
  requests no route serves, and a route inventory checked at startup. The storefronts, the registry, the
  provisioning service, the site kit (the API-credits service) and the deal-lifecycle
  routes all move onto it (design D3, D4).
- **Every route declares how an exact retry is resolved**: `RERUN` or `RECORDED`,
  required, with no default, each `RERUN` mutation proven by a double-dispatch test
  with a later write between the request and its retry (D5). Reads and the mutations
  whose domain recognises a retry as applied re-run and record no body; every other
  mutation, absolute setters and deletes included, keeps its outcome (D6), and is
  dispatched once: the core renews a running attempt's lease, and an exact retry
  finding no outcome after the attempt's lease has ended concludes the attempt by a
  write in the store, which on the authority's own SQLite database cannot overtake a
transaction the attempt still holds, and
  is then answered with a signed "outcome unknown"; a recorded 500's effect is likewise
  unknown, and the caller reads current state before writing again (D3, D7). A replay
  store failing while it admits a request is a signed 503, after which the caller
  retries the same request (D7). A response carrying a secret is
  never recorded.
- **Every row is bounded.** Each request carries a signed origin; a row expires at a
  time computed from the request, never before its lease ends, and a periodic sweep
  the admission core runs, daily by default, deletes it. Recorded outcomes are kept
  for an operator-configurable retention, 24 h by default; an exact retry after it gets
  a signed 410 (D7, D8).
- **A version 3 envelope, an RFC 9421 profile.** It binds the caller's
  expected-authority set as its audience, states its operation and resource, and
  carries the request origin; every answer that names a request is signed, including
  "operation not served", operation mismatch, misdirected requests and unsupported
  protocols, a version 2 request alone, which carries none of the version 3 fields,
  refused unsigned. Signed webhook deliveries bind their endpoint (D2, D10, D11).
  `Market-Resource` is sent only when the operation acts on one object, and the profile
  accepts one spelling of everything it signs (D2, D21). Every request's signature
  covers its query string, `@query`, so a read's filters and paging are signed on every
  authority (D25).
- **The registry's descriptor is a public read answered signed.** Its request carries
  only a request identity, so a client adding a registry by its URL, knowing no
  principal yet, verifies the signed answer against the principals the descriptor names
  (D24). The listing read's filter-spec ETag becomes a covered query parameter (D26);
  an applied publisher rotation or retirement answers its exact retry before its expiry
  and primary checks (D27); singleton and collection reads carry no resource (D28).
- **Signed messages retained as evidence are records of their signed values.** The
  registry's publications, buyers' and storefronts' negotiation evidence and the
  end-delivery receipt keep, beside the exact body, a record readable as data —
  protocol, principal, role, method, query, operation, resource where present, request ID,
  timestamp, origin, audience, proof — which `kit/identity`'s evidence verifiers check
  offline under either version, a response bound by its exact trusted principals; the
  listing read's evidence fields become `publication` and `updates`, names a seller's
  publication may not carry (D21–D23).
- **One cutover.** Version 3 replaces version 2 in the release that introduces it; the
  three 0.4.0 replay tables are dropped and the SQLite space reclaimed by the migrate
  command (D9). Version 2 stays readable as an evidence format (D12).
- **Two small domain fixes:** `idempotency_key` is required on credits consume, and an
  exact replay of an introduction start whose completion failed completes it (D6).
- **Corrections that fall out of the move:** the deal-lifecycle routes reserve request
  IDs and stop signing refusals over an invented identity; the VM callback middleware's
  refusals are signed (D3, D15).

The identity-lifecycle remainder of `service-identity-signing` — the API-credits
`X-Admin-Key` fallback's removal, durable rotation of the API-credits service's trust,
one site-registry interface, provisioning-side retirement and disablement, and an
operator route to the storefront's disablement — moves to
`complete-service-identity-lifecycle` (D1, D19).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `marketplace-identity`: the version 3 profile; the three replay jobs and their
  lifetimes; per-route exact-retry resolution; a recorded route dispatched once; the
  retention and the 410; secrets never recorded; signed refusals; version 2 as an
  evidence format; every request covering `@query`; a public operation answered signed.
- `physical-provisioning`: exact retry per declaration; a failure after authentication
  recorded only on a recorded route.
- `registry-discovery`: durable replay reservation per declaration; seller publication
  evidence as `publication` and `updates`, each a request record and its body; the
  registry's authentication under version 3; the descriptor a public read answered
  signed; the filter-spec ETag a query parameter; an applied rotation or retirement
  answering its exact retry first.
- `deal-lifecycle`: the end-delivery acknowledgement under version 3; commitment
  envelopes kept and captured as signed records with their exact bodies.
- `storefront-publication`: version 3 authorization and exact retry per declaration.
- `introduction-delivery`: an exact replay of a failed start completes it; signed
  deliveries bind their endpoint.
- `compute-provisioning-contract`: a resent capacity-released notification is re-run.
- `api-credits`: `idempotency_key` required on consume.
- `deployment-state`: the migrate command reclaims space; the replay table belongs to
  `kit/authenticated-requests`.

## Non-Goals

- Skew enforcement on first use, which conforms and is unchanged.
- The introduction record's retention, which `contact-payload-retention` owns.
- The storefront role middleware set, its administrator route contracts and how the
  shell applies them, which `kit-owned-storefront-auth-and-persistence` keeps.
- The identity-lifecycle remainder, which `complete-service-identity-lifecycle` owns.
- Making the non-convergent mutations idempotent in their domains.

## Dependencies and Acceptance Boundary

No change gates it; `unify-compute-delivery-path`, whose credential-capable
declaration this generalizes, is archived. `retain-authenticated-request-outcomes` is
superseded by it (D18), and `sign-multi-language-credits-middleware` and
`contract-driven-authenticated-routing` wait on it (D19).

Acceptance: every authority authenticates through the one admission core under version
3; every authenticated route declares its exact-retry resolution and every `RERUN`
mutation passes its double-dispatch case; no `RECORDED` request is dispatched twice; no
expired replay row affects an answer, and
every expired row is deleted within one sweep interval; no recorded outcome holds a
contact or a secret; the 0.4.0 tables are gone and the
SQLite files compacted after the upgrade; every refusal that names a request is signed,
on a path no route serves too, and an unexpected failure after authentication is a
signed 500, a replay store's failure while admitting a request a signed 503; on an authority's own SQLite
database no `exact_retry_outcome_unknown` answer precedes the end of a transaction its
attempt holds;
version 2 requests are refused and version 2 evidence still verifies; version 3
evidence verifies offline from its record and body alone; a request whose query was
changed after signing is refused; a client knowing no registry principal bootstraps
from the registry's public descriptor read and verifies its signed answer.

## Impact

Code: `kit/identity` (version 3 profile, wire names, declaration vocabulary, evidence
records and their verifiers for both versions, the capture seam); a new standalone component under `tools/`; a new
`kit/authenticated-requests`; `kit/schema-migrations` (space-freeing migrations); every
authority's authentication code listed in the design's findings; every typed client;
`kit/delivery`'s webhook sink; each service's migration chain and the registry's
Alembic revisions, the registry's renamed evidence columns among them; the API-credits
consume models; the evidence carriers and verifiers of `kit/deal-lifecycle-contracts`,
`kit/deal-lifecycle`, `kit/deal-lifecycle-buyer`, `kit/deal-servicing` and the VM
buyer. Configuration: a retention key and a
sweep-interval key on every authority, in its settings and Helm values schema. Packages: `arkhai-kit-identity`
takes an incompatible minor bump and every dependent's bound moves (D17).

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — "Marketplace identity", "Authenticated
      service boundaries" (whose generic substance moves to engineering guidance), and
      the new foundation kit in "Kit areas"
- [x] Existing subsystem specifications — `marketplace-identity`,
      `physical-provisioning`, `registry-discovery`, `storefront-publication`,
      `introduction-delivery`, `compute-provisioning-contract`, `api-credits`,
      `deployment-state`, `deal-lifecycle`
- [ ] New subsystem specification
- [ ] No permanent documentation change

Engineering guidance, shared across repositories, gains a messaging file and a
`messaging` topic tag, and the route contract in
`docs/guidance/engineering/implementation.md` gains the exact-retry declaration.

### Knowledge to promote

- D1: no permanent destination — scope is the change's own, and the split-off change
  records its scope in its proposal.
- D2 version 3 as an RFC 9421 profile, its tags, its one accepted spelling and
  `Market-Resource` only where the operation has a target:
  `openspec/specs/marketplace-identity/spec.md` and `architecture.md`; the principle of a
  standard signature format to a new `messaging.md` in `docs/guidance/engineering/`.
- D3 one authenticated-request layer: `docs/development/ARCHITECTURE.md`, "Marketplace
  identity" and "Authenticated service boundaries"; `marketplace-identity`
  `architecture.md`.
- D4 placement: `docs/development/ARCHITECTURE.md`, "Kit areas", with
  `docs/development/diagrams/kit-areas.drawio` and its SVG export, and
  `docs/development/ARCHITECTURE.toml`; `tools/README.md`, "Standalone infrastructure
  components", and the component's own README.
- D5 per-route exact-retry declaration: `marketplace-identity` spec; its proof in
  `openspec/specs/marketplace-identity/testing.md`; the declaration as part of the route
  contract in `docs/guidance/engineering/implementation.md`, "Route contracts and their
  HTTP binding".
- D6 which routes record, and secrets never recorded: `marketplace-identity` spec and
  `architecture.md`; `introduction-delivery` and `api-credits` specs; the rule that a
  message carrying a secret is never stored or logged as it stands, and is stripped
  before any persistence, to the new engineering `messaging.md`.
- D7 bounds, the lease floor, the `RECORDED` lease renewal, expired rows treated as
  absent, the periodic sweep, database stores and the retention and sweep-interval keys:
  `marketplace-identity` `architecture.md` and its settings table in `configuration.md`;
  `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Stateful service persistence".
- D8 request origin, retention and the 410: `marketplace-identity` spec.
- D9 cutover, table drops and `VACUUM`: `deployment-state` spec, and its
  `architecture.md`, "One engine, one contract";
  `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Migrations at startup".
- D10 audience, and D10a signed deliveries: `marketplace-identity` spec;
  `introduction-delivery` spec; the principle of binding the audience to the new
  engineering `messaging.md`.
- D11 stated operation and signed refusals: `marketplace-identity` spec; the principle
  of signing every refusal bound to a request to the new engineering `messaging.md`,
  together with the generic substance of `ARCHITECTURE.md`'s "Authenticated service
  boundaries" (both directions signed, trust from configured public principals, a
  timestamp as a claim checked within a tolerance), which `ARCHITECTURE.md` then cites.
- D12 version 2 as an evidence format: `marketplace-identity` spec and `architecture.md`.
- D13 wire names owned by `kit/identity`: `marketplace-identity` `architecture.md`.
- D14: no permanent destination — the deltas themselves are merged
  by the archive.
- D15: no permanent destination — the existing requirement
  already demands it.
- D16 capability check: `marketplace-identity` spec, through D11's refusal.
- D17: no permanent destination — the version numbers are the record.
- D18: no permanent destination —
  index rows and the archive record it.
- D19: no permanent destination — index rows
  are planning state.
- D20: no permanent destination — the cadence is the plan's, not current behaviour.
- D21 signed messages retained as records of their signed values: `marketplace-identity`
  spec, and its `architecture.md`, a new section "Signed messages retained as evidence";
  `registry-discovery` spec and its `architecture.md`, "Seller publication evidence"
  (`publication`, `updates`); `deal-lifecycle` spec (the end-delivery acknowledgement)
  and its `architecture.md`, "Buyer surrender and cases"; to the new engineering
  `messaging.md`, two principles the owner stated: each kind of message carries exactly
  the fields some message of that kind needs, its fields' presence fixed by the kind and
  never by one message's values; and a retained signed message is stored as its signed
  values, readable as data, not as its transport form.
- D22 evidence verifiers: `marketplace-identity` spec and its `architecture.md`, "Signed
  messages retained as evidence".
- D23 capture carrying records: `marketplace-identity` `architecture.md`, beside the
  admission core; `deal-lifecycle` spec, its capture requirements.
- D24 the descriptor a public operation answered signed: `marketplace-identity` spec;
  `registry-discovery` spec and its `architecture.md`, "Self-description boundary",
  which states that the protocol keeps trust on first use for adding a registry by URL
  and that a directory's countersignature is a separate layer;
  `docs/development/ARCHITECTURE.md`'s discovery flow.
- D25 `@query` on every request: `marketplace-identity` spec and `architecture.md`; the
  principle that a signature covers every request input that changes behaviour, the
  query included, to the new engineering `messaging.md`.
- D26 the filter-spec ETag as a query parameter: `registry-discovery` spec, its
  filter-spec consistency and query compilation requirements.
- D27 an applied rotation or retirement answering its exact retry first:
  `registry-discovery` spec, "Publisher principal rotation".
- D28: no permanent destination — it applies D2's and D21's rule, which the
  `marketplace-identity` spec records, and the routes' declarations are the record.
- D29: no permanent destination — the cadence is the plan's, not current behaviour.
