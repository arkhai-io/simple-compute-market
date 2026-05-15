# Generic-escrow + registry-self-description plan-of-record

Three loosely-coupled milestones that together let the protocol support
arbitrary escrow shapes, registry-specialized indexes, and per-registry
publish payloads — without baking listing schemas, filter vocabularies,
or escrow-kind discriminators into protocol code.

Order: **(b) → (c) → (a)**. (b) and (a) may bundle if (b)'s `listings`
table changes overlap meaningfully with (a)'s filter-driven schema work.

## Motivation

Three things are protocol-baked today and shouldn't be:

1. **Listing shape is hardcoded.** `offer_resource` + `demand_resource`
   (Pydantic `Union[ComputeResource, TokenResource]`) is the only legal
   shape. Pricing is implicitly "ERC20 escrow at `demand_resource.token`,
   amount per hour." Multi-escrow, multi-arbiter, hidden-price, and
   non-VM listings (data, models, etc.) all want a different shape.
2. **Filter vocabulary is hardcoded — same 22 fields copy-pasted across
   registry-service and storefront.** Adding `token` as a filter
   needs edits to FastAPI Query params, `ListingFilterParams`,
   `to_spec_kwargs`, and `matches_listing_filters` on both sides. The
   storefront-side `listing_filters.py` even documents that it
   "mirrors the registry-service's `matches_resource_filters` semantics"
   — a clear smell. Buyer policy can't dynamically discover what's
   filterable; specialized registries can't ship their own filter set.
3. **Escrow shape is discriminated by a `kind` string.** `EscrowTermsProposal`
   carries `escrow_kind: "erc20_non_tierable"` + `arbiter_kind: "recipient"`
   + `token` + `expiration_unix`, validated against a hardcoded
   single canonical shape. Adding a new escrow contract requires a new
   `kind` string + new codec entry + new validator branch. The contract
   address is the natural identity; the discriminator is redundant.

## Cross-cutting design decisions

These hold across all three milestones:

- **Codec lookup keys on `(chain_id, address)`, not `kind`.** Reverse-map
  built at startup by walking `alkahest_py.DefaultExtensionConfig.for_chain(name)`
  across every supported chain plus the override JSON, producing
  `{(chain_id, lowercase_addr): slot_name}`. Codec registry keys on the
  slot name (the ABI type — `erc20_escrow_obligation_nontierable`,
  `recipient_arbiter`, etc.); the address→slot indirection is invisible
  at call sites. New chains/anvil deployments fold in automatically.
  Lives in `service/src/service/clients/alkahest.py` next to the existing
  `_sdk_addresses_for_chain`.
- **Listing data is JSON-shaped, not relational.** SQLite already stores
  `offer_resource`/`demand_resource` as `TEXT` blobs round-tripped
  through Pydantic; we're staying in that model, not introducing junction
  tables. Filtering uses `json_extract` (and `json_each` for array
  projection) when pushed to SQL, in-memory dict matching when not.
- **Schema lives in the registry, not the protocol.** Validation,
  filter-spec, and listing-shape advertising are all registry concerns
  (registries are userland roles). The protocol layer (buyer client,
  storefront publish path) treats listings as opaque dicts with a small
  required core (see milestone a) and lets the registry reject what
  doesn't fit its `listing_shape`.
- **"Validation" is two distinct things.** Shape validation = "does this
  listing/proposal satisfy the registry's JSON Schema / the codec's ABI?"
  — protocol infrastructure, runs at publish/round-0. Acceptability =
  "does the seller's negotiation policy accept this proposal's specific
  values?" — userland policy middleware, runs during negotiation. Today's
  `_validate_escrow_terms_proposal` conflates the two; (c) splits them.
- **Set/unset on a partial `accepted_escrows[i].fields` is advertisement,
  not constraint.** Sellers may list a price but be willing to go lower,
  or omit a payment-token-list and accept alternatives at negotiation
  time. The seller's negotiation policy decides what to do with the
  buyer's proposal; the schema only describes shape.

## Milestone (b) — `demand_resource` → `accepted_escrows`

**Goal:** replace the implicit single-canonical-escrow pricing slot with
an explicit list of accepted escrow tuples; rekey codecs on
`(chain, address)`; add publish-tracking so the same listing can have
different payloads in different registries.

