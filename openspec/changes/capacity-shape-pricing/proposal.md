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

The pricing path also carries amounts that routinely exceed 64 bits, and several
places on it compute them inexactly: a float-parsed negotiation floor, a reference
amount and two mechanism scalers computed under a 28-significant-digit decimal
context. A change that produces longer composed totals has to fix them first.

## What Changes

- **Per-family rates.** A seller states a rate per unit-hour for each capacity
  family, in an asset, under the family it prices — `gpu` keyed by model, `cpu`,
  `memory`, and `storage` unkeyed — in one nesting shared by the configured
  default, the pool pricing hint, and the site-scoped storefront pool override.
- **Two pricing modes, decided by the GPU family.** A listing whose GPU model
  resolves rates is shape-priced: its clauses name mechanism, asset, and mechanism
  input, and the storefront composes each clause's rate from the listing's own
  shape. Otherwise it is flat-priced exactly as today. A configuration that states
  no family rates publishes byte-identical options. Mixed or incomplete inputs
  refuse the candidate with a reason; a named family with no rate is unpriceable,
  never free.
- **A replaceable aggregator** in `kit/capability-shape`: shape and one asset's
  family rates in, an exact price or an unpriceable result out. Linear summation is
  the only implementation, and evaluation is callable outside the negotiation path.
- **Exact amounts throughout.** One exact decimal-to-base-units helper in
  `kit/settlement-runtime`, used by the Alkahest and hosted mechanism scalers;
  integer arithmetic for the seller's reference amount; exact parsing of the
  `default_min_price` floor.
- **The rate structure as a storefront term of sale.** A shape-priced listing's
  resolved family rates are recorded on the storefront's listing record and
  returned by its listing read. The registry receives exactly what it receives
  today: each option's composed rate for the listing's own shape.
- **Retire the dead `min_price`/`token` resolution.** Per-model resolution of
  `min_price` and `token`, the candidate fields, and the
  `[pricing.defaults.gpu.<model>].min_price/token` and `default_token_address`
  defaults are removed. Stored overrides and configurations that still state them
  are tolerated and reported, not refused. `default_min_price` stays as the
  hidden-reserve floor.
- **Seller feasibility guard (Section 5)** for a requested shape, ordered before
  pricing. Not part of the Sections 1–3 implementation; whether it becomes its own
  change is decided when it is taken up.

This change does not change what is negotiated. Making the negotiated variable a
rate multiplier, reinterpreting the kit's amount hooks, and the revised-terms field
are one deployment boundary owned by `negotiation-driven-capacity-resize`. After
this change every existing negotiation prices exactly as before.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `storefront-publication`: commercial resolution yields per-family rates that
  price any admissible shape through a replaceable aggregator; a listing is
  shape-priced or flat-priced; a clause's rate is stated or composed, and converts
  to base units exactly or is refused; the dead `min_price`/`token` resolution
  leaves the hint precedence.
- `negotiation-protocol`: a seller policy evaluates a requested shape's feasibility
  before pricing it (Section 5); the seller's reference amount is exact.

## Non-Goals

- Do not add the protocol field carrying a shape change between rounds, reinterpret
  the negotiated amount as a multiplier, or call `resize_reservation`.
  `negotiation-driven-capacity-resize` owns all three.
- Do not decide the admissible range for a shape (`capacity-shape-envelope`).
- Do not check whether the site can currently serve a shape
  (`negotiation-capacity-feasibility-probe`).
- Do not price capacity holds (`billable-capacity-reservations`), though it
  consumes this change's rates and aggregator.
- Do not implement non-linear or coupled aggregators.
- Do not advertise the rate structure through the registry, and do not change the
  registry. Keeping listing-level fields the registry currently discards is
  `store-registry-listings-as-published`'s.
- Do not retire the `default_min_price` hidden-reserve floor, the legacy local
  tables' pricing columns (`pools-9-retire-local-physical-authority`), or the legacy
  pricing migration's reading of legacy inputs.
