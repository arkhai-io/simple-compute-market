## Why

Both compute domains can offer, accept and approve an on-demand or spot deal, but
neither can deliver one. `negotiate-open-ended-compute-terms` and
`spot-deals-through-arkhai-payments` (both archived) built the terms, the
servicing declaration, exact rate mandates with authority-priced `partialPeriod`,
one payments transaction adapter serving once and rate parts, the seller's
`deals preempt`, the buyer's canonical `end` and its opt-in watchdog. Spot then
made end service refuse to commit every deal that is not once-only
(`kit/deal-servicing/src/market_deal_servicing/end.py`, `_unserviceable`), because
nothing yet services a rate deal once it is delivered: a delivered deal would run
with billing started and nobody acting on the buyer's stop, on exhaustion or on a
seller's pending stop. Its design leaves lifting that refusal to whichever change
composes rate servicing (spot D12, D13).

Most of what a running deal needs already exists. Billing starts on delivery,
after site activation and before disclosure
(`domains/compute/delivery/src/compute_delivery/path.py`); the payment watch
records each part's verified final stop as the deal's selected end
(`kit/deal-servicing/src/market_deal_servicing/watch.py`); end service truncates
and tears down once an end is due (`end.py`). Funding exhaustion, the term end, a
notice taking effect, the buyer's stop and the dispute authority's stop are all
stops the payment authority records, so the storefront keeps no funding timer.

This change is Goal 8's MVP servicing change: it lifts the refusal, services
running rate deals in both compute storefronts, and qualifies them in both lanes
against the payments and mediation doubles. It runs beside
`drive-the-storefront-clock-in-lanes`, whose clock its funds-exhausted rows need,
and `switch-on-hosted-per-period-vm` follows it. It takes the servicing slice of
`converge-ongoing-compute-leases`; convergence keeps the opt-in funding timer,
self-penalty filings and revision netting, the recovery runner, one kit loop and
the rest of its matrix.

## What Changes

- **The refusal lifted.** End service stops refusing the commit of a deal whose
  seller projection is not once-only, and authorizes it through the payment
  adapter like any other deal. A deal refused before this change is committed on
  a later drive under a key that does not collide with the refusal journaled as a
  completed commit authorization.
- **Rate servicing composed in both storefronts.** Each composition builds its
  payments seller stage over the servicing declaration and binds the rate
  adapter's `authorize` and `start_billing` into the shared delivery path. The VM
  composition builds its stage itself, as bare metal's does, rather than relying
  on its composition root to build it.
- **Stop causes classified.** The payment watch maps each verified stop cause —
  the buyer's stop, the seller's entitled notice, funding exhaustion, the term end
  and the dispute authority's stop — to the lawful end it is. Exhaustion and the
  term end share the authority's cause `terms`; the stop's effective time against
  the Agreement's end tells them apart.
- **Teardown on a stop in both domains.** A stop taking effect ends delivery at its
  effective time: VM through its end service, bare metal through its
  `drive_physical`.
- **What *ended* means.** The seller's lifecycle list calls a deal *ended* only when
  it is physically released, every payment part has a verified authority stop or
  end, and no end-related case is open; otherwise it is *ending* with its reason,
  such as "rate still running at the authority", which is what operators' manual
  triage acts on.
- **One owner of the servicing step order.** The per-deal step order and its error
  isolation move into a `kit/deal-servicing` helper both storefronts' cycles call;
  the loop registers through `kit/storefront`; the VM cycle's cursor becomes
  durable. Bare metal adopting the helper fixes the remaining defect in its cycle,
  where a failure in `drive_physical` skips that deal's local reconciliation, site
  corrections and filing dispatch for the cycle.
- **The loop's journal allowance.** `settlement-servicing` states that a neutral
  lifecycle loop may journal observations and injected-adapter effects, never
  balances.
- **Startup coherence and withdrawal.** A storefront holding rate deals refuses to
  start without rate servicing composed; withdrawing a treatment from the
  declaration withdraws new offers and keeps servicing existing deals.
- **Restart recovery in both domains.** A restarted storefront rebuilds every
  running deal's servicing from its database and the authorities' records.
- **What the buyer is shown.** The pre-approval display states that an on-demand
  option's premature-stop penalty is collectible only from the seller's earnings
  still held. After a funding stop, the buyer is told the deal cannot be revived
  by a top-up and a new deal is needed.
- **A stale buyer requirement corrected.** `buyer-orchestration`'s "The buyer
  refuses seller ends that keep the started period" says the buyer configures the
  treatments it accepts; the code offers one waiver per refused term instead
  (`kit/settlement-runtime/src/market_settlement_runtime/buyer_terms.py`), as "Each
  default refusal has its own waiver" states. The requirement is reworded to
  match.
