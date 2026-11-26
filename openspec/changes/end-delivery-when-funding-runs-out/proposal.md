# End delivery when funding runs out

## Why

A compute deal stops being delivered for want of funds by three routes that share
nothing but the journal they end in:

- A deal paid per period ends when the storefront reads the payment authority's own
  stop. The authority stops the deal at the instant it is funded through, and the
  storefront's watch records that stop on its next verified read
  (`kit/deal-servicing/src/market_deal_servicing/watch.py`).
- A deal paid once ends at the Agreement's end, which the servicing cycle records for
  itself (`kit/deal-servicing/src/market_deal_servicing/servicing.py`).
- An Alkahest deal ends when its settlement becomes terminal without being collected,
  through a hook each compute storefront wires for itself. The two hooks differ: the VM
  storefront ends on any outcome but a collection and leaves the end's classification
  pending, and the bare-metal storefront ends on three named outcomes and classifies
  the end as the terms' own
  (`domains/vms/storefront/src/market_storefront/settlement_composition.py`;
  `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/runtime.py`).

No rule says when a deal's delivery ends from what the deal has funded. The instant a
per-period deal is funded through is read, saved and shown at every servicing read, and
it gates delivery phases, but nothing ends delivery on it
(`kit/arkhai-payments/src/market_arkhai_payments/rate_parts.py`;
`openspec/specs/deal-lifecycle/architecture.md`, "Current limits").

One case falls through. When a storefront cannot read the payment authority after a
deal's funded instant has passed, it records no stop and ends nothing, so the seller
serves unpaid for as long as the authority stays out of reach. On-demand and spot VM
are a supported configuration in marketplace 0.4.0, and those are the deals whose
funded instant moves while they run.

## What Changes

- **One rule ends delivery at the funded instant.** `kit/deal-servicing` ends a deal's
  delivery once the instant its mechanism reports as funded has passed, in the
  servicing cycle both compute storefronts run, for every mechanism and every class of
  deal (design D1, D5).
- **A read comes first.** The rule ends nothing on a saved instant. It reads the
  mechanism again: a later funded instant replaces the earlier one, and the mechanism's
  own end is the end, as today (D6).
- **Every mechanism reports its funded instant through one port**, Alkahest included.
  The two storefronts' terminal-settlement hooks are removed, and an Alkahest
  settlement that ends uncollected reaches end service on the same path as every other
  mechanism's end (D4).
- **The calculation always runs.** No setting enables it (D3).
- **The site, the payments contract and the payments kit's operations are unchanged**
  (D1, D2). The rule reads instants and computes no money (D7).
- **Each compute lane runs funds running out with the payment authority out of reach**,
  on lane time against the payments double, beside the row that runs today with the
  authority readable.

What a storefront does when a funded instant has passed and cannot be confirmed, how
such an end is classified, and the port's shape are open in the design's "Open
Questions".

## Capabilities

### Modified Capabilities

- `deal-lifecycle`: the rule and its place in the servicing order, the classification
  of an end the rule records, terminal settlement as a mechanism's report, and an
  Alkahest deal's authority view.
- `settlement-servicing`: what a rate observation is used for.
- `test-compatibility`: the lane row with the payment authority out of reach.
- `resource-pool-management`: only if the design states the unconfirmed posture as a
  pool tag.

`.openspec.yaml` sets `skip_specs` until the design session settles the open
questions; the design names the requirements to be modified.

### New Capabilities

None.

## Non-Goals

- A billing horizon the seller advances at the payment authority. Nothing is asked of
  the payments contract (D2).
- A deadline on the active site lease that the storefront renews, and any site policy
  for one that lapses. The site is untouched; the alternative is revisited when a
  site's operator is not its storefront's (D1).
- Pooled funding, one balance behind several leases, which the roadmap tables as
  unowned.
- A cancellation term for a buyer leaving a committed deal early, which the roadmap
  tables as unowned. A deal billed in parts ends at its funded instant; what the buyer
  then owes is not this change's (D5).
- Ending a lease whose storefront is not running. An operator ends it at the site, as
  the operator handbook's "Leases the storefront has not delivered" says (D1).
- API credits, whose roles compose no lifecycle servicing.
- Any change to what a buyer may do at the authorities.

## Dependencies and Related Changes

