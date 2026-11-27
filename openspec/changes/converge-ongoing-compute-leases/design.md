# Design: converge-ongoing-compute-leases

## Context

**What services a deal.** Both compute storefronts run one kit-owned servicing cycle,
`ServicingCycle` (`kit/deal-servicing/src/market_deal_servicing/servicing.py`), in a
`deal-servicing` loop registered through the kit loop controller, as `deal-lifecycle`'s
"Each deal's servicing steps run in one kit-owned order" and `market-composition`'s
"Both compute storefronts run one loop layout" state. A cycle discovers counterparty
cases once per dispute authority, then takes the page deal by deal: the authorities
read, the domain's recovery steps (a read of the site's lease: `recover_site_reports`
in the VM storefront, `recover_site` in bare metal), the physical end, local
reconciliation, site-report correction, filing dispatch, and the physical end again,
each step isolated. A deal's physical end runs after its own authorities read and after
every earlier deal's steps, and each authority client waits ten seconds by default
(`kit/arkhai-payments/src/market_arkhai_payments/client.py`,
`kit/arkhai-mediation/src/market_arkhai_mediation/client.py`). With both authorities
down a deal costs at least two timeouts before its physical end, so on a page of 100
deals the last deal's teardown waits half an hour or more, even when its end was
recorded before the cycle began. A physical end calls the site only for a pending
`terminate` or `truncate` intent (`kit/deal-servicing/src/market_deal_servicing/end.py`).

**Ends and filings.** End service keeps every final request and selects the earliest.
A seller failure cannot be recorded without its `delivery_end(cause=payee)` filing
(`kit/deal-servicing/src/market_deal_servicing/journal.py`, `record_end`), for every
kind of deal: an administrator's failure end, a site's unentitled withdrawal, and a
missed delivery deadline, which for a rate deal is recorded only after a payment read
made at or after the deadline. A filing for a failure before the Agreement's start
waits for that start.

**A changed claim.** When a new, earlier seller failure becomes the selected end, the
journal adds a filing for it. The mediation adapter treats every filed `delivery_end`
on the Agreement as the original — the seller's own filing, or the buyer's
`delivery_end(cause=payer)` case that `market end` files with the storefront's signed
concurrence (`kit/deal-lifecycle-buyer/src/market_deal_lifecycle_buyer/ending.py`) — and
answers a claim that differs from it `repair required: delivery-end revision requires
resolved prior rulings and effects`
(`kit/arkhai-mediation/src/market_arkhai_mediation/adapter.py`). A rejected filing is
terminal. The precondition is the adapter's own: the vendored contract's
`case_concurrency` allows repeated and concurrent cases on one Agreement, each holding
its own extensions, and nets earlier cases' effects; its `automatic_rulings` admits one
mechanical `delivery_end` ruling per Agreement, so a second endorsed claim goes to an
operator (`kit/arkhai-mediation/src/market_arkhai_mediation/contract_data/`, the traces
`manual-second-mechanical-claim` and `operator-nets-earlier-ruling`). A buyer's
surrender case carries the seller's concurrence and is ruled mechanically, so the
storefront's correction after any buyer end also goes to a person today. The authority
nets a later ruling's rate stops and reversals against earlier cases through the
payment snapshot, but its default effects for a second payee claim carry the
premature-stop penalty again and decline to compute once a once part was reversed. The
mediation lane double admits a second case on one Agreement with per-case extensions
(`tools/mediation-lane-double/src/mediation_lane_double/service.py`, `file`).

**When a deal is ended.** "The seller half lists deals" lists a deal with a recorded
end `ended` only when its resource is proven released, every payment part has a
verified stop or end, and a saved read of its dispute authority shows no case open;
otherwise `ending`, naming each outstanding condition from four closed codes. The list
computes this at read time (`kit/deal-servicing/src/market_deal_servicing/seller.py`,
`_outstanding`) and never reads the deal's own filings, so a deal whose filing is
unsent, waiting or unanswered can be listed `ended`. The list's `filings` report an
unattempted intent as `delivery-end filing has not been attempted`; the dispatcher's
`waits for Agreement start` answer is never journaled. The operator handbook's drain
procedure waits for `ended`.

