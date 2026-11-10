## Why

Goal 8's MVP change `offer-per-period-vm-terms` offers on-demand and spot only on
fixed-shape, flat-priced VM listings: every started period is charged, there is no
premature-stop penalty or setup part, the delivery deadline is the seller's
configured value, `max_duration_seconds` is the only seller bound, the Agreement's
amount is an absolute per-period price, and one composition flag, the declared
treatment list `[charged]`, gates the offer. It takes reduced forms of this change's
tasks 2.1, 2.2, 2.3, 3.1, 3.2 and 4.1 and D1's derived classes.

The full product still needs: per-period options, doors and buyer display in bare
metal; the seller's calendar bound `available_until_utc` and the runway that keeps a
horizon deliverable; presets that return the unstarted period when the seller
preempts; the premature-stop penalty, shown as a ceiling; a seller-priced setup part
where the seller wants one; the payout hold as a term the seller chooses and the
buyer sees; a servicing declaration that names each treatment a composition has
qualified; a repository check that nothing reads `Agreement.amount` around the
accessor; and the default buyer's acceptance policy for those terms in both CLIs.

## What Changes

- Derive reserved, on-demand and spot from billing kind and the selected option's
  payee entitlement, as the MVP does for VM, in both domains; the existing Alkahest
  splitter stays prepaid interruptible (D1).
- A fail-closed repository check refuses direct `Agreement.amount` reads outside the
  unit-bearing accessor and declared raw negotiation hooks, and bare metal's readers
  move to the accessor (D2). The negotiated multiplier's reading of the accessor is
  `negotiation-driven-capacity-resize`'s.
- Keep listing-level `max_duration_seconds` and add `available_until_utc`, through
  hints, storefront overrides and configured defaults. An unnamed recurring horizon
  binds `duration_seconds = min(max_duration, available_until - start)` over stated
  finite bounds at the resolved start, without rounding and with at least one whole
  period; reserved deals satisfy both bounds. A recurring horizon leaves the runway:
  its term end is no earlier than the latest permitted approval plus
  `delivery_deadline_seconds` plus one period, checked at derivation for the default
  horizon and at acceptance for a buyer's (D5).
- Publish bare metal's per-period options on its existing capacity/shape identities,
  and add to both domains' presets the premature-stop penalty, the setup once part
  (seller opt-in on VM, required and seller-priced on bare metal), payee
  `last_boundary` treatment for spot, and the payout hold term (D3, D8, D9).
- The servicing declaration lists the `partialPeriod` treatments a composition has
  qualified; publication, acceptance of cached selections and rate-part
  materialization all read it, and an option naming an undeclared treatment is
  omitted or refused. The MVP's flag is that list, `[charged]` (D6).
- The default buyer refuses charged treatment on a seller's preemption (the payee
  entitlement) and at the term end, accepts it on its own stop, and never
  requires a premature-stop penalty, which it displays as a ceiling. A shorter payout
  hold is displayed as reduced buyer protection, never refused by default (D3, D7).
- Both buyer CLIs show class, unit-bearing price, setup once charge, reserve, maximum
  term, the delivery deadline, entitlements and notices, per-stopper and term-end
  `settles_through`, the penalty as a ceiling, the payout hold and adjudication and
  retention terms (D7).
- Drop bare metal's minimum-spend gate; churn is seller pricing and policy (D8).

## Capabilities

### Modified Capabilities

- `negotiation-protocol`: amount-read guard, both bounds, the runway, and bare metal's horizon and starts.
- `storefront-publication`: listing bounds, classes and option combinations in both domains.
- `resource-pool-management`: validated capacity-bound hints.
- `settlement-configuration`: the declared treatment list and its three doors.
- `buyer-orchestration`: optional recurring horizon in bare metal, the default acceptance policy and the pre-approval display.

### New Capabilities

None. The lifecycle codec and its common semantics belong to `deal-lifecycle`; this change adds the payout hold term to that codec.

## Non-Goals

- Rate settlement, payment and dispute adapters, notice-stop commands, and deriving
  `returned` treatment, setup parts and the payout hold into a mandate:
  `spot-deals-through-arkhai-payments`.
- The negotiated multiplier's reading of the accessor, its discriminator, and keeping
  absolute-reading Agreements absolute: `negotiation-driven-capacity-resize`.
- The pool's `delivery_deadline_seconds` tag, its provider defaults, publishing it as
  the option's term from the site projection, its site enforcement, and retiring the
  payments-clause parameter: `renewable-compute-lease-deadlines`. This change
  publishes whatever deadline the composition supplies.
- Omitting unbounded per-period VM candidates and amending the permanent
  `deal-lifecycle` partial-period rules: `offer-per-period-vm-terms`.
- End service, `end_delivery`, buyer end commands and signed end evidence: the
  lifecycle foundation, archived.
- Discovery and `--class`: `discover-open-ended-compute-listings`.
- Minimum-spend primitives, storefront-local stop scheduling, backdated payment
  stops, or extending accepted leases after listing edits.

## Dependencies and Related Changes

- `offer-per-period-vm-terms`: this change builds on its accessor, its VM presets,
  its declared treatment list, its horizon resolution and whole-second starts, its VM
  buyer CLI and display, and its derived classes.
- `derive-rate-parts-in-the-payments-kit`: fixes `period` and
  `reserve_ahead_seconds`, which the presets consume, and the materialization door
  this change's declaration contract feeds.
- `spot-deals-through-arkhai-payments`: freezes setup pricing and the preset encoding
  with this change, derives `returned` treatment once a composition declares it, and
  derives the payout hold term. Section 2's presets publish in a lane only for
  treatments the composition declares.
- `negotiation-driven-capacity-resize` and `renewable-compute-lease-deadlines` are
  related, not prerequisites: each owns a reading or a value this change consumes
  through the accessor and the composition.
- `converge-ongoing-compute-leases` owns startup and continued servicing in both
  domains; `activate-per-period-compute-servicing` extends each production
  composition's declared treatments after hosted qualification, including
  setup-bearing presets once the hosted mediation service runs the vendored
  delivery_end revision.

## Impact

`scripts/`, `kit/resource-pools-contracts`, `kit/settlement-runtime`,
`kit/deal-lifecycle` (the payout hold term), both compute domain models, both
storefronts' publication, policy and negotiation composition, and both buyer CLIs.
Terms affect option identity; accepted options are immutable and cannot be rewritten
from the current listing. An MVP option keeps its terms and ID.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- Derived classes in both domains and the amount-read guard: architecture vocabulary and negotiation spec.
- Listing bounds, the runway and tier resolution: publication spec and architecture companion; resource-pool-management spec.
- The declared treatment list and its three doors: settlement-configuration spec and publication architecture.
- The default acceptance policy, the payout hold term and truthful display: buyer-orchestration spec and architecture; the hold term in the `deal-lifecycle` codec requirements.
- Codec and authority ownership stays in the lifecycle contract; no second codec is introduced here.
