## Why

A VM listing cannot say how a deal is billed or whether its seller may end it,
the VM buyer's `buy` requires a duration, and an Agreement's price has no stated
unit: `Agreement.amount` is an absolute total over `duration_seconds`
(`core/src/market_core/schemas.py`). So no buyer can be offered an on-demand or a
spot VM, even in a lane.

This change is one of Goal 8's MVP changes: the smallest set that lets a buyer
take an on-demand or spot VM paid per hour from a prepaid Arkhai payments
balance, with disputes handled by operators. It supplies the terms half — the
offer a buyer finds, reads and accepts — and keeps the offer dark behind a
composition flag until the servicing changes turn it on. It takes its parts from
[`negotiate-open-ended-compute-terms`](../negotiate-open-ended-compute-terms/)
and [`discover-open-ended-compute-listings`](../discover-open-ended-compute-listings/),
in a reduced form that does not wait on their cross-goal prerequisites.

## What Changes

- **Per-period options on a VM listing.** A VM storefront publishes, beside its
  existing once-only options, an on-demand option and a spot option on a listing
  with a fixed shape and a flat per-period price. On-demand carries a payer
  entitlement with zero notice and no payee entitlement; spot adds a payee
  entitlement with the seller's priced notice. Every entitlement and the term end
  settle through the started period (`started_period`, carried on the wire as
  `partialPeriod: charged`). No premature-stop penalty and no setup part.
- **A unit-bearing price.** An accessor states whether an Agreement's amount is a
  total or a per-period price, with only the absolute reading in this change, so
  the negotiated multiplier `negotiation-driven-capacity-resize` plans adds a
  reading later instead of migrating callers twice.
- **The horizon.** The seller's bound is the listing's existing
  `max_duration_seconds`; an on-demand Agreement's `duration_seconds` is resolved
  from it when the buyer names none. Recurring starts are whole seconds.
- **The delivery deadline from seller configuration.** The option's
  `delivery_deadline_seconds` stays the value the seller's payments clause
  configures today (`kit/arkhai-payments/src/market_arkhai_payments/settlement_config.py`),
  and storefront servicing enforces it. The permanent `deal-lifecycle`
  requirements that call it "the deadline its site enforces" are amended to say
  so, since no site enforces one.
- **Derived classes and buyer display.** Reserved, on-demand and spot are derived
  from an option's terms, never declared. The VM buyer CLI no longer requires a
  duration for a per-period option and shows, before approval, the class, the
  per-period price, the reserve ahead, the latest end, the notice each party has
  and that a started period is charged.
- **The MVP buyer defaults.** The default buyer accepts a started-period final
  period on every entitlement and at the term end, and does not require a
  premature-stop penalty, so a buyer who changed no setting can take one.
- **Finding the options.** A local `arkhai_payments.period` settlement clause
  field, and documented `--resource`/`--settlement` recipes over the registry's
  existing lifecycle filters, which already correlate predicates to one option.
- **The composition flag.** One flag in the VM composition gates publication and
  acceptance of per-period options; it stays off until
  `serve-running-rate-deals-on-vm` composes the servicing.

## Capabilities

### Modified Capabilities

- `negotiation-protocol`: the unit-bearing price accessor; whole-second recurring starts; the horizon resolved into `duration_seconds`.
- `storefront-publication`: separately priced on-demand and spot options on one fixed-shape VM listing, gated by the composition flag.
- `settlement-configuration`: the per-period lifecycle presets; the `arkhai_payments.period` clause field.
- `buyer-orchestration`: the optional duration, the pre-approval display, derived classes, and the MVP acceptance defaults.
- `deal-lifecycle`: the delivery deadline's source and enforcer stated as they are.

### New Capabilities

None.

## Non-Goals

- Negotiating shape or price on a per-period option; the multiplier and its carrier stay with `negotiation-driven-capacity-resize`.
- `available_until_utc`, its registry carrier, and registry bound filters (`store-registry-listings-as-published`, `discover-open-ended-compute-listings`).
- A `--class` shortcut; recipes stand in for it.
- The premature-stop penalty, its presets and the default refusal of an on-demand option without one; setup parts; the runway inequality; a static check on direct `Agreement.amount` reads.
- A site-enforced delivery deadline and its pool tag (`renewable-compute-lease-deadlines`).
- Bare metal and Alkahest per-period options.
- Rate mandate derivation and billing (`derive-rate-parts-in-the-payments-kit`) and running a deal (`serve-running-rate-deals-on-vm`).

## Impact

- Wire: an accepted Agreement's amount for a per-period option is an absolute per-period price. Agreements are signed and immutable, so this reading stays valid for every Agreement made under it; a later multiplier reading needs a discriminator, not a migration.
- Buyer behaviour: the default acceptance policy for per-period options is new; once-only options are unchanged.
- No database or deployment change; the composition flag ships off.

## Dependencies and Related Changes

- Runs in parallel with `derive-rate-parts-in-the-payments-kit` and `drive-the-storefront-clock-in-lanes`. The per-period payment parameters (`period`, reserve ahead) are defined once, by `derive-rate-parts-in-the-payments-kit`'s first task; this change consumes them.
- `serve-running-rate-deals-on-vm` turns the flag on.
- Parts taken from `negotiate-open-ended-compute-terms` (task numbers in its `tasks.md`): 2.1 (accessor, absolute reading only), 2.2 (reduced to `max_duration_seconds`), 2.3 (on-demand and spot options; deadline from seller configuration), 3.1 (one flag over publication and acceptance), 3.2 (horizon resolution and whole-second starts), 4.1 (VM CLI and display; MVP defaults), and D1's derived classes for display.
- Parts taken from `discover-open-ended-compute-listings`: 1.2 and the local half of 2.2 (the `arkhai_payments.period` field), 2.3 (unit preservation), 3.1 reduced to recipes.
- Those changes keep everything else and are rewritten against this one once the MVP change set's boundaries are settled.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `negotiation-protocol`, `storefront-publication`, `settlement-configuration`, `buyer-orchestration`, `deal-lifecycle`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- D1: the accessor's absolute reading and the fixed-shape restriction to `negotiation-protocol`'s spec.
- D2: the presets to `settlement-configuration`'s spec; the default acceptance to `buyer-orchestration`'s spec; a charged started period as an accepted limitation in `deal-lifecycle/architecture.md`.
- D3: no permanent destination — a scope choice, recorded in Goal 8 of `docs/development/ROADMAP.md`.
- D4: `deal-lifecycle`'s spec, amending its two delivery-deadline requirements.
- D5: the `arkhai_payments.period` field to `settlement-configuration`'s spec; the recipes to the buyer documentation that already describes `--resource` queries.
