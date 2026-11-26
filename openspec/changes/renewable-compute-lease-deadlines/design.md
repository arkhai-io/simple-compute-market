# Design: renewable-compute-lease-deadlines

## Context

**What the site does today.** `kit/site` owns the reservation and the agreed lease
window. Commit is idempotent and records only the window
(`kit/site/src/market_site/ledger.py`, `commit`). The due read selects a `leased`
reservation by its `lease_end_utc` alone (`list_lease_due`), and entering `releasing` is
conditioned on the reservation's state, not on what the watchdog read
(`begin_releasing`). Activation writes `activated_at_utc` once and changes nothing else;
whether a lease is activated is derived from it. The compute lease lifecycle begins
release and does provider work outside the ledger's transaction
(`provisioning/compute/src/compute_provisioning/lease_lifecycle.py`). The API-credits
service hosts the same ledger and commits quota holds with no lease end.

**What the storefront enforces.** End service's delivery record holds the deal's
commitment instant and accepted `delivery_deadline_seconds`, and its deadline is the
earlier of the term end and that many seconds after the later of the commitment instant
and the start (`kit/deal-servicing/src/market_deal_servicing/journal.py`,
`DeliveryRecord`). A missed deadline is recorded as the seller's non-delivery, with its
`delivery_end` filing. For a deal that is not once-only it is recorded only after a
payment read made at or after the deadline; until then admission answers
`awaiting_observation` and nothing is recorded or filed. The deadline is met by the
storefront's durable `available` record, not by the site's activation (`deal-lifecycle`'s
"Non-delivery is established at the delivery deadline").

**What is published.** A compute option whose mechanism has a lifecycle adapter carries
the value the composition's `delivery_deadline_for_pool` port gives, else the value the
payments clause configures
(`kit/settlement-runtime/src/market_settlement_runtime/rate_publication.py`;
`kit/arkhai-payments/src/market_arkhai_payments/settlement_config.py`). The port
defaults to none in both compute compositions. A default buyer refuses such an option
with no deadline. Two checks read the published value: derivation refuses an option
whose dispute window is shorter than the deadline plus the authority's minimum window,
and acceptance requires a recurring horizon to leave the deadline plus one whole period
(`kit/settlement-runtime/src/market_settlement_runtime/horizon.py`).

**What a storefront can read of a pool.** The site's pool projection carries a pool's
`label`, `enabled`, `mechanism`, `policy_tags` and `pool_views`
(`kit/site/src/market_site/projections.py`), and storefronts read `policy_tags` from it
verbatim. A provider's defaults are the provisioning service's composition data and are
projected nowhere.

**The lease-end report.** The signed `lease_ended` record carries `claimed_deadline` and
`deadline_phase`, required together
(`provisioning/compute/contracts/src/compute_provisioning_contracts/lease_ends.py`). The
site writes phase `lease` at a term end and `reservation` at a hold's expiry. The
storefront's classifier reads the phase: `lease` at the term end is the terms' end,
`reservation` with nothing available is a provisioning failure, and a phase it does not
know stays unclassified
(`domains/compute/src/arkhai_compute/end_classification.py`, `classify_site_end`).

**One commit step.** Both compute domains commit at one place, the delivery path's
commit step, which also adopts a live hold
(`domains/compute/delivery/src/compute_delivery/path.py`), through
`CapacityEffects.commit` and the site client to the site's capacity route. The compute
contract writes no lease. The path already holds the delivery record. On a payments
deal the commitment instant is the receipt's approval instant, the payment service's
clock. Otherwise the VM storefront records the Agreement's acceptance instant
(`domains/vms/storefront/src/market_storefront/delivery_records.py`) and the bare-metal
storefront records its database's clock at evidence verification
(`domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/sqlite_client.py`).

**Pool facts.** The site ledger reads pool rows from `kit/resource-pools` directly.
`inject-site-pool-authority` replaces that with pool facts the site's composition
injects, read in the caller's session, and is in design. This change needs one more
fact through that port: the pool's resolved delivery deadline, readable in the commit's
own transaction. The port's names, its typing and how a missing fact fails follow that
change's recorded design.

**Released.** `marketplace-v0.4.0` carries all of the above. Its supported VM
configuration sets the clause's `delivery_deadline_seconds`, and its operator handbook
has an operator end an undelivered lease by hand.

