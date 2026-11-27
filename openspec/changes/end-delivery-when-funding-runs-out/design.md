# Design: end-delivery-when-funding-runs-out

## Context

**Three routes end a deal for want of funds.** Each records a final request in the
kit's end journal, and end service then terminates the lease, or truncates it where the
end is still ahead (`kit/deal-servicing/src/market_deal_servicing/journal.py`,
`schedule_physical`). Nothing else is shared.

- A rate deal ends on the payment authority's own stop. The authority stops every
  co-funded part at the instant it is funded through, with cause `terms`. The
  storefront's watch records that stop on its next verified read
  (`kit/deal-servicing/src/market_deal_servicing/watch.py`, `_record_payment_stop`), and
  the compute family's classifier calls a `terms` stop before the Agreement's end
  exhaustion (`domains/compute/src/arkhai_compute/end_classification.py`,
  `classify_payment_stop`).
- A deal paid once ends at the Agreement's end. The servicing cycle records the term
  end itself (`kit/deal-servicing/src/market_deal_servicing/servicing.py`, `reconcile`),
  and the site's lease watchdog expires the lease at its agreed end.
- An Alkahest deal ends when its settlement becomes terminal without being collected,
  through a hook each storefront wires to the settlement worker for itself. The VM
  storefront ends on any outcome but a collection and records the end with its
  classification pending
  (`domains/vms/storefront/src/market_storefront/settlement_composition.py`,
  `truncate_lease_for_terminal_settlement`; `delivery_records.py`,
  `record_delivery_end`). The bare-metal storefront ends on `expired`, `reclaimed` and
  `failed` and records the end classified as the terms' own
  (`domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/runtime.py`,
  `on_terminal`; `lifecycle.py`, `local_end`).

**What reads the funded instant today.** The payments adapter's read reports, for each
rate part, the instant it is reserved through as `funded_through`, and folds the
earliest of each part's end, funded instant and pending or final stop into the view's
`deadline` (`kit/arkhai-payments/src/market_arkhai_payments/rate_parts.py`,
`observations` and `state`). The watch saves that view on every verified read. The
seller's list shows the deadline, and the buyer's `market delivery` prints the funded
boundary. Delivery authorization refuses a phase once the signed snapshot's
`fundedThrough` has passed (`rate_parts.py`, `authorize`). Nothing ends delivery on any
of it: `openspec/specs/deal-lifecycle/architecture.md`, "Current limits", says a
storefront runs no funding timer.

The Alkahest adapter authorizes delivery phases and reports nothing: its read answers
that the mechanism has no lifecycle adapter
(`kit/alkahest/src/market_alkahest/payment_adapter.py`, `AlkahestOnceAdapter.read`),
which `deal-lifecycle`'s "A read without an adapter still shows delivery" requires.

**The gap.** When the storefront cannot read the payment authority after a rate deal's
funded instant has passed, it records no stop, so nothing ends delivery: the seller
serves unpaid until a read succeeds. When the storefront is not running, the lease runs
to its agreed end, which for an on-demand or spot deal is the seller's maximum horizon.
In both cases the authority's stop still bounds what the buyer pays. For the second,
the operator handbook's "Leases the storefront has not delivered" has an operator end
the lease at the site.

**What the payment authority publishes.** In the vendored payments contract
(`kit/arkhai-payments/schema/payments.schema.json`) a rate part states its `period`,
`reserveAhead` and an absolute `end`. A signed snapshot carries an optional
`fundedThrough` and, per part, `rate.reservedThrough`, `started`, `end`, `stop` and
`pendingStop`. The lifecycle events are `start`, `stop`, `reverse`, `extend` and
`lift`. A stop's cause is one of `payer`, `payee`, `authority` and `terms`; funds
running out and a part's end both stop it with `terms`. `fundedThrough` is absent before
`start`, and the contract does not state when a started part is reserved further: the
lane double's reservation control stands in for that decision
(`openspec/specs/test-compatibility/architecture.md`).

