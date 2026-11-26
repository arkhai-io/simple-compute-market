# Design: converge-ongoing-compute-leases

## Context

**What services a deal.** Both compute storefronts run one kit-owned servicing cycle,
`ServicingCycle` (`kit/deal-servicing/src/market_deal_servicing/servicing.py`), in a
`deal-servicing` loop registered through the kit loop controller, as `deal-lifecycle`'s
"Each deal's servicing steps run in one kit-owned order" and `market-composition`'s
"Both compute storefronts run one loop layout" state. A cycle discovers counterparty
cases once per dispute authority, then takes the page deal by deal: the authorities
read, the domain's recovery steps, the physical end, local reconciliation, site-report
correction, filing dispatch, and the physical end again, each step isolated. A failed
step skips nothing. A deal's physical end still runs after its own authorities read and
after every earlier deal's steps, and each authority client waits ten seconds by
default (`kit/arkhai-payments/src/market_arkhai_payments/client.py`,
`kit/arkhai-mediation/src/market_arkhai_mediation/client.py`).

**Ends and filings.** End service keeps every final request and selects the earliest.
A seller failure cannot be recorded without its `delivery_end(cause=payee)` filing
(`kit/deal-servicing/src/market_deal_servicing/journal.py`, `record_end`), for every
kind of deal: an administrator's failure end, a site's unentitled withdrawal, and a
missed delivery deadline, which for a rate deal is recorded only after a payment read
made at or after the deadline (`deal-lifecycle`'s "The seller files ends its terms do
not entitle", "Administrator interruption explicitly classifies its cause" and
"Delivery authorization delegates payment interpretation"). A filing for a failure
before the Agreement's start waits for that start.

**A changed claim.** When a new, earlier seller failure becomes the selected end, the
journal adds a filing for it. The mediation adapter reserves one original
`delivery_end` writer per commitment, Agreement and authority; a different caller
adopts an equivalent filed claim, and a claim that differs from the one filed is
answered `repair required: delivery-end revision requires resolved prior rulings and
effects` (`kit/arkhai-mediation/src/market_arkhai_mediation/adapter.py`). A rejected
filing is terminal and shows repair required. That is the fallback "Filing identities
and revised requests are safe across callers" gives an unsupported mapping, and no
mapping exists; "Revised cases carry their prior rulings" is otherwise unmet. The
vendored mediation contract has no revision or linked-case construct. Its
`CaseConcurrencyPolicy` fixes `repeated_cases: allowed` and
`rulings: net_prior_effects`, and its published traces include
`manual-second-mechanical-claim` and `operator-nets-earlier-ruling`
(`kit/arkhai-mediation/src/market_arkhai_mediation/contract_data/`): a second
mechanical claim goes to an operator, and the authority nets its earlier ruling.

**When a deal is ended.** "The seller half lists deals" lists a deal with a recorded
end `ended` only when its resource is proven released, every payment part has a
verified stop or end, and a saved read of its dispute authority shows no case open;
otherwise `ending`, naming each outstanding condition from four closed codes. The list
computes this at read time from saved views
(`kit/deal-servicing/src/market_deal_servicing/seller.py`, `_outstanding`) and never
reads the deal's own filings, so a deal whose filing is unsent, waiting or unanswered
can be listed `ended`. The single-deal read and the list both carry the filings
themselves.

**Release.** For a delivered deal, each storefront records the release when the site's
provisioning service delivers its capacity-released event. The service sends it once a
teardown is proven or an administrator force-releases the lease, which leaves the lease
`force_released`, and sends it again each lease-watchdog cycle until acknowledged
(`provisioning/compute/src/compute_provisioning/lease_lifecycle.py`).

