## Why

Goal 8's MVP changes sell an on-demand or spot VM paid per hour from a prepaid
Arkhai payments balance: every started period is charged, there is no setup part
and no premature-stop penalty, Arkhai operators handle disputes through the
dispute account's stop and the payments service's reversal, and running deals
drain before a payments signing key retires. That is not yet the product Goal 8
promises. A spot buyer preempted a minute into an hour pays the hour; a seller
who fails an on-demand deal faces no mechanical remedy; bare metal cannot be sold
per period, because provisioning a host is a cost only a setup charge covers; a
seller cannot offer an earlier payout in exchange for reduced buyer protection;
and a key rotation ends every running deal.

The MVP changes land first and supply the rate mechanics this change builds on:
[`derive-rate-parts-in-the-payments-kit`](../derive-rate-parts-in-the-payments-kit/)
derives rate parts under charged treatment, checks them for the buyer, and
supplies the stateless rate adapter, its verified observations and the pure
authorization hook; [`serve-running-rate-deals-on-vm`](../serve-running-rate-deals-on-vm/)
composes them in the VM storefront with the seller's notice command, the buyer's
rate end and the lane's test-mode declaration. Each took a reduced form of this
change's tasks, named by number in `tasks.md`. This change completes the hosted
payment mechanics on top of them, in both compute domains.

The vendored payments contract already publishes every primitive this needs —
per-part authorities, stop entries with notice and all three partial-period
treatments plus the dispute authority's `chosen`, part ends, extensions and both
hold forms (`kit/arkhai-payments/schema/SOURCE.md`). What remains is SCM's half.

## What Changes

- **Authority-executed returned and prorated treatment.** Rate derivation lifts
  the MVP's charged-only refusal for each treatment the composition's servicing
  declaration lists as qualified, never globally. The payment authority prices the
  period in progress at a stop or at the term end; SCM computes no correction.
  Once `returned` is declared, the shipped spot preset carries `last_boundary` on
  the seller's entitlement and at the term end, under new option IDs; deals made
  under earlier presets keep their terms.
- **The dispute authority's `chosen` treatment qualified.** If the MVP ships the
  fixed `charged` fallback on the dispute stop entry, that treatment is bound into
  the option's settlement parameters, so restoring `chosen` gives new options new
  IDs and leaves running deals intact.
- **Setup parts.** An optional seller-priced setup `once` part precedes the rate.
  VM presets carry none by default and a seller opts in with a configured price;
  bare-metal presets require one. Setup is kept on a buyer's stop and returns only
  when the seller never delivered, through the delivery_end ruling. Setup-bearing
  presets stay disabled until a hosted dispute authority is qualified on the
  vendored delivery_end revision.
- **The premature-stop penalty** encoded from the value the terms change resolves,
  and checked by the buyer.
- **A seller-chosen payout hold.** Where the accepted option states a shorter
  payout hold than the default hold until the stop plus the dispute window, the
  rate part derives a `for` hold instead of `afterStop`, and the buyer's exact
  mandate check verifies it. The term and its display are the terms change's.
- **The seller's exceptional end on rate parts.** A seller's `delivery_end` filing
  is observed through the authority's ordinary stop and reversal records,
  including the mediation self-penalty's returned stop, with no seller payment
  call. On-demand notice refusal names that filing path once it is qualified, and
  the VM admin route files it for a seller-caused emergency.
- **Held money on rate parts.** Case extensions, `releaseAt` and the money held
  under them are observed per rate part, and a matured hold surfaces its shortfall
  and the case path rather than a retried refund.
- **The buyer's watchdog**, an opt-in probe loop in the buyer's foreground `buy`
  command that sends the buyer's ordinary stop when the disclosed access fails.
- **Identity re-anchoring** of running rate deals during a bounded service-identity
  overlap, so a key rotation need not drain them.
- **Bare metal's share** of the per-period surfaces the MVP built for VM: preset
  helpers, `deals preempt`, the canonical rate buyer end and first-use fixtures.

## Capabilities

### Modified Capabilities

- `settlement-servicing`: returned, prorated and chosen treatment; setup parts;
  the seller-chosen payout hold; rate-part extensions and matured shortfalls;
  exceptional-end observation; rate-deal identity re-anchoring.
- `settlement-configuration`: the setup amount and per-declared-treatment
  derivation.
- `storefront-publication`: setup-bearing and returned-treatment presets in both
  domains.