**Release and the site's sends.** The provisioning service records a lease's end and
its capacity's release as events and sends them to the owning storefront: the signed
lease-end report and the capacity-released callback, its only sends to another
service. A command — terminate, retry-release, force-release — and a lease-watchdog
cycle that made a transition deliver them inline before returning, through the event
delivery worker's `deliver`, which a pause of that worker does not hold
(`provisioning/compute/src/compute_provisioning/lease_lifecycle.py`,
`provisioning/compute/service/src/compute_provisioning_service/services/operator_events.py`).
The worker's timer is the only path for a lease end with no inline delivery: the site's
release route, a resize supersede, a hold expiry. The capacity-reservation watchdog,
which records hold expiries, runs a timer with no pause. No compute lane holds event
delivery or that watchdog. The procedure for a deal ending on a pending release is
already in `docs/operator-handbook.md`, "A deal ending on a pending release".

**The lanes.** Every party of a Compose lane runs on one lane time a stage sets,
forward only. A scenario holds a storefront's loops and steps them; it cannot stop the
service, and a storefront whose loops are held still answers its routes. What runs
today is `test-compatibility`'s "A recurring purchase is delivered end to end in each
compute lane", "Rate deals are qualified in both compute lanes on lane time", "The
buyer's watchdog is qualified against a delivered deal", "Controls scenarios prove the
lane's dispute wiring in the VM lane" and "A dispute on a running rate deal is
qualified in the VM lane"; the bare-metal lane runs no dispute row on a rate deal. Both
lane storefronts declare `charged` and `returned` and no setup charge.

**What is released.** `marketplace-v0.4.0` carries all of the above; the kits this
change touches differ from it only in lockfiles.

## Decisions

### D1 — One change holds the remaining rows and the servicing fixes

This change is the remaining rate qualification rows and the fixes they need: a
revised `delivery_end` claim reaches the dispute authority (D6), the seller's list does
not show a deal `ended` while a filing of its own is unanswered (D11), a physical end
waits behind no authority read (D7), and the site's sends to a storefront become steps
a lane takes (D8).

A change costs a design, reviews, a validation and a closeout, so a piece of work left
over is placed by one rule: it goes to a related change where it fits; with no such
home, a small piece stays with the others; only a large piece with no home becomes a
change. The servicing fixes are small and exercised by the rows. The provisioning
refactor (D8) and the live evidence the revision needs (D14) came with the design; each
is needed by the rows here and neither closes out usefully apart, so the change keeps
them.

Rejected:

- A qualification change and a servicing change. Two designs and two closeouts for
  fixes the rows exercise.
- Splitting the provisioning refactor and lane holds into a change of their own. Rows 2,
  12 and 12b and every existing release stage need them, and the owning-change model
  would leave this change unable to fix what it meets.
- One change also holding the funding timer, operator recovery and a release
  acknowledgement. D2 to D4 place each elsewhere or drop it.

### D2 — Operator recovery with the storefront stopped is its own change

Filing a seller's `delivery_end`, or sending its notice, for a deal whose storefront is
not running is a storefront command, designed in
`recover-deals-from-the-storefront-cli`, which is deferred. It is large — an evidence
export, a client method, a command, a durable command envelope and a rule for a filing
that overlaps the restarted storefront's own — and nothing here needs it: a buyer's
protection is its own stop and a case, and a seller whose storefront is down ends the
lease at the site and lets the restarted storefront file
(`docs/operator-handbook.md`, "Leases the storefront has not delivered").

Rejected: keeping it here, where the largest item with no named user would hold the
fixes; and an unowned roadmap row, which would drop the design already worked out for
it.

### D3 — A pending release is cleared at the site