**Cutover, no transitional dual-write.** Single one-shot DB migration
that synthesizes `accepted_escrows` rows from existing `demand_resource`
JSON and drops the column.

**Listing is one-sided.** A listing represents a seller's offer of
compute (or any single resource) plus an upper bound on what they
accept in exchange (the `accepted_escrows` advertisement). The buyer
proposes a specific instance against that bound — they don't publish
their own listings. The `_we_are_compute_buyer` / "buyer-as-maker"
branch in `action_executor.py` is dormant code from an earlier
symmetric-maker/taker design; nothing publishes orders with
`offer=TokenResource, demand=ComputeResource`. That branch (plus the
`MAKE_OFFER` handling of token-side-offer) gets deleted as part of
the `demand_resource` removal, not preserved.

### New listing core (protocol-required)

```python
class Listing(BaseModel):
    listing_id: str
    seller: str
    offer_resource: dict[str, Any]       # registry-specific shape; protocol stays opaque
    accepted_escrows: list[AcceptedEscrow]
    max_duration_seconds: int | None
    oracle_address: str | None

# Attestation UIDs (seller_attestation, buyer_attestation) and deal-record
# fields (buyer, matched_offer_id, escrow_uid) are intentionally NOT on the
# listing. Multi-escrow deals (payment + bond + penalty) need per-escrow
# attestation tracking — those live on the `escrows` table (evolved from
# settlement_jobs; see "Multi-escrow deal record" below).

class AcceptedEscrow(BaseModel):
    chain_id: int
    escrow_address: str                  # codec key with chain_id; lowercase
    fields: dict[str, Any]               # Partial<EscrowData> for this contract's ABI
                                         # Unset = advertisement-silent; set = advertised
                                         # value (NOT a hard constraint — see milestone c)
```

`demand_resource` removed. The buyer's `EscrowTermsProposal` shape
changes correspondingly:

```python
class EscrowProposal(BaseModel):
    chain_id: int
    escrow_address: str                  # picks one tuple from accepted_escrows
    fields: dict[str, Any]               # complete EscrowData values
    expiration_unix: int
```

The proposal references an entry in the listing's `accepted_escrows` by
`(chain_id, escrow_address)` and supplies a complete `fields` map.

### Codec registry changes

`service/src/service/clients/alkahest.py`:

- Add `chain_id_for_network(name)` helper (alkahest_py likely exposes
  this on `DefaultExtensionConfig`; check before reimplementing).
- Add `address_to_slot(chain_id, address) → slot_name | None` reverse
  lookup, built lazily and cached.
- Existing `ArbiterCodec` / `RecipientArbiterCodec` / `EscrowKindCodec` /
  `Erc20NonTierableEscrowCodec` registries rekey on slot name. The
  proposal-to-obligation-data path becomes
  `address → slot → codec.encode(fields)`.

### Storefront publish-tracking

New table:

```sql
CREATE TABLE publications (
  listing_id TEXT NOT NULL,
  registry_url TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  published_at INTEGER NOT NULL,
  registry_assigned_id TEXT,
  status TEXT NOT NULL,                  -- 'published' | 'failed' | 'unpublished'
  last_error TEXT,
  PRIMARY KEY (listing_id, registry_url)
);
```

`multi_registry_client.publish_listing` grows two modes:

