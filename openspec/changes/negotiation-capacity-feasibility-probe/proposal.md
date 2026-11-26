# Ask the site whether it would admit what a round would reserve

## Why

Before terms are agreed, a compute seller checks its listing against the listing's own
source: before every seller decision, and before a buyer's or an administrator's
acceptance (`kit/negotiation-runtime/src/market_negotiation_runtime/runtime.py`,
`_listing_source`, `_enforce_on_decision`, `_enforce_on_acceptance`). For a
capacity-backed listing that check also asks whether capacity is available, and neither
compute domain puts that question to the site as admission would decide it.

- **VM.** The check reads the bound site's snapshot and judges whether the quantity the
  listing advertises is free now
  (`domains/vms/storefront/src/market_storefront/services/listing_source_check.py`,
  `_pinned_site_availability`). It does not judge the shape the round carries, holds
  over the deal's window, or a conflict on the physical host.
- **Bare metal.** The check reads the projection the storefront holds, which lags the
  site by up to the source-confirmation window, and calls no site
  (`domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/listing_source_check.py`).

Two things follow.

- **A claim the site would refuse is found after the buyer has paid.** The VM storefront
  ships `capacity.hold_ttl_seconds = 0` and the bare-metal storefront composes no hold,
  so nothing is held at acceptance, and the first admission is the reserve at
  settlement (`domains/compute/delivery/src/compute_delivery/path.py`,
  `_reserve_settlement`). A refusal there ends in a refund.
- **A buyer cannot negotiate a shape larger than the advertised one.** Nothing judges a
  requested shape against capacity, so the VM seller refuses any quantity above the
  listing's as `shape_exceeds_advertised`
  (`domains/vms/storefront/src/market_storefront/negotiation_runtime.py`,
  `within_advertised`). A buyer who finds a one-GPU listing on an eight-GPU machine
  cannot ask for four. A seller must publish every size it would sell, and a large
  listing closes once any of its quantity is taken although smaller shapes still fit.

The site already answers the question. `POST /api/v1/capacity/probe` runs the candidate
search a reserve runs and reserves nothing
(`kit/site/src/market_site/ledger.py`, `probe` and `_find_candidate`). Marketplace 0.3.0
and 0.4.0 both serve it. Nothing in negotiation calls it.

## What Changes

- **A seller asks its site whether it would admit the claim a round would reserve**, in
  both compute domains, with the site's existing dry-run (design D1).
- **The question is the availability half of the listing-source check.** The check is
  given the round's effective terms, so the site is asked before every seller decision
  and on all four acceptance paths, for VM and bare metal (D2).
- **Nothing is reserved or held.** The answer is advisory and two negotiations may both
  be told yes; the reserve at settlement stays the admission (D3, D4).
- **A shape the seller's own policy refuses never reaches the site** (D5).
- **The site is unchanged**, and only the listing's own site is asked (D6).
- **An unbacked listing is never asked about, and a site that cannot answer is a
  retryable refusal**, as the source check already decides (D7).
- **The advertised-shape cap lifts.** What then bounds a larger ask where a seller
  stated no maximum is the design's Q1, settled first.

Whether a buyer can ask about feasibility without opening a negotiation, whether the
probe replaces the present availability judgement, the window it asks for, and the
shape of the kit hook are open in the design's "Open Questions".

## Capabilities

### Modified Capabilities

- `negotiation-protocol`: the cap in "A round may revise the capacity shape", and one
  added requirement for the question the seller asks its site.
- `storefront-publication`: what the availability half of "The seller's inventory guard
  checks a listing against its own source" asks, and of "Bare-metal opening rechecks its
  listing against its source".
- `market-composition`: only if the design changes when the runtime obtains the
  listing-source verdict (design Q5).

`.openspec.yaml` sets `skip_specs` until the design session settles the open questions;
the design's Q6 names the requirements to be modified and the one to be added.

### New Capabilities

None.

## Non-Goals

- Holding capacity before settlement. `negotiation-time-capacity-hold` moves the hold
  earlier once held time is charged (D3).
- Removing the race between two negotiations for the same capacity (D4).
- Any change to the site: its route, its ledger, its client or its matching (D6).
- Which shapes a seller will consider, and their price. Admissibility and shape pricing
  have landed and are used as they stand.