- Nothing gates this change.
- `converge-ongoing-compute-leases` overlaps it in text only. Both modify
  `deal-lifecycle`'s "Each deal's servicing steps run in one kit-owned order";
  whichever lands second reverifies against the other. That change gave up the funding
  timer (its design, D4), and its scenario diagram of one is redrawn here.
- `renewable-compute-lease-deadlines` names this change as the owner of any end
  calculated from what a deal has funded (its design, D4). Nothing of it is used: the
  site is untouched.
- `discover-open-ended-compute-listings` settles how a class is read. The rule reads no
  class (D5).
- `activate-per-period-compute-servicing` completes Goal 8, which waits for this
  change (D8). Whether it depends on this change is open in the design.
- **Builds on**, all archived: `agreed-evidence-and-early-termination` (end service and
  its journal), `spot-deals-through-arkhai-payments` (the rate adapter and its
  observations), `serve-running-rate-deals` (the servicing cycle and the payment-stop
  classifier), `unify-compute-delivery-path` (one delivery path for both domains),
  `add-arkhai-payments-lane-double` and `drive-the-storefront-clock-in-lanes` (the
  double's controls and lane time).

## Impact

`kit/deal-servicing` (the servicing cycle, the watch), `kit/arkhai-payments` and
`kit/alkahest` (each adapter's report), `kit/deal-lifecycle` and
`kit/deal-lifecycle-contracts` if the port changes the adapter protocol or the
authority view, `domains/compute` (the classification of an end), both compute
storefronts (the removed hooks and their settlement-worker wiring),
`kit/resource-pools-contracts` if the posture is a pool tag, both lanes' scenario
stages, `docs/operator-handbook.md` and `docs/development/ARCHITECTURE.md`.

Compatibility is owed to `marketplace-v0.4.0`, the newest release tag, which carries
every form below as it stands on the development branch.

- **Behaviour.** Where the payment authority can be read, a deal ends as it does under
  0.4.0, on the authority's recorded stop. A pool that states nothing keeps 0.4.0's
  behaviour where it cannot be read; that is a constraint on the design's Q1. An
  Alkahest settlement that ends uncollected still ends delivery; the two storefronts
  then agree on which outcomes do and how the end is classified, which changes one of
  them.
- **The site.** Nothing changes. A 0.4.0 site serves an upgraded storefront, and a pool
  tag, if the design chooses one, is accepted and projected by a 0.4.0 site as a tag it
  does not know.
- **The payments contract.** Nothing is requested, and the vendored revision is
  unchanged.
- **Wire.** None is settled. The lifecycle wire models refuse an unknown field, so a
  field the port adds to the authority view is an incompatible step of
  `kit/deal-lifecycle-contracts`, shipped with the clients that read it; a released
  client is not owed reading a later storefront.
- **Persistence.** No decision needs a record a 0.4.0 storefront did not write. If the
  design adds one, it is an additive migration appended to each storefront chain, and
  deals a 0.4.0 storefront serviced read correctly with no backfill.
- **Configuration.** No setting is added.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`: "Settlement servicing".
- [x] Existing subsystem specification: the capabilities above.
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- D1: `openspec/specs/deal-lifecycle/spec.md` and its companion;
  `docs/development/ARCHITECTURE.md`, "Settlement servicing";
  `docs/operator-handbook.md`, "Serving rate deals".
- D2: `openspec/specs/deal-lifecycle/architecture.md`, "External authorities".
- D3: `openspec/specs/deal-lifecycle/spec.md`;
  `openspec/specs/deal-lifecycle/architecture.md`, "Current limits", which stops saying
  a storefront runs no funding timer.
- D4: `openspec/specs/deal-lifecycle/spec.md` and its companion;
  `openspec/specs/settlement-servicing/architecture.md`.
- D5: `openspec/specs/deal-lifecycle/architecture.md`, "Parts and terms".
- D6: `openspec/specs/deal-lifecycle/spec.md`;
  `openspec/specs/settlement-servicing/spec.md`.
- D7: `openspec/specs/settlement-servicing/spec.md`;
  `docs/development/ARCHITECTURE.md`, "Settlement servicing".
- D8: `docs/development/ROADMAP.md`, Goal 8, whose open-gap row leaves the table and is
  absorbed into the goal's current state when this change closes out.