**The precedent for waiting on a read.** End service already holds one end back for a
payment read. A missed delivery deadline on a deal that is not once-only is recorded
only once a verified payment read made at or after the deadline has had the chance to
record an earlier end; until then admission answers `awaiting_observation` and nothing
is recorded or filed (`journal.py`, `_deadline_unobserved`; `deal-lifecycle`'s "Delivery
authorization delegates payment interpretation"). The instant of the latest verified
payment read is recorded per deal for it (`watch.py`, `record_payment_observation`).

**Pool policy.** The site's pool projection carries a pool's `policy_tags`, which a
storefront reads verbatim (`kit/site/src/market_site/projections.py`). A pool write
accepts a tag it does not know (`resource-pool-management`'s "Typed pool models validate
policy hints").

**Released.** `marketplace-v0.4.0` carries all of the above. A storefront it runs ends
a rate deal only on the authority's recorded stop.

## Decisions

### D1 — One rule in the kit ends delivery at the funded instant, and the site is untouched

A deal's delivery ends when the instant its mechanism reports as funded has passed.
`kit/deal-servicing` holds that as one rule, run by the servicing cycle both compute
storefronts already run, for every deal the cycle services, whatever its mechanism and
whatever its class. The end is a final request in the end journal like any other, so
the earliest final request still governs, and end service terminates or truncates as it
does today.

The site gains nothing: no column, no transition, no route, no policy read, no report
field. A lease still ends at the site when its storefront ends it, at its agreed end,
or when an operator terminates it.

When a storefront is not running, the lease therefore runs on, and the seller serves
unpaid until the storefront returns or an operator ends the lease at the site. That is
chosen. Of the two outcomes a storefront's outage can have, the one that favours the
buyer is right: a site that reclaimed a machine at its last renewed instant would take
it from a buyer whose balance is still being charged, for the seller's own outage. Here
the seller alone bears its outage.

Rejected:

- A deadline on the active lease that the storefront renews to the funded instant and
  the site enforces. It ends a working, paid lease when the storefront stops, which
  harms the buyer for the seller's failure. `enforce-delivery-deadlines-at-the-site` leaves
  it buildable: its expiry claim is stated over what made a lease due, and its
  lease-end report names which deadline was claimed (that change's D2 and D5). It is
  revisited when a site's operator is not its storefront's, since such a site has its
  own exposure to bound.
- The storefront moving the lease's agreed end with the funded instant. The site
  refuses a later end (`site-capacity`'s "Lease truncation neither resurrects nor
  extends a lease"), and admission frees capacity past a truncated end.
- A rule in each storefront. The two terminal-settlement hooks already differ in which
  outcomes end a deal and how the end is classified, with no reason stated
  (`docs/guidance/repository/family-kits.md`, "Sibling domains behave alike").

### D2 — Nothing is asked of the payments contract

The calculation stands on what the storefront already verifies and saves at each read.
No operation, field or behaviour is requested of the payments service, and the
payments kit sends nothing new.

Rejected: a billing horizon the payee advances, where the storefront tells the payment
authority each cycle how far it may bill and the authority stops the part when the
horizon lapses. The published contract has no such operation. It would bound billing by
the seller's liveness, which is not a calculation from what a deal has funded. A buyer's
protection against a seller that fails is its own stop at the payment authority and a
case over held money (`docs/development/ARCHITECTURE.md`, "Post-commitment
counterparts").

### D3 — The calculation always runs

Every storefront that services deals runs the rule, for every deal. No setting turns it
on, and nothing is shipped off to be turned on later. What may vary is only what a
storefront does when a funded instant has passed and cannot be confirmed (Q1).

Rejected: a seller's funding timer enabled by a composition setting, off by default. A
switch shipped off is a second product state to qualify, and a timer for rate deals
alone would be one of several mechanisms each ending delivery for its own kind of deal.

### D4 — Every mechanism reports its funded instant through one port

Each mechanism's adapter reports what its deal is funded through, through one port the
rule reads, and Alkahest's adapter is one of them. The two terminal-settlement hooks are
removed: an Alkahest settlement that becomes terminal without being collected reaches
end service through the adapter's report and the kit's rule, on one path, with one set
of outcomes and one classification for both storefronts.

| Mechanism and billing | What it is funded through |
|---|---|
| Arkhai payments, paid once | The Agreement's end |
| Arkhai payments, per period | The instant the payment authority has reserved through |
| Alkahest | The Agreement's end while its escrows stand; the instant a settlement became terminal uncollected |

Rejected: a calculation over payment-adapter deals only, with Alkahest keeping its
hooks. It leaves two mechanisms and two domains each ending delivery their own way.

### D5 — The class never enters the calculation

A compute option's class is read from its early-termination entitlements alone, as
`discover-open-ended-compute-listings` settles it. The rule reads what the mechanism's
adapter reports as funded and never the class. How a class of deal comes out follows
from how it is billed:

| Class | Entitled to end early | Funded through, as billed today |
|---|---|---|
| Reserved, prepaid | Nobody | The Agreement's end |
| Reserved on a downpayment, further payment due | Nobody | The funded instant of the part that bills the remainder; no preset publishes one |
| On-demand | The payer | The instant reserved through |
| Spot | The payer and the payee | The instant reserved through |
| Committed spot | The payee | The instant reserved through; no preset publishes one |

A reserved or committed-spot deal billed in parts ends at its funded instant like any
other. What a buyer owes for leaving a committed term that way is no part of the rule.

Rejected: a rule per class or per product. The class says who may end a lease, not what
has been paid for.

### D6 — A read comes before an end

The rule records no end on a saved funded instant alone. Once that instant has passed,
the storefront reads the mechanism again, and the read decides:

- a verified read that shows a later funded instant replaces the earlier one, and
  nothing ends;
- a verified read that shows the mechanism's own end, such as the payment authority's
  stop, is that end, recorded as the watch records it today;
- only when no such read can be made, because the authority is out of reach or its
  answer cannot be verified, does the posture of Q1 apply.

A top-up that lands before the funded instant is therefore never lost to a stale view,
and where the authority can be read, the end the rule records is the authority's own.
The read is bounded, so an authority that is down does not hold the page's physical
work.

Rejected: ending on the saved instant. The payment authority reserves further on a
schedule the contract does not state, so a saved instant is out of date as often as not.

### D7 — The calculation reads an instant and computes no money

The port reports an instant, and the rule compares instants. It reads no balance, no
amount and no price, journals none, and derives no instant from a rate and an amount of
its own. Money moves and is priced only at the payment authority
(`docs/development/ARCHITECTURE.md`, "Settlement servicing";
`settlement-servicing`'s "Payment settlement is retryable and idempotent").

Rejected: the storefront dividing a funded amount by a price. It would make the
storefront a second ledger that can disagree with the first.

### D8 — Goal 8 waits for this change

The gap is one of
[Goal 8's](../../../docs/development/ROADMAP.md#goal-8--sell-compute-by-the-period-until-either-party-stops)
open gaps, listed in its table with the change that owns it, and the goal is not
complete while it is open. The products the goal sells are the ones whose funded instant
moves while the deal runs.

The roadmap carries that order: its "Done when" names this change's closeout among
those the goal waits for. No change depends on this one for it.
`qualify-per-period-bare-metal-and-setup-charges`, which makes Goal 8's remaining live
observations, adds none for this change: funds running out with the payment authority
readable is already compared live, and a funded instant the authority cannot confirm
cannot be made live, so it stays lane-double evidence.

Rejected: keeping it outside the goal as preserved work. The goal's own current state
names the missing funding timer. Rejected too: a dependency of
`qualify-per-period-bare-metal-and-setup-charges` on this change, which would gate
nothing that change does and make the goal's order a property of one change's index row.

## Open Questions

Each is decided in this change's design session.

### Q1 — A funded instant that has passed and cannot be confirmed

D6 leaves one case: the funded instant has passed and no verified read can be made.
Marketplace 0.4.0 serves on until a read succeeds. Three things bound the answer:
policy that varies is stated on the resource pool, not in a service-wide setting; a
pool that states nothing commits to nothing (`docs/development/ARCHITECTURE.md`,
"Omission states no commitment") and must behave as 0.4.0 does; and the party that
bears unpaid serving is the site whose hardware is in use, which is the party that
states a pool.

- (a) A pool policy tag the storefront reads from the pool projection. A number ends
  delivery that many seconds after a funded instant no read has confirmed. Nothing, and
  none, serve until a read succeeds.

  ```yaml
  pools:
    - id: vm-california
      provider: vm.ansible
      policy_tags:
        deliverable_modes: [vm]
        advertisable_modes: [vm]
        capacity_backing: backed
        unconfirmed_funding_seconds: 900
    - id: whole-host-california
      provider: bare_metal.ansible
      policy_tags:
        deliverable_modes: [bare_metal]
        advertisable_modes: [bare_metal]
        capacity_backing: backed
  ```

  The first pool's deals end fifteen minutes after an unconfirmed funded instant; the
  second pool's serve on, as today.
- (b) The same tag, with nothing resolving a default its provider declares, as
  `enforce-delivery-deadlines-at-the-site`' pool tag does. A pool written under 0.4.0 states
  nothing, so its running deals would gain an end on upgrade, and the operator handbook
  would need an upgrade step.
- (c) No posture. The storefront always serves until a read succeeds, and the seller's
  list names a deal past an unconfirmed funded instant. The change is then the one rule
  and the one port, with no new end.

A storefront setting and a settlement-clause value are not among the alternatives.

Recommended: (a). It gives a site a bound it states for itself and changes nothing for
a pool that states nothing. It would move to (c) if no seller wants an end it cannot
confirm, given what Q2 says such an end can cost.

Whichever is chosen, a 0.4.0 site accepts the tag as one it does not know and projects
it verbatim, so only the tag's validation waits for the site's release. Its name and
its validation follow the hold and SLA preferences (`resource-pool-management`'s
"Reservation hold and SLA preference validation").

### Q2 — How an end on an unconfirmed instant is classified

An end recorded under Q1 is recorded without knowing whether the deal was still funded.
A later read settles it either way.

- (a) Recorded with its classification pending, as the VM storefront records a terminal
  settlement today. A later verified stop effective at or before the recorded end
  resolves it as a lawful end. A later read showing the deal funded past it resolves it
  as the seller's failure, with its `delivery_end(cause=payee)` filing, through
  `deal-lifecycle`'s "Pending correction resolves in the same journal".
- (b) Recorded as a lawful end at once, as the bare-metal storefront records a terminal
  settlement today. A deal that was in fact funded is then ended with nothing filed.
- (c) Recorded as the seller's failure at once, with its filing. A deal whose funds had
  in fact run out then carries a filing against the seller.

Recommended: (a). Neither party is charged with a fault the evidence does not yet show,
and physical work does not wait for the classification. The same answer settles what
the Alkahest path records (D4).

### Q3 — The port's shape, and the size of the Alkahest read

Callers and what each needs:

| Caller | Needs |
|---|---|
| The servicing cycle's rule | The funded instant, and whether the report it came from was verified at or after it |
| The watch | The mechanism's own end when it has one, to record as it records a stop today |
| The seller's list and single-deal read | The instant to show, which they show today as `deadline` |
| The buyer's `market delivery` | The funded boundary, which it prints today from each part |
| Delivery authorization | Nothing new: the adapter's `authorize` reads its own snapshot |

- (a) The adapter's existing read is the port. The rule reads the neutral part
  observations the view already carries; a view with no rate part is funded through
  the Agreement's end; and Alkahest's adapter answers an accepted view that reports a
  terminal uncollected settlement as a stop. A per-period view as it is served today,
  abridged:

  ```json
  {"outcome": {"status": "accepted"}, "state": "running", "parts": [
    {"part": "1", "started_at": 1794819600, "end_at": 1797411600,
     "funded_through": 1794823200, "evidence_ref": "9f2c…:snapshot:14:1794820900"}],
   "deadline": 1794823200}
  ```

  No wire field is added. `deal-lifecycle`'s "A read without an adapter still shows
  delivery" changes, since an Alkahest deal's authority view is no longer `rejected`.
- (b) A view-level funded instant beside `deadline`, which today also folds in a
  pending stop. The lifecycle wire models refuse an unknown field, so this is an
  incompatible step of `kit/deal-lifecycle-contracts`, shipped with the clients that
  read it.
- (c) A separate adapter operation answering an instant, an end, or unknown. Every
  adapter and double implements it, and a deal is read twice a cycle.

Under each, generic servicing reads neutral observations only
(`deal-lifecycle`'s "Delivery authorization delegates payment interpretation").

Recommended: (a). It would move to (b) if the rule must tell a funded instant from a
pending stop's instant, which Q4's answer may require.

The Alkahest read is the unknown in size. Its adapter reads nothing today, and what a
settlement's state is lives in the settlement worker and its repository, which each
storefront composes. If reporting that state through the adapter proves large, it is
split into a change of its own that this one precedes; the direction of D4 stands
either way.

### Q4 — Clocks

A funded instant is the payment authority's claim on its own clock. The storefront's
clock may run ahead of it, so a read the storefront makes just after the instant can
show the same instant and no stop, the authority not yet having reached it.

- (a) The storefront's own instant before the read, as the delivery-deadline rule uses
  and as delivery authorization checks every bound. A read that shows neither a later
  instant nor a stop confirms nothing, and the next cycle reads again.
- (b) The mechanism's own observation instant where it reports one: a verified
  snapshot observed at or after the funded instant, on the authority's clock, is the
  confirming read. The port then carries that instant.
- (c) A fixed allowance added to the funded instant before it counts as passed.

Recommended: (a), stating the third outcome of a read beside D6's two. It adds nothing
to the port and no setting.

### Q5 — What SCM needs of a `terms` stop

The payment authority records funds running out and a part's end under one cause. The
storefront tells them apart by the stop's effective instant against the Agreement's
end, and both are lawful ends; the buyer is told after a funding stop that a top-up
cannot revive the deal.

- (a) Nothing more. Under the vendored contract a part's periods are reserved only up
  to its end, so a `terms` stop before the end is funds running out and one at it is
  the end.
- (b) The comparison reads the snapshot part's own effective `end` in place of the
  Agreement's end, which the contract defines as the later of the mandate's end and the
  approval instant.
- (c) A distinct cause in the published contract. SCM would then need nothing but the
  stop record.

Recommended: (a). The rule needs an end and its instant, not its reason, and the
classification that needs the reason already has it. It would move to (b) if a deal
approved after its mandate's end can be delivered.

### Q6 — Provisional answers

Each follows from something settled or from the nearest precedent, and is confirmed or
moved in the design session.

- **Requirements this change modifies**, their deltas written once Q1 to Q4 settle:
  `deal-lifecycle`'s "Each deal's servicing steps run in one kit-owned order", "Cause
  classification is owned by end service", "End service keeps the earliest final
  request" and "A read without an adapter still shows delivery";
  `settlement-servicing`'s "Rate observations require verified authority state";
  `test-compatibility`'s "Rate deals are qualified in both compute lanes on lane time";
  and, if Q1 settles on a tag, `resource-pool-management`'s "Reservation hold and SLA
  preference validation". No `site-capacity` or `physical-provisioning` requirement
  changes.
- **Companion text.** `openspec/specs/deal-lifecycle/architecture.md` stops saying a
  storefront runs no funding timer, and its "Funding and scheduled rate stops are
  authority behavior, not local clock-derived corrections" is restated: the authority's
  stop is still the end wherever it can be read.
- **Lane rows.** Funds running out with the authority readable runs today in both
  lanes. This change adds the unreadable case, made with the payments double's
  transport-fault rule on lane time, in both lanes, and an Alkahest settlement ending
  through the one path in each lane that sells one.
- **Test levels.** The rule and its read outcomes are library integration in
  `kit/deal-servicing`; each adapter's report is its kit's own suite; each storefront
  proves the rule and the removed hook at application integration through its typed
  lifecycle client; the lane rows are the system-level proof.
- **The diagram.** `converge-ongoing-compute-leases` keeps a scenario diagram of a
  seller's funding timer. It is redrawn here once Q1 and Q2 settle, since both decide
  what it shows.
- **The operator handbook.** "Serving rate deals" says what a storefront does at a
  funded instant, and "Pool definitions" documents the tag if Q1 settles on one.

### Q7 — Implementation cadence

Recommended: two rounds. First the port, the rule with its read outcomes and the
payments adapter's report, with their kit and application integration tests, one
session. Then the Alkahest report with both hooks removed, the posture Q1 settles and
the lane rows, one session, or two if Q3 finds the Alkahest read large.

## Verification

Provisional levels are in Q6. Nothing here is proven against a hosted authority: every
lane row is lane-double evidence, and no live scenario is added (D8).

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| D1 one rule in the kit, the site untouched | `openspec/specs/deal-lifecycle/spec.md` and `architecture.md`; `docs/development/ARCHITECTURE.md`, "Settlement servicing" |
| D2 nothing asked of the payments contract | `openspec/specs/deal-lifecycle/architecture.md`, "External authorities" |
| D3 the calculation always runs | `openspec/specs/deal-lifecycle/spec.md`; `openspec/specs/deal-lifecycle/architecture.md`, "Current limits" |
| D4 one port for every mechanism | `openspec/specs/deal-lifecycle/spec.md` and `architecture.md`; `openspec/specs/settlement-servicing/architecture.md` |
| D5 the class is not an input | `openspec/specs/deal-lifecycle/architecture.md`, "Parts and terms" |
| D6 a read before an end | `openspec/specs/deal-lifecycle/spec.md`; `openspec/specs/settlement-servicing/spec.md` |
| D7 an instant, no money | `openspec/specs/settlement-servicing/spec.md`; `docs/development/ARCHITECTURE.md`, "Settlement servicing" |
| D8 Goal 8 waits for this change | `docs/development/ROADMAP.md`, Goal 8 |
