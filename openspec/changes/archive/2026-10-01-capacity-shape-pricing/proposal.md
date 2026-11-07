## Why

A seller cannot put a price on a capacity shape. A listing's price is a settlement
clause's `rate`, a flat rate per listing-hour that nothing scales by the listing's
shape: the default shape generator publishes one listing per GPU count, and every
one of a model's listings carries the same configured rate, so a 1×H100 and an
8×H100 listing cost the same. Nothing can answer "what would this cost with more
RAM and fewer GPUs", so the VM opening validator (`_validate_vm_opening`, injected
into `kit/negotiation-runtime` as the domain's `validate_opening` hook) rejects any
buyer who names a shape differing from the listing's.

Every layer below is ready: the site authority admits and matches
multidimensionally, `PhysicalSettlementScheduler` fit-checks each requested
dimension, `resize_reservation` is implemented, and the Ansible playbooks build
variable shapes. The missing piece is a seller that can price a shape. This change
is that piece, and it is the prerequisite `negotiation-driven-capacity-resize` §2
and `billable-capacity-reservations` are parked on.

Two defects sit on the same path. Amounts that routinely exceed 64 bits are computed
inexactly in places: a float-parsed negotiation floor, reference amounts and two
mechanism scalers under a 28-significant-digit decimal context. And the seller's
reference amount ignores the option the buyer selected, so a hosted-only listing
negotiates from the floor and a two-mechanism listing negotiates a hosted selection
against the Alkahest rate. A change that composes a rate per asset has to fix both.

## What Changes

- **Per-family rates.** A seller states a rate per unit-hour for each capacity
  family, in an asset, under the family it prices, in one nesting shared by the
  configured default, the pool pricing hint, and the site-scoped storefront pool
  override. Which families are priced, and by what key, is an explicit domain
  pricing projection: for VM, `gpu` per model, `cpu`, `memory`, and `storage`.
- **Two pricing modes.** A listing for which any family resolves rates is
  shape-priced: its clauses name mechanism, asset, and mechanism input, and the
  storefront composes each scalar clause's rate from the listing's shape. A family
  without a rate is not charged. A listing that would be free in an asset is
  refused before it is posted. Otherwise a listing is flat-priced exactly as today.
- **A recorded rate structure able to price other shapes.** A shape-priced listing
  records every family's resolved rates for its GPU model, including families its
  shape omits, as a storefront term of sale on the generic listing record. The
  registry receives exactly what it receives today: each option's composed rate.
- **A replaceable exact aggregator in a new foundation kit**,
  `kit/capability-pricing`, depending only on `kit/capability-shape`. Linear
  summation is the only implementation.
- **Unreadable rates hold the pool, diagnosably.** The provisioning service refuses
  a structurally malformed `pricing` rate list when a pool is written; the storefront
  holds a pool whose rates it still cannot read, keeping its last-published terms,
  and reports the tier, family, and problem in its derivation report and logs.
- **The seller's reference amount is the selected option's rate.**
  `kit/negotiation-runtime`'s `reference_amount` hook receives the buyer's pinned
  proposal; the VM and API-credit storefronts read the selected option's amount
  rate, falling back to `default_min_price` only for an option with no rate.
- **Exact amounts throughout.** One exact decimal-to-base-units helper in
  `kit/settlement-runtime`, used by the Alkahest and hosted mechanism scalers;
  integer arithmetic for both domains' reference amounts; exact parsing of the
  `default_min_price` floor.
- **Retire the dead `min_price`/`token` resolution.** Stored overrides and
  configurations that still state them are tolerated and reported, not refused.
  `default_min_price` stays as the hidden-reserve floor.

This change does not change what is negotiated. Making the negotiated variable a
rate multiplier, the revised-terms field, and the seller's check of a requested
shape before pricing it belong to `negotiation-driven-capacity-resize`, with the
quantitative admissibility it composes from `capacity-shape-envelope`.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `storefront-publication`: commercial resolution yields per-family rates that price
  any shape through a replaceable aggregator; a listing is shape-priced or
  flat-priced and never free; unreadable rates hold the pool; a clause's rate is
  stated or composed, and converts to base units exactly or is refused; the dead
  `min_price`/`token` resolution leaves the hint precedence.
- `negotiation-protocol`: the seller's reference amount is the selected option's
  rate, computed exactly.
- `resource-pool-management`: a pool write refuses a structurally malformed
  `pricing` rate list.

## Non-Goals

- Do not add the protocol field carrying a shape change between rounds, reinterpret
  the negotiated amount as a multiplier, check a requested shape before pricing it,
  or call `resize_reservation`. `negotiation-driven-capacity-resize` owns all four.
- Do not decide the admissible range for a shape (`capacity-shape-envelope`).
- Do not check whether the site can currently serve a shape
  (`negotiation-capacity-feasibility-probe`).
- Do not price capacity holds (`billable-capacity-reservations`), though it consumes
  this change's rates and aggregator.