A deal listed `ending` with `release_pending` is cleared at its site, through the
provisioning service's administrator API: `retry-release` re-observes a teardown that
has since finished, and `force-release` returns the capacity on the operator's word,
with a reason and evidence. Either leads the service to deliver the capacity-released
event the storefront records. A site that no longer serves listings does the same: it
runs its provisioning service to answer those requests. The storefront gains no command
for it. `docs/operator-handbook.md`, "A deal ending on a pending release", already gives
the procedure; this change keeps it current with D11's code.

The site is the party that can see the host and that owns the lease's release, so it is
where an operator's assertion belongs
(`docs/guidance/engineering/implementation.md`, "Deciding which party is authoritative").

Rejected: a seller command acknowledging physical recovery at the storefront. It would
add a command kind, a client method and an audit record for an assertion the site
already records, made by the party that cannot check it. Rejected too: recording a
condition under which to revisit, since a site can always run its provisioning service
again.

### D4 — The funding timer is `end-delivery-when-funding-runs-out`'s

This change builds no funding timer. When a deal's delivery ends for want of funds is
calculated by one rule from what the deal has funded, for every class of deal, and
`end-delivery-when-funding-runs-out` holds it. Until it lands, a running rate deal's
funding end reaches end service only as the payment authority's recorded stop, as
`deal-lifecycle`'s companion states under "Current limits".

Rejected: a seller's opt-in timer for rate deals here. It would be one of several
mechanisms each ending delivery for its own category of deal.

### D5 — The late-anchor row is `enforce-delivery-deadlines-at-the-site`'

The row in which a storefront commits with a later anchor than the payment authority's
approval, the site enforces the longer physical deadline, and the buyer's case is ruled
non-delivery at the accepted deadline needs a delivery deadline the site enforces.
`enforce-delivery-deadlines-at-the-site` builds that, so it runs the row. Here the row
would make this change wait on another.

### D6 — The dispute authority rules a payee's earlier-end revision, identified from its own record

The storefront files a changed claim at once, as a plain `delivery_end` filing; the
dispute authority recognises it as a revision from its own record of the Agreement's
cases, rules it mechanically, and nets it against what earlier cases applied. Nothing
new goes on the wire.

What the dispute authority owes, recorded in `deal-lifecycle`'s companion under
"External authorities" and in the roadmap's Goal 8 row:

- **R1.** A payee-endorsed `delivery_end(cause=payee)` filed on an Agreement holding an
  earlier `delivery_end` case is a revision of the latest such case when its `ended_at`
  is no later than that case's claim, whichever party filed it. A revision is ruled
  mechanically, outside the once-per-Agreement guard, at most once per revised case. A
  claim with a later end, or one the payee did not endorse, goes to an operator.
- **R2.** A revision's effects are its own claim's, net of what every earlier case on
  the Agreement applied: rate stops and reversals as today, once parts only the
  unserved share not already reversed, the premature-stop penalty at most once per
  Agreement. The operator default nets the same way.
- **R3.** A revision is accepted and protected at once and ruled only after every
  earlier case on the Agreement has closed or applied all its effects.
- **R4.** The authority's advertisement says so — `automatic_rulings` takes a new value
  — and its published vectors carry a trace of a payee revision ruled against an
  earlier mechanical ruling.

Rule R1 keeps the authority's endorsement principle: it rules automatically only on a
claim endorsed by the side it costs, and moving the end earlier costs the payee, who
files it.

In `kit/arkhai-mediation` the adapter drops its "resolved prior rulings" precondition:
it adopts a filed claim equal to its own, and otherwise files at once, keeping a
single-writer reservation per revised request and staying `Pending` only while its own
earlier filing is of unknown outcome. The same path serves the buyer kit, whose
`delivery_end` filed after a seller's case is no longer refused; the authority routes it
to an operator. The filing's `claim` names the revised case. While the revision waits
the deal shows `case_open`. Against an authority without R1–R4 the same filing is an
ordinary second case for an operator, so nothing need land first. Deals a 0.4.0
storefront already refused keep their terminal rejection, as "The seller half lists
deals" requires; the operator handbook says how to raise such a deal by hand. Row 3's
lane scenario programs the netted ruling the producer's trace shows, and D14's live
scenario proves the authority's behaviour.

