## Why

Both compute domains can offer, accept and approve an on-demand or spot deal, but
neither delivers one. `negotiate-open-ended-compute-terms` and
`spot-deals-through-arkhai-payments` (both archived) built the terms, the servicing
declaration, exact rate mandates with authority-priced `partialPeriod`, one payments
transaction adapter serving once and rate parts, the seller's `deals preempt`, the
buyer's canonical `end` and its opt-in watchdog. Spot then made end service refuse to
commit every deal that is not once-only
(`kit/deal-servicing/src/market_deal_servicing/end.py`, `_unserviceable`), because
nothing yet serviced a delivered rate deal, and left lifting the refusal to whichever
change composes rate servicing (spot D12, D13).

Most of what a running deal needs already runs for any deal: the delivery path
authorizes each phase and starts billing through the one payments adapter
(`domains/compute/delivery/src/compute_delivery/path.py`), the payment watch records
each rate part's verified final stop as the deal's end
(`kit/deal-servicing/src/market_deal_servicing/watch.py`), and end service terminates
or truncates on it. What breaks once the refusal goes is narrower: end service refuses
a payment answer that changes while a deal's revision stands still, which a rate
answer does; no payment stop is ever classified, so a buyer's stop cannot discharge a
later seller-failure filing; the seller list calls a deal *ended* while a rate part may
still bill; and the two storefronts' servicing cycles order their steps differently,
bare metal's skipping its filings when its physical work fails.

This change is Goal 8's MVP servicing change: it lifts the refusal, services running
rate deals in both compute storefronts, unifies the two storefronts' servicing and
delivery-recovery loops, and qualifies rate deals in both lanes against the payments
and mediation doubles. It runs beside `drive-the-storefront-clock-in-lanes`, whose lane
time its lane rows are written against, and `switch-on-hosted-per-period-vm` follows
it. It takes the servicing slice of `converge-ongoing-compute-leases`.

## What Changes

- **The refusal lifted, and changed answers held back** (D1). End service no longer
  refuses to commit a deal that is not once-only. When the payment adapter answers a
  phase differently at a revision whose first answer is journaled, end service returns
  `pending` and journals nothing, so a changed answer only holds a phase back.
- **Payment stops classified** (D2, D3). One classifier in `arkhai_compute`, passed by
  both storefronts' watches, classifies every payment stop, once-only deals' included,
  from its cause and the deal's entitlements; a `terms` stop before the Agreement's end
  is funds running out. Earlier pending payment stops are resolved when next read.
- **One servicing step order, and the cycles unified** (D4, D6). A `kit/deal-servicing`
  helper runs respondent discovery, then each deal's steps in a fixed order, each
  isolated. Both domains record their own term end, discover respondents once per
  dispute authority through a respondent port they fill, page every registered deal,
  and keep the page position in a kit-owned table.
- **One loop layout and one delivery re-drive** (D5). Both storefronts run
  `deal-servicing`, `delivery-recovery`, `payment-reconciliation` and
  `settlement-servicing`, one job each; the re-drive is one routine in
  `domains/compute/delivery` over domain ports.
- **What *ended* means, and why a deal is ending** (D7). *Ended* requires physical
  release, every payment part stopped or ended at the payments service, and no open
  case; the seller list's `ending` codes say what is outstanding. The lifecycle
  contracts take an incompatible version, and the lifecycle read and list stop omitting
  newer fields for 0.1.0 clients.
- **A storefront that cannot service its deals reports them** (D8). It starts, shows
  them repair required and reports them at startup; withdrawing a treatment keeps
  servicing existing deals.
- **The VM composition builds its own payments seller stage** (D11).
- **The loop's journal allowance** (D12) in `settlement-servicing`.
- **What the buyer is shown** (D13): the penalty's collectible bound before approval,
  and after a funding stop that a top-up cannot revive the deal.
- **A stale buyer requirement corrected, and restart recovery proven** (D14).
- **An Agreement nobody filed on is observed** (D16): the mediation adapter reads the
  authority's first-page `404 invalid_request` as no case, so such a deal can be listed
  *ended*, both halves' reads carry an accepted dispute outcome, and evidence retention
  runs; the kit's fake answers as the authority does. The read is not verified: the
  authority gives a reader who is no party the same answer, so it rests on the
  credential authenticating the Agreement's party, and the limit under one that does
  not is stated.
- **The scenario programs the payments double's further reservation** (D17): a control
  reserving each running rate part through a named instant, as far as its end and the
  payer's balance allow, in place of the service's scheduler, and refusing a
  transaction with no running rate part.
- **Lane qualification in both lanes, against both doubles** (D9, D10, D18, D19): the
  on-demand baseline with the buyer's stop, funds running out, spot preemption with
  notice, the maximum term ending with `returned`, and the buyer watchdog's
  delivered-deal cases with the storefront paused, each reaching its instants by
  setting lane time. Lane compositions declare `[charged, returned]`. Each run is
  labelled lane-double evidence, never live; the Compose lanes are this change's
  evidence.