**The lanes.** Every party of a Compose lane runs on one lane time a stage sets,
forward only (`test-compatibility`'s "Every party in a lane shares one lane time the
scenario sets"). A scenario holds a storefront's loops and steps them; it cannot stop
the service, and a storefront whose loops are held still answers its API
(`docs/guidance/repository/deterministic-tests.md`, "Pause the loop, then advance it
explicitly"). The mediation double takes a ruling as a programmed rule and executes its
`reverse`, `stop` and `penalty` effects, the penalty capped at what is held. Both lane
storefronts declare `charged` and `returned` and no setup charge. What runs today is
`test-compatibility`'s "A recurring purchase is delivered end to end in each compute
lane", "Rate deals are qualified in both compute lanes on lane time", "The buyer's
watchdog is qualified against a delivered deal", "Controls scenarios prove the lane's
dispute wiring in the VM lane" and "A dispute on a running rate deal is qualified in the
VM lane"; the bare-metal lane runs no dispute row on a rate deal.

**What is released.** `marketplace-v0.4.0` carries all of the above.

## Decisions

### D1 — One change holds the remaining rows and three servicing fixes

This change is the remaining rate qualification rows and three fixes to how a
storefront services a deal: a revised `delivery_end` claim reaches the dispute
authority, the seller's list does not show a deal `ended` while a filing of its own is
unsent or unanswered, and the order of work within a page lets a physical end run
without waiting for authority reads.

A change costs a design, reviews, a validation and a closeout, so a piece of work left
over is placed by one rule: it goes to a related change where it fits; with no such
home, a small piece stays with the others; only a large piece with no home becomes a
change. Each fix here is small, each has evidence in the code, and each is exercised by
the rows this change qualifies.

Rejected:

- A qualification change and a servicing change. Two designs and two closeouts for
  three small fixes and the rows that exercise them.
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

Rejected: keeping it here, where the largest item with no named user would hold three
small fixes; and an unowned roadmap row, which would drop the design already worked out
for it.

### D3 — A pending release is cleared at the site

A deal listed `ending` with `release_pending` is cleared at its site, through the
provisioning service's administrator API: `retry-release` re-observes a teardown that
has since finished, and `force-release` returns the capacity on the operator's word,
with a reason and evidence. Either leads the service to deliver the capacity-released
event the storefront records. A site that no longer serves listings does the same: it
runs its provisioning service to answer those requests. The storefront gains no command
for it, and `docs/operator-handbook.md`, "A deal ending on a pending release", gives the
procedure.

The site is the party that can see the host and that owns the lease's release, so it is
where an operator's assertion belongs
(`docs/guidance/engineering/implementation.md`, "Deciding which party is authoritative").

Rejected: a seller command acknowledging physical recovery at the storefront. It would
add a command kind, a client method and an audit record for an assertion the site
already records, made by the party that cannot check it. Rejected too: recording a
condition under which to revisit, since a site can always run its provisioning service
again.

### D4 — The funding timer is `lapse-billing-with-the-site-lease`'s

This change builds no funding timer. When a deal's delivery ends for want of funds is
to be calculated by one mechanism from what the deal has funded, for every class of
deal, and `lapse-billing-with-the-site-lease` is where that is designed, with the site
lease it lapses. Whether a seller opts into it, and what it asks of the payments
service, are that change's questions. Until it lands, a running rate deal's funding end
reaches end service only as the payment authority's recorded stop, as `deal-lifecycle`'s
companion states under "Current limits".

Rejected: a seller's opt-in timer for rate deals here. It would be one of several
mechanisms each ending delivery for its own category of deal.

### D5 — The late-anchor row is `renewable-compute-lease-deadlines`'

The row in which a storefront commits with a later anchor than the payment authority's
approval, the site enforces the longer physical deadline, and the buyer's case is ruled
non-delivery at the accepted deadline needs a delivery deadline the site enforces.
`renewable-compute-lease-deadlines` builds that, so it runs the row. Here the row would
make this change wait on another.

## Open Questions

Each is decided in this change's design session.

### Q1 — The order of work within a page

D1 keeps the fix; how it is made is open. Today a physical end waits for its own deal's
authorities read and for every earlier deal's steps.

- (a) Passes over the page: the physical end for every deal, then the authority work,
  then the physical end again for ends the authority work recorded. It changes the
  order "Each deal's servicing steps run in one kit-owned order" states, in one method.
- (b) The per-deal order as it is, and after an authority's first failure in a cycle no
  further read of that authority in that cycle. The landed order stands; the cycle
  gains state it does not have.

Recommended: (a). It is the smaller change and removes the wait instead of bounding
it. It would change if a measurement showed a page's physical ends never wait
materially, which would make the fix unnecessary.

### Q2 — How the list accounts for a deal's own filings

Settled, and in the `deal-lifecycle` delta: a deal with a filing of its own unsent or
unanswered is listed `ending`. Open is how the list names the condition and what else
counts.

- (a) A fifth code in the closed list, computed at read time from the journal, for a
  required filing that is unsent, waiting or of pending or unknown outcome. Whether a
  journaled operation of unknown outcome counts under it too is part of the question.

  ```json
  {"negotiation_id": "n-123", "state": "ending", "ending": ["filing_pending"],
   "filings": [{"intent_ref": "9f2c…", "outcome": {"status": "pending",
     "reason": "delivery-end filing waits for Agreement start"}}]}
  ```

  A 0.4.0 seller client refuses the unknown code, so the lifecycle contracts take an
  incompatible step and ship with the client that reads it. The list's readers are the
  typed seller client and an operator's raw read; neither storefront CLI lists deals.
- (b) Persisted completion state per end, with its history, the age of each gap and
  references to what is pending. It adds tables to each storefront chain and fields no
  reader uses yet.

Recommended: (a), the code arriving with its text in the contracts' `ENDING_TEXT`, as
the four codes did. It would change if Q3's answer needs a record of which end a filing
answers.

### Q3 — How a revised `delivery_end` reaches the authority

D1 keeps the fix; the mapping is open.

- (a) Once the original case is ruled or closed, the adapter files the changed claim as
  a repeated case, naming the earlier case in its evidence. The authority routes a
  second mechanical claim to an operator and nets its earlier ruling, as its published
  traces show. New work in `kit/arkhai-mediation`; the mediation double must accept a
  second case on one Agreement, which is not verified.
- (b) The adapter keeps answering repair required, and the operator handbook says how
  an operator raises the correction with the authority by hand.

Recommended: (a): repair required is permanent today and says nothing to the buyer. It
would change if the dispute authority's maintainers want corrections raised another
way.

### Q4 — How a lane row holds a storefront back

Rows 2, 12 and 12b were written for a storefront that is absent. A lane can only hold
its loops, and a storefront so held still accepts a site's pushed report or a buyer's
hint.

- (a) "Absent" means the loops are held, and each row states what else it holds back
  through a control that exists. For row 2 that is the site's delivery of its report;
  whether a lane can hold that is not verified.
- (b) Rows 12 and 12b drop the premise: they are the buyer's stop and case against the
  doubles, with the storefront not stepped.
- (c) What a storefront does on returning from an absence is proven at application
  integration by rebuilding the application over its database, as restart recovery is
  in both domains, and the lane rows keep only what crosses services.

Recommended: (b) for rows 12 and 12b; for row 2, (c) for the return and a lane row
under held loops for the filing.

### Q5 — Which lane runs which row

`docs/guidance/repository/family-kits.md`, "Sibling domains behave alike", argues for
running a row in both lanes; `docs/guidance/engineering/test-levels.md` asks for the
fewest system tests that cover a cross-service contract. The baseline rows run in both lanes; the two rate dispute rows run in the VM
lane only.

- (a) Every remaining row in both lanes.
- (b) Each row once, in the VM lane, and in the bare-metal lane too where bare-metal
  code is on its path: the buyer's commands, the teardown, the physical end.
- (c) Each row once, in the VM lane, and in the bare-metal lane only the twins of the
  two rate dispute rows the VM lane runs today.

Recommended: (b), beginning with those two twins, since the bare-metal lane has no
dispute row on a rate deal.

### Q6 — Rows that need a setup charge

Row 0's setup variant, the setup returned in rows 5 and 8, and the end of row 10's cap
where the setup charge alone is held all need an option with a setup part. No lane
declares `setup`, and "Setup returns by delivered for either cause" keeps setup-bearing
presets disabled until a hosted dispute authority is qualified on the vendored
`delivery_end` revision.

- (a) The lane storefronts declare `setup = true`, in the lane configuration only, as
  they declared `charged` and `returned` before either was a supported configuration.
- (b) The setup rows go to `activate-per-period-compute-servicing`, which switches
  setup charges on.

Recommended: (a). The rows prove this repository's handling against the doubles, and
activation then repeats them against the hosted authorities.

### Q7 — Provisional answers

Each follows from something settled or from the nearest precedent, and is confirmed or
moved in the design session.

- **Deltas modify the landed requirements.** The pass order changes "Each deal's
  servicing steps run in one kit-owned order"; the list's new condition changes "The
  seller half lists deals", replacing this change's added requirement once Q2 names
  the condition; anything added about restart changes "Bare-metal storefront restart
  recovery is proven at integration level". A specification states each rule once.
- **Rulings are programmed, effects are executed.** A row's ruling is a rule the
  scenario installs; the double executes its `stop` and `penalty` as the contract
  defines them, the cap included; the row proves the storefront's handling, not the
  authority's arithmetic (`docs/guidance/engineering/test-doubles.md`, "A double
  mirrors its producer").
- **Row 4 is proven at integration.** The activate, start and disclose races are in
  `domains/compute/delivery/tests/integration`; no lane row repeats them
  (`docs/guidance/engineering/test-levels.md`).
- **Compatibility.** As the proposal's "Impact" states it against `marketplace-v0.4.0`.
- **Diagrams.** Only a pair that draws what the product does is promoted, to
  `docs/development/diagrams/`; `diagrams/README.md` says which pairs need redrawing
  first.

### Q8 — Implementation cadence

Recommended: two rounds. First the three fixes with their kit and application
integration tests, one session. Then the lane rows, the VM lane's and then the
bare-metal lane's, a session each.

## Scenarios and evidence

Rows keep the numbers the diagrams use. Every row runs against the lane doubles on lane
time, each on a deal of its own, and is lane-double evidence.

| # | Row | Runs today | Remains | Needs |
|---|---|---|---|---|
| 0 | On-demand baseline, ended by the buyer's stop | Both lanes | A setup part beside the rate | Q6 |
| 1 | The buyer ends while the payment authority is unreachable | — | The buyer journals its stop and retries it under one key, sends `end_delivery`, keeps the signed receipt and files `delivery_end(cause=payer)` with it; billing runs until the stop lands (`buyer-orchestration`'s "The buyer's end is backed by its own stop or a case") | Nothing new |
| 2 | The site ends a lease the storefront is not servicing | — | The buyer's own stop and case; the site's late report; the storefront's `delivery_end(cause=payee)`; release proven apart | Q4 |
| 3 | Authority effects interrupted | A lost filing answer and a held ruling's resend, on once-only deals in the VM lane | The same on a rate deal; earlier evidence after a filed end | Q3 |
| 5 | An undelivered rate deal passes its delivery deadline | At integration, with the payment read the deadline waits for | The filing at the Agreement's start and the ruled return, setup included | Q6 |
| 7 | Spot preemption with notice | Both lanes | The buyer's earlier stop during the notice | Nothing new |
| 8 | Activated, never available | — | Both orders of "Non-delivery is established at the delivery deadline": no start sent, refused; a start accepted before the deadline standing as history, the ruling returning what the rate earned | Q6 for the setup variant |
| 9 | Maximum term | Both lanes | A late start; an end inside a period | Nothing new |
| 10 | Seller emergency | An on-demand seller's filing ruled with a stop and the penalty, in the VM lane | The on-demand notice refused at `deals preempt`, naming `delivery_end`; a spot seller's filing; the cap's other ends | Q5, Q6 |
| 12 | The seller never files | — | The buyer's stop and its case from the accepted Agreement and kept evidence are the whole remedy | Q4 |
| 12b | Availability asserted | — | The seller's timely `available` weighed against the buyer's kept observation of failure | Q4 |
| 13 | A case over paid-out money | A once part, in the VM lane | A rate part: the filing accepted, the part `not_held`, no money moved | Nothing new |

Rows no longer here:

| # | Row | Where it went |
|---|---|---|
| 4 | A stop between start and disclosure | Proven at integration (Q7) |
| 6 | Funds running out | Runs in both lanes. Its variants under a funding timer left with the timer (D4) |
| 11 | Receipt key rotation across a running deal | No change owns it: a key change is a drained cutover, and re-anchoring is tabled in Goal 8's unowned work |
| 12a | A late anchor against a site-enforced deadline | `renewable-compute-lease-deadlines` (D5) |

A row that holds a ruling at the double's gate steps no storefront servicing while the
ruling waits: the storefront ends delivery on a ruling's delivery end whatever its
applied state, an unowned question in the roadmap.

## Verification

Provisional levels, for planning and review to confirm. The pass order and the list's
accounting are library integration in `kit/deal-servicing/tests/integration`, beside
`test_servicing_order.py`; a revised claim is library integration in
`kit/arkhai-mediation` against its published traces; each storefront proves all three
at application integration through its typed lifecycle client; the rows above are the
system-level proof.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| D1 scope of the change | none; each fix and row as the design settles it |
| D2 boundary with operator recovery | none |
| D3 a pending release is cleared at the site | `docs/operator-handbook.md`, "A deal ending on a pending release" |
| D4 boundary with the funding timer | none |
| D5 boundary with the site-enforced deadline | none |
