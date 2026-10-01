# Design: redesign authenticated replay state

## Context

Found while closing `contact-payload-retention`, whose introduction retention could
not reach copies of a counterparty's contact held in the storefront's replay store.
Investigating why showed the problem is the replay design itself rather than one
mechanism's use of it. This document records what was found, so the decisions below
start from evidence rather than rediscovering it.

## Findings

### Four stores, none bounded

| Authority | Implementation | Holds | Lifetime |
|---|---|---|---|
| Storefront | `core/storefront/src/core_storefront/sqlite_client.py` (`auth_replay_reservations`) | reservation, request hash, status, full response body, attempt token, lease | durable, never deleted |
| Registry | `core/registry/src/core_registry/db/models.py` (`publisher_replay_reservations`) | the same, with lease owner and completion time | durable, never deleted |
| Provisioning service | `provisioning/compute/service/src/compute_provisioning_service/middleware/auth.py` | reservation | durable, never deleted |
| Site authorities | `kit/site/src/market_site/auth.py` (`InMemoryReplayStore`, the default) | reservation | process memory, never evicted |

Nothing in the repository deletes from either durable body-retaining table. Each
authenticated request adds a row; state grows with all traffic ever served.

### The storefront records every authenticated response, reads included

The bare-metal response-authentication middleware
(`domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/response_auth.py`)
records the status and parsed body of every response on an authenticated route whose
request was dispatched. That includes `GET` reads. An introduction read therefore adds
a row holding the counterparty's contact on every call; so does every reveal.

### The reference callers never replay most of what is stored

`core_buyer`'s introduction transport mints a fresh request ID on every call and never
retries with the same one, so the recorded introduction bodies are, in practice, never
read back. Settlement submission reuses one ID across retries inside a single process.
No buyer code keeps a request ID across a restart. The client contract nonetheless
invites unbounded reuse — "reuse `request_id` with an identical body after an
uncertain acknowledgement" — so a third-party caller may legitimately depend on it,
and a design cannot assume the reference callers are the only ones.

### Three jobs, three lifetimes

The store does three things, and they need different data for different lengths of
time:

1. **Replay refusal.** Reserve `(principal, request_id)` with the request hash before
   dispatch; refuse a second dispatch of the same request and any changed reuse. Needs
   the hash, not the body.
2. **Exactly-once resolution of a lost acknowledgement.** Answer an exact retry of a
   mutation with its recorded outcome rather than running it again. The only job that
   needs the body.
3. **In-flight leasing.** Tell a concurrent retry the first attempt is still running,
   and let a crashed attempt be retried once its lease expires. Needs the lease, for
   the life of the attempt.

### Replay refusal has a natural horizon

A request's timestamp is checked against the configured skew on first use, and replay
identity excludes the timestamp so a caller may re-sign. Once a reservation is older
than the skew bound plus the lease, a captured copy of its request would be refused by
the timestamp check if the reservation were gone. Pruning past that horizon therefore
costs nothing for job 1. What it costs is job 2: a caller that re-signs an old request
ID after its row is pruned has the mutation run again rather than resolved.

### Domain idempotency already does job 2 for most routes

Most mutations are idempotent where their state lives: an introduction start converges
on its persisted record, a settlement submission on its obligation, a contact redaction
on its tombstone, a credits consume on its idempotency key. For those, re-running the
handler on an exact retry gives the right answer, and gives the *current* one — after
a deletion, the deleted outcome — where a stored body can only repeat the past.
`SiteRouteContract.exact_retry_safe` already declares, per site route, that re-running
an exact retry is safe; the storefront and registry have no equivalent and store a body
for everything instead.

## Direction

Not yet decided; the decisions below settle it. The working direction is:

- reservations bounded by the replay-refusal horizon and then pruned;
- each route declaring how an exact retry is resolved — *re-run* for a route idempotent
  in its own domain and for every read, *recorded outcome* only for a route that cannot
  be re-run;
- recorded outcomes kept for a stated period, not indefinitely;
- one contract and store implementation shared by every authority.

## Decisions owed

Each of these is a decision gate in `tasks.md`; none is settled here.

- **Where the shared contract and store live.** `kit/identity` owns replay reservation
  today; whether the store implementation and the route declaration belong there or in
  a storefront-side kit, given the registry and provisioning service are core and
  provisioning-layer services.
- **How a route declares retry resolution, and who checks it.** A declaration that a
  route may be re-run is only as good as the route's idempotency. Whether the
  declaration is a route-contract field like `exact_retry_safe`, whether its absence
  defaults to the safe choice, and how a test proves a declared route really converges.
- **The reservation horizon.** Whether it is derived from skew and lease or configured,
  and how pruning runs — on write, as a sweep under the storefront loop controller, or
  per authority.
- **Retained outcomes.** How long they live, and what an exact retry receives after one
  expires. Re-running is wrong for exactly these routes, and silently doing so is the
  defect `retain-authenticated-request-outcomes` set out to fix; the answer is likely a
  distinct, stable refusal that tells the caller the outcome is no longer held.
- **Existing rows.** Recorded bodies cannot be attributed to an operation, since the
  tables record neither operation nor resource. Whether existing bodies are dropped
  outright on migration, which the pre-1.0 contract allows, or aged out under the new
  bound.
- **The requirement.** How `marketplace-identity`'s exact-reuse requirement is restated
  so that re-running an idempotent route, and refusing an expired outcome, both conform.
- **`retain-authenticated-request-outcomes`.** Whether it is superseded, narrowed to
  the routes that genuinely need retained outcomes, or folded into this change.

## Consequences for other changes

- `contact-payload-retention` scopes its disclosure to the introduction record and
  points here. Once introduction routes resolve exact retries by re-running and record
  no body, the replay store no longer holds contact data, and the disclosure's scope
  can widen.
- `retain-authenticated-request-outcomes` is blocked on this change.
- `kit-owned-storefront-auth-and-persistence`, which plans one authentication
  middleware set for every storefront, should adopt the result rather than extract the
  current design.