- Do not change escrow mechanics, obligation shapes, settlement, or the published
  `RateValue`.

## Impact

- **Affected code:** `domains/vms/listings` (`pricing_resolution.py`,
  `reconciler.py`, `pricing.py`), `domains/vms/negotiation/storefront_round.py`,
  the VM storefront's `services/publication_terms.py`, `services/publication_loop.py`,
  `models/pool_override_models.py`, `negotiation_runtime.py`, its listing read and
  `settings.toml`; `kit/capability-shape`; `kit/settlement-runtime`; the Alkahest
  and hosted mechanism scalers in `kit/alkahest` and `kit/hosted-settlement`; the
  example storefront configurations and Helm values schemas that state retired
  keys. Section 5 adds `domains/vms/negotiation/policies.py` and the VM
  `evaluate_round` composition.
- **Affected tests:** pricing resolution, reconciler and publication-cycle suites,
  pool-override validation, mechanism rate construction, negotiation reference
  amount, and e2e price assertions.
- **Wire compatibility:** no published field changes for a configuration that
  states no family rates; settlement options and their identities are
  byte-identical. A shape-priced listing's options carry composed rates in the
  existing fields. The storefront's listing read gains the rate structure.
- **Configuration:** new `rates` lists under `[pricing.defaults.<family>]`, the
  pool hint, and the override terms. Retired keys are accepted and reported.
- **Persistence:** the storefront's listing record carries the rate structure as
  JSON text. No amount is stored in a fixed-width column.
- **Rollback:** a code revert. Shape-priced listings' rateless clauses are then read
  as today — an Alkahest clause as a hidden reserve, a hosted clause refused — so an
  operator reverting restores clause rates first.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — the "Discovery and negotiation" section's
      account of how a listing is priced.
- [x] Existing subsystem specification — `openspec/specs/storefront-publication/spec.md`
      and `openspec/specs/negotiation-protocol/spec.md`.
- [x] `docs/development/DEPLOYMENT_AND_CONFIG.md` — the pricing configuration and
      override terms an operator states.
- [ ] New subsystem specification — none.

### Knowledge to promote

- Per-family rates, the two pricing modes, refusal of mixed and incomplete inputs,
  and the rate structure as a storefront term of sale —
  `openspec/specs/storefront-publication/spec.md`.
- The replaceable aggregator and the prohibition on reconstructing totals —
  `openspec/specs/storefront-publication/spec.md`.
- Exact conversion of a publication rate to base units —
  `openspec/specs/storefront-publication/spec.md`, "Publication pricing is explicit
  per settlement clause".
- An exact seller reference amount; feasibility before pricing (Section 5) —
  `openspec/specs/negotiation-protocol/spec.md`.
- Why rates live inside families, why the flat rate is never reinterpreted, why
  `RateValue` was not widened, and why the structure is storefront-served —
  `openspec/specs/storefront-publication/architecture.md`.
- Operator-facing pricing configuration — `docs/development/DEPLOYMENT_AND_CONFIG.md`.

## Dependencies and Related Changes

- Depends on `publish-multidimensional-listing-shape` (archived): it delivered the
  listing shape, `kit/capability-shape`, and the site-scoped pool override store
  this change's override tier is.
- Independent of `settle-capacity-claim-vocabulary`; family names follow
  `COMPUTE_CAPABILITY_SCHEMA`.
- Unblocks `negotiation-driven-capacity-resize` §2, which consumes the rates and
  the aggregator, and owns where a buyer reads the rate structure.
- Unblocks `billable-capacity-reservations`, whose hold rate sits beside these
  rates in the same nesting and is evaluated through the same aggregator.
- Section 5 consumes `capacity-shape-envelope`'s admissibility when present; the
  two are otherwise independent.
- `store-registry-listings-as-published` is not a dependency: nothing here needs
  the registry to keep a new field.
- `publish-indicative-listing-rates` publishes a distinct catalogue asking rate;
  see `design.md` for why neither quantity is read as the other.
