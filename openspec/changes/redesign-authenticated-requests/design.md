# Design: redesign authenticated requests

## Context

Found while closing `contact-payload-retention`, whose introduction retention could
not reach copies of a counterparty's contact held in the storefront's replay store.
Investigating why showed the problem is the replay design itself rather than one
mechanism's use of it. `resolve-compute-family-findings` (its decision D3) widened
the change to the shared request contract: a version 3 envelope that binds its
audience and states its operation. This design keeps that widening and moves the
identity-lifecycle remainder of `service-identity-signing` to its own change (D1).

The record of what has been deployed is the release tags
(`docs/guidance/repository/package-versions.md`). The newest is
`marketplace-v0.4.0`, read with `git log --tags --no-walk --decorate`; every
compatibility and migration statement below is measured against it.

## Findings

### Seven arrangements, three durable stores, none bounded

| Authority | Where verification, reservation, retry resolution and signing live | Replay state |
|---|---|---|
| VM storefront | `seller_auth`, `admin_identity`, `buyer_auth`, `service_peer_auth`, and retry handling in `negotiate_controller`, `deals_controller`, `settle_controller`, `settlement_stages`, `introductions_controller` | core's `auth_replay_reservations` |
| Bare-metal storefront | `api.py` (`_principal`, `_authorize_introduction_request`), `response_auth.py` | core's `auth_replay_reservations` |
| API-credits storefront | `admin_auth`, `seller_auth`, `buyer_auth`, `response_auth`, `negotiate_controller` | core's `auth_replay_reservations` |
| Registry | `core/registry/src/core_registry/api/publisher_auth.py`, called from each route | `publisher_replay_reservations` |
| Provisioning service | `ProvisioningAuthMiddleware`, `SqlAlchemyProvisioningReplayStore` (`provisioning/compute/service/src/compute_provisioning_service/middleware/auth.py`) | `provisioning_replay_reservations` |
| API-credits service, through the site kit | `SiteAuthMiddleware`, `InMemoryReplayStore` (`kit/site/src/market_site/auth.py`) | process memory |
| Deal-lifecycle routes | `kit/deal-servicing/src/market_deal_servicing/routes.py` (`dispatch`, `_authenticate`) | none |

The three durable tables each hold a reservation, the request hash, a lease, and the
full response status and body; provisioning's also holds an empty-body flag, the
media type and an attempt count
(`provisioning/compute/service/src/compute_provisioning_service/db/models.py`).
Nothing in the repository deletes from any of them. Marketplace 0.4.0 carries all
three. A provisioning service in mock mode behind a long-running bare-metal seller
held 401 MB of its 508 MB database in `provisioning_replay_reservations`, which left
too little space on its 1 GiB volume for the pre-upgrade backup.

The site kit's in-memory store backs one deployed service, the API-credits service;
the site the provisioning service hosts sits behind provisioning's durable store.
The deal-lifecycle routes reserve no request ID at all and rely on domain operation
keys, contrary to `marketplace-identity`'s "the receiving authority MUST reserve
`(principal, request_id)` before dispatch", and sign a refusal for a request with no
request ID against the literal `"unauthenticated"`, which the same requirement
forbids.

### What a stored body holds, and who reads it

Every storefront and the registry record the body of every authenticated response,
reads included, so each introduction reveal or read leaves a copy of the
counterparty's contact. The compute storefronts already declare credential-capable
routes, whose outcome is recorded without access material and which run again on an
exact retry (`unify-compute-delivery-path`, in 0.4.0). The site kit's
`SiteRouteContract.exact_retry_safe` declares the opposite default: every route may
re-run unless it says otherwise, and only `credits_key_adjust` says otherwise.

`core_buyer` mints a fresh request ID per call; settlement reuses one only within a
process; no reference caller keeps an ID across a restart. The client contract still
invites reuse after an uncertain acknowledgement
(`core/storefront-client/src/storefront_client/client.py`), so a third-party caller
may depend on it.

### Three jobs, three lifetimes

1. **Replay refusal.** Reserve the request with its hash before dispatch; refuse a
   second dispatch and any changed reuse. Needs the hash, not the body.
2. **Exactly-once resolution of a lost acknowledgement.** Answer an exact retry of a
   mutation that cannot run again. The only job that needs a body.
3. **In-flight leasing.** Tell a concurrent retry the first attempt is still running,
   and let a crashed attempt be retried once its lease expires.

