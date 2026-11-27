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

### Signed messages retained as evidence

Found by section 6. Beside live authentication, signed HTTP messages are kept as
evidence that a third party verifies offline: the registry keeps each publisher's
version 2 request as `listings.publisher_publication` and in `publisher_updates`
(`core/registry/src/core_registry/api/publisher_auth.py`, `retained_request_evidence`)
and serves both in every listing read; the VM buyer verifies that publication to bind
accepted pricing to the seller's signed terms, and its negotiation evidence as version
2 envelopes (`domains/vms/buyer/src/arkhai_vms_buyer/pricing_record.py`);
`SignedEndDeliveryReceipt`
(`kit/deal-lifecycle-contracts/src/market_deal_lifecycle_contracts/models.py`) holds a
version 2 request and response, verified by `verify_end_acknowledgement`; the buyer
store, the storefronts and deal-servicing capture version 2 envelopes as evidence
items. Every carrier shipped in marketplace 0.4.0. The admission core's signed-outcome
hook (`kit/authenticated-requests`, `SignedOutcome`) carries the response but not the
signed request, and `kit/identity`'s capture seam is typed on version 2 envelopes.

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

- the signature's `tag` names the profile (`arkhai.market-request-signature.v3`,
  `arkhai.market-response-signature.v3`), so that only the version differs from
  version 2's protocol names; `keyid` is the complete principal; `alg` is omitted,
  so the principal's scheme selects the verifier, as verifier dispatch does today;
- the semantic fields are covered header fields: `Market-Role`, `Market-Operation`,
  `Market-Resource`, `Market-Audience` (D10), `Market-Request-ID`, and
  `Market-Request-Origin` (D8);
- `Market-Resource` is present exactly when the request's operation acts on one object
  — a listing, a negotiation, a reservation — and names that object's identifier; an
  operation with no target object, such as `listing.publish` or a collection read,
  carries no `Market-Resource`, and the route, not the request, says which kind an
  operation is (D21);
- the profile accepts one spelling of everything it signs: the covered components in
  the profile's order, the signature parameters in the order `created`, `keyid`,
  `tag`, the audience in its canonical list serialization, and one `sha-256`
  `Content-Digest`; any other spelling is refused as malformed, so a retained record
  of the signed values rebuilds the exact signature base (D21);
- every request covers RFC 9421's `@query`, the target URI's query string exactly as
  sent with its leading `?`, which is `?` alone for a request with no query, so a
  read's filters and paging are signed on every authority (D25);
- the request ID is a covered field, not the RFC's `nonce`, because an exact retry
  reuses it, re-signed;
- `Content-Digest` hashes the bytes sent, not canonical JSON;
- a response covers `@status` and `content-digest` and binds its request with the
  `;req` flag over the request's method, operation, resource (where the request
  carries one) and request ID. A request and a response each therefore have two
  coverage lists, with and without `market-resource`, and the operation fixes which.

```http
POST /api/v1/capacity/reservations HTTP/1.1
Content-Digest: sha-256=:X48E9qOokqqrvdts8nOJRJN3OWDUoyWxBf7kbu9DBPE=:
Market-Role: storefront
Market-Operation: capacity_reserve
Market-Resource: pool-gpu-a100
Market-Audience: ed25519:Hq7kZp0TnR4vW9xYcB2dLmS8eJ5fQ1gA6uIoN3hK7rE
Market-Request-ID: 0f6c2b1e7d4a4c1e9a523e8b6d0f1a77
Market-Request-Origin: 1795000000
Signature-Input: market=("@method" "@query" "market-role" "market-operation" "market-resource" "market-audience" "market-request-id" "market-request-origin" "content-digest");created=1795000000;keyid="ed25519:9mQ3vX2kq8sJdLr0aYbWcZtNeHf1uGpRiOxTyEwKjVs";tag="arkhai.market-request-signature.v3"
Signature: market=:3q2-7w...:
```

A request whose operation has no target object omits the field and its component:

```http
POST /listings HTTP/1.1
Content-Digest: sha-256=:X48E9qOokqqrvdts8nOJRJN3OWDUoyWxBf7kbu9DBPE=:
Market-Role: seller
Market-Operation: listing.publish
Market-Audience: ed25519:Hq7kZp0TnR4vW9xYcB2dLmS8eJ5fQ1gA6uIoN3hK7rE
Market-Request-ID: 0f6c2b1e7d4a4c1e9a523e8b6d0f1a77
Market-Request-Origin: 1795000000
Signature-Input: market=("@method" "@query" "market-role" "market-operation" "market-audience" "market-request-id" "market-request-origin" "content-digest");created=1795000000;keyid="ed25519:9mQ3vX2kq8sJdLr0aYbWcZtNeHf1uGpRiOxTyEwKjVs";tag="arkhai.market-request-signature.v3"
Signature: market=:3q2-7w...:
```

The implementation's first gate proves EIP-191 signing and verification through the
`http-message-signatures` library's algorithm interface, and a small ASGI adapter. If
that interface cannot take a scheme-dispatched algorithm, `kit/identity` implements
the profile's signature base itself and keeps the library as an interoperability
test oracle. The non-HTTP signed artifacts — rotation intents, payment receipts — keep
`kit/identity`'s own framing. The VM buyer's pricing record and the end-delivery
acknowledgement are not among them: the first rests on the seller's signed HTTP
publish request and the second is a signed HTTP response, so each is retained as a
record of a version 3 message (D21).

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
where the route declares one; sign every answer, refusals, unroutable requests and an
unexpected failure after authentication included (D11); and prune (D7). All seven
arrangements move onto it, storefront routes
included. Each authority keeps its own wiring: which roles and principals each route
admits, and where its trust comes from.

The component's interface, walked through every caller:

- one admission per request: `dispatch`, `rerun` (an exact retry the route lets the
  handler run again), `answered` (a recorded outcome or a refusal, already signed,
  `exact_retry_outcome_unknown` among them, D7), or `in progress`;