Rejected:

- A repeated case ruled by an operator, the authority netting only its default. Every
  correction waits for a person.
- An explicit `revises` field naming the revised case. Released readers are not owed
  reading it before 1.0, but it adds nothing the authority's own sequence does not
  give, and opens refusals of its own: a case on another Agreement, a case that is not a
  `delivery_end`, a case that is not the latest.
- Waiting in the adapter for the earlier case's ruling before filing. The contract
  admits concurrent cases, and the authority, which knows its cases' state, sequences
  them (R3).
- Keeping `repair required` with a handbook procedure. The deal stays repair required
  and the buyer's remedy rests on an out-of-band request.

### D7 — A leading physical pass, with the per-deal order unchanged

Each cycle first drives the physical end of every deal on its page, then discovers
counterparty cases, then runs each deal's steps in today's order. An end recorded
before the cycle — a site's pushed report, a buyer's `end_delivery`, an administrator's
interrupt, a teardown that failed — waits behind no read; an end a deal's own steps
discover is torn down after those steps, as today. A deal with no pending end costs
one local transaction in the pass.

Rejected:

- Passes over the page with the second physical end after the whole page's authority
  work. An end a deal's own payment read discovers would wait for every later deal's
  reads: with payments answering and the mediation authority timing out, deal 1's
  teardown would wait for 99 timeouts.
- A per-cycle breaker skipping an authority after its first failure. It bounds a
  partial outage too, but adds cycle state and an outage-or-refusal distinction the
  gap does not need.
- Servicing deals concurrently, and a fifth loop for physical ends. The first changes
  the page model and makes ordering harder to prove; the second changes the four-loop
  layout and adds an interval key a release must keep.

### D8 — Every send from the site to a storefront is a step a lane takes

In a lane every state change is a step the harness takes. A request the harness makes
may carry its own effect into the service it addresses; any further delivery from that
service to another is a pausable step of its own. The provisioning service's sends to a
storefront become such steps:

- While event delivery is paused, a command or a stepped watchdog cycle records its
  events and leaves them for the event delivery worker; `POST
  /api/v1/system/event-delivery/run-cycle` delivers them. Unpaused, delivery is inline
  as today.
- The capacity-reservation watchdog gains a pause and a one-cycle step, through route
  contracts and the provisioning client.
- Every compute lane holds event delivery and the capacity-reservation watchdog for the
  whole module, Alice's provisioning in the VM lane too; stages that wait today for a
  release or a report step event delivery instead.

The rule goes into `docs/guidance/engineering/system-tests.md` and, with the new
holds, `docs/guidance/repository/deterministic-tests.md`. The other ungated sends an
inventory found — the VM settle and payments drive tasks, the introduction mail, loops
unheld before a module's holds, the chain probe's thread, sends a route starts and only
logs, the mediation double's ungated rulings — have no owning change: each change that
meets one fixes it under the written rule.

The rows then hold a storefront back with held loops and held event delivery:

- **Row 2** runs in production's order: the site terminates the lease and its report
  waits; the buyer's `market end` is answered by the storefront, which has not heard
  from the site, and the buyer kit files its case with the storefront's concurrence;
  event delivery is stepped and the report arrives with its earlier instant; servicing
  is stepped and the storefront files the payee's revision (D6). The storefront's return
  from a real outage — rebuilt over its database, reading the site's lease — is proven
  at application integration.
- **Row 12** holds the storefront's loops throughout. The buyer stops at the payments
  double and files its case through the harness's dispute adapter, since `market end`
  files only after the storefront's acknowledgement and no buyer command files on a
  running deal.
- **Row 12b** holds nothing more: the storefront contests with its `available` record,
  the buyer's case carries its watchdog's observation, and the row asserts both evidence
  classes in the case record.