- Do not implement non-linear or coupled aggregators.
- Do not advertise the rate structure through the registry, and do not change the
  registry (`store-registry-listings-as-published`).
- Do not retire the `default_min_price` hidden-reserve floor, the legacy local tables'
  pricing columns (`pools-9-retire-local-physical-authority`), or the legacy pricing
  migration's reading of legacy inputs.
- Do not change escrow mechanics, obligation shapes, settlement, or the published
  `RateValue`.

## Impact

- **Affected code:** a new `kit/capability-pricing`; `kit/settlement-runtime`;
  `kit/negotiation-runtime`'s hook contract; the Alkahest and hosted mechanism
  scalers; `kit/resource-pools`' hint validators; `domains/vms` (domain pricing
  binding, `arkhai_vms_listings` resolution, reconciler, pricing, and comparison,
  `arkhai_vms_negotiation`'s round hook, and the VM storefront's publication terms,
  publication cycle, override terms, migration narrowing, startup, negotiation
  runtime, and settings); the API-credit storefront's reference amount; the generic
  listing persistence and models in `core/storefront`; example configurations and
  Helm values schemas that state retired keys.
- **Affected tests:** the new kit's, settlement runtime, mechanism rate
  construction, resource-pool validation, pricing resolution, reconciler and
  publication-cycle suites, pool-override validation, negotiation reference amounts
  in both domains, and an end-to-end shape-pricing scenario.
- **Wire compatibility:** no published field changes for a configuration that states
  no family rates and whose rates convert exactly. A shape-priced listing's options
  carry composed rates in the existing fields. The storefront's listing read gains
  the rate structure. Inputs accepted today only through precision loss are refused.
- **Negotiation behavior:** hosted selections negotiate from their option's rate
  instead of the floor; a selection is never referenced against another asset.
- **Configuration:** new `rates` lists under `[pricing.defaults.<family>]`, the pool
  hint, and the override terms. Retired keys are accepted and reported. A fractional
  float floor is refused.
- **Persistence:** a nullable `rate_structure` text column on the generic storefront
  `listings` table, added by a versioned storefront migration; null for every other
  domain. No amount is stored in a fixed-width column.
- **Packaging:** a new distribution, `arkhai-kit-capability-pricing`, on which
  `arkhai-vms` depends; downstream locks change.
- **Rollback:** a code revert. Shape-priced listings' rateless clauses are then read
  as today — an Alkahest clause as a hidden reserve, a hosted clause refused — so an
  operator reverting restores clause rates first.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — the foundation kit list, and the
      "Discovery and negotiation" account of how a listing is priced and what a
      seller negotiates from.
- [x] Existing subsystem specification — `openspec/specs/storefront-publication/spec.md`,
      `openspec/specs/negotiation-protocol/spec.md`, and
      `openspec/specs/resource-pool-management/spec.md`.
- [x] `docs/development/DEPLOYMENT_AND_CONFIG.md` — the pricing configuration,
      override terms, and the refused fractional floor.
- [ ] New subsystem specification — none.

### Knowledge to promote

- Per-family rates, the two modes, the free-listing refusal, the recorded structure,
  and unreadable rates holding the pool — `openspec/specs/storefront-publication/spec.md`.
- The replaceable aggregator and the prohibition on reconstructing totals —
  `openspec/specs/storefront-publication/spec.md`.
- Exact conversion of a publication rate to base units —
  `openspec/specs/storefront-publication/spec.md`, "Publication pricing is explicit
  per settlement clause".
- The selected-option reference amount, computed exactly —
  `openspec/specs/negotiation-protocol/spec.md`.
- Write-time structure check of pricing rate lists —
  `openspec/specs/resource-pool-management/spec.md`.
- Why rates live inside families, why the flat rate is never reinterpreted, why
  `RateValue` was not widened, why pricing is its own kit, and why the structure is
  storefront-served — `openspec/specs/storefront-publication/architecture.md`.
- `kit/capability-pricing` in the foundation layer — `docs/development/ARCHITECTURE.md`.
- Operator-facing pricing configuration — `docs/development/DEPLOYMENT_AND_CONFIG.md`.

## Dependencies and Related Changes

- Depends on `publish-multidimensional-listing-shape` (archived), which delivered the
  listing shape, `kit/capability-shape`, and the site-scoped pool override store.
- Builds beside `publish-indicative-listing-rates` (archived): the asking rate is a
  distinct, per-shape catalogue price; see `design.md`.
- Independent of `settle-capacity-claim-vocabulary`; family names follow
  `COMPUTE_CAPABILITY_SCHEMA`.
- Independent of `add-database-migration-commands`: the rate-structure column is an
  additive entry in the versioned chain that change will run explicitly.
- Unblocks `negotiation-driven-capacity-resize` §2, which consumes the rates, the
  recorded structure, and the aggregator, and owns the seller's check of a requested
  shape before pricing.
- Unblocks `billable-capacity-reservations`, whose hold rate sits beside these rates
  in the same nesting and is evaluated through the same aggregator.
- `store-registry-listings-as-published` is not a dependency.