## Capabilities

### Modified Capabilities

- `deal-lifecycle`: the refusal removed and changed answers pending; payment-stop classification, the `terms` split and the resolution of earlier pending stops; the kit-owned servicing step order, the unified term end, respondent discovery and paging; what *ended* means and the `ending` codes; an authority holding no record of the Agreement read as no case.
- `compute-delivery`: the shared delivery re-drive over domain ports.
- `market-composition`: the four-loop layout in both storefronts; the startup report and withdrawal; the VM composition building its payments seller stage.
- `settlement-servicing`: the neutral lifecycle loop's journal allowance.
- `buyer-orchestration`: the penalty's collectible bound and the funding-stop message; "The buyer refuses seller ends that keep the started period" reworded to the per-term waivers.
- `test-compatibility`: the recurring purchase delivered; the rate lane rows and watchdog cases in both lanes on lane time, and their evidence labels; the payments double's reservation control.

### New Capabilities

None.

## Non-Goals

- The seller's opt-in funding timer, revision netting, and the refined financial completion fact (convergence tasks 2.1 and 2.3 beyond what this change takes).
- One kit loop with whole-page passes (convergence task 2.2).
- Self-penalty filings and mechanical rulings on rate parts (convergence task 3.2), and execution of a ruling's `stop` or `penalty` effects in the mediation double (convergence task 3.5a).
- The stateless recovery runner and evidence export (convergence task 3.4).
- Convergence's matrix rows 1–5, 8 and 10–13, and the extra windows and races of its task 4.2.
- Setup parts in the lane rows; they need the self-penalty filing path that returns a setup charge on non-delivery.
- Re-anchoring running deals across a payments receipt key change; spot made a key change a drained cutover (its D17).
- Recovery for deals end service refused before this change; no release carried the refusal (`marketplace-v0.3.0`).
- The site-enforced delivery deadline (`renewable-compute-lease-deadlines`), and the seller-chosen payout hold and the penalty's collectibility rule (`offer-a-seller-chosen-payout-hold`).
- Hosted runs and any production declaration (`switch-on-hosted-per-period-vm`).

## Impact

- Behaviour: a storefront whose declaration lists rate treatments now delivers its rate deals. No deployed composition declares any, so production rate behaviour is unchanged until `switch-on-hosted-per-period-vm`. Every deal's payment stops are now classified, and VM records its own term end.
- Wire: `kit/deal-lifecycle-contracts` takes an incompatible version for the seller list's `ending` codes and the removed omissions; the seller client and both storefront CLIs ship with it.
- Persistence: one kit-owned servicing table for the page position, by a migration appended to each storefront chain, which drops bare metal's `bare_metal_lifecycle_cursor`.
- Configuration: interval keys for `deal-servicing` and `delivery-recovery`, defaulting to today's intervals; released keys keep their meaning.
- Operations: loop names change in both storefronts; lane stages and operator documentation follow.
- Buyer behaviour: the default buyer's refusals are unchanged; a deal nobody filed on reads with an accepted dispute outcome.
- Packages beyond the compute family: `kit/arkhai-mediation`'s read of an Agreement with no record and its fake (D16); `kit/arkhai-payments`' engine reservation method, `tools/payments-lane-double`'s reservation control and second payer, and `tools/lane-double-controls`' route and client (D17). Neither kit's version moves past its unreleased one.

## Dependencies and Related Changes