### The replay-refusal horizon

The skew check is symmetric, 300 s: a request with signed timestamp T is fresh while
|now − T| ≤ skew. A reservation made on arrival A can hold a T as late as A + skew, so
a captured copy stays fresh until T + skew, which is as late as A + 2 × skew. The
lease bounds a pending row and is no part of the horizon; with the registry's and the
provisioning service's 30 s leases, a horizon of skew plus lease would leave a replay
window.

### Libraries

No library provides the replay and exactly-once layer with a durable store, signed
request identity and per-route resolution: the ASGI idempotency middlewares surveyed
(`asgi-idempotency-header`, the `tempest-fastapi-sdk` middleware, `ichido`) cache
every body under an unsigned header, mostly in Redis. The Idempotency-Key draft
(`draft-ietf-httpapi-idempotency-key-header-07`) gives the same semantics this
design uses. For message authentication, RFC 9421 (HTTP Message Signatures) with RFC
9530 `Content-Digest` is the standard form of what version 2 frames by hand, with
Python (`http-message-signatures`), TypeScript and Rust implementations; it leaves
replay to the application. JWS and DPoP (RFC 9449) were weighed and fit less well:
neither binds an HTTP response to its request, and neither carries EIP-191.

## Decisions

### D1 — Scope: bounded replay state and the version 3 envelope; the identity-lifecycle remainder splits

This change bounds every authority's replay state, unifies how every authority
authenticates requests, and introduces the version 3 envelope. What
`service-identity-signing` left undone in identity lifecycle and trust configuration
moves to a new change, `complete-service-identity-lifecycle` (D19): the API-credits
`X-Admin-Key` fallback's removal, durable rotation of the API-credits service's
trusted principals, one site-registry interface, provisioning-side principal
retirement and disablement, and an operator route to the storefront's existing
disablement. Three small remainder items stay here because they ride on the envelope
or the middleware this change rewrites: the VM callback middleware's signed refusals
(D15), the protocol-capability check (D16), and the identity pins (D17).

The unbounded growth is the immediate need, and unifying the middleware while it is
open is wanted; this is the minimal split that removes any wait on
`sign-multi-language-credits-middleware`, which gates the fallback's removal.

Rejected: keeping everything in one change, which could not close out before
`sign-multi-language-credits-middleware`; splitting the envelope out as well, which
would leave a second wire cutover for later; deferring, which lets every store keep
growing at the rate of all traffic.

### D2 — Version 3 is an RFC 9421 profile

The version 3 request and response are an RFC 9421 profile with RFC 9530
`Content-Digest`:

- the signature's `tag` names the profile (`arkhai.market-request.v3`,
  `arkhai.market-response.v3`); `keyid` is the complete principal; `alg` is omitted,
  so the principal's scheme selects the verifier, as verifier dispatch does today;
- the semantic fields are covered header fields: `Market-Role`, `Market-Operation`,
  `Market-Resource`, `Market-Audience` (D10), `Market-Request-ID`, and
  `Market-Request-Origin` (D8);
- the request ID is a covered field, not the RFC's `nonce`, because an exact retry
  reuses it, re-signed;
- `Content-Digest` hashes the bytes sent, not canonical JSON;
- a response covers `@status` and `content-digest` and binds its request with the
  `;req` flag over the request's method, operation, resource and request ID.

```http
POST /api/v1/capacity/reservations HTTP/1.1
Content-Digest: sha-256=:X48E9qOokqqrvdts8nOJRJN3OWDUoyWxBf7kbu9DBPE=:
Market-Role: storefront
Market-Operation: capacity_reserve
Market-Resource: pool-gpu-a100
Market-Audience: ed25519:Hq7kZp0TnR4vW9xYcB2dLmS8eJ5fQ1gA6uIoN3hK7rE
Market-Request-ID: 0f6c2b1e7d4a4c1e9a523e8b6d0f1a77
Market-Request-Origin: 1795000000
Signature-Input: market=("@method" "market-role" "market-operation" "market-resource" "market-audience" "market-request-id" "market-request-origin" "content-digest");created=1795000000;keyid="ed25519:9mQ3vX2kq8sJdLr0aYbWcZtNeHf1uGpRiOxTyEwKjVs";tag="arkhai.market-request.v3"
Signature: market=:3q2-7w...:
```

