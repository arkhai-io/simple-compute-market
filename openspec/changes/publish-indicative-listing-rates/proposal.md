## Why

`unbacked-listing-publication` makes supply the marketplace cannot admit against
discoverable. It does not make it comparable. A buyer can find unbacked listings
and filter them by region, GPU model, and form factor, but not by price.

That gap is the difference between a catalogue and a directory. Goal 7's value
statement is that a buyer gets one place to compare rates across backed and
unbacked supply; without a comparable rate, the goal delivers half of it.

Being precise about the gap matters, because the imprecise version points at the
wrong fix. A seller-advertised price is already published — inside the settlement
carriers. `AcceptedEscrow.rates` carries a per-hour price for an ERC-20 escrow, and
`settlement_options[*].rates` carries the mechanism-neutral equivalent alongside a
required `asset`. What does not exist is any filter over a rate *value*: every
rate-adjacent filter in `filter-spec.yaml` reads `literal_fields.token` or
`mechanism`, never an amount.

So there are two gaps rather than one, and only a listing-level field closes both.
The first is that no rate is filterable. The second is that the supply this change
exists to serve has no rate to filter: an out-of-band deal settles through
`contact-exchange.v1`, whose options are rateless because the mechanism declines
scalar participation.

**The generic registry also cannot evaluate the field this change publishes, so
two domain-neutral filter-engine capabilities are in scope here.** Range
evaluation is float-typed, so a decimal-text listing value matches no range at all;
and `FilterDecl` has no relationship between filters, so "a rate bound requires an
asset and a period" has no declarative expression. Neither is fixable locally:
`registry-discovery` requires the buyer compiler to resolve every rule from the
active filter specification and add no domain fields. See `design.md`.

The price is per listing shape. A pool that offers several shapes publishes several
listings, and one pool-wide price would misprice all but one of them. It is one
number per shape rather than a per-dimension structure: that structure belongs to
`capacity-shape-pricing`, which prices a shape a buyer proposes during negotiation,
whereas a listing's advertised shape does not vary.

Bare metal is Goal 7's primary target domain, so the rate is designed for VM and
bare metal alike, through one declaration form.

## What Changes

- Publish a seller's asking rate for a compute listing's shape as an
  `asking_rate` object on the published listing resource, carrying an `amount`, the
  `asset` it is quoted in, and the `period` it is quoted per. All three are
  required together. One rate per listing shape, not nested under a capability
  family and not decomposed per dimension.
- Carry the asset as an opaque, non-empty identifier of the same kind a settlement
  option's published asset already carries, not structured token metadata.
- Carry the amount as exact decimal text.
- Accept `hour` as the period, as a local asking-rate contract validated against the
  settlement time-scaling table for parity rather than inherited from it.
- **Extend the generic filter-specification vocabulary with an exact-decimal
  declared value type** whose wire representation is a JSON string and whose
  comparison domain is exact decimal, leaving the JSON-number type untouched.
- **Extend it with declarative filter co-requirements**, resolved from the
  specification by both the registry and the buyer compiler. A filter declaring none
  serializes exactly as it does today, so no existing specification's etag changes.
- Keep every rate-specific concept out of registry engine code. The compute filter
  specification declares the `asking_rate` object and `asking_rate_max`,
  `asking_rate_min`, `asking_rate_asset`, and `asking_rate_period`, all
  fail-on-missing, with both bounds co-requiring the asset and period.
- Match rate filters on the period and the asset rather than normalizing across
  either.
- **Let a site declare asking rates per shape** in a new domain-neutral
  `asking_rates` Resource Pool policy tag, keyed by offering mode, each entry naming
  the capability shape it prices. Validate its structure at every pool-write surface,
  as `listing_shapes` is.
- **Give the storefront final authority** through its site-scoped pool override,
  which may state asking rates for a pool at any site and replaces the pool's as a
  whole list; an empty list withholds every rate. No storefront configuration default
  supplies an asking rate.
- **Join bare metal to the site-scoped override store** for the `bare_metal`
  offering mode, so the storefront tier has final authority on both compute domains.
  Bare metal's vocabulary is settlement clauses, the terms `min_duration_seconds` and
  `max_duration_seconds`, and asking rates; it states no shapes. The override HTTP
  handling moves from the VM storefront into a framework-free route service in the
  override kit, which both storefronts bind. A bare-metal `pool-override` command
  mirrors VM's over the kit's typed client.
- Fail a pool closed on a malformed or unreadable declaration or override, and
  publish no rate for a shape nothing prices.
- Refresh a listing in place when its rate changes or is removed: price is a term of
  sale under the listing-identity rule.
- State normatively that the published rate is a listing attribute and not a
  settlement option rate, and that it and any mechanism rate are independent carriers.
- State that a listing publishing no rate is excluded from a rate-bounded query, and
  that a rate bound naming no asset or no period is refused.

## Capabilities

### Modified Capabilities

- `registry-discovery`: the filter grammar gains an exact-decimal declared value
  type and declarative filter co-requirements, neither changing any specification
  that does not declare them; the compute schema carries the asking rate as a frozen
  three-part object with exact, fail-on-missing filters that match asset and period.
- `storefront-publication`: the asking rate is declared per shape at the listing's
  origin pool and overridable by the storefront's site-scoped override, with no
  configuration default; a malformed declaration fails its pool closed; the rate is a
  listing attribute never derived from or written into a settlement carrier, and a
  rate change refreshes the listing in place.
- `resource-pool-management`: a new domain-neutral `asking_rates` policy tag whose
  structure every pool-write surface validates.

### New Capabilities

None.

## Non-Goals

