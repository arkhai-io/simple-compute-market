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
   registry-service and storefront.** Adding `payment_token` as a filter
   needs edits to FastAPI Query params, `ListingFilterParams`,
   `to_spec_kwargs`, and `matches_listing_filters` on both sides. The
   storefront-side `listing_filters.py` even documents that it
   "mirrors the registry-service's `matches_resource_filters` semantics"
   — a clear smell. Buyer policy can't dynamically discover what's
   filterable; specialized registries can't ship their own filter set.
3. **Escrow shape is discriminated by a `kind` string.** `EscrowTermsProposal`
   carries `escrow_kind: "erc20_non_tierable"` + `arbiter_kind: "recipient"`
   + `payment_token` + `expiration_unix`, validated against a hardcoded
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
    seller_attestation: str | None
    buyer_attestation: str | None
    oracle_address: str | None

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
                "payment_token": dr["token"]["contract_address"],
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
`integration-tests/tests/e2e/`. The e2e suites pass `payment_token`
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

## Milestone (a) — Registry self-description (filter-spec + listing_shape)

**Goal:** registries advertise their own listing shape (JSON Schema) and
filter set; storefront drops its `/api/v1/listings` endpoint (sellers
who want a local view co-locate a registry instance with a
`seller==self` filter).

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
  - name: payment_token
    path: $.accepted_escrows[*].fields.payment_token
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
GET /listings?payment_token=0x...&strict.payment_token=true
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

- Drop `GET /api/v1/listings` from the storefront. Drop
  `storefront/src/market_storefront/utils/listing_filters.py` entirely.
- Drop `storefront/src/market_storefront/models/listing_models.py`'s
  `ListingFilterParams` + `listing_filter_params` factory.
- A seller who wants a "show me my own listings" view runs a registry
  instance pointed at their own storefront's `publications` table (or
  similar) with a filter-spec that exposes `seller`.
- The `storefront-client` callers that hit `/api/v1/listings` migrate
  to hitting a registry directly.
- `registry-service/src/api/validate_routes.py` becomes the `listing_shape`
  validator (already mostly the right shape; just driven by the loaded
  JSON Schema instead of hardcoded `gpu_model/region/sla` checks).

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
  `payment_token` and `gpu_model`. Costs disk + write latency; pays
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
- `seller_attestation: str | None`
- `buyer_attestation: str | None`
- `oracle_address: str | None`

Plus `offer_resource: dict[str, Any]` — present on every listing, but
its inner shape is registry-defined. A buyer client treats it as opaque;
the registry's `listing_shape` constrains it.

`AcceptedEscrow` and `EscrowProposal` shapes are protocol-fixed; their
inner `fields` map is ABI-defined per `(chain_id, escrow_address)`.

Everything else (filter vocabulary, listing extensions like `region`,
`gpu_model`, `ram_gb`, etc.) is registry-userland.

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
5. **PR (a1):** Registry `/filter-spec` endpoint + JSON Schema-driven
   validation; storefront `/api/v1/listings` dropped.
6. **PR (a2):** Per-query `on_missing` override + `indexed: true` side
   indexes (defer until proven necessary).

Each PR runs the full verification process documented in
`memory/reference_full_verification_process.md`: per-package unit +
integration tests, `make build`, `make test-e2e`, `make test-multi-registry`.