The implementation's first gate proves EIP-191 signing and verification through the
`http-message-signatures` library's algorithm interface, and a small ASGI adapter. If
that interface cannot take a scheme-dispatched algorithm, `kit/identity` implements
the profile's signature base itself and keeps the library as an interoperability
test oracle. The non-HTTP signed artifacts — rotation intents, payment receipts,
deal-lifecycle acknowledgements, pricing records — keep `kit/identity`'s own framing.

A standard format lets callers in other languages and outside this repository sign
without reimplementing a bespoke frame (TypeScript and Rust implementations exist),
binds a response to its request in the standard way, and removes the bespoke request
frame and the header constants copied into nine packages. The wire changes in this
change regardless (D1); making it a standard one is the gain.

Rejected: a bespoke version 3 frame, which keeps a format every other language must
reimplement; a JWS form, which has no EIP-191 and no HTTP response binding; deferring
the standard to a version 4, which costs a second cutover.

### D3 — This change unifies the authenticated-request layer for every authority

One authority-neutral component (D4) does, for every authority: verify a version 3
request (signature, audience, freshness, role and principal against an injected trust
set); reserve it; resolve an exact retry as its route declares (D5); record an outcome
where the route declares one; sign every answer, refusals and unroutable requests
included (D11); and prune (D7). All seven arrangements move onto it, storefront routes
included. Each authority keeps its own wiring: which roles and principals each route
admits, and where its trust comes from.

The component's interface, walked through every caller:

- one admission per request: `dispatch`, `rerun` (an exact retry the route lets the
  handler run again), `answered` (a recorded outcome or a refusal, already signed), or
  `in progress`;