- **Lane qualification in both lanes, against both doubles.** The on-demand
  baseline (start, the buyer's stop, teardown); spot preemption with notice; the
  maximum term ending with `returned`; funds running out, which moves the
  storefront's clock with the doubles'; and the buyer watchdog's delivered-deal
  cases spot could not run while every rate commit was refused. Compositions in
  the lanes declare `[charged, returned]`, the treatments the shipped presets use.
  Each run is labelled lane-double evidence, never live.

## Capabilities

### Modified Capabilities

- `deal-lifecycle`: end service's rate-commit refusal lifted and the refused deal's next commit keyed; stop-cause classification for rate parts; the kit-owned per-deal step order; what *ended* means in the seller's list.
- `market-composition`: rate servicing composed in both compute compositions; startup coherence and withdrawal; loop registration through `kit/storefront`.
- `settlement-servicing`: the neutral lifecycle loop's journal allowance.
- `compute-delivery`: a rate deal delivered and its billing started through the shared path; teardown when a stop takes effect.
- `buyer-orchestration`: the penalty's collectible bound and the funding-stop message in the display; "The buyer refuses seller ends that keep the started period" reworded to the per-term waivers.
- `test-compatibility`: the rate lane rows in both lanes, the watchdog's delivered-deal cases, and their evidence labels.

### New Capabilities

None.

## Non-Goals

- The seller's opt-in funding timer, revision netting, and the financial completion fact's revision scoping, pending and unknown operations and manual acknowledgement (convergence tasks 2.1 and 2.3 beyond what this change takes).
- One kit loop with whole-page passes (convergence task 2.2).
- Self-penalty filings and mechanical rulings on rate parts (convergence task 3.2), and execution of a ruling's `stop` or `penalty` effects in the mediation double (convergence task 3.5a).
- The stateless recovery runner and evidence export (convergence task 3.4).
- Convergence's matrix rows 1–5, 8 and 10–13, and the extra windows and races of its task 4.2.
- Setup parts in the lane rows; they need the self-penalty filing path that returns a setup charge on non-delivery.
- Re-anchoring running deals across a payments receipt key change; spot made a key change a drained cutover (its D17).
- The site-enforced delivery deadline (`renewable-compute-lease-deadlines`), and the seller-chosen payout hold and the penalty's collectibility rule (`offer-a-seller-chosen-payout-hold`).
- Hosted runs and any production declaration (`switch-on-hosted-per-period-vm`).

## Impact

- Behaviour: a storefront whose declaration lists rate treatments now delivers its rate deals instead of holding them in repair. No deployed composition declares any, so production is unchanged until `switch-on-hosted-per-period-vm`.
- Buyer behaviour: the default buyer's refusals are unchanged. A seller's option promises a delivery deadline only when its payments clause configures one, which the storefront enforces; `renewable-compute-lease-deadlines` replaces that with the site-enforced pool deadline.
- Composition: the VM settlement composition builds its payments seller stage.
- Database: the physical completion fact, if the existing journal does not already record it in a form the seller's list can read.

## Dependencies and Related Changes

- Depends on no open change. Its funds-exhausted rows need `drive-the-storefront-clock-in-lanes`; its other rows do not, so the two run in parallel.
- `switch-on-hosted-per-period-vm` follows it.
- Builds on `spot-deals-through-arkhai-payments` (archived): the refusal it lifts (D12–D14), the payments transaction adapter (D11), rate `authorize` (D4), the seller's notice and `deals preempt` (D6) and the buyer's `end` and watchdog (D6a), all landed.
- Parts taken from `converge-ongoing-compute-leases` (task numbers in its `tasks.md`): 1.3 (rate servicing in both compositions), 2.1 (the physical fact, and the simple financial fact *ended* reads), 2.2's per-deal step order as a helper (not the whole-page loop), 2.3 (stop-cause classification in both domains, without timers), 2.4 (one operator signal, reduced to *ended* and *ending* with its reason), 2.5 (stop to teardown, authority outage and restart in both domains, without timers or the runner), 3.1 (the rate delivery binding in both domains), 3.5 (startup coherence and withdrawal, without re-anchoring), 4.1 (matrix rows 0, 6, 7 and 9 in both lanes, without setup parts or timer variants), 4.3 (evidence labels); the loop-journal allowance in its `settlement-servicing` delta; and the two items its campaign-index row carries from spot: the refused deal's next commit key, and the watchdog's delivered-deal cases.
- `drive-the-storefront-clock-in-lanes` takes convergence's task 4.1a, the bare-metal storefront clock, since this change's bare-metal funds-exhausted row needs it.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `deal-lifecycle`, `market-composition`, `settlement-servicing`, `compute-delivery`, `buyer-orchestration`, `test-compatibility`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- D1: `deal-lifecycle`'s spec — the refusal's removal and the refused deal's next commit key.
- D2: `deal-lifecycle`'s spec and architecture companion — authority-recorded stops as the only end source for a running rate.
- D3: `deal-lifecycle`'s spec — stop-cause classification, including the `terms` split.
- D4: `deal-lifecycle`'s spec and architecture companion — the kit-owned per-deal step order and its isolation.
- D5: `deal-lifecycle`'s spec — what *ended* and *ending* mean in the seller's list.
- D6: `settlement-servicing`'s spec — the loop's journal allowance.
- D7: `market-composition`'s spec — both compositions build their payments seller stage; startup coherence and withdrawal.
- D8: `buyer-orchestration`'s spec — the penalty's collectible bound and the funding-stop message.
- `buyer-orchestration`'s spec — "The buyer refuses seller ends that keep the started period" names the per-term waivers rather than buyer-configured treatments (a correction, no decision).
- D9: `test-compatibility`'s spec and `docs/development/TESTING.md` — the rate lane rows.