## Decisions

### D1 — The deadline is written at commit, from the deal's accepted value

A reservation gains one nullable activation deadline, in the shared site schema both
ledger-hosting services apply. Existing rows have none. No phase is stored: an
unactivated lease is one whose `activated_at_utc` is null.

- **What is written.** On the first commit that carries the deal's accepted
  `delivery_deadline_seconds`, the site records the later of the deal's commitment
  instant and the lease start, plus that many seconds, on every pool. The commit carries
  the accepted value as a fact of the deal, like its window. A commit that carries none
  takes the value its pool resolves (D3), as the site's own safeguard: an option whose
  mechanism has no lifecycle adapter, a buyer who waived the term, and a storefront that
  predates this change all commit so. A commit that carries none, to a pool that
  resolves none, records none.
- **A value the pool resolves is a ceiling.** A commit whose accepted deadline exceeds
  what the pool now resolves is refused with nothing written: a seller cannot ask its
  site for more time than the site gives. A pool that resolves none sets no ceiling.
  Delivery records a refused commit of a reservation it holds as seller failure before
  dispatch and releases the reservation through end service's no-dispatch path
  (`compute-delivery`'s "An undelivered deal is handed to the end operation with
  classified evidence"). A pool lengthened after acceptance changes nothing for the
  deal; a pool shortened below the accepted value refuses the deal instead of
  reclaiming it early.
- **The site enforces the deadline it is told, on every pool.** A pool that resolves
  none contributes no value of the site's own (D3). It does not stop the site reclaiming
  a lease at the deadline the deal accepted. The storefront makes the delivery promise
  and enforces it; once the site is told the deadline, leaving an operator to end the
  lease by hand would protect nothing.
- **The record does not move.** A repeated commit leaves it unchanged, whatever the pool
  now resolves. Activation writes only `activated_at_utc`. Truncation moves only the
  agreed end.
- **The due instant.** A lease with a deadline and no recorded activation is due at the
  earlier of the deadline and its agreed end. Every other lease is due at its agreed
  end. Admission accounts the agreed window throughout: an elapsed deadline frees no
  capacity until release succeeds.

The site's deadline is the seller's capacity safeguard, not the buyer's guarantee. The
site knows no payment mechanism, so the commitment instant is the storefront's word. The
buyer's deadline is judged by the dispute authority from the payment authority's
approval record and the Agreement, and the storefront's journaled commit is evidence
where the two disagree.

Rejected:

- A site-wide deadline, or reuse of the hold's time to live. Providers differ in how
  long delivery takes.
- A stored phase beside `activated_at_utc`. Activation derives it and stores it nowhere.
- The deadline as a movable agreed end. It changes what admission accounts.
- Reclaiming a lease early when its pool is shortened. The deal was accepted at the
  longer value.
- A commercial flag on the commit. The site stays independent of how a deal is billed
  and of its class, which is read from its early-termination entitlements.

### D2 — Expiry claims the lease as it read it

The due read returns, for each due lease, what made it due: its agreed end, any
deadline, and whether an activation was recorded. Before any teardown effect, expiry's
transition into `releasing` is conditioned on the reservation still being `leased` and
on those values being unchanged, inside the ledger's serialized transaction. If
activation or truncation changed them, the claim fails with no write, no event, no
outbox entry and no provider call, and the next pass reads again. A claim that matches
begins `releasing`, which activation cannot undo.

The deadline is enforced by the claim, not by the clock. Activation stays admissible on
any `leased` reservation with a lease end, so a lease whose deadline has elapsed and
that expiry has not claimed can still be activated. Refusing it would turn the
watchdog's polling interval into an eviction. Such an activation is a capacity fact:
the storefront's own deadline rule decides whether the deal was delivered.

The claim supplements the release guard. It does not free capacity while a create is in
flight or teardown is unproven, and no database lock spans a provider call.

The rule is stated over what made the lease due, not over the activation deadline by
name, so another deadline a site enforces joins the same claim (D4).

Rejected: provider calls under a row lock; refusing activation by the clock alone.

### D3 — A pool states a deadline, nothing, or none

`delivery_deadline_seconds` is a Resource Pool policy tag with three states. The pool
resolves one value from it, and that value is what the site contributes. It does not
decide whether a deadline a deal accepted is enforced (D1).

| The pool states | Hint to the listing | Ceiling on a commit | Deadline for a commit that carries none |
|---|---|---|---|
| A number of seconds | That number | That number | That number |
| Nothing | Its provider's declared default, or none where the provider declares none | The same | The same |
| None | No hint | No ceiling | No deadline |

- **What the site contributes varies by pool; enforcement does not.** A site may give
  its VM pools a deadline and its bare-metal pools none. On those bare-metal pools a
  seller's clause deadline is still enforced by the site once committed, and a deal that
  accepted no deadline gets none. No service-level or site-wide setting exists, and
  nothing is shipped off to be turned on.
- **Per lease, the deadline is the one the deal accepted**, never above a value the pool
  resolves (D1). A committer cannot opt a lease out: the commit carries what the deal
  accepted (D6), and the pool's value applies where the deal accepted none.
- **None is the site's omission.** Under `docs/development/ARCHITECTURE.md`, "Omission
  states no commitment", a pool that states none commits the site to nothing of its own:
  publication gets no hint, a commit meets no ceiling, and a commit that carries no
  deadline gets none. The option then carries the clause's deadline where the seller
  configures one, and that is the only delivery promise the buyer reads. The storefront
  enforces it, and so does the site once the commit carries it. Stating none costs only
  the site, which gives up its safeguard for commits that carry no deadline.
- **Providers declare their default as data.** Each provisioning adapter exports its
  declaration and the composition merges them, as with the host requirement. The VM and
  bare-metal providers declare one. The API-credits provider declares none and its
  commits carry no deadline, so its quota holds get none by the same rule, with no
  exemption in the site.
- **A pool edit changes no recorded deadline** (D1).
- **Upgrading.** A pool written before this change states nothing, so it resolves its
  provider's default for new commits once the provisioning service is upgraded. A 0.4.0
  storefront commits with no accepted deadline and no commitment instant and published
  its clause's value. Where the pool's value is shorter, the site reclaims the lease
  before the storefront's own deadline, and the storefront's activation attempt is
  handed to end service as an activation lapse. The operator handbook's upgrade step
  covers it: upgrade the storefronts first, or state none, or a value at least the
  clause's, on the pools they sell until they are upgraded. A 0.4.0 storefront's commit
  carries no deadline, so on a pool that states none its leases record none.

Rejected:

- A composition switch shipped off and turned on after qualification. Every compute
  commit passes one step, so there are no callers left to wait for.
- A permanent site-wide setting. What a site contributes differs by pool, and enforcing
  a deadline a deal accepted needs no setting.
- The tag's presence as the opt-in. A pool that states nothing takes its provider's
  default, so a compute commit that carries no deadline still gets one.
- A per-lease opt-out. The party the deadline protects is not the committer.
- A pool stating none recording the deal's deadline for an operator to act on by hand.
  Nothing is protected by holding capacity past a deadline at which the storefront's own
  rule already counts the deal as not delivered.
- A pool stating none discarding the deadline the commit carries. The site would hold
  capacity for a deal it was told how long to wait for.

### D4 — An end calculated from what a deal has funded is `end-delivery-when-funding-runs-out`'s

This change's deadline reads no money. It answers when a lease that was never activated
is reclaimed, from the time since the deal's commitment. When a running deal's delivery
ends, calculated from what the deal has funded, is one calculation for every class of
deal, and `end-delivery-when-funding-runs-out` holds it.

That change has the storefront end delivery itself and leaves the site untouched, so it
uses nothing built here. It rejects a deadline on an active lease that a storefront
renews and the site enforces, to be revisited when a site's operator is not its
storefront's. This change stays built so that such a deadline can follow it:

- one activation deadline, written at commit and never rewritten;
- an expiry claim over what made the lease due (D2);
- a lease-end report that names which deadline was claimed (D5).

No renewal of a deadline on an active lease, and no site policy for one that lapses,
is built by any change.

Rejected:

- One neutral due instant, holding the delivery deadline before activation and a funded
  instant after it. It has the site enforce a funded instant, which that change
  rejects, and it needs activation to write more than `site-capacity`'s "Activation
  records its instant once and changes nothing else" allows.
- Waiting for that change. The gap this change closes is released and reads no funding.

### D5 — An activation lapse is lease-end evidence

When expiry claims a lease at its activation deadline, the `lease_ended` record states a
cause for the lapse, the deadline as its claimed deadline, and a phase naming that
deadline, beside the phases `lease` and `reservation`. The cause and the phase are open
strings, so the record's version does not change (`site-capacity`'s "Every ending
transition records one event").

- The record is written with the claim, before teardown. It states an intended end.
  Proven release stays the separate fact the capacity-released callback carries.
- It authorizes nothing about money and is no prerequisite. The storefront's own
  deadline rule and its `delivery_end` filing do not wait for it.
- The storefront's classification of a site's end gains this phase.
- The site's reservation view and the compute contract's lease view show the deadline
  beside `activated_at_utc`.

Rejected: a refund triggered by the site's event; a second event format.

### D6 — The storefront supplies the deal's facts and publishes the pool's value

- **The commit.** The delivery path's commit step sends the deal's accepted
  `delivery_deadline_seconds` and its commitment instant, as end service's delivery
  record holds them, through `CapacityEffects.commit` and the site client. Both domains
  commit through that step, so neither derives the values for itself.
- **Publication.** Each compute composition supplies `delivery_deadline_for_pool`,
  returning the pool's resolved deadline, or none where the pool resolves none.

Rejected: each domain deriving what its commit carries.

### D7 — The clause-configured deadline is kept

Publication takes the pool's value where the port gives one, else the payments clause's
`delivery_deadline_seconds`. `deal-lifecycle`'s "The delivery deadline is the
availability term the site or the clause sets" and `storefront-publication`'s "A compute
option's delivery deadline is its pool's, else its clause's" already state that, and
this change modifies neither. A pool that states none (D3) gives publication no value,
so the clause's deadline is what its options promise. The storefront enforces it, and
the site does too once the commit carries it (D1).

Where a pool's value replaces a different value a clause configures, publication reports
it, naming the clause and both values, so a seller's configured promise is never
silently changed.

Rejected: retiring the clause key in stages. Marketplace 0.4.0 ships it as the supported
configuration, and it would be safe only once no pool could state none.

## Open Questions

Each is decided in this change's design session.

### Q1 — The late-anchor row, and a lane scenario of this change's own

`converge-ongoing-compute-leases` gives this change the row in which a storefront
commits with a later anchor than the payment authority's approval, the site enforces the
longer deadline, and the buyer's case is ruled non-delivery at the accepted one. Three
facts bear on its form. The commit reads the delivery record's commitment instant, so a
storefront never sends another. No buyer command files a case on a running deal. A
lane's dispute authority rules only as the scenario programs it.

- (a) A lane row. It needs a way to make the storefront send a later anchor, either a
  control in the storefront or the harness committing in its place; a case the harness
  files through the mediation kit; and a programmed ruling.
- (b) Two integration proofs. At the site, a later anchor that is not in the future
  yields the later deadline. In the delivery path, the site's deadline never precedes
  the delivery record's for one deal. The ruling stays the accepted limitation Goal 8
  states.

Separately, whether this change adds a lane scenario of its own: the storefront's loops
held before delivery, lane time set past the deadline, the lease watchdog stepped, the
site reclaiming, and the report reaching the storefront once its loops resume.

- (c) In both compute lanes.
- (d) In the VM lane only, the path being the compute family's.
- (e) None; the site's integration suite and a first-use trace through the typed
  clients.

Recommended: (b) and (d). (b) proves what this repository's code decides, at the lowest
level that can. (d) is the change's premise end to end, once. It would move to (c) if
convergence's design settles that such rows run in both lanes.

### Q2 — How the resolved deadline reaches publication

D6 has each composition return the pool's resolved deadline. A storefront reads the
tag from the projection but not the provider's default. Today's projected pool:

```json
{"pool_id": "vm-default",
 "pool_metadata": {"label": "VM default", "enabled": true, "mechanism": "vm.ansible",
                   "policy_tags": {"deliverable_modes": ["vm"], "capacity_backing": "backed"}}}
```

- (a) An allowlisted pool-metadata field carrying the resolved number, absent where the
  pool resolves none:

  ```json
  {"pool_id": "vm-default",
   "pool_metadata": {"label": "VM default", "enabled": true, "mechanism": "vm.ansible",
                     "policy_tags": {"deliverable_modes": ["vm"], "capacity_backing": "backed"},
                     "delivery_deadline_seconds": 1800}}
  ```

- (b) A versioned `pool_views` key:

  ```json
  {"pool_id": "vm-default",
   "pool_metadata": {"label": "VM default", "enabled": true, "mechanism": "vm.ansible",
                     "policy_tags": {"deliverable_modes": ["vm"], "capacity_backing": "backed"},
                     "pool_views": {"delivery_deadline.v1": {"seconds": 1800}}}}
  ```

- (c) No new field. The storefront reads the tag from `policy_tags` and holds the
  providers' defaults itself. A default then lives in two services, and a storefront
  publishes a term the site may not enforce.

Under (a) and (b) a 0.4.0 storefront ignores the addition, and a 0.4.0 site omits it, so
the port gives none and the clause's value is published. Either changes
`site-capacity`'s "Resource-pool projection metadata".

Recommended: (a). The value is one neutral number any provider may have; `pool_views`
holds content a domain shapes. The projected number and the one the site's commit reads
come from one resolution.

### Q3 — A future, late or missing commitment instant

On a payments deal the commitment instant is the payment service's clock, and the site
compares it with its own process's time source. A commit that follows approval quickly,
from a payment service a few seconds ahead, carries an instant the site reads as future.
An instant later than the true approval lengthens only the seller's own safeguard (D1).
A commit from a 0.4.0 storefront, and a deal whose delivery record holds none, carry no
instant. That matters only where a deadline is recorded: the pool resolves a value, or
the commit carries a deadline with no instant.

For an instant after the site's clock:

- (a) Refuse the commit. Clock skew then becomes a seller-failure filing.
- (b) Use the site's clock in its place. The safeguard shortens by the skew.

For no instant:

- (c) The later of the site's commit instant and the lease start.
- (d) Refuse the commit.

Recommended: (b) and (c). Neither turns a clock difference or an older storefront into a
failed deal.

### Q4 — A pool value a clause's window or horizon cannot cover

Once a pool's value is published in place of a clause's, a larger value can fail the
two checks that read it. An option that publishes today is then omitted, with the
diagnostic `dispute_window_before_delivery_deadline`, or its shortest horizons are
refused at acceptance.

- (a) The existing per-option diagnostic alone.
- (b) The storefront refuses to start.
- (c) The existing diagnostic, and a line in the storefront's startup report.

Recommended: (c). The cause is another service's pool, so a refusal to start would make
the storefront's availability depend on it.

### Q5 — The providers' default values

- (a) 1800 seconds for VM and 7200 for bare metal. Neither is measured; 1800 is the
  value 0.4.0's VM example configures in its clause.
- (b) One value for both until bare-metal delivery is measured.

Two things follow whichever is chosen. The packaged seed pools state nothing, so they
follow a default that changes later. The lanes' listings compose their deadline from
`PAYMENTS.VM_DELIVERY_DEADLINE_SECONDS`, which `test-compatibility`'s "VM payment
scenarios declare their configured delivery allowance" requires; the lanes' pools state
that same value, or none, so the requirement stays true. Either way the site enforces
the value the deal accepted.

Whichever is chosen, a default is a statement of how long a provider's delivery takes.
The records of the real-host runs made for earlier releases may hold delivery
durations for both providers; where they do, the values are taken from them and not
from the VM example's clause.

Recommended: (a), with the lanes' pools stating the lanes' value, replaced by measured
durations where the run records hold them.

### Q6 — The bare-metal commitment instant read from the database clock

For a deal not paid through Arkhai payments, the bare-metal storefront records
`SELECT unixepoch()` as the commitment instant. That reads the database's wall clock,
which the time-read check does not see, and under injected time it differs from every
other party's. D6 makes that instant an input to the site.

- (a) Fix it here: the instant comes from the process's time source.
- (b) Fix it here and derive the instant alike in both domains. The VM storefront
  records the Agreement's acceptance instant for the same case.
- (c) Table it as unowned work in the campaign index.

Recommended: (a). It is small and understood, and this change is what makes the instant
matter outside the storefront. (b) needs a decision on which instant commits such a
deal.

### Q7 — Provisional answers

Each follows from something settled or from the nearest precedent, and is confirmed or
moved in the design session.

- **Classifying the lapse report.** `deal-lifecycle`'s "Cause classification is owned by
  end service" already names an activation lapse a seller failure. The report is an echo
  where the storefront recorded its own deadline failure, a seller failure where nothing
  was available and no earlier lawful end exists, and unclassified while a deal that is
  not once-only waits for its payment read.
- **The cause and the phase.** A cause of its own and a phase naming the activation
  deadline, as `expiry` pairs with `lease` and `hold_expired` with `reservation`.
- **The column's name.** `activation_deadline_utc`: `deal-lifecycle` already calls it
  "the site's activation deadline", and the site's instants end in `_utc`.
- **How none is spelled.** The word `none`. An explicit null is hard to tell from
  absence in a patch and in a pool document, and zero reads as "immediately".
- **Validation.** One shared check on every pool write surface, as the hold and SLA
  preferences have: a stated value is a positive whole number of seconds or none.
- **A number stated for a provider that declares no default.** Doubtful, and the least
  settled item here. It was to be refused while a provider with no default meant one
  whose leases take no deadline. The site now enforces a carried deadline on every pool,
  so declaring no default says only that the provider contributes none, and a pool of
  its own stating a number is not obviously wrong. Against accepting it: the one such
  provider's commits have no lease end, which a recorded deadline needs.
- **Which specification states what.** `resource-pool-management` states the tag and
  what a pool resolves; `site-capacity` states what the ledger does with the resolved
  value. The tag is documented with the pool document's format, in the operator
  handbook and `docs/development/DEPLOYMENT_AND_CONFIG.md`.
- **One publication function.** Both compositions pass the same function, which reads
  the pool through the resolver every reader of the pool projection already uses.
- **The handbook.** "Leases the storefront has not delivered" is rewritten: the site
  reclaims a lease that has a recorded deadline. The manual procedure remains for a
  lease with none: one committed before the site recorded deadlines, and one whose
  commit carried no deadline to a pool that resolves none.
- **A tie.** A lease due at its deadline and its agreed end at one instant reports the
  ordinary term end.
- **A finite end.** A commit that would record a deadline requires a lease end. The only
  commits with no end are API credits' quota holds, which carry no deadline to a pool
  that resolves none.
- **The anchor.** The later of the commitment instant and the lease start, as
  `deal-lifecycle` defines the term; delivery dispatches nothing before the start.
- **Test levels.** The claim in both orders and the pool-edit and anchor cases are
  library integration in `kit/site`; the tag is unit in `kit/resource-pools-contracts`
  and library integration in `kit/resource-pools`; the migration is each hosting
  service's chain test; the commit's fields and the refused commit are the delivery
  path's integration suite.

### Q8 — Implementation cadence

Recommended: two rounds, after `inject-site-pool-authority` lands. First the site: the
tag and its resolution, the column, the commit, the due read, the claim, the report and
the views, one session. Then the storefront: the commit's fields, publication, the
classification, the handbook and whatever Q1 settles, one session.

### Q9 — Reclaiming a lease whose create is still running

A lease can end while its create is in flight today, and the release guard holds its
capacity until the create settles and teardown is proven. With a deadline recorded at
commit, that stops being rare: every delivery slower than its deadline is reclaimed
mid-create. The site's part, the claim and the guard, is proven in `kit/site` and in a
lane, where a provisioning job is held at a gate under lane time. What a lane cannot
show is that a real host is left clean when teardown follows an interrupted create.
That behaviour is the provisioning roles', which this change does not touch, and the
observations the validation runbook owes cover teardown of delivered machines only.

- (a) Nothing here. The path is unchanged, and a real-host run is owed when a change
  touches the provisioning roles or how an adapter runs them.
- (b) One real-host observation of a reclaim during a create, made with this change,
  because this change is what makes the case routine.
- (c) Table it with `complete-real-provisioning-qualification`, as an observation the
  runbook lacks. That change's design holds it as its Q4.

Recommended: (c). The gap is in the provisioning roles' evidence and exists without
this change; (b) would make this change wait on a host for behaviour it does not alter.