Rejected:

- Held loops alone, rows reshaped around them. The site's report would race the
  buyer's end, and the release stages would keep waiting on a timer.
- Gating every ungated send the lanes meet in this change. Three further subsystems,
  none needed by these rows.
- A follow-up change owning the rest. It would go unprioritised and make every other
  change hesitate to fix what it meets.

### D9 — Each row runs once in the VM lane, and in bare metal where bare-metal code is on its path

`docs/guidance/repository/family-kits.md`, "Sibling domains behave alike", asks the
domains to behave alike; `docs/guidance/engineering/test-levels.md` asks for the fewest
system tests covering a cross-service contract. One lane proves the shared code — the
kit servicing cycle, end service, the seller's list, the mediation adapter, the compute
delivery path — and both lanes prove what differs: site-report recovery, the physical
end, the buyer CLIs and each storefront's `deals preempt`. The scenario table gives each
row's lanes. The bare-metal lane gains the twins of the VM lane's two rate dispute rows.

Rejected: every row in both lanes, which mostly re-proves shared code; the VM lane plus
only the two twins, which leaves bare metal's buyer CLI, `deals preempt` and site-report
recovery unexercised by the new rows; and leaving bare-metal rows to
`qualify-per-period-bare-metal-and-setup-charges`, whose design is live twins and
documentation.

### D10 — Setup rows run on a lane-only setup declaration

Each lane storefront that runs a setup row declares `setup = true` in its lane
configuration only, beside a lane option whose clause prices a setup amount; every other
row keeps today's setup-free option. This follows the lanes' declaring `charged` and
`returned` before either was supported. No shipped example or document changes, and
"Setup returns by delivered for either cause" stands until
`qualify-per-period-bare-metal-and-setup-charges` rewords it; that change's design
records this decision and adds live twins only for the setup rows that reach an
authority.

Rejected: moving the setup rows to that change, which would add lane work to a design
of live twins and documentation; and dropping the setup variants, which would leave no
setup reversal crossing from the authority to the payer.

### D11 — The list names an unanswered filing with a fifth code

`EndingCode` gains `filing_unanswered`, with the text "A filing of the deal's own has
no answer from the dispute authority." in `ENDING_TEXT`, as the four codes arrived. The
list computes it at read time from the journal: a `delivery_end` filing intent whose
outcome is neither accepted nor rejected — unsent, waiting for the Agreement's start,
pending or unknown. A rejected filing already shows repair required; a revision is
accepted at once (D6) and shows `case_open`. Other intents do not count: `terminate` and
`truncate` are `release_pending`'s, billing is `payment_running`'s. The startup report
of unserviceable deals applies the same rule.

```json
{"negotiation_id": "n-123", "state": "ending", "ending": ["filing_unanswered"],
 "filings": [{"intent_ref": "9f2c…", "outcome": {"status": "pending",
   "reason": "delivery-end filing has not been attempted"}}]}
```

The code is an incompatible step of `kit/deal-lifecycle-contracts`, shipped with the
seller client that reads it; until 1.0 a released client is not owed reading a later
storefront.

Rejected: folding the condition into `case_unobserved`, which would misname a case that
does not exist; and persisted completion state, tables no reader needs.

### D12 — Consequences and conventions

- **The deltas modify the landed requirements**, so each rule is stated once:
  `deal-lifecycle`'s servicing order (D7), seller's list (D11), filing identities and
  revised cases (D6); a `physical-provisioning` requirement for its sends (D8);
  `test-compatibility`'s module holds (D8), the remaining rows (D9, D10) and the live
  verification (D14).
- **Rulings are programmed, effects executed.** A row's ruling is a rule the scenario
  installs, its netted amounts taken from the producer's published trace; the double
  executes `stop`, `reverse` and `penalty` and computes nothing
  (`docs/guidance/engineering/test-doubles.md`, "A double mirrors its producer"). A row
  that steps servicing while a ruling waits gates it with `pause_before_effects`.