- an `exact_retry` flag on the admission, for handlers that re-run but must know it is
  a retry (VM settle's `refuse_after_end`, the credential reads);
- a signed-outcome hook that hands the signed response's raw body and headers to the
  caller, for evidence capture (bare metal's `EvidenceSession.capture`, VM's
  `capture_negotiation`, deal-servicing's `lifecycle_response`);
- a middleware form for authorities that route by a contract table (provisioning, the
  site kit) and a request-dependency form for authorities that authenticate inside the
  route (registry, storefront controllers, deal-servicing), over one core.

`kit-owned-storefront-auth-and-persistence` keeps the storefront role set, the
administrator route contracts, how the shell applies them, and persistence; it
composes this component. This move fixes the deal-lifecycle routes' missing
reservation and invented refusal identity as a consequence.

Rejected: taking the whole storefront middleware set, which would design how the set
is applied ahead of `kit-owned-storefront-shell`; changing each arrangement in place,
which lands every later fix seven times; waiting for
`kit-owned-storefront-auth-and-persistence`, which puts the production fix behind a
chain still in design.

### D4 — Where it lives: `kit/identity`, a standalone replay component, and a thin market kit

```text
standalone component under tools/   no internal dependencies; stdlib, optional SQLAlchemy and Starlette
  reserve, lease, resolve (RERUN/RECORDED/REFUSE), record, expire, prune over an opaque key and hash;
  sqlite3 and SQLAlchemy stores; its DDL as published statements; ASGI and dependency wrappers
        ▲
kit/authenticated-requests          foundation kit; authorities only
  the admission core: version 3 verification through kit/identity, audience, trust,
  Market-* fields, signed refusals, the signed-outcome hook;
  wraps the component's DDL into kit/schema-migrations migrations
        ▲
kit/identity                        foundation kit; every client and contract may use it
  the version 3 profile (sign and verify request and response parts), wire names (D13),
  the exact-retry declaration vocabulary as data (D5), the version 2 evidence reader (D12)
```

The replay and exactly-once machinery is generic infrastructure, so it is a standalone
component under `tools/`, holding its boundary with its own structure test and joining
the test targets through a root target as `tools/README.md` describes
(`docs/guidance/engineering/implementation.md`, "Generic infrastructure is a
standalone component"; `docs/guidance/repository/package-layers.md`).
`kit/authenticated-requests` (distribution `arkhai-kit-authenticated-requests`) is the
market layer over it, in the foundation area so that `kit/site` (authority area),
`kit/deal-servicing` (storefront side), and the composition-layer storefronts,
registry and provisioning service can all use it; it carries a package allowlist.
`kit/identity` gains `http-message-signatures` and `http-sf` on its allowlist (D2) and
no HTTP framework or database. Each service's migration chain composes the kit's
migrations in its fixed order; the registry mirrors the table in an Alembic revision.

Every caller, through this placement: typed clients sign and verify through
`kit/identity` only; contracts packages import the declaration vocabulary from
`kit/identity`, which their kind allowlist already admits; each authority constructs
the admission core with its signer, a trust provider, its route declarations, and a
store bound to its own database.

Rejected: everything in `kit/identity`, which would make every client and contract
install server middleware and a database layer; the replay machinery inside a market
kit, against the standalone-component rule; `kit/site`, `core/storefront` or
`kit/storefront`, which the registry or provisioning cannot depend on by layer or
ownership.

### D5 — Each route declares how an exact retry is resolved

Each route's contract carries a required `exact_retry` field, from `kit/identity`'s
vocabulary:

- `RERUN` — the handler runs again; no body is recorded;
- `RECORDED` — the outcome is kept for the retention (D8);
- `REFUSE` — an exact retry is refused with nothing recorded, for an outcome that
  cannot be recorded. No route uses it today.

```python
_contract(
    "POST", r"/api/v1/keys/(?P<key_id>[^/]+)/consume", "credits_key_consume", _SELLER,
    path_resource="key_id",
    exact_retry=ExactRetry.RERUN,
)
_contract(
    "POST", r"/api/v1/keys/(?P<key_id>[^/]+)/adjust", "credits_key_adjust", _SELLER,
    path_resource="key_id",
    exact_retry=ExactRetry.RECORDED,
)
```

There is no default: the admission core refuses to construct over an authenticated
route without a declaration, so the authority fails at startup, and a unit test over
each route table catches the omission first. Leasing applies to every kind, so a
concurrent exact retry is always `in progress`; reads stay reserved. A credential-capable
route is a `RERUN` route that records no body, so the separate stripped-body mechanism
goes; handlers that must know they serve a retry read the admission's `exact_retry`
flag.

Each `RERUN` declaration on a mutation is proven by a double-dispatch harness in the
standalone component, which each authority's integration suite drives with one case
per operation: the request, then its exact retry re-signed later, through the real
admission core and application, asserting that the domain state after both equals
the state after the first (the replay table excluded) and that the second answer is
the route's current answer. A completeness test per authority fails when a `RERUN`
operation has no case. Test level: integration, the lowest at which the real handler
and database exist (`docs/guidance/engineering/test-levels.md`).

Rejected: a per-authority mapping beside the routes, which drifts; a default of re-run,
which double-applies a new non-idempotent mutation; a default of recorded, which is the
body retention this change removes; a default of refuse, which surfaces a forgotten
declaration only as a runtime 409; proof by review alone.

### D6 — Which routes keep a recorded outcome

A route is `RERUN` where its domain converges and a re-run's answer still tells a
caller who lost its acknowledgement what happened — a 404 after a delete, "time is
already later", a stale heartbeat. Everything else is `RECORDED`. A response carrying a
secret is never `RECORDED`: it is `RERUN` where the re-run supersedes the lost answer
(issuance rotates an unused key's secret, `grant-keys/stage` stages a new key, relay
`token`, VM `reset-password`), and `REFUSE` otherwise.

Two small domain fixes come with this: `idempotency_key` becomes required on
`credits_key_consume` and `consume-batch` in the version 3 wire models (every gate
already mints one), and `introduction-delivery` changes so that an exact replay of a
start whose completion failed completes it, as a new start does; seller dispatch stays
once-only through its claim.

The `RECORDED` set:

| Authority | Routes |
|---|---|
| VM, bare-metal and API-credits storefronts | `negotiate_new`, `negotiate_continue`, `admin_advance_negotiation`, `admin_force_accept_negotiation`, `admin_reserve_capacity`, `admin_release_reservations`, `admin_run_lifecycle_cycle`, `admin_refresh_site_projections` |
| VM storefront | `refund_listing`, `arbitrate_listing` |
| API-credits storefront | `publish-from-quota` |
| Provisioning service | `POST relays`; the VM-domain job routes but `reset-password`; the `check-leases`, convergence `run-cycle` and `advance-cycle` routes |
| API-credits service | `credits_key_adjust` |

Every other authenticated route on every authority is `RERUN`, reads included. None of
the `RECORDED` responses carries a contact or a secret. The absolute setters —
pause and resume, registry publish and update, host and pool upserts — are `RERUN`: an
exact retry re-asserts what the same caller asked for. A retry that arrives after the
same caller's later write re-applies the older value; a retried registry publish
clears status overrides set since (`core/registry/src/core_registry/api/listing_routes.py`).
Only a caller that retries without waiting for its own acknowledgement meets this.

Rejected: `RERUN` only where the answer is identical, which keeps bodies whose re-run
answer already tells the caller what happened; making every unsafe route idempotent in
its domain now, which pulls negotiation, relays, refund and admin reserve into designs
of their own; recording the successful introduction start's body; recording consume,
the highest-volume route; giving `credits_key_adjust` an idempotency key now.

### D7 — Bounds, pruning and stores

Every row stores an `expires_at`, computed at insert from the request alone on the
authority's process time source:

- `RERUN`: origin + 2 × skew;
- `RECORDED`: origin + max(retention + skew, 2 × skew).

The origin rule depends on the route's kind. On a `RERUN` route the origin decides only
when the row is pruned; a re-signed retry that finds no row is dispatched, which its
declaration has proven safe, while `created` within the skew still refuses a captured
copy. On a `RECORDED` route, a first use needs an origin within the skew; a retry
whose origin is older than the retention, or that finds no row inside it, is answered
with the signed 410 (D8). A provisioner retrying a capacity-released notification for
hours under one request identity (`compute-provisioning-contract`) is therefore
dispatched again and converges.

Pruning runs on write: every reservation deletes a bounded batch of expired rows,
through an index on `expires_at`, in its own transaction, so authorities without a
loop controller need none. The component has no in-memory backend for production;
every authority binds the store to its own database — the API-credits service its
credits database, the provisioning-hosted site provisioning's — replacing `kit/site`'s
`InMemoryReplayStore` default, which accepted a replay across a restart and could not
hold a `RECORDED` outcome. An in-memory backend remains a test double only.

The retention is `authenticated_requests.recorded_outcome_retention_seconds`, a
positive integer defaulting to 86400 when absent, in each authority's layered settings
and Helm values schema, following `contact-exchange`'s `retention_seconds`.

Rejected: a sweep loop per authority, which most authorities would have to gain; an
in-memory production store.

### D8 — Recorded outcomes: a signed request origin, a configurable retention, a signed 410

Every version 3 request carries `Market-Request-Origin`, its first signing time, kept
unchanged on every retry while each re-signing gets a fresh `created`. It is covered by
the signature and part of the request hash, so a changed origin is changed reuse. An
origin may not be later than now + skew. This lets a receiver refuse a too-late retry
of a `RECORDED` route from the request alone, so every row is bounded (D7) and nothing
is kept indefinitely.

The retention of recorded outcomes is operator-configurable per authority and defaults
to 24 h when the setting is absent; `marketplace-identity` publishes the default, as the
Idempotency-Key draft asks a resource to publish its expiry.

An exact retry of a `RECORDED` route whose outcome is no longer held is answered with a
signed `410 Gone`, body `{"code": "exact_retry_expired", "detail": "…"}`, distinct from
the 409 of an attempt in progress or a changed reuse.

Rejected: a hash-only tombstone kept forever, which never ends the growth; a UUIDv7
request ID carrying the origin, which makes the ID's format a security input every
client must honour; deleting the row at expiry and re-running a late retry, which
double-applies; a retention fixed in code; a 409 for an expired outcome.

### D9 — Version 3 replaces version 2 in one release; the 0.4.0 tables are dropped and the space reclaimed

The release that introduces version 3 stops accepting version 2: every authority and
typed client moves together, and a version 2 request is refused as an unsupported
protocol (D11). Before 1.0 a versioned contract's introducing release may stop
accepting the one before (`docs/guidance/engineering/versioning.md`), clients upgrade
with the storefront (`docs/guidance/repository/package-versions.md`), and the release
record, read at `marketplace-v0.4.0`, shows no party that cannot. No compatibility path
is built, so none retires.

One migration per service drops the 0.4.0 replay table: a core storefront migration for
`auth_replay_reservations`, the provisioning chain for
`provisioning_replay_reservations`, an Alembic revision for
`publisher_replay_reservations`. Under the cutover no version 2 retry can arrive, so the
old reservations protect nothing; replay rows are not evidence. `kit/schema-migrations`
lets a migration declare that it frees space, and the migrate command then runs
`VACUUM` on a SQLite database after applying the chain, outside any transaction, in the
deployment phase; the registry's PostgreSQL returns the space on `DROP TABLE`. The first
backup after the upgrade is small.

Rejected: accepting both versions for a release, with its compatibility path and
retirement row, which no deployed party needs; carrying the reservation hashes forward;
keeping the old tables until they age out; an operator `VACUUM` step; leaving the file
at its peak size.

### D10 — The audience is the caller's expected-authority set

`Market-Audience` is a structured list of the principals the caller would accept the
answer from: the trust set it already passes to response verification. An authority
accepts a request only when its own signing principal is in the list. A request
captured for one authority fails at any other; rotation needs no step, since during an
overlap the caller's set holds both principals and whichever the authority signs with is
in it. Two authorities sharing one principal are one trust domain, as they already are
for response verification.

```http
Market-Audience: ed25519:Hq7kZp0TnR4vW9xYcB2dLmS8eJ5fQ1gA6uIoN3hK7rE, ed25519:Pw3eNc8yLq1sF6tVb0zXk4dRm7aJh2gU9oIiT5uYxCQ
```

**D10a — Signed deliveries bind their endpoint.** `kit/delivery`'s webhook sink signs a
one-way delivery to an endpoint known only by its URL, with no expected authority, so a
signed delivery covers RFC 9421's `@target-uri`, the configured webhook URL, in place of
`Market-Audience`, and the receiver checks it against its own endpoint.

Rejected: a stable authority name, which needs a name on every authority and in every
listing; the URL origin for authority requests, which reintroduces proxy and naming
fragility; one principal with configured predecessors, which adds a step to every
rotation; leaving signed deliveries unbound.

### D11 — Paths route; the stated operation is checked; every answer that names a request is signed

The authority routes by method and path; the stated operation and resource must equal
what the route derives. Every answer is signed when the request carries a request
identity:

| Failure | Status | Signed body | Bound over |
|---|---|---|---|
| No route serves the path or method | 404, or 405 with `Allow` | `{"code": "operation_not_served", "operation": "capacity_reserve"}` | the stated operation, resource and request ID |
| The route binds another operation or resource | 400 | `{"code": "operation_mismatch", "stated": {…}, "bound": {…}}` | the route's operation and resource |
| The audience does not include this authority | 421 Misdirected Request | `{"code": "audience_mismatch"}` | the route's operation and resource |
| An unsupported protocol tag, version 2 included | 400 | `{"code": "unsupported_protocol", "supported": ["arkhai.market-request.v3"]}` | the stated fields where the request carries them |

An answer is unauthenticated only when the request carries no request identity. Bodies
name what the caller sent and the authority's expectation, and never list the operations
an authority serves.

Rejected: routing by the stated operation, which replaces seven routers for a problem no
deployment has reported; one status for every refusal; keeping unroutable answers
unsigned.

### D12 — Version 2 remains a readable evidence format

Version 2 signed responses are retained as evidence (bare metal's `seller-response:`
capture, deal-servicing's `lifecycle_response`, deal-lifecycle acknowledgements, VM
pricing records) for each deal's own retention, so `kit/identity` keeps verifying
version 2 envelopes as a permanent evidence format, never accepted on the wire
(`docs/guidance/engineering/persistence.md`, "A retained record stays readable"). No
release can be named after which no version 2 evidence remains, so this is current
behaviour rather than a compatibility path with a retirement
(`docs/guidance/engineering/retiring-compatibility.md`).

### D13 — `kit/identity` owns the wire names

`kit/identity` owns every version 3 field name, the profile tags, the refusal codes of
D11, and `exact_retry_expired`. Every client and authority imports them; no copies
remain.

### D14 — The restated requirements

- `marketplace-identity`: the version 3 profile with audience, stated operation and
  origin; the three jobs and their lifetimes; per-route exact-retry resolution; the
  retention and the 410; secrets never recorded; the signed-refusal table; version 2 as
  an evidence format.
- `physical-provisioning`: the authenticated provisioning boundary's exact retry per
  declaration; a failure after authentication recorded only on a `RECORDED` route.
- `registry-discovery`: durable replay reservation per declaration.
- `storefront-publication`: version 3, and exact retry per declaration.
- `introduction-delivery`: an exact replay of a failed start completes it; signed
  deliveries bind their endpoint.
- `compute-provisioning-contract`: a resent capacity-released notification is re-run.
- `api-credits`: `idempotency_key` required on consume.
- `deployment-state`: the migrate command's `VACUUM`, and the replay table owned by
  `kit/authenticated-requests`.

`settlement-servicing`'s identical-retry scenario concerns the payments service's own
replay, and `vm-storefront-fulfillment`'s settle-status retry already reads as a
re-run; neither changes.

### D15 — The VM callback middleware's refusals are signed

`domains/vms/storefront/src/market_storefront/middleware/service_peer_auth.py` returns
unsigned refusals; moving it onto the admission core signs them (D3, D11).

### D16 — The protocol-capability check is the signed `unsupported_protocol` refusal

A caller learns the protocols an authority accepts from the signed refusal, which lists
them (D11). No probe route is added.

### D17 — Identity pins move with the incompatible bump

Version 3 is an incompatible change to `arkhai-kit-identity`, a minor bump before 1.0
(0.5.0 to 0.6.0). Each dependent moves its declared bound to 0.6.0 in the form it uses
today, exact or lower bound. The remainder item asking for exact pins in `kit/site` and
`kit/arkhai-payments` is dropped: no rule asks for exact pins, and
`docs/guidance/engineering/versioning-python.md` prescribes lower bounds.

### D18 — `retain-authenticated-request-outcomes` is superseded

Its aims are met: outcomes are retained where a route declares `RECORDED`, with a
durable store per service (D5, D7); the API-credits service gets a durable provider
(D7); `exact_retry_safe` is replaced (D5); its expiry question is answered (D8). The
adjust idempotency key is dropped, since `credits_key_adjust` is `RECORDED`. Its index
row is marked superseded and deferred now, and this change's closeout archives it as
superseded.

### D19 — The split-off change and the neighbouring rows

`complete-service-identity-lifecycle` is proposed beside this change, `ready for design`,
in the service-to-service trust lesser goal, depending on
`sign-multi-language-credits-middleware`. Neighbouring rows in the change index,
`openspec/changes/README.md`, name what moved:

- `kit-owned-storefront-auth-and-persistence` composes `kit/authenticated-requests`; the
  replay and signing layer left it, and its version 2 wording becomes version 3;
- `sign-multi-language-credits-middleware` gains a dependency on this change, so it signs
  the version 3 profile, with the TypeScript and Rust RFC 9421 libraries;
- `replace-polling-with-authenticated-push` uses version 3 and the admission core;
- the campaign text records where the `service-identity-signing` remainder went.

The change keeps its name.

### D20 — Implementation cadence

Two rounds:

- **Round 1, the foundations, in two sessions.** Session 1: `kit/identity`'s version 3
  profile, opening with D2's EIP-191 and ASGI gate, the wire names (D13), the declaration
  vocabulary (D5), and the version 2 evidence reader (D12). Session 2: the standalone
  replay component, `kit/authenticated-requests`, both stores, its migrations, the
  migration engine's `VACUUM` (D9), and the double-dispatch harness (D5). Unit and
  conformance tests; reviewed before anything depends on it.
- **Round 2, the cutover, in three sessions.** Session 1: the registry, the provisioning
  service, the site kit and the API-credits service, and deal-servicing, with their typed
  clients, route declarations and double-dispatch cases, the table drops, the consume key
  and the retention setting. Session 2: the three storefronts, with their declarations and
  cases, the introduction change, and the VM callback's signed refusals. Session 3: the
  buyers' clients, the signed-delivery binding (D10a), the end-to-end lanes, and the
  documentation closeout promotes. Reviewed, then closeout.

The cutover is atomic (D9), so round 2 lands whole before any end-to-end lane passes.

## Open Questions

- **Request tracing may carry the origin.** Once request tracing carries a request's
  time in flight, the signed `Market-Request-Origin` (D8) may be replaced by that
  metadata. Revisit when a change introduces request tracing across the authorities.

## Consequences for other changes

- `contact-payload-retention` scoped its disclosure to the introduction record; with
  introduction routes `RERUN` and recording no body, the replay store holds no contact,
  and the disclosure's scope can widen at this change's closeout.
- `retain-authenticated-request-outcomes` is superseded (D18).
- `kit-owned-storefront-auth-and-persistence` composes the admission core (D3, D19).
- `sign-multi-language-credits-middleware` waits on this change (D19).