- Do not make the rate a settlement option rate, and do not add scalar
  participation to a mechanism that declines it.
- Do not describe the published rate as a weaker class of claim than any other
  published field. Claim-strength vocabulary must not enter the schema, the filter
  names, or the specification.
- Do not change the existing `number` value type's comparison semantics.
- Do not encode this change's field, or any rate, asset, or period concept, into
  generic registry or `RegistryClient` logic.
- Do not enforce the asking rate's shape at the registry's publish boundary. The
  registry deliberately validates its full listing shape only in the dry run.
- Do not add a filter over an escrow or settlement-option rate value.
- Do not enforce consistency between the asking rate and a mechanism rate.
- Do not bound what a storefront may advertise or agree against a site-declared
  range, and do not carry any price across the provisioning boundary. Deferred with
  a revisit trigger in `design.md`.
- Do not supply an asking rate from storefront configuration.
- Do not build a rate-honesty control, and do not imply one exists.
- Do not change negotiation-floor pricing policy.
- Do not restrict the rate to unbacked listings.
- Do not add a time period to the settlement vocabulary.
- Do not unbundle the rate across dimensions.

## Impact

- Affected code: the generic registry's filter specification model, etag
  serialization, and filter evaluation; the buyer query compiler's type mapping and
  co-requirement check; the resource-pool kit's policy-tag validation and reader; the
  pool-override kit (a framework-free route service and optional after-write
  effects) and the VM override terms and admin routes; VM publication candidate
  derivation and listing comparison; bare-metal publication once its dependencies
  land; the bare-metal storefront's override contribution, admin routes, migrations,
  durable record of accepted site generations, system status, and `pool-override`
  command.
- Affected specification: `openspec/specs/registry-discovery/spec.md`,
  `openspec/specs/storefront-publication/spec.md`,
  `openspec/specs/resource-pool-management/spec.md`.
- Affected sequencing: the filter-engine work ships before any filter specification
  that uses it — a registry running the current engine fails to load a spec
  declaring the new type or `requires`, rather than ignoring them.
- Affected registry deployment: `core/registry/filter-spec.yaml` gains the
  `asking_rate` object and four filters; its etag changes and buyers re-fetch,
  without a version bump. Other deployed specifications are unaffected.
- Not affected: settlement options, escrow terms, negotiation policy, any agreed
  amount, the provisioning boundary, or the existing `number` value type.

## Dependencies and Related Changes

- **Depends on `bare-metal-publication-reads-pool-declarations`** (complete), without
  which bare-metal publication would read no pool policy tag.
- **Blocked on `bare-metal-listing-shapes`**, which publishes a capability shape per
  bare-metal listing — the key an asking rate is declared against. Joining bare metal
  to the site-scoped override store was scoped there first and moved here: it is
  independent of the shape work, and the storefront tier's authority over asking
  rates is its first bare-metal consumer.
- **System evidence for unbacked supply blocked on `unbacked-bare-metal-listings`**
  (bare metal) and **`compose-contact-exchange-across-compute`** (VM). Until those
  land, no unbacked compute listing can be published in a running stack.
- Builds on the archived `unbacked-listing-publication` and
  `publish-multidimensional-listing-shape`: the backing field, source-publication
  reconciliation, the listing-identity rule, listing shapes, and the site-scoped
  override store.
- **Forward-compatible with `capacity-shape-pricing`**, not dependent on it. Its
  design already states that its single-rate compatibility reading applies to the
  negotiation-side rate and not to a published asking rate.
- Reuses the published-rate vocabulary `kit/settlement-runtime`'s settlement
  publication clause already defines — opaque asset, decimal-text rate, unit supplied
  with the rate. The vocabulary is read, not changed.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md` — no change expected; the declaration
      follows the existing hint-and-override pattern, and nothing crosses a new
      authority boundary. Re-confirm at implementation time rather than assuming.
- [x] Existing subsystem specification —
      `openspec/specs/registry-discovery/spec.md`,
      `openspec/specs/storefront-publication/spec.md`,
      `openspec/specs/resource-pool-management/spec.md`.
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- An exact-decimal declared value type whose comparison never passes through binary
  floating point, leaving the JSON-number type unchanged —
  `openspec/specs/registry-discovery/spec.md`.
- Declarative filter co-requirements, resolved from the active specification by both
  the registry and the buyer compiler, invisible to the etag when undeclared —
  `openspec/specs/registry-discovery/spec.md`.
- The compute schema's asking-rate field and its exact, fail-on-missing, co-required
  filters matching asset and period — `openspec/specs/registry-discovery/spec.md`.
- The asking rate is a listing attribute, not a settlement option rate, and is
  independent of any mechanism rate — `openspec/specs/storefront-publication/spec.md`.
- The asking rate is declared per shape at the origin pool, overridable by the
  site-scoped storefront override with final authority, with no configuration
  default; a malformed declaration fails its pool closed; a rate change refreshes in
  place — `openspec/specs/storefront-publication/spec.md`.
- The `asking_rates` policy tag and its structural validation —
  `openspec/specs/resource-pool-management/spec.md`.
- Bare metal's override vocabulary, its status source (the durable record of each
  site's last accepted generation), and the override route service the storefronts
  bind — `openspec/specs/storefront-publication/spec.md` and its `architecture.md`
  ("Storefront pool overrides"); the bare-metal command and status in
  `docs/development/DEPLOYMENT_AND_CONFIG.md` ("Storefront listing shapes and pool
  overrides").
- Why the rate is keyed by shape beside the shape, and why a site range is deferred
  — `openspec/specs/storefront-publication/architecture.md`.
