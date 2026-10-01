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

## Design questions this owes

See `design.md`. In short: where the shared contract lives; how a route declares its
retry resolution and who checks the declaration is true; the reservation horizon and
how it relates to clock skew and leases; how long a retained outcome lives and what an
exact retry after it receives; how existing rows are migrated or dropped; and what
becomes of `retain-authenticated-request-outcomes`.

## What this change does not cover

- The request and response signature protocol, principal binding, and skew
  enforcement on first use, all of which conform and are unchanged.
- The introduction record's retention, which `contact-payload-retention` owns.

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