- `deal-lifecycle`: bare metal's seller notice and rate buyer end; on-demand
  refusal naming the exceptional-end filing; the buyer's watchdog.
- `test-compatibility`: vector qualification of the treatments and parts the MVP
  excluded.

### New Capabilities

None.

## Dependencies and acceptance boundary

Implementation builds on:

1. The archived foundation,
   [`agreed-evidence-and-early-termination`](../archive/2026-11-03-agreed-evidence-and-early-termination/):
   the lifecycle codec and authority derivation, the vendored payments and
   mediation contracts, the delivery_end dispute intent and its signing, the
   evidence stores and the verifier that accepts bounded identity history.
2. `derive-rate-parts-in-the-payments-kit` and `serve-running-rate-deals-on-vm`:
   the rate derivation, adapter, observations, authorization hook, materialization
   gate, seller notice, buyer rate end and lane declaration this change extends.
3. `negotiate-open-ended-compute-terms`: the servicing declaration's list of
   qualified treatments, the buyer acceptance policy, the premature-stop penalty's
   resolution and display, the payout-hold term and its display, the injected
   preset-helper interface and bare metal's publication, horizon and starts.
4. The archived lane double's in-process engine for kit library integration and
   its HTTP doubles for lane evidence, labelled lane-double evidence, never live.

`converge-ongoing-compute-leases` depends on this change: it owns rate servicing
beyond the MVP in both domains, the consolidated rate qualification matrix and its
runnable scenarios, including the mediation double's execution of a ruling's stop
and penalty effects. This change prepares entry points and runs no lane
qualification of them. `activate-per-period-compute-servicing` owns the hosted
switch-on of what this change adds.

Complete here means exact derivation and buyer checking of every part, treatment
and hold this change adds, usable adapter mechanics and both domains' preset,
notice and buyer-end surfaces, with vector, kit and application evidence. A
passing double-backed scenario never qualifies the external payment or dispute
authority.

## Non-Goals

- Everything an MVP change owns; `tasks.md` names each moved task.
- The buyer acceptance policy, the penalty and payout-hold terms and their
  display, and the servicing declaration's contract, which the terms change owns.
- The multiplier price reading and its accepted rate-structure carrier, which
  `negotiation-driven-capacity-resize` owns as an input to the price accessor.
- A minimum-spend primitive, payee backdating, or a local payment-stop scheduler;
  the design records the rejected payment primitives.
- Storefront continuation, funding timers, site deadline or renewal policy,
  provisioning or teardown.
- Snapshot-proof verification, immediate `end_delivery` transport and mediation
  rulings, which are the foundation's or the authority's.
- Durable once-only identity re-anchoring; those deals drain before a key retires.
- Discovery sugar, automated preemption strategy, Alkahest splitter execution,
  API-credit rate servicing, metering other than time, and reserved
  fixed-interval deals expressed as rate parts.
- Any guarantee that depends on a cooperative storefront: the buyer's backstop is
  its own authority stop and a case over held money.

## Compatibility and impact

No backwards-compatibility promise for pre-upgrade hosted mandates; rollout is
forward only. Every new preset shape — a treatment, a setup part, a penalty, a
shorter payout hold, a bound dispute-entry treatment — receives a new option ID,
and deals made under earlier options keep their accepted terms. Reserved and
API-credit options keep `once`-part mechanics. Examples use `USD/6`; production
derivation reads the selected Agreement's asset.

Affected code: `kit/arkhai-payments`, `kit/deal-lifecycle-buyer`, both compute
storefront compositions and operator CLIs, and the bare-metal buyer's end verb.
No mechanism kit imports a domain or the persistence-owning servicing kit.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — adapter and servicing ownership
- [x] Existing subsystem specifications — the five capabilities above
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- Returned, prorated and chosen treatment, setup parts, the payout hold,
  rate-part extensions and re-anchoring: `openspec/specs/settlement-servicing/spec.md`
  and its architecture companion.
- Per-declared-treatment derivation and identity-overlap configuration:
  `openspec/specs/settlement-configuration/spec.md` and
  `docs/development/DEPLOYMENT_AND_CONFIG.md`.
- Setup and returned-treatment presets: `openspec/specs/storefront-publication/spec.md`
  and its architecture companion.
- Bare metal's notice and buyer end, the watchdog and the on-demand refusal:
  `openspec/specs/deal-lifecycle/spec.md` and its architecture companion.
- Vector qualification of the added treatments: `openspec/specs/test-compatibility/spec.md`.