- **Row 4 is proven at integration**, in `domains/compute/delivery/tests/integration`.
- **Compatibility** is owed to `marketplace-v0.4.0`. Persistence: none. Wire: D11's code;
  the mediation filing is unchanged; the provisioning routes are additive.
  Configuration: none. Pausing event delivery now holds inline delivery too, which the
  operator handbook notes.
- **Diagrams.** Pairs 00, 02, 03 and 05 are redrawn to the settled design; 06 stays for
  `end-delivery-when-funding-runs-out`. At closeout the pairs that draw the product are
  promoted to `docs/development/diagrams/` and cited from `deal-lifecycle`'s companion.

### D13 — Implementation cadence

Two rounds, then a pause:

- **Round 1**, two sessions, in either order or together: the kit fixes — D7's pass,
  D11's code through contracts, client and kit, D6's adapter — with their library and
  application integration tests; and the provisioning refactor with the lane holds —
  D8's paused delivery, the watchdog's pause and step, both lanes' holds, the existing
  stages stepping event delivery, and the rule in the guidance.
- **Round 2**, two sessions: the VM lane's rows with the setup option and D14's live
  verification scenario; then the bare-metal lane's rows and twins.
- **Pause**: the coordinator's live verification evidence (D14), then pre-closeout and
  closeout.

### D14 — The revision's live verification is run by a coordinator, and closeout waits for it

This change writes the revision's live verification scenario in the VM live
verification, extending the live seller-filing scenario on a deal of its own and
sharing one assertion with row 3's lane twin: basis `payee_filed`, `end_delivery` at the
earlier instant, a stop whose reversal covers only the earnings between the two ends,
no second penalty, the case closed. Its topology requirement is a dispute authority
advertising R4's `automatic_rulings` value; it reads the advertisement through a new
`describe` method on the mediation client, over the authority's public description
route, and leaves the observation unproven without it.

The change does not run the scenario. A coordinator deploys the change and a dispute
authority meeting R1–R4 to a prepared topology, runs it, and writes the evidence into
this change as a sanitized summary naming no host, project or path, each observation
made, failed or unproven (`docs/guidance/engineering/system-tests.md`). The change takes
the evidence in good faith. Closeout waits for it, so the change reaches closeout only
once R1–R4 are deployed. The other live twins of rows here stay with
`qualify-per-period-bare-metal-and-setup-charges`.

Rejected: writing the scenario here and leaving its run to that change, closing out on
lane-double evidence; and leaving the scenario wholly to that change, which would
separate a twin from the row whose assertion it shares.

## Open Questions

None.

## Scenarios and evidence

Rows keep the numbers the diagrams use. Every row runs against the lane doubles on lane
time, each on a deal of its own, with every lane timer held (D8), and is lane-double
evidence; D14's scenario is live evidence the coordinator supplies.