- Telling a buyer which shapes a seller would sell. `publish-shape-bounds` owns that.
- A counter-offer naming what the site could serve. The probe returns one match, not a
  range (design Q6).
- The VM storefront's dependency on the site authority package, `arkhai-kit-site`. It is
  recorded as unowned in the change index (D10).
- API credits, whose listings derive from no declaration and compose no listing-source
  check.

## Dependencies and Related Changes

- Nothing gates this change (D8).
- `publish-shape-bounds` discloses a listing's bounds to a buyer. A published maximum
  above the offer can be bought only once the cap lifts, and what an unstated maximum
  means is this change's Q1. Neither waits for the other; whichever lands second
  reverifies against the other.
- `settle-capacity-claim-vocabulary` adds the category of compute to the claim this
  change probes. The probe sends the claim the reserve would send, so it carries the
  category once that change lands. Whichever lands second reverifies against the other.
- `negotiation-time-capacity-hold` holds capacity during negotiation. A thread that
  holds a reservation is judged by resizing it, not by a probe, which is that change's
  to state (design Q6). Its documents have a buyer verify feasibility; whether a buyer
  can do so without proposing is this change's Q2.
- **Builds on**, all archived: `bare-metal-mock-provisioned-deal` (the kit's
  listing-source check), `capacity-shape-envelope` (admissibility),
  `negotiation-driven-capacity-resize` (a round's shape, the evaluation order and the
  cap), `unify-compute-delivery-path` (one settlement reserve for both domains), and
  `inject-site-pool-authority` (the pool facts the site's decisions read).

## Impact

`kit/negotiation-runtime` (the listing-source hook), `kit/capacity-publication` (a probe
at the listing's bound site), both compute storefronts' listing-source checks and
negotiation runtimes, `kit/policy` if a refusal reason is added, both lanes' scenario
stages, `docs/configuration.md`, `docs/development/ARCHITECTURE.md`, and the
`negotiation-protocol` and `storefront-publication` companions.

Compatibility is owed to `marketplace-v0.4.0`, the newest release tag, which carries
every form below as it stands on the development branch.

- **The site.** Nothing changes. The probe route, its route contract and its request
  are those 0.3.0 and 0.4.0 serve, so a 0.4.0 provisioning service answers an upgraded
  storefront.
- **Behaviour.** A round within the advertised shape is refused where the site would
  not admit its claim, which 0.4.0 finds at settlement. A bare-metal round makes one
  site call where 0.4.0 makes none. What a buyer may ask above the advertised shape of
  a listing whose seller stated no maximum is the design's Q1; keeping 0.4.0's
  behaviour for such a seller is one of its alternatives.
- **Wire.** No field is added. A refusal is a reason a buyer reads as text, and a
  released buyer is owed nothing for a reason it has not seen.
- **Persistence.** No decision needs a record a 0.4.0 storefront did not write, and no
  migration is planned. A thread opened under 0.4.0 continues.
- **Configuration.** No setting is added, and nothing is shipped disabled.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`: "Discovery and negotiation" and "Capacity
      reservation".
- [x] Existing subsystem specification: the capabilities above.
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- D1: `openspec/specs/negotiation-protocol/spec.md` and its companion's "Evaluation
  order" and "Current limits"; `docs/development/ARCHITECTURE.md`, "Discovery and
  negotiation" and "Capacity reservation".
- D2: `openspec/specs/storefront-publication/spec.md` and its companion;
  `docs/development/ARCHITECTURE.md`, "Discovery and negotiation";
  `docs/configuration.md`, the row for `has_matching_inventory_guard`.
- D3: `openspec/specs/negotiation-protocol/architecture.md`, "Evaluation order".
- D4: `openspec/specs/negotiation-protocol/spec.md`, as a scenario.
- D5: `openspec/specs/negotiation-protocol/architecture.md`, "Evaluation order".
- D6: `openspec/specs/storefront-publication/spec.md`;
  `docs/development/ARCHITECTURE.md`, "Storefront capacity boundary".
- D7: `openspec/specs/storefront-publication/spec.md`.
- D8: no permanent destination — it records that nothing gates the change.
- D9: `docs/development/ROADMAP.md`, Goal 2, whose open-gap row leaves the table and is
  absorbed into the goal's current state when this change closes out.
- D10: no permanent destination — the change index's unowned entry holds the question.