- an `exact_retry` flag on the admission, for handlers that re-run but must know it is
  a retry (VM settle's `refuse_after_end`, the credential reads);
- a signed-outcome hook that hands the caller the request's and the signed
  response's records with their bodies, for evidence capture, and the request's record
  and body on the admission itself (D23) (bare metal's `EvidenceSession.capture`, VM's
  `capture_negotiation`, deal-servicing's `lifecycle_response`);
- a middleware form for authorities that route by a contract table (provisioning, the
  site kit) and a request-dependency form for authorities that authenticate inside the
  route (registry, storefront controllers, deal-servicing), over one core;
- whichever form an authority uses, an application-level fallback the core installs
  around the whole application: a request carrying request identity (the profile's
  `Market-Request-ID` and signature fields) that no route admitted — a path or method
  no route serves, answered 404 or 405 by the router before any dependency runs — is
  verified and answered with D11's signed refusal, its body naming only what the
  caller stated;
- a route inventory, checked when the core is constructed over the application: every
  route in the application's route table carries an exact-retry declaration through
  its admission, in either form, an explicit unauthenticated mark (health and the
  OpenAPI document everywhere; the injected time route only where its authority does
  not sign it, as the registry's API-key `/admin/time`), or a public mark (the
  registry's descriptor read, D24), and the authority refuses to start naming any
  route that has none of them (D5). A signed time-setting route — a
  storefront's, the API-credits service's — carries a `RERUN` declaration, since a
  time-set only moves forward (D6), and the core applies to it the freshness exemption
  `marketplace-identity`'s "The time-setting operation is exempt from request
  freshness" gives it (design review 27, F5). If the round 1 gate finds the framework's
  route table cannot tell an admitted route from one that is not, the dependency form
  registers each declaration in an explicit table at import, and the inventory reads
  that;
- a signed 500 for an unexpected failure after authentication: a handler that raises
  is answered with a signed 500 carrying a fixed detail that reveals nothing of the
  error, and the error is logged; on a `RECORDED` route the 500 is the attempt's
  recorded outcome, so an exact retry receives the same signed answer and is never
  dispatched, and its effect is unknown: the core sees the error, not where the
  handler committed, so a write may have applied before it (`KeysService.adjust`
  commits before it builds its answer), and the caller reads current state before any
  new write, as after `exact_retry_outcome_unknown` (D7); on a `RERUN` route nothing
  is recorded. A failure of the replay store while admitting a request is not this
  500 but the signed 503 `admission_unavailable` (D7, design review 61 F1). This
  generalizes `physical-provisioning`'s existing requirement, which
  `unbacked-bare-metal-listings` delivered for provisioning and the site kit, to every
  authority on the core;
- a lease renewal around a `RECORDED` attempt: in either form, the core renews the
  attempt's lease while its handler runs and stops when the handler returns or raises
  (D7).

*Design review 35, F2:* D3 first said a `RECORDED` 500 was recorded once the domain
write had rolled back, so an exact retry learned that nothing applied. The core cannot
know that, and the owner judged that a 500 only says something went wrong on the
server, whose side effects cannot be ruled out. A route that wants to promise a caller
more — that a failure applied nothing — does so with a specific error code and message
and atomicity its code enforces, designed with that route; the owner rejected a
per-route rollback declaration the core would have to trust and could not check.

The fallback and the inventory settle design review 16's F2: the request-dependency
form alone never runs for an unmatched request, so the registry's handler, which signs
only when route authentication left its object on `request.state`
(`core/registry/src/core_registry/main.py`), answers an unmatched path unsigned, and a
core reached only through the routes that call it cannot see one that forgot to. Moving
every authenticated route onto a contract-driven router would remove the two forms and
is the cleaner long-term shape, but it rewrites seven routers; the owner recorded it as
its own change, `contract-driven-authenticated-routing` (D19). The signed 500 settles
16 F5.

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
  reserve, lease, renew, resolve (RERUN/RECORDED), record, expire, sweep over an opaque key and hash;
  sqlite3 and SQLAlchemy stores; its DDL as published statements; ASGI and dependency wrappers
        ▲
kit/authenticated-requests          foundation kit; authorities only
  the admission core: version 3 verification through kit/identity, audience, trust,
  Market-* fields, signed refusals and 500s, the signed-outcome hook, the unmatched-request
  fallback, the route inventory, the sweep's lifespan task;
  wraps the component's DDL into kit/schema-migrations migrations
        ▲
kit/identity                        foundation kit; every client and contract may use it
  the version 3 profile (sign and verify request and response parts), wire names (D13),
  the exact-retry declaration vocabulary as data (D5), the evidence records and their
  verifiers, version 2 read beside version 3 (D12, D21, D22)
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
- `RECORDED` — the outcome is kept for the retention (D8).

There is no third mode. A `REFUSE` mode — an exact retry refused with nothing recorded,
for an outcome that can neither be recorded nor run again — had no expiry, no
first-use rule and no answer to a retry once its row was gone, after which a retry is
indistinguishable from a first use, and no route used it (design review 16, F4). A
route that needs it is designed with its whole lifecycle when it arrives (D6).

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
per operation: the request, then a later write to the same resource, then the first
request's exact retry re-signed, through the real admission core and application,
asserting that the domain state after the retry equals the state before it (the replay
table excluded) — the retry undoes nothing the later write did — and that the retry's
answer is the route's current answer. The interleaved write is what tests D6's
criterion (16 F3); a retry straight after its request proves only idempotence. A completeness test per authority fails when a `RERUN`
operation has no case. Test level: integration, the lowest at which the real handler
and database exist (`docs/guidance/engineering/test-levels.md`).

Rejected: a per-authority mapping beside the routes, which drifts; a default of re-run,
which double-applies a new non-idempotent mutation; a default of recorded, which is the
body retention this change removes; a default of refuse, which surfaces a forgotten
declaration only as a runtime 409; proof by review alone.

### D6 — Which routes keep a recorded outcome

A route is `RERUN` only where its domain recognises the retry as already applied, so
that a re-run after any later write changes nothing, and its answer still tells a
caller who lost its acknowledgement what happened. That holds for keyed and monotonic
operations: consume carries its idempotency key, terminate and the capacity-released
notification name the lease they act on, a heartbeat or time-set only moves forward.
Idempotence alone is not enough: an absolute setter is idempotent against itself but
does not commute with a later write, so a delayed retry, or one from another client
under the same principal, would re-assert an older value over a newer one. Everything
else is `RECORDED`, whose outcome answers the retry within the retention and whose
signed 410 answers it after (D8); the replay layer remembers what the domain cannot
recognise.

A secret in the request is never recorded under either declaration: the replay store
keeps only the request's hash and, on a `RECORDED` route, the response. Only a secret
in the response constrains the declaration. A response carrying a secret is never
`RECORDED`: its route is `RERUN` where the re-run supersedes the lost answer (credits
issuance rotates an unused key's secret), and a route whose secret a re-run cannot
supersede is not admitted until a design gives it a mode with its whole lifecycle
(D5). The plan's route check applies this distinction to every route it classifies.

*Design review 27, F4:* D6 first listed relay `token` rotation, relay
`grant-keys/stage` and VM `reset-password` beside issuance as secret-bearing `RERUN`
routes. None answers a secret. Rotation replaces the relay's token with the one the
request supplies and answers a redacted `RelayView`; staging replaces any staged key,
supplied or generated, and answers its public half
(`provisioning/compute/src/compute_provisioning/relays/service.py`). As `RERUN` routes
both fail the interleaved-write test: an old exact retry of a rotation restores a token
rotated away since, and an old staging overwrites a key staged since, whose public half
the operator may already have added to the relay's plugin. Both are therefore
`RECORDED`, holding a redacted view or a public key, no more than `POST relays` holds.
`reset-password` answers a job submission, its password fetched afterwards from the
job's credentials read, and derives the job's operation ID from the request
(`domains/vms/provisioning/adapter/src/vm_provisioning_adapter/controllers/vms_controller.py`):
it is `RERUN` as a keyed operation, which the plan's route check confirms. The owner
chose the reviewer's first alternative over domain guards recognising an older retry,
which would need durable domain changes for the same effect, and over refusing later
rotations while an earlier request may still retry, which blocks normal operator work.

The plan checks every authenticated route on every authority against this criterion
and names its declaration; the table below is the set known at design.

*Design review 16, F3:* D6 first made the absolute setters `RERUN` on the ground that
an exact retry re-asserts what the same caller asked for, bounding the harm to a caller
that retries without waiting for its acknowledgement. The authority cannot rely on that
premise: the lease admits a retry at any time, the origin rule admits a `RERUN` retry
hours later, and another client may share the principal. The registry's publish
replaces `published_document` and pops the status and oracle overrides, so a delayed
retry clears an operator's later override; its delete removes whatever listing holds
the ID, so a delayed retry deletes a listing republished since
(`core/registry/src/core_registry/api/listing_routes.py`). The owner considered
ordering writes by the signed origin and request ID and chose the criterion above:
the origin is the caller's clock, admitted within the skew, so it orders
deterministically but not causally across clients and principals, and it would make a
client's clock an input to domain state (the concern D8 rejects a UUIDv7 request ID
on). Ordering distinct concurrent writes is domain concurrency control, whose standard
form is a conditional request refused when stale; no change takes it on now, and a
setter that gains it may then be `RERUN`.

Two small domain fixes come with this: `idempotency_key` becomes required on
`credits_key_consume` and `consume-batch` in the version 3 wire models (every gate
already mints one), and `introduction-delivery` changes so that an exact replay of a
start whose completion failed completes it, as a new start does; seller dispatch stays
once-only through its claim.

The `RECORDED` set:

| Authority | Routes |
|---|---|
| VM, bare-metal and API-credits storefronts | `negotiate_new`, `negotiate_continue`, `admin_advance_negotiation`, `admin_force_accept_negotiation`, `admin_reserve_capacity`, `admin_release_reservations`, `admin_run_lifecycle_cycle`, `admin_refresh_site_projections`; trading and listing pause and resume |
| VM storefront | `refund_listing`, `arbitrate_listing` |
| API-credits storefront | `publish-from-quota` |
| Registry | listing publish, update and delete |
| Provisioning service | `POST relays`, relay `token` rotation and relay `grant-keys/stage`; host and pool upserts and deletes; the VM-domain job routes but `reset-password`; the `check-leases`, convergence `run-cycle` and `advance-cycle` routes |
| API-credits service | `credits_key_adjust` |

Every other authenticated route on every authority is `RERUN`, reads included. None of
the `RECORDED` responses carries a contact or a secret. The absolute setters and
deletes are `RECORDED`: their bodies are small, and 24 hours of them is bounded, where
the growth this change removes was not.

Rejected: `RERUN` only where the answer is identical, which keeps bodies whose re-run
answer already tells the caller what happened; `RERUN` for every idempotent route,
absolute setters included, which lets a delayed retry clobber a later write (16 F3);
ordering writes by the signed origin, which is deterministic but not causal; making
every unsafe route idempotent in its domain now, which pulls negotiation, relays,
refund, admin reserve and every setter into designs of their own; recording the
successful introduction start's body; recording consume, the highest-volume route;
giving `credits_key_adjust` an idempotency key now.

### D7 — Bounds, pruning and stores

Every row stores an `expires_at` on the authority's process time source: the later of
its bound, computed at insert from the request alone, and its lease deadline, raised whenever a lease is reclaimed or renewed:

- `RERUN`: origin + 2 × skew;
- `RECORDED`: origin + max(retention + skew, 2 × skew).

The lease floor keeps a row while its attempt runs (design review 16, F1). A `RERUN`
request with an old origin — the capacity-released notification below — has a bound
already in the past; without the floor, a sweep could delete its row while its handler
ran, and a concurrent exact retry, finding no row, would dispatch a second time. A
first use with a fresh origin is unaffected: its bound is at least arrival + skew,
beyond any lease.

An expired row is treated as absent: it answers nothing and refuses nothing, and a
reservation under its key replaces it. Expired rows wait for the sweep, so this is what
keeps a leftover row from refusing a request that should be served (16 F6).

A `RECORDED` attempt is dispatched once. Its outcome is recorded after the handler
returns, in the store's own transaction. While the handler runs, the core renews the
attempt's lease: a task beside the handler, in either form, extends the lease every
third of its period and stops when the handler returns or raises, so a live attempt
keeps its lease however long it runs while its store can be written, and otherwise only
an attempt whose process is gone loses it. An exact retry that finds the row with no
outcome is refused as in progress while the attempt's lease is held. Once the lease has
ended, the retry concludes the attempt before it is answered: one conditional write in
the store marks the row concluded where it still has no outcome and its lease has
ended, keeping the attempt's owner, so that the attempt's outcome is still recorded
when its handler returns and a later exact retry receives it. Only a retry whose
concluding write applied, or that finds the row already concluded, is answered with a
signed 409 whose body code is `exact_retry_outcome_unknown`, and it is never
dispatched. The concluding write takes the store's write lock, so on the authority's
own SQLite database the answer cannot overtake a transaction the attempt still holds: under
SQLite, whose one writer the handler's transaction is, a handler writing in one
transaction has committed or rolled back before its retry is told the outcome is
unknown, whichever store the authority uses, the SQLAlchemy store's plain read
included. A database with finer locks, PostgreSQL among them, gives no such order: a
handler's transaction on its own tables does not conflict with the replay row, so the
answer may precede its commit, and the requirement promises the order only on SQLite.
Under SQLite that answer therefore
means, but in the cases below, that the attempt ended without recording: none of its
local writes can still commit. A lease is reclaimed only
on a `RERUN` route, where a second run is proven safe (D5). A caller told the outcome is
unknown, or answered a recorded 500 (D3), learns what applied by reading current state,
as it does after the 410 (D8), and sends any further write under a new request ID.

A failure to reserve, resolve or conclude a request — its store refusing or timing
out, as a store locked by a long transaction does — is answered with a signed 503 whose
body code is `admission_unavailable`, on either route kind. It tells the caller that
nothing about the request was concluded, so the caller retries the same request rather
than reading state and replacing it; the first attempt may still be running. It is
never the signed 500, which means only that a route raised after it was admitted (D3).

Renewal writes the store only for an attempt running longer than a third of its lease,
so an ordinary request costs nothing more. Four cases stay outside the guarantee: a
handler that blocks the event loop past the whole lease, which stalls its renewal and
is a defect of that handler; a store unwritable for the whole lease while the handler
outlasts it, after which the handler's first write commits after its retry concluded
the attempt; a handler that writes across several transactions, a later one committing
after the conclusion — each of these two logged by the renewal as an error naming the
request when it finds the lease lost; and a call to another authority that an ended
attempt had already sent, which that authority's state settles, as the plan's route
check below covers. The route check of an authority on SQLite also names any
`RECORDED` route holding a write transaction near its lease period, and any writing in
more than one transaction.

*Implementation review 45, F1:* the renewal retried a store's every failure and stopped
when a renewal found the lease ended, and neither stopped the handler, so a store
refusing renewals for a whole lease let the lease end under a live attempt and its
retry be told the outcome is unknown. The owner chose to name this the third case
above, logged as an error and its sequence proven through the core, over cancelling the
handler when its lease is lost, which narrows the window only for an async handler at
its next await and adds a cancellation path every `RECORDED` handler must tolerate, and
over answering in progress until a recorded outcome or the 410, rejected under 35 F3,
or recording the outcome in the handler's transaction, rejected under 27 F1.

*Design review 61, F1:* the 45 F1 resolution still told a retry the outcome was unknown
while the attempt could commit, and a log reaches the operator, not the caller, so a
caller following the instruction to read state and replace could be overtaken by the
original's late commit, the 35 F3 sequence in a case the design admitted. The
`sqlite3` store already ordered the answer, every step opening with `BEGIN IMMEDIATE`,
but the registry's SQLAlchemy store answered a retry older than the skew through a
plain read while its handler held the write lock; and the core answered a failed
reservation with the route-failure 500, so a retry meeting a busy or failing store was
told to read state while a healthy attempt still ran. The owner chose that a retry
conclude the attempt by a write before it is told the outcome is unknown, and that a
failed admission be a signed 503, narrowing the residual to an outage spanning a whole
lease and a handler writing in several transactions, over restating the guarantee as
holding except after a logged lease loss, which left the registry's case open; over
answering in progress until an outcome or the 410, rejected under 35 F3; and over a
shared unit of work, rejected under 27 F1. The plan proves it with a retry arriving
while a handler holds the database's write lock, answered only after that handler's
commit, then a read and a replacement write that the original no longer overtakes, in
both stores; and a retry whose reservation fails, answered the 503.

*Implementation review 71:* the 5b notes recorded that the requirement promised the
conclusion's order on any database while the concluding write gives it only under
SQLite's one write lock. The owner chose to narrow the requirement to the authority's
own SQLite database over giving PostgreSQL an order of its own.

*Design review 35, F3:* the 27 F1 triage answered `exact_retry_outcome_unknown` once a
fixed lease ended, and told the caller to read current state. A handler still running
past its lease could then commit after that read, and a replacement write sent on it
could be overwritten by the older one, most plainly for the absolute setters D6 made
`RECORDED`. The owner chose renewing a live attempt's lease, so that the answer means
the attempt has ended, over keeping the fixed lease and telling callers to poll the
exact retry until a recorded outcome or the 410 before writing again, which would leave
a crashed attempt's caller waiting out the retention or needing an operator.

*Design review 27, F1:* the 16 F3 triage required a `RECORDED` outcome to commit in the
same transaction as the handler's domain write, so that a crash between them could not
leave a write applied with no outcome for a reclaimed lease to find and dispatch again.
Nothing gave the core that transaction: `KeysService.adjust` opens its own session and
commits before it returns
(`domains/apicredits/service/src/apicredits_service/services/keys_service.py`), the
site middleware sees the response only after the handler returns, and provisioning's
durable store records in its own session and reclaims an expired lease for a second
dispatch. A handler running longer than its lease met the same double dispatch without
any crash. The owner chose never to dispatch a `RECORDED` attempt again over a shared
unit of work, which would change every `RECORDED` handler's interface in both forms and
still could not hold for the handlers that call other services (`admin_reserve_capacity`,
the lifecycle cycle), and over making adjust idempotent in its domain, which fixes one
route of the many. The crash boundary is proven by an integration case: a crash after
adjust's commit and before its outcome is recorded, whose exact retry is answered
`exact_retry_outcome_unknown` with the balance adjusted once; a second, that a handler
running past its lease is renewed, its exact retry refused as in progress and then
answered with the recorded outcome; and a third, that a write raising after it commits
is answered with a recorded 500 whose exact retry dispatches nothing, the balance
adjusted once. Where a `RECORDED` route's
caller could not learn by reading whether its write applied, that route would need the
unit of work; the plan's route check names any such route.

The origin rule depends on the route's kind. On a `RERUN` route the origin decides only
when the row is pruned; a re-signed retry that finds no row is dispatched, which its
declaration has proven safe, while `created` within the skew still refuses a captured
copy. On a `RECORDED` route, a first use needs an origin within the skew; a retry
whose origin is older than the retention, or that finds no row inside it, is answered
with the signed 410 (D8). A provisioner retrying a capacity-released notification for
hours under one request identity (`compute-provisioning-contract`) is therefore
dispatched again and converges.

Pruning is a periodic sweep the admission core owns. The core starts it from the
lifespan each authority already composes, so no authority writes a loop of its own: it
runs once at startup, then every `authenticated_requests.replay_prune_interval_seconds`,
deleting expired rows through an index on `expires_at` in bounded batches, each its own
transaction, so a backlog never holds SQLite's write lock for long. Replicas or workers
each sweeping is harmless; the delete is idempotent. Between sweeps a store holds at
most one interval of `RERUN` rows beside the retention's `RECORDED` rows, small rows
either way; the startup sweep covers an upgrade or restart. Expired rows are therefore
deleted within one interval of their expiry, and none affects an answer meanwhile
(16 F6). The component has no in-memory backend for production;
every authority binds the store to its own database — the API-credits service its
credits database, the provisioning-hosted site provisioning's — replacing `kit/site`'s
`InMemoryReplayStore` default, which accepted a replay across a restart and could not
hold a `RECORDED` outcome. An in-memory backend remains a test double only.

The retention is `authenticated_requests.recorded_outcome_retention_seconds`, and the
sweep's interval `authenticated_requests.replay_prune_interval_seconds`; each is a
positive integer defaulting to 86400 when absent, in each authority's layered settings
and Helm values schema, following `contact-exchange`'s `retention_seconds`.

*Design review 16, F6:* D7 first pruned on write — every reservation deleting a batch
in its own transaction, which under steady traffic is an extra write commit per request
— and rejected a sweep because most authorities would have to gain a loop. The owner
judged per-request pruning the wrong trade: growth only needs keeping in check, which a
daily sweep does, and the core can own the loop through the lifespan, so no authority
gains one.

Rejected: pruning on every reservation, which costs a commit per request for no
urgency; a loop written in each authority; an in-memory production store; committing a
`RECORDED` outcome in the handler's domain transaction through a shared unit of work
(27 F1); reclaiming a `RECORDED` attempt's expired lease for a second dispatch; a fixed
`RECORDED` lease with callers polling the exact retry until an outcome or the 410
(35 F3); answering `exact_retry_outcome_unknown` from a read, and holding the guarantee
only outside a logged lease loss (61 F1).

### D8 — Recorded outcomes: a signed request origin, a configurable retention, a signed 410

Every version 3 request carries `Market-Request-Origin`, its first signing time, kept
unchanged on every retry while each re-signing gets a fresh `created`. It is covered by
the signature and part of the request hash, so a changed origin is changed reuse. An
origin may not be later than now + skew, except on the time-setting operation mounted
under injected time: its request is first signed at the instant it sets, so its origin
and `created` are as far ahead as the advance, and it is exempt from both bounds while
its signature, principal, operation, resource and request-ID reservation are checked as
every request's (`marketplace-identity`'s "The time-setting operation is exempt from
request freshness"). Its row is `RERUN`, bounded at origin + 2 × skew, which once the
set lands is the authority's new instant plus twice the skew. A typed client's advance
beyond the skew is tested end to end through the core (design review 35, F1). This lets a receiver refuse a too-late retry
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
deployment phase. The registry runs SQLite by default (its chart's `databaseUrl`) and
migrates through Alembic rather than that engine, so its migrate command applies the
same rule itself: once the revision dropping `publisher_replay_reservations` has
applied on SQLite, it runs `VACUUM` after the upgrade, outside any transaction; on
PostgreSQL, `DROP TABLE` returns the space. The first backup after the upgrade is
small.

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
what the route derives, and a request for an operation with no target object must
state no resource, as one with a target must state its identifier (D2, D21); either
difference is an `operation_mismatch`. A request carries a request identity when it carries the
version 3 profile's covered fields `Market-Request-ID` and `Market-Operation`, with
`Market-Resource` where it states one, over which D2's response binds its request. Every answer is signed
when the request carries a request identity:

| Failure | Status | Signed body | Bound over |
|---|---|---|---|
| No route serves the path or method | 404, or 405 with `Allow` | `{"code": "operation_not_served", "operation": "capacity_reserve"}` | the stated operation, resource and request ID |
| The route binds another operation or resource | 400 | `{"code": "operation_mismatch", "stated": {…}, "bound": {…}}` | the route's operation and resource |
| The audience does not include this authority | 421 Misdirected Request | `{"code": "audience_mismatch"}` | the route's operation and resource |
| An unsupported protocol tag | 400 | `{"code": "unsupported_protocol", "supported": ["arkhai.market-request-signature.v3"]}` | the stated fields, when the request carries a request identity; unsigned otherwise, a version 2 request included |

An answer is unauthenticated only when the request carries no request identity. Bodies
name what the caller sent and the authority's expectation, and never list the operations
an authority serves.

A version 2 request carries none of the version 3 fields — its request ID is
`X-Market-Request-ID`, and its route supplies the operation and resource — so its
`unsupported_protocol` refusal is unsigned, and no identity is invented to sign it. An
old typed client verifies only version 2 responses, so it could not verify a version 3
refusal however it were signed, and a new typed client never sends version 2: the old
client fails on the unauthenticated answer, and the body's code tells whoever reads its
log why. A request under a later profile that keeps the version 3 field names is
refused signed over them (D16).

*Design review 27, F2:* D11 first promised a signed refusal wherever a version 2
request carried identity, but D2's response binding needs request components a version
2 request lacks. The owner chose the unsigned answer over a separate signed refusal over
version 2's fields, a second verification path no caller could use, and over signing it
in the version 2 format, the compatibility path D9 rejects.

Rejected: routing by the stated operation, which replaces seven routers for a problem no
deployment has reported; one status for every refusal; keeping unroutable answers
unsigned.

### D12 — Version 2 remains a readable evidence format

Version 2 signed requests and responses are retained as evidence for each deal's own
retention and for a listing's life: the registry's publication and update evidence,
the buyer store's `signed_request` and `signed_response` items, the end-delivery
receipt in the buyer's end journal, the VM storefront's `buyer-envelope:` and
`seller-envelope:`, bare metal's `seller-response:`, deal-servicing's
`lifecycle_response` and `buyer-end-envelope:`, and the VM buyer's retained pricing
records. Every one of these carriers shipped in marketplace 0.4.0. `kit/identity`
keeps verifying version 2 envelopes as a permanent evidence format, never accepted on
the wire (`docs/guidance/engineering/persistence.md`, "A retained record stays
readable"), through the same evidence verifiers that read version 3 records, which
tell the two apart by the record's `protocol` (D21, D22). No release can be named
after which no version 2 evidence remains, so this is current behaviour rather than a
compatibility path with a retirement
(`docs/guidance/engineering/retiring-compatibility.md`).

### D13 — `kit/identity` owns the wire names

`kit/identity` owns every version 3 field name, the profile tags, the refusal codes of
D11, `exact_retry_expired`, `exact_retry_outcome_unknown` and `admission_unavailable`
(D7), and the field names
of the evidence record (D21). Every client and authority imports them; no copies
remain.

### D14 — The restated requirements

- `marketplace-identity`: the version 3 profile with audience, stated operation and
  origin; the three jobs and their lifetimes, the lease floor, expired rows treated as
  absent, and the periodic sweep; per-route exact-retry resolution, `RERUN` only where
  the domain recognises a retry; a `RECORDED` attempt never dispatched twice, its
  lease renewed while its handler runs, an ended attempt with no outcome answered
  `exact_retry_outcome_unknown`; the retention and the 410;
  secrets never recorded; the signed-refusal table, unmatched requests included, a
  version 2 request's refusal unsigned, and the signed 500 after authentication on
  every authority, its effect unknown on a `RECORDED` route; the time-setting
  operation exempt from the origin's bound as from `created`'s; the route inventory refusing to start; version 2 as an evidence
  format; the profile's tags, its one accepted spelling and `Market-Resource` only
  where the operation has a target; a signed message retained as evidence verifying
  offline as a record of its signed values, under either version (D21, D22); every
  request covering `@query` (D25); a public operation answered signed, the registry's
  descriptor read the only one (D24).
- `registry-discovery`: the registry's authentication under version 3, its query values
  covered by `@query` (D25); the descriptor a public read whose signed answer the
  bootstrap verifies (D24); the filter-spec ETag a query parameter (D26); an applied
  rotation or retirement answering its exact retry first (D27).
- `registry-discovery`: seller publication evidence as `publication` and `updates`,
  each the body bytes and the seller's request record (D21).
- `deal-lifecycle`: the end-delivery acknowledgement signed under version 3; each
  party's commitment envelopes kept, and captured at the signed transport boundary, as
  signed records with their exact bodies (D21, D23).
- `physical-provisioning`: the authenticated provisioning boundary's exact retry per
  declaration, a lease reclaimed only on a `RERUN` route; a failure after
  authentication recorded only on a `RECORDED` route, the general rule now
  `marketplace-identity`'s.
- `registry-discovery`: durable replay reservation per declaration, listing publish,
  update and delete `RECORDED`.
- `storefront-publication`: version 3, and exact retry per declaration, pause and
  resume `RECORDED`.
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

A caller learns the protocols an authority accepts from the `unsupported_protocol`
refusal, which lists them (D11), signed when its request carries the version 3 field
names and unsigned for a version 2 request. No probe route is added.

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

`contract-driven-authenticated-routing` is proposed beside it, `ready for design`,
depending on this change: every authenticated route on every authority moves onto a
router driven by its route contract, so the request-dependency form, the
unmatched-request fallback and the route inventory (D3) give way to one form that sees
every route. Design review 16's F2 found the two-form seam; the owner judged the
migration the cleaner long-term solution and too large for this change.

The change keeps its name.

### D20 — Implementation cadence

Four rounds. Rounds 1 and 2 are implemented and reviewed; round 3 was added when
section 6 stopped a second time, on the descriptor bootstrap and the unsigned query
(D24–D26, D29); round 4 is the cutover as first planned, with the registry's share of
D26–D28 in its first session:

- **Round 1, the foundations, in two sessions.** Session 1: `kit/identity`'s version 3
  profile, opening with D2's EIP-191 and ASGI gate, the wire names (D13), the declaration
  vocabulary (D5), and the version 2 evidence reader (D12). Session 2: the standalone
  replay component, `kit/authenticated-requests`, both stores, its migrations, the
  sweep, the `RECORDED` lease renewal, the unmatched-request fallback, the route
  inventory and the signed 500 (D3, D7), the migration engine's `VACUUM` (D9), and the double-dispatch harness with its
  interleaved write (D5). Unit and
  conformance tests; reviewed before anything depends on it.
- **Round 2, the foundation amendments, in one session.** `kit/identity`: the renamed
  tags, the one accepted spelling, `Market-Resource` only where the operation has a
  target, the evidence records, the two evidence verifiers reading either version,
  and the version 3 capture seam (D2, D21–D23). The admission core: the request record
  on the admission and both records on the signed outcome, the resource-absence
  check, and the signed 503 `admission_unavailable` (D7, D11, D23). The replay
  component: the concluding write before `exact_retry_outcome_unknown`, in both stores
  (D7, design review 61 F1). Unit and library integration tests, the record round trip
  under both schemes and a retry behind a handler's held write lock among them;
  reviewed before the cutover depends on it.
- **Round 3, the second foundation amendments, in one session.** `kit/identity`:
  `@query` in both request coverage lists, in the request record and in rebuilding
  the signature base, the one query encoding the typed clients sign and send, and the
  public request builder with the binding its answer is verified against (D24, D25).
  The admission core: the public route mark in the route inventory, the raw query
  string handed to verification in both forms, the request hash over the query, and a
  public route refusing signature fields as malformed (D3, D24, D25). Unit and
  library integration tests, a record round trip with a non-empty query, a request
  whose query was altered after signing refused, and a public read answered signed and
  verified through the builder's binding among them; reviewed before the cutover
  depends on it.
- **Round 4, the cutover, in three sessions.** Session 1: the registry, with
  `publication` and `updates` and their column rename (D21), the public descriptor
  read and the bootstrap client (D24), the filter-spec ETag as a query parameter
  (D26), the rotation and retirement retries answered first (D27), the provisioning
  service, the site kit and the API-credits service, and deal-servicing, with its
  lifecycle evidence and the end-delivery receipt as records (D23), with their typed
  clients, route declarations and double-dispatch cases, adjust's crash-boundary, renewed-lease and post-commit 500 cases (D7), the relay rotation and staging interleaved-write cases (D6), the table drops, the consume key
  and the retention and sweep-interval settings. Session 2: the three storefronts, with their declarations and
  cases, their evidence captured as records (D23), the introduction change, and the VM
  callback's signed refusals. Session 3: the buyers' clients and the buyer store
  capturing records, the VM buyer's pricing verification of version 3 and stored
  version 2 publications and of its negotiation evidence (D22), a typed client's time advance beyond the skew (D8), the signed-delivery binding (D10a), the end-to-end lanes, and the
  documentation closeout promotes. Reviewed, then closeout.

The cutover is atomic (D9), so round 4 lands whole before any end-to-end lane passes.

*Section 6's return:* the first cadence had two rounds, the cutover in round 2. Section
6 stopped before its first task on finding that the cutover left the retained evidence
of signed messages undesigned. The owner chose a reviewed foundation round over
folding the amendments into the cutover's first session, which would leave a flaw in
the profile to surface across five authorities before anyone reviewed it, and over
placing each piece in the section that first needs it, which splits the foundation
across its consumers.

### D21 — A signed message retained as evidence is a record of its signed values

Several parties keep a signed request or response as evidence, which a third party
later verifies offline against a trusted principal (D12 lists them): the registry its
publishers' publications and updates, served in every listing read, which the VM buyer
verifies to bind accepted pricing to the seller's own signature; each buyer its
counterparties' signed negotiation messages and the end-delivery receipt, verified
against the Agreement alone; each storefront its counterparties' messages. Version 3
keeps all of them as a **record of the message's signed values**, readable as data,
beside the exact body bytes. A seller's publication, in a listing read:

```json
"publication": {
  "body_base64": "eyJsaXN0aW5nX2lkIjoibGlzdC03ZjNhIiwi...",
  "request": {
    "protocol": "arkhai.market-request-signature.v3",
    "principal": "ed25519:9mQ3vX2kq8sJdLr0aYbWcZtNeHf1uGpRiOxTyEwKjVs",
    "role": "seller",
    "method": "POST",
    "query": "?",
    "operation": "listing.publish",
    "request_id": "0f6c2b1e7d4a4c1e9a523e8b6d0f1a77",
    "timestamp": 1795000000,
    "origin": 1795000000,
    "audience": ["ed25519:Hq7kZp0TnR4vW9xYcB2dLmS8eJ5fQ1gA6uIoN3hK7rE"],
    "proof": "3q2-7w…"
  }
}
```

- `protocol` is the signature's tag; `principal` and each `audience` member are the
  complete principal as one string, as the signature's `keyid` writes it; `timestamp`
  is the signature's `created`; `proof` is the signature value alone, its scheme the
  principal's.
- `resource` is present exactly when the request carries `Market-Resource` (D2): an
  update's record names its listing, a publish's has none.
- `query` is the covered `@query` value, on every request record, `?` where the request
  had no query (D25).
- A response's record carries `protocol`, `principal`, `status`, `timestamp`,
  `proof`, and the method, operation, resource where present, and request ID of the
  request it answers, which its signature binds.
- No digest is kept: the verifier computes the content digest from the body. No
  header is kept: the record holds every value the signature covers, and the profile's
  one accepted spelling (D2) lets `kit/identity` rebuild the exact signature base from
  it.
- A version 2 record keeps its stored shape — `request` as the version 2 envelope —
  and its own `protocol`, `arkhai.market-request-signature.v2`, tells a reader which
  verifier applies.

The record is for a message bound to an authority: a version 3 request carrying
`Market-Audience`, and the response that answers it, which is every carrier above. A
signed delivery to an endpoint that is not an authority covers `@target-uri` in place
of the audience (D10a), so this record cannot rebuild its signature base; no party
keeps one as evidence today, and the change that first keeps one defines its record
(design review 61, F3).

The listing read's evidence fields are `publication` and `updates`, renamed from
`publisher_publication` and `publisher_updates`: `updates` maps each field a signed
update changed (`status`, `oracle_address`) to that update's publication. The read
lays these fields over the seller's published document, whose shape admits any extra
field, so `publication` and `updates` join the registry metadata a publication may not
carry, refused by name at publication, and `publisher_publication` and
`publisher_updates` stay reserved, so no seller term is silently overwritten by
evidence or reads as historical evidence (design review 61, F2). The registry renames its columns in the Alembic revision that adds its replay table, and
the VM buyer reads a pricing record it retained under the old key, as D12 keeps every
retained record readable. The end-delivery receipt keeps its layout, a request record
with its body and a response record with its body, and a receipt stored in a buyer's
end journal under version 2 still decodes by its `protocol`.

Each kind of message carries exactly the fields some message of that kind needs: a
field no message of its kind ever needs, to act on it or to verify it, is left out
rather than filled with a placeholder, and a field some message of its kind needs is
always present, even where in one message its value repeats another's. Presence is
fixed by the kind of message, known to sender and receiver before it is sent, never by
the values in one message. So `Market-Resource` is absent for an operation with no
target, `Market-Request-Origin` is on every request, since every operation may be
retried and a retry's origin is its only record of the first signing, `@query` is
covered on every request, since every request has a target URI and so a query value,
and the record keeps no digest. The same rule is what makes one accepted spelling possible.

`Market-Request-ID` stays although a body could fingerprint a request: every retry is
re-signed with a fresh `created`, so only the request ID tells an exact retry from a
new request with the same body; it keys the replay reservation (D7), binds a response
to its request, and pairs a seller's signed acceptance with the buyer request it
answers.

Rejected: storing the message's signed header fields verbatim beside the body, which
needs no spelling rule but leaves the principal and the signing time inside
`Signature-Input`, pairs with nothing in the version 2 record, and makes every reader
parse RFC 9421 to learn who signed and when; a separately signed non-HTTP artifact
inside each body, which changes every publisher's, buyer's and seller's payload, signs
each message twice, and makes the evidence other than the request the authority
admitted; signing version 2 beside version 3 on the routes that produce evidence, the
compatibility path D9 rejects, kept forever; relying on the authority's signature in
place of the party's, against `registry-discovery`'s rule that the registry attests
what it served and the seller's proof attests the terms; deferring, under which the
VM buyer refuses every purchase against a republished listing; reopening D2 for a
bespoke version 3 frame, which keeps the same record without a spelling rule but
gives up the standard form other languages sign with, rebuilds sections 2 and 4, and
returns the response binding to hand framing; a constant collection name in
`Market-Resource`; leaving `Market-Request-Origin` out of a first attempt, whose
presence would then depend on the attempt; keying requests on their origin and body
in place of a request ID, which merges intended identical requests sent within one
second and re-keys the replay layer, the response binding and the evidence pairing.

### D22 — Evidence verifies offline through `kit/identity`'s evidence verifiers

`kit/identity` offers two evidence verifiers, one for a request record and one for a
response record, each reading either version by its `protocol`. Each takes the record,
the body bytes, the principals trusted for it — kept with the evidence, such as a
listing's `publisher_principals` or an Agreement's parties — and the expected
operation and resource where the caller knows them; the request verifier also takes
the expected role. A version 3 response signs no role, so the response verifier takes
none: the exact trusted principals bind its signer, as the Agreement's seller alone
binds an end acknowledgement's, and a version 2 response envelope's signed role is not
checked (design review 61, F4). Each rebuilds the signature base, computes the digest
from the body, checks the proof under the principal's scheme and the principal against
the trusted set, and returns one view for both versions: principal, timestamp,
operation, resource, request ID, and the role for a request or the status for a
response. It
applies no freshness, since a retained message is not a live request, and checks no
audience membership, which concerned only the authority that admitted the request.

Every caller, through these verifiers alone: the VM buyer's publication check verifies
the publication's request record with the listing's publisher principals; its
recovered-pricing check verifies the buyer store's request and response records with
the Agreement's parties; `verify_end_acknowledgement`, from the buyer's ending and
deal-servicing's self-check, verifies the receipt's two records. None keeps its own
version 2 branch.

Rejected: verifying evidence through the live verifiers with freshness defeated by
`now` set to the message's own time and no skew, as version 2 readers do today, which
is obscure and leaves each consumer dispatching on version; consumers rebuilding the
signed headers from the record and calling the live verifier, which makes each
interpret the profile's internals.

### D23 — Capture carries records

Signing and verifying produce the record, so no party builds one by hand:

- the admission core's admission carries the verified request's record and body
  bytes, so a handler that keeps the request — the registry's publish and update,
  deal-servicing's end-delivery ingress — stores it before it answers; the signed
  outcome carries the request's and the response's records with both bodies, for
  capture after the answer — the VM storefront's negotiation evidence, bare metal's
  `seller-response:`, deal-servicing's `lifecycle_response`;
- `kit/identity`'s client-side capture seam carries a record, its body and the
  expected principals in place of the version 2 envelope and raw headers, and the
  typed clients (`core_buyer`, `storefront-client`, `deal-lifecycle-client`) pass the
  record their signing or verification produced;
- a version 3 evidence item keeps its record in `context` and no headers; the record
  is everything verification needs.

`deal-lifecycle`'s requirements that each party keep its commitment envelopes, and
capture them at the signed transport boundary, then speak of the signed record and the
exact body in place of proof headers.

Rejected: authorities reading the raw request from the framework beside the admission
core, which is the interface gap the core exists to close.

### D24 — The registry descriptor read is a public operation answered signed

`GET /.well-known/arkhai/registry-descriptor.json` is a **public operation**: its
request carries a request identity — `Market-Operation` and `Market-Request-ID` — and
no signature, audience, origin or digest, and the registry answers it with the version
3 signed response bound over that identity, as the core already signs a refusal over
the values an unverified request states. Nothing is reserved: a public read changes
nothing and has nothing to replay. A request to a public route carrying signature
fields is refused as malformed, since each operation's message has one shape (D21).
The descriptor is the only public operation; `marketplace-identity` names it.

```http
GET /.well-known/arkhai/registry-descriptor.json HTTP/1.1
Market-Operation: registry.descriptor.read
Market-Request-ID: 5b1e0c9a2f3d4e8b9c7a6d5e4f3a2b1c

HTTP/1.1 200 OK
Content-Digest: sha-256=:…:
Signature-Input: market=("@status" "content-digest" "@method";req "market-operation";req "market-request-id";req);created=1795000003;keyid="ed25519:Hq7kZp0TnR4vW9xYcB2dLmS8eJ5fQ1gA6uIoN3hK7rE";tag="arkhai.market-response-signature.v3"
Signature: market=:…:
```

The descriptor is a trust bootstrap: `RegistryClient.bootstrap_registry_descriptor`
reads it knowing no registry principal, then verifies the signed answer against the
principals the descriptor names, so a client adding a registry by its URL learns and
pins its principal (`registry-discovery`'s "Registry self-description is
authority-authenticated"). Under D10 every authenticated request names the authorities
it would accept, which such a client cannot. What the bootstrap relies on is the
registry's signature bound to the client's fresh request ID — proof that whoever
answered holds the named key now, and no replay of an older descriptor — not the
request's signature, which admitted any key under any of three roles and restricted
nothing; the descriptor is readable without a read key. That proof establishes
possession, not that the key is the URL's rightful operator: first contact rests on
TLS, or on a directory's countersignature over the descriptor body, a separate trust
layer; after it, every pinned read is verified against the learned principal.

`kit/identity` gains a public request builder that returns the request-identity
headers and the binding its answer is verified against; the bootstrap drops its
`signer` and `caller_role` arguments, and an ordinary client's
`get_registry_descriptor` sends the same public request and verifies the answer
against its configured registries. The admission core's route inventory gains the
public mark beside a declaration and the unauthenticated mark (D3).

Rejected: exempting the descriptor's signed request from the audience check, which
keeps a signature that restricts nothing at the cost of a third request coverage shape
and an exception to D10's universal check; retiring the bootstrap, so that a new
registry's principal always arrives from a directory or out of band, which removes the
add-a-registry-by-URL flow its originating issue was opened for; sending a placeholder
audience and learning the principal from the signed 421, which makes a refusal part of
the protocol and costs two round trips (an empty list cannot be sent: RFC 8941 omits
the field, and RFC 9421 refuses to cover an absent one); an unauthenticated route
serving a self-signed descriptor document, which changes the descriptor's wire, gives
up the binding to the client's request, and needs an issue time and expiry against a
replayed stale descriptor.

### D25 — Every request covers `@query`

Every version 3 request covers RFC 9421's `@query` derived component, the target URI's
query string exactly as sent with its leading `?`; a request with no query covers `?`
alone. It sits second in both request coverage lists, after `@method` (D2):

```http
GET /listings?filter_spec_etag=3f9a2c&limit=50&offset=0&status=open HTTP/1.1
Content-Digest: sha-256=:47DEQpj8HBSa+/TImW+5JCeuQeRkm5NMpJWZG3hSuFU=:
Market-Role: buyer
Market-Operation: listing.list
Market-Audience: ed25519:Hq7kZp0TnR4vW9xYcB2dLmS8eJ5fQ1gA6uIoN3hK7rE
Market-Request-ID: 7c2d4b9e1a0f4e3d8c6b5a4f3e2d1c0b
Market-Request-Origin: 1795000000
Signature-Input: market=("@method" "@query" "market-role" "market-operation" "market-audience" "market-request-id" "market-request-origin" "content-digest");created=1795000000;keyid="ed25519:9mQ3vX2kq8sJdLr0aYbWcZtNeHf1uGpRiOxTyEwKjVs";tag="arkhai.market-request-signature.v3"
Signature: market=:…:
```

Version 2 signed a read's query values through a canonical query document both sides
built and hashed without sending — the registry's `canonical_query_body`, the site
kit's (`kit/site/src/market_site/auth.py`), provisioning's
(`compute_provisioning_contracts/routes.py`). Version 3's `Content-Digest` hashes the
bytes sent (D2), and the profile as first built covered no query, so an intermediary
could change a read's filters or paging and the signed answer would still verify. The
query is now part of what the request's signature covers, of the request hash (so a
changed query under one request ID is changed reuse), and of the request record (D21).
The response needs nothing more: the authority answers only a request whose signature
verified, and the response binds its request ID.

The authority verifies against the raw query string it received (the ASGI
`query_string`), never a re-encoding; a proxy that re-encodes a query fails closed. A
typed client must send exactly the string it signed, so `kit/identity` offers one query
encoding from which each typed client builds both the signed value and the URL. The
three canonical query forms go.

Rejected: covering `@query` only on operations whose route declares query input, the
strictest reading of D21's presence rule, which adds a second coverage dimension and a
route property every authority must declare; sending the canonical query document as a
GET body, which RFC 9110 gives no meaning, intermediaries may drop, and which carries
every value twice; `@query-param` per parameter, whose coverage varies with the
message, against D2's one spelling, and which the library refuses for repeated
parameters; leaving query values unsigned, a regression from version 2.

### D26 — The listing read's filter-spec ETag is a query parameter

A listing read carries the filter-spec ETag it was compiled under as the query
parameter `filter_spec_etag`, covered by `@query` (D25); the registry answers a stale
value with 412 as it does today, and refuses an `If-Match` header on `listing.list` as
malformed, naming it, so a caller sending the old form is not silently left unchecked.
`registry-discovery`'s "Filter-spec consistency" and "Resource query compilation
preserves filter-spec authority" are restated to it, with the filter-spec route's
documentation and `registry_client.list_listings`, which `core_buyer`'s orchestrator and
the client's query compiler call with the ETag.

The ETag identifies the filter specification, not the `/listings` representation
`If-Match` would name, so a parameter is also the more accurate HTTP. Rejected: covering
`if-match` on `listing.list`, a header present on some messages only, against one
spelling, or always sent as `*`, a coverage list for one operation; leaving it unsigned,
which lets an intermediary strip the precondition while the answer still verifies.

### D27 — An applied rotation or retirement answers its exact retry first

Publisher identity rotation and retirement are `RERUN`, keyed by the rotation's nonce
(D6), and their answer must tell a caller who lost its acknowledgement what happened.
Each route therefore answers an applied rotation or retirement — the same nonce and
intent hash, to the principal the intent names — before its proof-expiry, primary and
overlap checks, which govern only applying a new intent. Today rotation checks the
intent's expiry first (by default its signing time plus 300 s) and retirement checks
that the replacement is still primary first, so a late retry is answered 401 or 403
(`core/registry/src/core_registry/api/publisher_routes.py`). The answer discloses
nothing the public rotation read does not serve. Each route's double-dispatch case
(D5) sends its retry after the intent's expiry and after a later write.

Rejected: making both `RECORDED`, which keeps bodies for a domain that recognises the
retry; leaving the order, which fails D6's criterion.

### D28 — Singleton and collection reads carry no `Market-Resource`

The registry's descriptor, filter-spec, health and stats reads, its collection reads
(`listing.list`, `publisher.list`) and `listing.validate` act on no identified object,
so their routes declare no target and their requests carry no `Market-Resource` (D2,
D21); version 2 stated constant names such as `filter-spec` and `health`. For the
descriptor this fixes D24's public request at `Market-Operation` and
`Market-Request-ID`. Rejected: a constant per singleton, the constant name D21 rejects.

### D29 — A reviewed foundation round precedes the cutover again

D24 and D25 amend `kit/identity`'s profile, record and client operations and the
admission core's inventory and verification, which every authority of the cutover
consumes. They are implemented as their own round, reviewed before the cutover depends
on them, and the cutover follows as round 4 (D20). Section 6's two planning findings —
section 9 cannot pass a functional commit's checks alone, and 6.5 omits the VM
storefront's registry-client contract test — are planning's.

Rejected, as at section 6's first return: folding the amendments into the cutover's
first session, which would have a profile change first reviewed beside five
authorities' cutover; placing each piece in the section that first needs it, which
splits one profile change across its consumers.

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
- `contract-driven-authenticated-routing` is proposed, depending on this change (D19).