- Its lane round depends on `drive-the-storefront-clock-in-lanes` landing: every lane row is written against its lane-time helper (D9). Its other work runs in parallel with it.
- `switch-on-hosted-per-period-vm` follows it.
- Builds on `spot-deals-through-arkhai-payments` (archived): the refusal it lifts (D12–D14), the payments transaction adapter (D11), rate `authorize` (D4), the seller's notice and `deals preempt` (D6) and the buyer's `end` and watchdog (D6a).
- Work taken from `converge-ongoing-compute-leases` (task numbers in its `tasks.md`): 1.3 and 3.1 (rate servicing in both compositions, which the code already binds but for VM's stage), 2.1 (the physical fact and the simple financial fact *ended* reads), 2.2's per-deal step order as a helper (not the whole-page loop), 2.3 (stop-cause classification in both domains, without timers), 2.4 (reduced to *ended* and *ending* with its codes), 2.5 (stop to teardown, authority outage and restart in both domains, without timers or the runner), 3.5 (startup coherence and withdrawal, as a report), 4.1 (matrix rows 0, 6, 7 and 9 in both lanes, without setup parts or timer variants), 4.3 (evidence labels); the loop-journal allowance in its `settlement-servicing` delta; and the two items its campaign-index row carries from spot: the refused deal's next commit, and the watchdog's delivered-deal cases. Also taken, and named in convergence's row Notes: respondent discovery, which its D3 listed as a composition-supplied step, and the four-loop layout its single loop will run beside.
- Closes the campaign index's unowned row "`VmSettlementComposition` builds no payments seller stage" (D11).

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `deal-lifecycle`, `compute-delivery`, `market-composition`, `settlement-servicing`, `buyer-orchestration`, `test-compatibility`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- D1: `deal-lifecycle`'s spec ("Delivery authorization delegates payment interpretation") and architecture companion ("One end instant, transactional admission", "Current limits"); `compute-delivery`'s spec ("Protected delivery steps are authorized and admitted") and architecture companion ("Commit and hold adoption") — the refusal's removal and a changed answer returned pending.
- D2: `deal-lifecycle`'s spec ("Cause classification is owned by end service") and architecture companion — the payment-stop classifier, its placement and the resolution of earlier pending stops.
- D3: `deal-lifecycle`'s spec — the `terms` split by the Agreement's end.
- D4: `deal-lifecycle`'s spec and architecture companion — the kit-owned servicing step order and the unified term end, respondent discovery and paging; `deal-lifecycle`'s and `settlement-servicing`'s architecture "Current limits" and `vm-storefront-fulfillment`'s "Evidence and delivery ownership" lose the respondent and term-end differences; `docs/development/ROADMAP.md`'s Goal 8 current state likewise.
- D5: `compute-delivery`'s spec and architecture companion — the shared re-drive; `market-composition`'s spec and architecture companion ("Storefront composition kit") — the four-loop layout; `storefront-publication`'s configuration companion — the interval keys; `docs/development/ARCHITECTURE.md` — the loop layout both storefronts share.
- D6: `deal-lifecycle`'s architecture companion — the kit-owned page position.
- D7: `deal-lifecycle`'s spec ("The seller half lists deals", "Stop requests are distinct from final stops") — what *ended* means, the `ending` codes, and the read and list carrying every field; `deal-lifecycle`'s architecture companion loses the routes' omission of once-only deals' empty fields.
- D8: `market-composition`'s spec and architecture companion ("Settlement runtime composition") — the startup report and withdrawal.
- D9: `test-compatibility`'s spec and `docs/development/TESTING.md` — the rate lane rows on lane time.
- D10: `test-compatibility`'s spec and `docs/development/TESTING.md` — the watchdog's delivered-deal cases.
- D11: `market-composition`'s spec and architecture companion ("Settlement runtime composition") — both compositions build their payments seller stage.
- D12: `settlement-servicing`'s spec — the loop's journal allowance.
- D13: `buyer-orchestration`'s spec and architecture companion ("Compute terms before approval", "The buyer's watchdog") — the penalty's collectible bound and the funding-stop message.
- D14: `buyer-orchestration`'s spec — the requirement reworded to the per-term waivers; restart recovery's evidence in `test-compatibility`'s companion.
- D15: no permanent destination — the implementation cadence orders this change's own work.
- D16: `deal-lifecycle`'s spec ("The seller half lists deals") — the authority's first-page `404` read as no case, its unchecked credential premise and its limit; `openspec/specs/settlement-servicing/architecture.md` (its "Initial missing mediation history permits the first filing only" sentence) and `kit/arkhai-mediation/README.md` (its initial-404 paragraph).
- D17: `test-compatibility`'s spec ("Lane double controls are typed deterministic steps", "Rate deals are qualified in both compute lanes on lane time"); `tools/payments-lane-double/README.md` (its controls and claims), `tools/lane-double-controls/README.md` (the route), `kit/arkhai-payments/README.md` (the engine's reservation method beside `advance`); `docs/development/TESTING.md`, "Private Service Dependencies" (the reservation control).
- D18: `test-compatibility`'s spec ("The buyer's watchdog is qualified against a delivered deal"); `docs/development/TESTING.md`, "The canonical compute deal" (the watchdog cases with the storefront paused).
- D19: `docs/development/TESTING.md`, "The canonical compute deal" — the rate rows and watchdog cases are Compose-lane, lane-double evidence.
- `docs/guidance/engineering/test-doubles.md`, "A double mirrors its producer" — a producer's scheduled actions, such as reserving ahead, are answers a scenario programs like its rulings and job outcomes; a double stays externally programmable, gaining no internal behaviour a scenario could program (the owner's principle, stated in this design).
- `docs/guidance/repository/deterministic-tests.md`, "Pause the loop, then advance it explicitly" — a local end-to-end test holds a party's time-based signals by pausing it, never by stopping it; external-topology tests handle time differently (the owner's principle, stated in this design).
- `docs/guidance/workflow/changes.md`, "Defects found during a change" — a change taking on work another change owns names the move in its own proposal and in that change's row Notes (the owner's principle, stated in this design).
- `docs/guidance/repository/package-versions.md`, "Compatibility is owed to what a release has shipped" — a released client or CLI is not owed compatibility with a later storefront, provided the client shipped with that storefront reads everything it serves; backwards client compatibility stays supported through the staged deprecation pattern of `docs/guidance/engineering/versioning.md`, but is not owed (the owner's principle, stated in this design).
