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
  component under `tools/` (reserve, lease, resolve, record, expire, prune, with
  `sqlite3` and SQLAlchemy stores) and a thin foundation kit,
  `kit/authenticated-requests`, over it: version 3 verification, audience, trust,
  signed refusals and a signed-outcome hook. The storefronts, the registry, the
  provisioning service, the site kit (the API-credits service) and the deal-lifecycle
  routes all move onto it (design D3, D4).
- **Every route declares how an exact retry is resolved**: `RERUN`, `RECORDED` or
  `REFUSE`, required, with no default, each `RERUN` mutation proven by a
  double-dispatch test (D5). Reads and convergent mutations re-run and record no body;
  a short list of non-convergent mutations keeps its outcome (D6). A response carrying
  a secret is never recorded.
- **Every row is bounded.** Each request carries a signed origin; a row expires at a
  time computed from the request, and is pruned on write. Recorded outcomes are kept
  for an operator-configurable retention, 24 h by default; an exact retry after it gets
  a signed 410 (D7, D8).
- **A version 3 envelope, an RFC 9421 profile.** It binds the caller's
  expected-authority set as its audience, states its operation and resource, and
  carries the request origin; every answer that names a request is signed, including
  "operation not served", operation mismatch, misdirected requests and unsupported
  protocols. Signed webhook deliveries bind their endpoint (D2, D10, D11).
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
  lifetimes; per-route exact-retry resolution; the retention and the 410; secrets never
  recorded; signed refusals; version 2 as an evidence format.
- `physical-provisioning`: exact retry per declaration; a failure after authentication
  recorded only on a recorded route.
- `registry-discovery`: durable replay reservation per declaration.
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
- A signed answer to a route that raises after authentication, which
  `unbacked-bare-metal-listings` owns.
- The storefront role middleware set, its administrator route contracts and how the
  shell applies them, which `kit-owned-storefront-auth-and-persistence` keeps.
- The identity-lifecycle remainder, which `complete-service-identity-lifecycle` owns.
- Making the non-convergent mutations idempotent in their domains.

## Dependencies and Acceptance Boundary

No change gates it; `unify-compute-delivery-path`, whose credential-capable
declaration this generalizes, is archived. `retain-authenticated-request-outcomes` is
superseded by it (D18), and `sign-multi-language-credits-middleware` waits on it (D19).

Acceptance: every authority authenticates through the one admission core under version
3; every authenticated route declares its exact-retry resolution and every `RERUN`
mutation passes its double-dispatch case; no replay row outlives its computed expiry;
no recorded outcome holds a contact or a secret; the 0.4.0 tables are gone and the
SQLite files compacted after the upgrade; every refusal that names a request is signed;
version 2 requests are refused and version 2 evidence still verifies.

## Impact

Code: `kit/identity` (version 3 profile, wire names, declaration vocabulary, version 2
evidence reader); a new standalone component under `tools/`; a new
`kit/authenticated-requests`; `kit/schema-migrations` (space-freeing migrations); every
authority's authentication code listed in the design's findings; every typed client;
`kit/delivery`'s webhook sink; each service's migration chain and the registry's
Alembic revisions; the API-credits consume models. Configuration: one retention key on
every authority, in its settings and Helm values schema. Packages: `arkhai-kit-identity`
takes an incompatible minor bump and every dependent's bound moves (D17).

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — "Marketplace identity", "Authenticated
      service boundaries" (whose generic substance moves to engineering guidance), and
      the new foundation kit in "Kit areas"
- [x] Existing subsystem specifications — `marketplace-identity`,
      `physical-provisioning`, `registry-discovery`, `storefront-publication`,
      `introduction-delivery`, `compute-provisioning-contract`, `api-credits`,
      `deployment-state`
- [ ] New subsystem specification
- [ ] No permanent documentation change

Engineering guidance, shared across repositories, gains a messaging file and a
`messaging` topic tag, and the route contract in
`docs/guidance/engineering/implementation.md` gains the exact-retry declaration.

### Knowledge to promote

- D1: no permanent destination — scope is the change's own, and the split-off change
  records its scope in its proposal.
- D2 version 3 as an RFC 9421 profile: `openspec/specs/marketplace-identity/spec.md` and
  `architecture.md`; the principle of a standard signature format to a new `messaging.md`
  in `docs/guidance/engineering/`.
- D3 one authenticated-request layer: `docs/development/ARCHITECTURE.md`, "Marketplace
  identity" and "Authenticated service boundaries"; `marketplace-identity`
  `architecture.md`.
- D4 placement: `docs/development/ARCHITECTURE.md`, "Kit areas", and
  `docs/development/ARCHITECTURE.toml`; the standalone component's README under `tools/`.
- D5 per-route exact-retry declaration: `marketplace-identity` spec; its proof in
  `openspec/specs/marketplace-identity/testing.md`; the declaration as part of the route
  contract in `docs/guidance/engineering/implementation.md`, "Route contracts and their
  HTTP binding".
- D6 which routes record, and secrets never recorded: `marketplace-identity` spec and
  `architecture.md`; `introduction-delivery` and `api-credits` specs; the rule that a
  message carrying a secret is never stored or logged as it stands, and is stripped
  before any persistence, to the new engineering `messaging.md`.
- D7 bounds, on-write pruning, database stores and the retention key:
  `marketplace-identity` `architecture.md` and `configuration.md`;
  `docs/development/DEPLOYMENT_AND_CONFIG.md`.
- D8 request origin, retention and the 410: `marketplace-identity` spec.
- D9 cutover, table drops and `VACUUM`: `deployment-state` spec;
  `docs/development/DEPLOYMENT_AND_CONFIG.md`, its migrations section.
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