| # | Row | Runs today | Remains | Lanes (D9) |
|---|---|---|---|---|
| 0 | On-demand baseline, ended by the buyer's stop | Both lanes | A setup part beside the rate (D10) | VM |
| 1 | The buyer ends while the payment authority is unreachable | — | The buyer journals its stop and retries it under one key, sends `end_delivery`, keeps the signed receipt and files `delivery_end(cause=payer)` with it; billing runs until the stop lands | Both |
| 2 | The site ends a lease the storefront has not heard of | — | The site's report held; the buyer's `market end` and case; the report delivered late; the storefront's payee revision ruled mechanically and netted (D6, D8); release proven apart | Both |
| 3 | Authority effects interrupted | A lost filing answer and a held ruling's resend, on once-only deals in the VM lane | The same on a rate deal; earlier evidence after a filed end, the revision ruled as the producer's trace shows (D6) | VM; live twin (D14) |
| 5 | An undelivered rate deal passes its delivery deadline | At integration, with the payment read the deadline waits for | The filing at the Agreement's start and the ruled return, setup included (D10) | VM |
| 7 | Spot preemption with notice | Both lanes | The buyer's earlier stop during the notice | Both |
| 8 | Activated, never available | — | Both orders of "Non-delivery is established at the delivery deadline": no start sent, refused; a start accepted before the deadline standing as history, the ruling returning what the rate earned; the setup variant (D10) | VM |
| 9 | Maximum term | Both lanes | A late start; an end inside a period | VM |
| 10 | Seller emergency | An on-demand seller's filing ruled with a stop and the penalty, in the VM lane | The on-demand notice refused at `deals preempt`, naming `delivery_end` (both lanes); a spot seller's filing and the cap's other ends, the setup charge alone held among them (VM) | Both / VM |
| 12 | The seller never files | — | Storefront loops held throughout; the buyer's stop and its case from the accepted Agreement and kept evidence are the whole remedy (D8) | Both |
| 12b | Availability asserted | — | The storefront contests with its `available`; the buyer's case carries its watchdog's observation; both evidence classes in the record | Both |
| 13 | A case over paid-out money | A once part, in the VM lane | A rate part: the filing accepted, the part `not_held`, no money moved | VM |
| — | The VM lane's two rate dispute rows | VM lane | Their twins | Bare metal |

Rows no longer here:

| # | Row | Where it went |
|---|---|---|
| 4 | A stop between start and disclosure | Proven at integration (D12) |
| 6 | Funds running out | Runs in both lanes. Its variants under a funding timer left with the timer (D4) |
| 11 | Receipt key rotation across a running deal | No change owns it: a key change is a drained cutover, and re-anchoring is tabled in Goal 8's unowned work |
| 12a | A late anchor against a site-enforced deadline | `enforce-delivery-deadlines-at-the-site` (D5) |

## Verification

Provisional levels, for planning and review to confirm:

- The leading physical pass and the list's accounting: library integration in
  `kit/deal-servicing/tests/integration`, beside `test_servicing_order.py`.
- The revision path: library integration in `kit/arkhai-mediation` against the
  producer's traces, the revision trace once vendored.
- Paused inline delivery and the watchdog's pause and step: application integration in
  the provisioning service.
- The storefront's return from an outage, and all three servicing fixes through the
  typed lifecycle client: application integration in each storefront.
- The new holds: `e2e-tests/tests/unit/test_scenario_lane_holds.py`.
- The rows: system level, lane-double evidence.
- The revision's live verification: live evidence supplied by the coordinator (D14).

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| D1 scope of the change | none |
| D2 boundary with operator recovery | none |
| D3 a pending release is cleared at the site | `docs/operator-handbook.md`, "A deal ending on a pending release" (landed; kept current) |
| D4 boundary with the funding timer | none |
| D5 boundary with the site-enforced deadline | none |
| D6 the authority rules a revision | `openspec/specs/deal-lifecycle/spec.md`; `openspec/specs/deal-lifecycle/architecture.md`, "External authorities"; `docs/development/ROADMAP.md`, Goal 8; `docs/operator-handbook.md` |
| D7 leading physical pass | `openspec/specs/deal-lifecycle/spec.md` |
| D8 the site's sends are lane steps | `openspec/specs/physical-provisioning/spec.md` and its companion; `openspec/specs/test-compatibility/spec.md`; `docs/guidance/engineering/system-tests.md`; `docs/guidance/repository/deterministic-tests.md`; `docs/operator-handbook.md` |
| D9 which lane runs which row | `openspec/specs/test-compatibility/spec.md`; `docs/development/TESTING.md` |
| D10 lane-only setup | `openspec/specs/test-compatibility/spec.md`; `docs/development/TESTING.md` |
| D11 the fifth ending code | `openspec/specs/deal-lifecycle/spec.md`; `docs/operator-handbook.md` |
| D12 consequences and conventions | as each item names |
| D13 implementation cadence | none |
| D14 coordinator-run live verification | `openspec/specs/test-compatibility/spec.md`; `docs/development/TESTING.md` |