1. **Fan-out same payload** (existing behavior, default for callers that
   don't care): publish identical `listing` to all configured registries.
2. **Per-registry payload**: `publish_listing(listing_id, {registry_url:
   payload, ...})`. Each row gets persisted in `publications`. Updates
   and deletes consult `publications` to know what's where.

The current "fan-out and remember nothing" path becomes a thin wrapper
that builds a uniform `{registry_url: same_payload, ...}` dict and
delegates to the new path.

### Multi-escrow deal record (`settlement_jobs` → `escrows`)

Today's `listings` row absorbs the deal outcome with flat columns:
`buyer`, `matched_offer_id`, `escrow_uid`, `seller_attestation`,
`buyer_attestation`. That shape assumes **one escrow per deal**. Real
deals will have multiple escrows attached — primary payment, performance
bond, penalty escrow, etc. — and each has its own lock/fulfill attestation
pair on chain. Flat columns don't accommodate that.

`settlement_jobs` is already keyed on `escrow_uid PK + negotiation_id` and
carries an `attestation_uid` column + provisioning state. It's the
**per-escrow record**, just hardcoded to one row per deal. Evolution:

- Rename `settlement_jobs` → `escrows`.
- Add `chain_name TEXT`, `escrow_address TEXT` — resolves which contract.
  Same `(chain_name, escrow_address)` pair as the listing's
  `accepted_escrows` and the buyer's `EscrowProposal`.
- Rename `attestation_uid` → `seller_attestation_uid` (the seller's
  fulfillment attestation). No separate buyer-side column: the row's PK
  ``escrow_uid`` IS the EAS attestation UID of the buyer's escrow
  obligation, so the legacy ``listings.buyer_attestation`` was just a
  denormalized duplicate.
- Add `is_primary INTEGER NOT NULL DEFAULT 1`. The primary escrow drives
  provisioning — existing `provisioning_job_id`, `tenant_credentials`,
  `connection_details` columns are populated only on the primary row.
  Non-primary escrows are lifecycle-tracked but don't trigger fulfillment.

`listings` sheds the deal-outcome columns entirely: `escrow_uid`,
`buyer_attestation`, `seller_attestation` drop. `buyer` and
`matched_offer_id` move to `negotiation_threads` where they conceptually
belong (the thread is the buyer↔seller pairing).

The `Listing.is_open()` / `is_closed()` predicates become derived queries
joining `escrows` via the winning `negotiation_id`: "any escrow row
missing `seller_attestation_uid` = open; every row has it = closed."

#### Migration

```python
# pseudo-code, idempotent — guarded on column existence
cur.execute("ALTER TABLE settlement_jobs RENAME TO escrows")
cur.execute("ALTER TABLE escrows ADD COLUMN seller_attestation_uid TEXT")
cur.execute("ALTER TABLE escrows ADD COLUMN chain_name TEXT")
cur.execute("ALTER TABLE escrows ADD COLUMN escrow_address TEXT")
cur.execute("ALTER TABLE escrows ADD COLUMN is_primary INTEGER NOT NULL DEFAULT 1")
cur.execute("ALTER TABLE negotiation_threads ADD COLUMN buyer TEXT")
cur.execute("ALTER TABLE negotiation_threads ADD COLUMN matched_offer_id TEXT")

# Backfill the per-escrow row from the pre-cutover listings:
#   seller_attestation_uid <- escrows.attestation_uid (the legacy column held this)
#   chain_name, escrow_address <- listing.accepted_escrows[0]
#   is_primary = 1 (every existing row was the only escrow)
# ``listings.buyer_attestation`` is not backfilled: escrow_uid (the row PK)
# already IS the buyer's escrow attestation UID, so the legacy column was a
# denormalized duplicate of the PK.
# And the negotiation-side backfill:
#   negotiation_threads.buyer            <- listings.buyer
#   negotiation_threads.matched_offer_id <- listings.matched_offer_id

cur.execute("ALTER TABLE escrows DROP COLUMN attestation_uid")
cur.execute("ALTER TABLE listings DROP COLUMN escrow_uid")
cur.execute("ALTER TABLE listings DROP COLUMN buyer_attestation")
cur.execute("ALTER TABLE listings DROP COLUMN seller_attestation")
cur.execute("ALTER TABLE listings DROP COLUMN buyer")
cur.execute("ALTER TABLE listings DROP COLUMN matched_offer_id")
```

#### Callers that touch attestation fields

Concentrated in `storefront/src/market_storefront/utils/`: `action_executor.py`
(writes `seller_attestation` post-fulfillment), `recovery.py` (reads to
detect mid-settlement crash recovery), `settlement_jobs.py`, `sqlite_client.py`
(persistence). Plus `registry-service`: the `/listings/closed` endpoint
filters on `seller_attestation IS NOT NULL AND buyer_attestation IS NOT NULL`;
moves to a join against `escrows` (or a denormalized
`listings.is_settled` flag maintained at attestation-write time, if the
join cost matters).

#### Surfacing escrows on the per-negotiation endpoint

Post-b3 the per-deal attestation data lives on `escrows` joined to
`negotiation_threads` via `negotiation_id`, but
`GET /api/v1/listings/{listing_id}/negotiations/{neg_id}` (backed by
`sqlite_client.load_negotiation_detail`) returns only thread + messages +
stage_events — it doesn't JOIN `escrows`. That's the natural home for
the data (was previously rolled up into the registry's now-deleted
`/system/stats/attestations`). Extend `load_negotiation_detail` to
include `escrows: [{escrow_uid, fulfillment_uid, chain_name,
escrow_address, is_primary, status}, ...]` populated from
`SELECT ... FROM escrows WHERE negotiation_id = ?`, and add the field
to the controller's response schema.

A cross-storefront aggregate (the old roll-up's shape) is a different
concern — would be a separate `GET /api/v1/system/stats/escrows` over
the storefront's own escrows table, counting open vs fulfilled. Defer
until someone needs a smoke-test signal back.

#### Open questions, not blocking

- `oracle_address` lives on `listings` today and is also per-deal. Multi-
  escrow with different arbiters would want it per-escrow row too. Defer
  until the first non-recipient-arbiter escrow ships; the move is small.
- Whether `is_primary` should be a `role TEXT` discriminator (`payment` /
  `bond` / `penalty`) or stay as a boolean flag. Boolean fits today's
  use; widen to enum when a second non-primary role appears.

### Migration

One-shot Python migration in `sqlite_client.py` schema-init block, after
the `listings` table exists and before any reads:

```python
# pseudo-code
for row in cur.execute("SELECT listing_id, demand_resource FROM listings"):
    dr = json.loads(row.demand_resource or "{}")
    if dr.get("token", {}).get("contract_address"):
        accepted = [{
            "chain_id": <derive from config.alkahest_network>,
            "escrow_address": <get_erc20_escrow_obligation_nontierable(chain)>,
            "fields": {
                "token": dr["token"]["contract_address"],
                "amount": dr.get("amount"),                     # nullable; per-hour
            },
        }]
    else:
        accepted = []
    cur.execute(
        "UPDATE listings SET accepted_escrows = ? WHERE listing_id = ?",
        (json.dumps(accepted), row.listing_id),
    )
cur.execute("ALTER TABLE listings DROP COLUMN demand_resource")
```

Wrap in an idempotent guard (skip if `accepted_escrows` column already
exists). Anvil chain_id resolution may need a config knob; check what
the test stack expects.

### Tests touched

`buyer/tests/`, `storefront/tests/`, `policy/tests/`, `service/tests/`,
`integration-tests/tests/e2e/`. The e2e suites pass `token`
through `negotiate_new` today (added during the step-7 refactor) — that
flow stays but the value gets sourced from a single-tuple
`accepted_escrows` on the test fixture rather than `demand_resource`.

### Non-goals for (b)

- Per-registry filter advertising (that's a).
- Replaceable negotiation policy (that's c).
- Storefront-side schema validation (registry-side only).

---

## Milestone (c) — Seller negotiation policy middleware

**Goal:** move acceptability decisions out of protocol infrastructure
into a swappable seller-side policy module. Today's
`_validate_escrow_terms_proposal` becomes the default policy, not a
hardcoded rule.

### What moves where

Today (`storefront/src/market_storefront/utils/sync_negotiation.py:57-105`)
this single function does three things:

1. Structural check: does the buyer's proposal pick a `(chain, address)`
   the listing actually advertises?
2. Shape check: are required ABI fields present?
3. Value match: does every seller-set value equal the buyer's proposed
   value?

Split:

- (1) and (2) stay as **protocol infrastructure** (they're
  shape/structure checks — the buyer's proposal must reference one of
  the listing's tuples, and `fields` must be a complete EscrowData per
  the codec's ABI). Live in a new module
  `storefront/src/market_storefront/escrow/proposal_shape.py` (name
  open) that raises a structural error on mismatch.
- (3) moves to **seller negotiation policy**. Default policy
  (`policy/src/market_policy/negotiation/default_seller_escrow.py` or
  similar) re-implements the existing "every set field must match
  exactly" behavior. Sellers can swap it for a counter-offer policy, an
  LLM-driven policy, etc.

### Policy interface (sketch)

```python
class SellerEscrowPolicy(Protocol):
    def evaluate(
        self,
        listing_accepted: list[AcceptedEscrow],
        buyer_proposal: EscrowProposal,
        listing_context: dict[str, Any],     # listing dict for ad-hoc reads
    ) -> EscrowPolicyDecision: ...

class EscrowPolicyDecision(BaseModel):
    action: Literal["accept", "counter", "reject"]
    counter: EscrowProposal | None = None    # only when action == "counter"
    reason: str | None = None
```

Wiring: `sync_negotiation.py`'s negotiate-new path calls the registered
policy after structural checks pass. `accept` continues the existing
flow with the buyer's proposal echoed back. `counter` swaps in the
seller's counter-proposal as `accepted_escrow_proposal` on the outcome
(buyer-side then has to handle counter-offers; today the assumption is
the seller echoes buyer's proposal verbatim — see the buyer flow
changes below). `reject` raises `OfferUnfulfillableError`.

### Buyer-side counter-offer handling

The buyer flow today (`buyer/market_buyer/buy_orchestrator.py`) treats
the seller's echoed proposal as the agreed proposal. With counters in
the picture, the buyer needs a small accept/reject decision on the
returned proposal — typically "accept any counter that's still within
my budget." Add a thin buyer-side counter policy with the obvious
default ("accept if no fields changed; reject if fields changed and
they're outside my budget; accept otherwise"). Keep the default narrow
to avoid bikeshedding multi-round negotiation now.

### Registry / config

Policy is selected by the seller's storefront config:

```toml
[seller.negotiation]
escrow_policy = "default"   # or a dotted-path import
```

Same plugin convention as the existing `policy_composites` system in
the storefront's policy package — reuse rather than invent.

### Non-goals for (c)

- Multi-round negotiation choreography. Counter exists; iterating on
  counters is out of scope unless trivially free.
- LLM-driven policies. Interface accommodates them; no implementation.

---

## ~~Milestone (a1) — Registry self-description (filter-spec + listing_shape)~~ (landed)

**Goal:** registries advertise their own listing shape (JSON Schema) and
filter set; storefront's `/api/v1/listings` sheds its discovery
vocabulary (filter params, schema-validation duplication) and reverts
to a plain REST collection view of the seller's own resources.
Buyer-side discovery happens against registries.

Landed as commits a1b-1 through a1b-6 on `test/role-separated-stage-tests`:

- **a1b-1**: `/filter-spec` endpoint serving the YAML-driven spec with a
  sha256 etag over `{version, listing_shape, filters}`. Loader uses
  pydantic for shape validation + `extra='forbid'` on filter
  declarations so YAML typos surface at startup.
- **a1b-2**: `POST /api/v1/listings/validate-publish` drives off the
  loaded JSON Schema (Draft202012Validator). Old hardcoded
  compute/token heuristics gone; enum violations + integer/null
  bounds now caught for free.
- **a1b-3**: `GET /listings` filter evaluator over jsonpath-ng, set-
  theoretic op model (in / not_in / range / exists), URL sugar via
  `alias_kind: lower_bound|upper_bound`, ETag gate via `If-Match` →
  412 with current etag in body, unknown filter → 400. Dropped
  `matches_resource_filters` + dead helpers (`get_resource_type`,
  `resources_match`).
- **a1b-4**: Storefront's `/api/v1/listings` trimmed to a plain
  resource-enumeration view (`limit/offset/status/paused`). Dropped
  `storefront/src/market_storefront/utils/listing_filters.py`,
  `ListingFilterParams`, `listing_filter_params` factory.
- **a1b-5**: `arkhai-registry-client 0.5.0 → 0.6.0` — typed filter
  surface on `list_listings` replaced with `**filters` passthrough +
  `etag=` → `If-Match` header. `get_filter_spec()` added. `arkhai-
  storefront-client 0.8.0 → 0.9.0` — discovery kwargs dropped.
- **a1b-6**: registry Dockerfile copies `filter-spec.yaml` into the
  image (otherwise the runtime `FileNotFoundError`s on any /listings
  call).

Deferred to **PR (a2)**: per-query `on_missing` override, `indexed: true`
side indexes, raw set-form URL syntax (`?gpu_model=in:[H100,A100]`).
The sections below describe the design as it landed.

### `/filter-spec` endpoint

```yaml
# GET /filter-spec
version: 3
etag: "..."                                 # hash of {version, listing_shape, filters}
listing_shape:                              # JSON Schema, draft 2020-12
  type: object
  required: [listing_id, seller, offer_resource, accepted_escrows]
  properties:
    listing_id: {type: string}
    seller: {type: string}
    offer_resource:                         # registry-specific
      type: object
      required: [gpu_model, region]
      properties:
        gpu_model: {type: string}
        region: {type: string}
        ram_gb: {type: integer}
        ...
    accepted_escrows:                       # protocol-required shape
      type: array
      items:
        required: [chain_id, escrow_address, fields]
        properties:
          chain_id: {type: integer}
          escrow_address: {type: string}
          fields: {type: object}
    max_duration_seconds: {type: integer, nullable: true}
filters:
  - name: gpu_model
    path: $.offer_resource.gpu_model
    op: in
    value_type: string
    on_missing: fail
    indexed: false
  - name: ram_gb_min
    path: $.offer_resource.ram_gb
    op: range
    value_type: integer
    alias_kind: lower_bound                 # URL sugar: ?ram_gb_min=16
    on_missing: fail
    indexed: false
  - name: token
    path: $.accepted_escrows[*].fields.token
    op: in
    value_type: address
    on_missing: pass                        # underreport-friendly
    indexed: true                            # registry materializes side index
```

### Op model

Set-theoretic primitive: criterion declares a set S; path resolves to
a (possibly singleton) collection R; filter passes iff `R ∩ S ≠ ∅`.

Closed op set:

- `in: [...]` — S is a literal list (covers `eq` as `in: [x]`)
- `range: {min, max, min_inclusive, max_inclusive}` — S is an interval
- `not_in: [...]` — passes iff `R ∩ S = ∅`
- `exists: bool` — `R ≠ ∅` vs `R = ∅`

Collection-valued paths (those containing `[*]`) get array-projection
semantics for free: "at least one element matches." Scalar paths
collapse to singleton R.

URL syntactic sugar layer maps `?ram_gb_min=16` → `range: {min: 16,
min_inclusive: true}`, `?gpu_model=H100` → `in: ["H100"]`. Aliases
declared in the spec via `alias_kind`. Raw set-theoretic form also
acceptable on the wire (`?ram_gb=range:[16,)`).

### Per-query `on_missing` override

```
GET /listings?token=0x...&strict.token=true
```

Overrides spec default for that filter on that query. Buyer policies
that want "show me sellers who publicly commit to USDC" tighten;
default underreport-friendly behavior loosens.

### JSONPath

Adopt RFC 9535 via `jsonpath-ng` (or its successor). Array projection
`[*]` is the only non-trivial construct we need; nested object access
and indexed access fall out. Avoid implementing a custom DSL.

### Version skew

`/filter-spec` returns an `etag`. Buyer caches the spec keyed by
registry URL + etag. Every filter request sends `If-Match: <etag>`.
Registry returns `412 Precondition Failed` on mismatch with the new
spec body so the buyer can refresh. Unknown filter names in a request
return `400`, never silently ignored.

### Storefront-side fallout

`GET /api/v1/listings` (and `GET /api/v1/listings/{id}`) **stay** on
the storefront, but their job narrows. Today the endpoint duplicates
the registry's discovery surface — same 22 filter params, same
`matches_listing_filters` mirror semantics. After (a) the storefront
collection becomes the REST-canonical "what listing resources does
this storefront own" view, paired with the lifecycle subpaths
(`/create`, `/{id}/close`, `/refund`, `/claim`, etc.) that operate on
the same resources by their storefront-local `listing_id`. Buyer
discovery moves to registries, where the federation, filter spec, and
JSON-Schema validation actually pay rent.

Concretely:

- Trim `GET /api/v1/listings` to basic resource enumeration: `limit`,
  `offset`, and an optional `status` (open / closed / paused — that's
  resource state, not market-discovery vocabulary). No `gpu_model`,
  `region`, `token`, etc. — those belong on registries.
- Drop `storefront/src/market_storefront/utils/listing_filters.py`
  entirely. Drop `storefront/src/market_storefront/models/listing_models.py`'s
  `ListingFilterParams` + `listing_filter_params` factory.
- `storefront-client` callers split: discovery callers migrate to
  hitting a registry directly; seller-introspection callers (the
  storefront's owner asking "what do I have?") keep using
  `/api/v1/listings` against the slimmed surface. The publications
  table mediates the registry side — `publications.listing_id` is
  storefront-local, `publications.registry_assigned_id` is what the
  registry returned (today same UUID; tomorrow possibly different).
- `registry-service/src/api/validate_routes.py` becomes the
  `listing_shape` validator — already mostly the right shape, just
  driven by the loaded JSON Schema instead of hardcoded
  `gpu_model/region/sla` checks.

The lifecycle subpaths (`/api/v1/listings/{id}/close`, `/refund`,
`/claim`, `/reclaim`, `/arbitrate`, `/pause`, `/resume`, plus
`POST /create`) are seller operations on local state, keyed on
storefront-local `listing_id`. They were never part of the discovery
question and stay untouched.

### Filter-spec authoring

YAML file loaded at registry startup; path configurable via env. Single
file per registry. Add a Makefile target to validate the file against
a meta-schema (op set, alias_kind, etc.) before startup so bad specs
fail fast.

### Performance

Two storage strategies, selected per filter via `indexed: true|false`:

- **`indexed: false`**: filter runs via `json_extract` (scalar) or
  `EXISTS(SELECT 1 FROM json_each(...))` (array projection) in SQL,
  no precomputed columns. Fine for low/medium row counts.
- **`indexed: true`**: registry maintains a denormalized side index
  at publish/update time (generated column + index for scalar paths,
  side table for array projections). Used for hot axes like
  `token` and `gpu_model`. Costs disk + write latency; pays
  for query latency at scale.

Mixed-predicate queries narrow on scalar/indexed filters first, then
evaluate array projections on the survivor set. SQLite's planner does
this for us when the WHERE clause ANDs both kinds.

### Non-goals for (a)

- Multi-registry federated search. Each registry serves its own spec
  + listings; buyer policy queries each separately.
- Full-text / fuzzy search.
- Registry-side aggregation (counts, group-by). Buyer-side problem.

---

## Required-core / userland-extensions boundary

The protocol-required core fields on every listing, across all registries:

- `listing_id: str`
- `seller: str` (agent card URL)
- `accepted_escrows: list[AcceptedEscrow]`
- `max_duration_seconds: int | None`
- `oracle_address: str | None`

Plus `offer_resource: dict[str, Any]` — present on every listing, but
its inner shape is registry-defined. A buyer client treats it as opaque;
the registry's `listing_shape` constrains it.

`AcceptedEscrow` and `EscrowProposal` shapes are protocol-fixed; their
inner `fields` map is ABI-defined per `(chain_id, escrow_address)`.

**Not on the listing.** Attestation UIDs (`buyer_attestation_uid`,
`seller_attestation_uid`) and deal-record fields (`buyer`,
`matched_offer_id`) are settlement-side state, not advertisement. They
live on the `escrows` table (one row per attached escrow, joined via
`negotiation_id`) and on `negotiation_threads`. Registries that want a
"deal closed" view query that join, not a flag on the listing.

Everything else (filter vocabulary, listing extensions like `region`,
`gpu_model`, `ram_gb`, etc.) is registry-userland.

## Post-(a1a) follow-ups

Surfaced during the (a1a) registry catch-up review. Items (1) and (2)
landed before (a1b) — the registry's `/filter-spec` endpoint will
advertise filter paths that reference these field names and types, so
fixing them up-front avoids a public-schema break later. Item (3) is
left for after (a1b) since the filter spec operates on addresses, not
symbols.

### ~~`fields` should match on-chain ObligationData keys~~ (done)

Landed: `accepted_escrows[i].fields.token` and
`EscrowProposal.fields.token` now mirror the on-chain
`ERC20EscrowObligation.ObligationData.token` key directly. The
`token` → `token` translation in `escrow_client.py` and
`escrow_verification.py` is gone — the value passes through unchanged.

Future escrow kinds (ERC721, native, bundle) will still want per-codec
`fields_to_obligation_data(fields, agreed_price, duration_seconds)`
methods; today's `build_payment_obligation_data` in
`service/clients/alkahest.py` becomes the ERC20 codec's implementation
of that method when the dispatch becomes polymorphic (alkahest.py
docstring still flags this as "step 6").

### ~~`price_per_hour` representation~~ (done)

Landed: `price_per_hour` is now a float in base units, and the codec
amount formula is `int(price_per_hour * duration_seconds / 3600)` —
float multiply, single int round at the wei boundary. This lets
sub-hour leases stay precise for small-base-unit rates (`int` math
would truncate `1 * 1800 // 3600 = 0` early), and admits sub-base-unit
rates per hour at the cost of representation-not-cardinality precision.

The "integer × 10^decimals" hybrid is gone. Token decimals are now
purely a presentation concern (CLI rendering via Decimal).

### Token references: addresses, not symbols

Storage carries addresses everywhere. Symbols are a presentation-layer
convenience attached at render time via `TOKEN_REGISTRY`.

Today symbol-as-shorthand leaks into storage / API in a few places:
- `storefront/resources.py:212-263` — CSV import accepts
  symbol-only entries, resolves via registry.
- `storefront/services/listing_service.py:72-75` — POST create-listing
  accepts symbol-only token entries.
- `storefront/data/token_registry_*.json` — symbol-indexed lookup tables.

Cleanup principle:
- API boundaries (listing creation, CSV import) resolve symbol →
  address; everything downstream sees only addresses.
- Display surfaces (CLI `market listing show`, dashboards) look up
  symbol from address at render time.
- `service/clients/token.py` keeps the by-symbol index but reframes
  it as a presentation cache — not primary identity.

Symbols are bug-prone across multi-chain configs (USDC has different
addresses per chain, occasional symbol collisions), make grep harder,
and need decimals-lookup-by-symbol for amount math. Addresses sidestep
all of it.

## Suggested PR sequence

1. **PR (b1):** `accepted_escrows` schema + codec rekey + DB migration,
   no behavior change beyond shape. e2e tests pass against the new
   shape. `_validate_escrow_terms_proposal` still hardcoded but now
   reads from `accepted_escrows[0]`.
2. **PR (b2):** `publications` table + per-registry payload publish
   API. Existing fan-out becomes a wrapper.
3. **PR (c1):** Lift `_validate_escrow_terms_proposal` into a default
   seller policy; structural checks stay in protocol layer.
4. **PR (c2):** Buyer-side counter-offer handling (if (c1) didn't
   already cover it).
5. **PR (b3):** Evolve `settlement_jobs` → `escrows` (multi-escrow per
   deal). Drop attestation/buyer/matched_offer_id from `listings`; move
   buyer/matched to `negotiation_threads`. Registry `/listings/closed`
   filter becomes a join. Sequenced after (c) so the negotiation-policy
   surface is settled before the deal-record shape changes underneath
   it; could move earlier if the multi-escrow use case becomes urgent.
6. ~~**PR (a1):** Registry `/filter-spec` endpoint + JSON Schema-driven
   validation. Storefront `/api/v1/listings` sheds its discovery filter
   vocabulary (drop `listing_filters.py`, drop `ListingFilterParams`);
   the endpoint stays as a REST collection view over the seller's own
   resources with just `limit` / `offset` / `status`.~~ landed as a1b-1
   through a1b-6 (out of the original PR sequence; (b)/(c) still ahead).
7. **PR (a2):** Per-query `on_missing` override + `indexed: true` side
   indexes (defer until proven necessary). Raw set-form URL syntax
   (`?gpu_model=in:[H100,A100]`) — currently only the URL-sugar layer
   (single-value `in` and `range` via `alias_kind`) is wired up; the
   raw form needs URL parsing + the `not_in` and `exists` ops have
   eval support but no URL surface yet.

Each PR runs the full verification process documented in
`memory/reference_full_verification_process.md`: per-package unit +
integration tests, `make build`, `make test-e2e`, `make test-multi-registry`.
