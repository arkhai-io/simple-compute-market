# Design: switch-on-hosted-per-period-vm

## Context

The last of Goal 8's MVP changes, after `drive-the-storefront-clock-in-lanes` and
`serve-running-rate-deals`, both archived. Both compute storefronts deliver and service
on-demand and spot deals in both lanes against the payments and mediation doubles, and
no shipped configuration offers them.

What this change builds on:

- A seller's `[Settlement.rate_servicing.arkhai_payments]` table declares the
  treatments its storefront services
  (`kit/settlement-runtime/src/market_settlement_runtime/rate_servicing.py`), and
  publication, acceptance and materialization refuse any it does not list. Absent or
  empty means none: every shipped configuration, and only the lanes' storefront
  configurations declare `charged` and `returned`
  (`openspec/specs/settlement-configuration/configuration.md`). The declaration is the
  seller's configuration; this repository has no production composition of its own.
- The shipped presets charge the buyer's stop through its started period (`charged`),
  return the unstarted remainder on a seller's preemption and at the term end
  (`returned`), and give the dispute authority a `chosen` stop entry
  (`kit/settlement-runtime/src/market_settlement_runtime/rate_publication.py`). The
  default buyer refuses `charged` on a preemption and at the term end, and an option
  promising no delivery deadline
  (`kit/settlement-runtime/src/market_settlement_runtime/buyer_terms.py`).
- Publication takes the pool's delivery deadline when the composition supplies one and
  the payments clause's otherwise; no composition supplies one
  (`rate_publication.py`). The storefront enforces the deadline, classifying a miss as
  seller non-delivery (`kit/deal-servicing/src/market_deal_servicing/journal.py`); the
  site does not.
- Every party learns of an authority's decisions by polling: the storefront reads each
  deal's signed transaction snapshot from payments and the dispute authority's signed
  record for its Agreement every servicing cycle, and records a stop or a ruled delivery
  end as the deal's end whoever caused it
  (`kit/deal-servicing/src/market_deal_servicing/watch.py`). Neither authority calls the
  storefront.
- SCM acts on two ruling-only side effects: a ruled `delivery_end` effect in the
  record, recorded as an end with cause `ruling`, and a stop by the dispute authority's
  account through its `chosen` entry (cause `authority`), classified `ruling`
  (`domains/compute/src/arkhai_compute/end_classification.py`). The lanes produce the
  first on once-only deals; the mediation double refuses a `stop` or `penalty` rule
  (`tools/mediation-lane-double/README.md`), so no lane produces the second.
- The newest marketplace release, `marketplace-v0.3.0`, carries no rate servicing, so
  no compatibility is owed to a deployed rate deal.

What the payments service's own repository documents, which this design relies on
without claiming it as SCM's behaviour:

- The hosted payments service runs on wall time with no test clock, accepts any positive
  rate period, and keeps a started rate part reserved ahead by its own scheduler.
  Approval answers `409 insufficient_funds` when the balance cannot cover the first
  reservation; a top-up before the funded boundary keeps a part running, and after it
  the `terms` stop is final. A seller is paid out a fixed delay after release, 7 days in
  live mode. No receipt-key retention commitment or rotation announcement is published.
- The hosted mediation service rules a payee's `delivery_end` filing mechanically —
  stopping rates `returned`, reversing held earnings since the end and applying the
  capped penalty — when its guards hold; other cases go to operators, who rule through a
  private operator API on a filed case, one decision per case.
- The published contract package and the `arkhai.mediation.v1` schema SCM vendors cover
  filing, appends, the respondent listing, record reads and the signed record; they
  include no operator route.

`activate-per-period-compute-servicing` keeps bare metal, setup charges, `prorated`, the
remaining mechanical-ruling qualification and Goal 8's completion bar.

## Decisions

### D1 — The switch-on is a documented, supported seller configuration

Switching on on-demand and spot VM is documentation and a shipped example, with no code
gate: the seller quickstart gains a section on offering them; the VM storefront chart
gains `examples/production-values.yaml`, declaring `[charged, returned]` with
`setup = false` and an on-demand and a spot recurring clause; and the caveats in
`settlement-configuration`'s companion and `deal-lifecycle`'s architecture saying hosted
qualification has not shown the `chosen` stop are corrected from the live evidence.
Withdrawal is the seller removing the table, or emptying its `treatments`: new recurring
offers stop and deals already materialized keep being serviced, as the existing
requirement states. `activate-per-period-compute-servicing` extends the example to bare
metal.

Rejected: a packaged default declaration, which changes "absent means none" for VM alone
and makes withdrawal each seller's explicit empty list; a release-carried gate refusing
unqualified treatments under `livemode = true`, which buys little while the payments
service's go-live gates production and adds livemode-keyed behaviour; configuration of
a particular deployment, which never appears in this repository; and deferring the
switch-on to the activation change.

### D2 — No release step

Creating a release is independent of any change. This change neither cuts nor names a
release; its documentation describes the system as it stands, and a seller follows it
on whatever release carries it.

Rejected: requiring a validated, promoted release candidate at closeout, which ties the
change to the deployment's operations and to the payments service's go-live; and binding
the live runs to a loaded candidate's images.

### D3 — Live verification names requirements, not a target

The change states what a topology must provide for its live verification scenarios and
names no target. Live verification is a pause in the change's workflow: the deployment
reads the requirements, prepares a topology meeting them — resolving the mediation
authority under its own plan — runs the live scenarios, and records their sanitized
evidence in the change. An unmet requirement leaves the observations needing it
unproven, never passed.

The switch-on is qualified only when the buyer's stop, funds running out, the spot
preemption, the term end and the seller's filing are each recorded made (18 F1). The
buyer's contested case is the one observation that may stay unproven, recorded as a
Goal 8 gap. Until the five are made, the caveats D1 corrects stay as they are and the
change does not go to pre-closeout: an unproven required observation holds the change at
live verification for the deployment to meet the requirement it names, or, on the
owner's word, returns it to design, as a failed comparison does (D14).

Rejected: gating on mediation being deployed to one named hosted target, which the
payments service's maintainers schedule only near production and which would hold the
change indefinitely; and naming a development topology here, which is the deployment's
choice and ties the evidence to one environment by name.

### D4 — The live scenarios extend the lane rows, with the provisioning their claim needs

The live verification scenarios are external-topology scenarios extending the lane rows
of `serve-running-rate-deals`, sharing their stages. Where a lane row uses a control only
the double has — lane time, the funding control, the reservation control — the live
scenario takes the input as the producer sees it: elapsed wall time, a balance the
topology funds, the producer's own scheduler. `LaneTime.reach` gains one admitted
wall-time case: an instant an authority recorded as the effect of the scenario's own
request, read from a signed record — a preemption's effective instant, the funded
boundary — and waited for, bounded. Period, notice and term come from run settings,
defaulting to the lanes' values. A live scenario's provisioning mode follows what it
proves: these prove the payment and dispute authorities, so they run on mock
provisioning, and each states its mode among its topology requirements.

Rejected: a separate hosted suite sharing no stages, which lets the lane and live paths
drift; a manual qualification procedure, which a coordinator cannot repeat; and waiting
for a payments test clock, which the payments service does not offer.

### D5 — SCM's dispute interface ends where the public client ends

SCM depends on no endpoint the dispute authority's public client lacks. Filing,
appending, the respondent listing and record reads are SCM's to exercise; an operator's
ruling is the authority's, made through its private API, and the interaction between
mediation and payments is qualified by the payments service's own live verification
scenarios. A person's decision reaches an SCM live scenario only through a policy the
topology applies — a policy watcher is a double for a person — or through the scenario
itself where a public client offers it.

Rejected: a harness client for the operator API, and acting at payments with the
mediation account's credential, which bypasses the dispute record; and a mediator hook
SCM defines and the topology implements, superseded by the topology's declared policy.

### D6 — Logic downstream of a ruling is proven on the doubles; live scenarios compare outputs

SCM logic downstream of a side effect SCM cannot create live is proven against the
doubles, whose limits are amended where the logic needs them. The mediation double
executes a ruling's `stop`, as one stop event from its own account through the part's
`chosen` entry with the ruling's treatment, followed, when its time has passed, by the
reversal of the earnings beyond what a stop at that time would have earned, as far as
the part still holds them, attributed to the stop, as the dispute authority documents a
stop effect; and its `penalty`, as reversals of earned amounts still held across parts
in mandate order, capped at what is held — executing effects the contract defines, while
which effects a ruling carries stays the scenario's programmed rule. A mechanical ruling
of a payee's `delivery_end` on a rate deal carries a delivery end, the `stop` and the
`penalty`, and no `reverse` of its own: the stop's reversal covers the earnings since
the end. `award` stays refused. The VM lane gains two rows on rate deals: a seller's
filing ruled as the producer documents a mechanical ruling, and a buyer's filing the
storefront contests, ruled by an operator decision; each shows the authority's stop
recorded and classified `ruling`, the payer's returns, the teardown and, once the case
closes, the deal listed `ended`. This takes the double's `stop` from
`converge-ongoing-compute-leases`, whose index row and Goal 8 gap keep `penalty`'s use
in its own rows.

A live verification scenario's minimum is to verify the interactions between SCM and
external systems the lane scenarios could not exercise: it gives the live producer the
inputs its lane twin gave the double, produced by SCM's own client code, and checks the
producer emits the outputs the lane twin expected; it need test nothing else. The
comparison is one assertion shared with the lane twin, stating which fields it compares
exactly, by relation or not at all. It polls the live producer, bounded, for an
asynchronous output. A different output fails the observation. This complements the
complete-scenario external form rather than replacing it. The live scenarios are six:

| Live scenario | Input to the producer | Output compared |
|---|---|---|
| Buyer's stop | a payer stop | cause `payer`, `charged`, the started period charged |
| Funds running out | a balance of N periods | a `terms` stop at the funded boundary, N periods settled |
| Spot preemption | a payee stop with notice | pending, then final at receipt plus notice, `returned`, the remainder refunded |
| Term end | the part's end | ended at the Agreement's end, `returned` |
| Seller's filing | the storefront's payee filing | each part protected; an authority stop `returned` with its reversal of any earnings since the end, the capped penalty, each reversal attributed to its effect by id, extensions lifted, the case closed |
| Buyer's contested case | the buyer's filing, contested | the topology policy's ruling: an authority stop `returned` with its reversal of any earnings since the ruled end, and a reversal |

A ruled `delivery_end` with no `stop` on a rate deal leaves the deal listed `ending` with
its payment running; that is the authority's to correct, since SCM sends no money
operation of its own, and the storefront runbook names it. A future-dated ruled delivery
end is not added to the double, since the producer documents none.

Rejected: switching on from SCM's evidence alone with a narrowed caveat; a mediator hook;
leaving the double to convergence with integration-level evidence only; and SCM stopping
the part itself after a ruled end, which reverses the rule that money decisions are the
authorities'.

### D7 — The delivery deadline comes from the seller's payments clause, as a stopgap

The production example and the seller quickstart set `delivery_deadline_seconds` in the
payments clause and a `dispute_window_seconds` covering it plus the authority's minimum
filing window, which publication refuses otherwise. Every VM option therefore promises a
deadline and the default buyer accepts it without a waiver. The storefront enforces it;
the site does not, so the storefront runbooks keep truncating a lease abandoned before
delivery and monitoring committed reservations still unactivated past their deadline.
`renewable-compute-lease-deadlines` retires the stopgap when the pool's tag supplies the
deadline and the site enforces it.

Rejected: shipping no deadline, which requires `--allow-no-delivery-deadline` from every
buyer; and waiting for `renewable-compute-lease-deadlines`, whose prerequisite is still
in design.

### D8 — The requirements land in test-compatibility and deployment-state

`test-compatibility` admits the live verification form beside the complete external
form, states the topology requirements in prose, the six live scenarios and the two lane
rows, and lets the mediation double execute `stop` and `penalty`. `deployment-state`
gains the VM chart's production example. `settlement-configuration`'s requirements are
unchanged — withdrawal is already a scenario there — and only its companion is corrected.

### D9 — Live evidence is the caller's sanitized summary in the change

The party running the live scenarios records a sanitized summary in
`docs/attachments/switch-on-hosted-per-period-vm/`: per observation, made, failed or
unproven, with public-safe provenance — source revision, target alias, authority
revision identifiers, provisioning mode. Raw logs and records stay in the caller's
storage. The summary states whether D3's threshold is met — the five required
observations made — and names any unproven observation with the requirement it lacked.
The closeout documentation cites that summary.

### D10 — What sellers and buyers are told

The seller quickstart states how to offer on-demand and spot: the recurring clause, the
declaration with no setup charge, the clause deadline and its dispute window, withdrawal,
and payout timing — at the earliest the part's stop plus the dispute window plus the
payments service's payout delay, 7 days in live mode by that service's documentation.
The buyer quickstart states the on-demand and spot options, the default refusals and
their waivers, that approval is refused when the balance cannot cover the first
reservation, that a top-up before the funded boundary keeps a deal running while after
it the buyer opens a new deal, that the premature-stop penalty is collectible only from
the seller's earnings still held, and that the dispute remedy is a case.

### D11 — The dispute authority's procedures stay with the authority

How the dispute authority dismisses and rules cases, its advisory time to rule and its
continuity are the authority's published policy and procedures, kept with it. SCM's
documentation states what SCM relies on — each environment's payments receipt key stays
stable for a deal's life, and a key change is a drained cutover — and links the
authority's policy where it is published. SCM's operator handbook keeps the storefront
operator's runbooks: truncating an abandoned lease, monitoring committed reservations
past their deadline, draining running deals before a receipt key change, and what a
seller operator sees for each dispute outcome, the `ending` codes included.

Rejected: hosting the authority's policy and operator procedures in this repository,
which places a producer's operating procedure in a consumer and leaves it to go stale
against a private API.

### D12 — Implementation cadence

Two rounds, split by internal and live verification.

- **Round 1, internal:** the mediation double's `stop` and `penalty` with its suite cases;
  the two VM lane rows on rate deals, with the shared output assertions the live
  scenarios reuse; the VM chart's production example, its render test and its
  publication check (18 F2); the
  convergence index row and Goal 8 gap edits. Two sessions: the double, then the lane
  rows and example. Its review includes the full internal end-to-end results.
- **Round 2, live verification:** `LaneTime.reach`'s wall-time case; the six live
  scenarios; their topology requirements in `e2e-tests/README.md`; the seller and buyer
  quickstart sections and the storefront runbooks. One session per slice as planning
  finds them. The round then waits for the deployment to run the live scenarios and
  record their evidence (D3, D9) before pre-closeout.

### D13 — Topology requirements start as prose

Each live scenario's requirements are prose beside its description in
`e2e-tests/README.md`: what it proves, its provisioning mode, the authorities and modes
it needs, its accounts and starting balances, any ruling policy, the settings it reads,
and the cleanup and balance reset its caller owes between runs. A coordinator agent
reads them with judgement, so their form is not constrained; structure and code that
interprets it come later, from patterns found across tests. The requirements name no
infrastructure. A mode earns its own scenario only where it makes the external party run
different code, so the payout delay's live and test values do not.

Rejected: a schema-checked requirements file, and markers exported by a command, both
premature before patterns across tests are known.

### D14 — No pre-written fallback

The design records no fallback for a failed live comparison. A failure is the producer
emitting something other than its documented output, reported to the producer; the
change returns to design with the evidence, and the owner then chooses between waiting,
a reduced declaration, or another course.

Rejected: a `[charged]`-alone contingency with two buyer waivers on every deal and a
charged term end billing past the agreed maximum, prescribed before any failure.

## Implementation notes

Reasoning and producer facts behind the implementation, moved here from the task notes
at closeout so the notes keep only behaviour, evidence and destinations.

### Section 1 — the mediation double

One admission check, `rules.check_ruling`, serves both rule installation and operator
decisions; before this change `decide` checked no effect, so a decision carrying a
`stop` would have been recorded and then failed building a reverse from it.

Each effect's payment events are built once, kept in `Case.events` and resent unchanged
until applied, so a lost answer or a later event's failure resends the identical
request. Payments refuses a past `at` (`invalid_event`) and never backdates a stop, so
a stop whose time has passed is sent as a stop now. That makes a kept stop with a
passed `at` refused on every resend, which would leave the case applying for good; the
events are therefore rebuilt on resume, but only when payments refuses an effect's
first event that no earlier send can have delivered (`Case.reached`). Rebuilding on any
refusal was wrong after a lost answer, because a middleware refusal comes before
payments' replay.

A `penalty` reads the snapshot once every earlier effect is applied and reverses each
part's `held` (earned and unreleased; a rate part's `reserved` is not held), in mandate
order, so a reversal placed before it leaves the penalty only what remains. The split
over parts is the pure function `penalty_reversals`, unit tested, with one integration
case left. A penalty's reversals are kept once one is taken; if money is released from
an unprotected part between a failure and the resume, a kept reversal can exceed what
is held and be refused on every resend. No lane row meets this; it is an unowned row in
Goal 8 of the roadmap.

The lane mandate's authority entry is `chosen` with no notice (`kit/deal-lifecycle`'s
`authorities.py`), so a ruled stop at the ruling's instant takes effect at once. The
double first computed no reversal beside a passed stop and recorded that as a
deviation; section 12 replaced it.

`scripts/change-workflow run test-before` cannot show these packages' new tests
failing at a base: it runs pytest with no project environment, so the double's tests
fail at collection importing `lane_double_controls`, and `e2e-tests`' at importing
`web3`. This held for every section that added tests.

### Section 2 — the shared payment assertions

The plan's separate read and assert stages are two functions, not two stage classes:
separate classes would change every module's stage order, bare metal's included. The
shared stages keep reading as before and call the assertion, and since a compute lane's
shared stage has one body, the bare-metal rows assert through them too. A funding
stop's treatment is ignored because it falls between periods. The unit tests run on
snapshots from the payments kit's `PaymentsAuthority` engine driven through each row's
input, not on a committed recording. `Recurring08` used to assert one period's price
held and released outright; the shared assertion checks settled amount against the
periods between start and stop, so the exact one period now rests on the stage setting
the stop a minute into the first period and on `Recurring09`'s balance. A live run
supplies each assertion the payer or payee account, the period price and seconds, the
notice, for funds running out the funded boundary and the funded period count, and for
the term end the Agreement's end rounded up to the whole second.

### Section 3 — the rate-deal dispute rows

The administrator's end goes through the storefront client's `admin_interrupt_deal`
with `interruption_kind="failure"`, since the seller lifecycle client offers only
`notice`, `read` and `list`; that route records the operator end, files `delivery_end`
as the payee and begins the teardown, answering the filing's outcome inline. Because the
double rules at filing and the end is at the filing's instant, the seller row holds its
rule at the gate (`pause_before_effects`) while lane time moves a period on, so there
are real earnings since the end; the hosted authority rules later than the filing
anyway, so the live twin needs no gate. The storefront's recorded end is then the
ruling's delivery end at the operator's instant, a `dispute-effect:` source sorting
before the `operator:` one at the same instant. No route reads the classification
`ruling` itself; its observable effect is that no filing follows the authority's stop.

The dispute assertions' unit tests use payment events written as the double's
`service.py` sends them and record entries validated by the mediation kit's
`RecordEntry` model, not a committed recording, which the filed entry's whole Agreement
makes too large. Round 1's triage (28 F1) bound both assertions to the claim the
scenario sent (`claimed_end`), since a ruling consistent with itself on another end
passed before; the contested case compares the ruled end and reverse amount only when
given, because a live topology's policy chooses both. The lane double records
`end_delivery` at its own clock, which equals the claim only because lane time is held
at the claimed instant from filing to ruling. Declined at the check: a domain-stage
order check, which the rate rows' domain stages lack too; and a `RateRow` of the rows'
own, since the borrowed one carries what they need.

### Section 4 — the production example

The example is the values of the storefront chart installed alone, as the bare-metal
example is of its chart, so it states `global.provisioning` and names its registry. The
chart's own checks do not validate a principal's spelling; only the storefront's loader
does (it caught a receipt identity no Ed25519 key can spell), so a placeholder change
wants `STOREFRONT_PYTHON` set. The loader keeps a portless `base_url` raw and warns, so
the example states the port. The publication probe states its wiring as the VM
storefront's `publication_artifacts` does rather than taking it from the composition,
so the two could drift without the check failing; readiness of a reachable service is
not run, since the render check has no service.

### Section 5 — wall-time reach and the live payment scenarios

The live modules were first planned to rehearse against the local Helm release, which
cannot serve them: its payments target is its double marked lane-owned
(`helm/local-values.yaml`), which the live modules refuse by design; its agent declares
no rate servicing, so publication refuses every recurring option; and serving them
would need values changes outside the plan and a deployment the implementation step
does not admit. Section 8's deployment run is therefore the only run of the live
modules.

The modules take their prerequisites as module fixtures set up before any hold
(`payments_config`, `live_provenance`, `mock_provisioning`, the payer's balance), so a
topology missing a requirement is a blocked skip naming it before anything is bought;
`LIVE_GATES` in `test_scenario_cleanup_order.py` holds that order. That check maps a
fixture by its function's name, so a fixture declared with `name=` reads as unknown and
so as having a finaliser. The run settings refuse only what the harness can see wrong;
the market refuses the other terms no deal can hold at publication or negotiation.

Funds running out reads the boundary from the part's `reservedThrough`, because the
payments engine's snapshot sets `fundedThrough` only over parts still running; a
finding about a stale funded boundary was declined for that reason. Also declined:
unifying `HOURLY_GROSS`'s third definition, the one-shot option's price, a separate
offering. A run's wall-time length is set by the `LIVE` terms: at a one-minute period
the term must exceed the five-minute approval window, the five-minute delivery deadline
and a period, so about a quarter of an hour serves.

The sections 5–7 triage (41 F1) found the buyer's stop could pass with nothing charged:
the payments kit's contract fixture charges nothing for a `charged` stop with no time
elapsed, as the archived serve-running-rate-deals design records, and the live stage
sent the stop as soon as the earlier stages ended. The assertion now also requires the
stop effective later than the part's `started`, and `LiveBuyerStop` sends the stop no
earlier than `STOP_INTO_PERIOD_SECONDS` after the Agreement's start, an instant the
scenario's own data fixes.

### Section 6 — the live dispute scenarios

The seller's filing reads the snapshot once after the record shows the case closed,
rather than polling both, since the closed entry records each effect applied at
payments; a lagging snapshot fails naming the field. `LiveDispute07`'s wait for the
first period's earnings is a bounded poll of the producer's output, not a reached
instant, so `LaneTime.reach`'s recorded case is not widened. `lane_time.poll_until`
raises `PollBoundPassed`, an `AssertionError` carrying the last read, and that is all
`await_case_closed` catches, so an assertion raised inside a read is not taken for an
unmet ruling policy. An Agreement naming no dispute terms fails rather than reading as
another authority. The contest is one servicing step, so a respondent listing that
shows the case only later fails the contest.

When no policy rules the contested case, the cleanup ends the deal by the buyer's own
`end` with the case open; if the hosted payments service refuses that stop, the last
stage's teardown fails and the ruling reads failed rather than unproven. Nothing here
shows which the payments service does.

A missing storefront dispute credential was first thought unreadable before a filing,
so the contest failed rather than going unproven. The sections 5–7 triage (41 F2)
corrected the premise: the seller lifecycle reports the missing credential on every
lifecycle read of the deal (`kit/deal-servicing`'s `seller.py`, `_observed`), so the
contest reads it first and skips naming `CREDENTIAL_REQUIREMENT`. That the hosted
storefront's read carries the outcome rests on that code; no run here removes the
credential.

### Section 7 — the seller, buyer and operator documents

The quickstart's TOML is held equal to the production example's `rate_servicing` and
`pricing` by a render test, so it must stay the section's only TOML block, with the
`<YOUR_PAYEE_ACCOUNT>` placeholder. The buyer's default refusals are only logged
(`BuyerTermsPolicy.__call__` reports them to `AuthoritySelection.report` and they never
reach its `refusals`), so a buy they alone empty prints "No listings matched" and exits
0, an unowned row in Goal 8 of the roadmap. Running the installed `market` and
`market-storefront` was not permitted in the implementing session, so commands, flags
and routes were checked against the CLI source and route tables. The handbook links no
published dispute policy, since this repository knows no published location, and points
at an `arkhai.mediation.v1` authority description's `contact`. Declined at the check:
the payments service's own facts in the quickstarts rest on this design's context, not
on code here; and how a refused approval (`insufficient_funds`) surfaces to the buyer
was not traced, the quickstart saying only that nothing is bought.

### Section 12 — the mechanical ruling's shape

A live rehearsal found the hosted authority rules a seller's filing with a delivery
end, a `stop` and the `penalty`, reversing earnings since a passed stop time as the
stop's own reversal, attributed to it. The double now derives that reversal once in
`stop_reversal_amount`, from the signed receipt's period and price and the part's
`started`, gross earned and held, kept under `<effect id>:since`; earnings an earlier
reversal took are not told apart. The guard on a stop payments has not recorded has no
test, since the double's `chosen` entry takes every stop at once and no lane input
reaches it. The assertions now match each reversal to the ruling's effect whose id its
payload names, rather than by order, so an effect's reversals may be several and a
reversal naming no effect is never taken for a missing stop's.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| D1 — the switch-on is a documented, supported seller configuration; withdrawal removes the declaration | `docs/seller-quickstart.md#offering-on-demand-and-spot` and `helm/charts/storefront/examples/production-values.yaml` (implementation); `openspec/specs/settlement-configuration/configuration.md#settlement-consumer-configuration-and-cutover` (the production example's declaration, and the hosted-qualification caveat replaced by the live summary's findings); `openspec/specs/deal-lifecycle/architecture.md#external-authorities` (the `chosen` stop and the live comparison) and `#current-limits` (rate deals against deployed authorities); `docs/development/ROADMAP.md`, Goal 8's current state |
| D2 — no release step; a change cuts no release and declares nothing in production | `docs/guidance/workflow/changes.md#a-change-cuts-no-release` |
| D3 — live verification names topology requirements, not a target; an unmet requirement leaves observations unproven | `docs/guidance/engineering/system-tests.md#locally-verifiable-and-external-topology-scenarios`; `docs/development/TESTING.md#live-verification`; `openspec/specs/test-compatibility/spec.md`, "Each live verification scenario states its topology requirements" (archive) |
| D4 — the live scenarios extend the lane rows, with the provisioning their claim needs; `LaneTime.reach`'s wall-time case | `system-tests.md#locally-verifiable-and-external-topology-scenarios` (modes follow what a scenario proves) and `#time-a-test-does-not-control` (an instant the scenario's data fixes or a component recorded); `openspec/specs/test-compatibility/architecture.md#lane-time-and-the-doubles-controls`; `docs/guidance/repository/deal-scenarios.md#the-discipline-every-scenario-follows` (the wall-time bullet); `docs/development/TESTING.md#lane-time` |
| D5 — SCM's dispute interface ends where the public client ends; a person's decision comes from a topology policy or the test | `docs/guidance/engineering/test-doubles.md#a-double-mirrors-its-producer`; `docs/development/ARCHITECTURE.md#authority-boundaries` (the dispute authority's row); `system-tests.md#locally-verifiable-and-external-topology-scenarios` (a policy watcher is a double for a person) |
| D6 — ruling-downstream logic proven on amended doubles; live scenarios compare outputs through a shared assertion | `system-tests.md#locally-verifiable-and-external-topology-scenarios` (the live verification form) and `#a-scenario-is-a-sequence-of-state-changes` (bounded polling of a live producer); `test-doubles.md#a-double-mirrors-its-producer` (polled and inbound decisions); `test-compatibility/architecture.md#the-in-lane-mediation-double` (`stop`, its reversal, `penalty`) and `#payment-evidence-ownership` (live evidence as boundary comparisons); `TESTING.md#the-canonical-compute-deal` (the rate-deal dispute rows, the shared assertions), `#private-service-dependencies` (the double's effects) and `#lane-time` (the bounded poll); `deal-scenarios.md#the-discipline-every-scenario-follows`; `tools/mediation-lane-double/README.md` and `e2e-tests/README.md` (implementation); `openspec/specs/test-compatibility/spec.md` (archive) |
| D7 — the delivery deadline from the seller's payments clause, enforced by the storefront | `settlement-configuration/configuration.md#settlement-consumer-configuration-and-cutover`; `docs/seller-quickstart.md#offering-on-demand-and-spot` and `docs/operator-handbook.md#serving-rate-deals` (implementation); the roadmap's open gap owned by `renewable-compute-lease-deadlines` |
| D8 — the requirements land in `test-compatibility` and `deployment-state` | `openspec/specs/test-compatibility/spec.md` and `openspec/specs/deployment-state/spec.md` (archive); `docs/guidance/repository/chart-render-tests.md#where-they-live-and-how-they-run` (the production example's startup and publication checks); `deployment-state/configuration.md` has no production-examples passage, so nothing is written there |
| D9 — live evidence is the caller's sanitized summary | `docs/attachments/switch-on-hosted-per-period-vm/live-verification.md` (section 8); cited by `ROADMAP.md` Goal 8, `settlement-configuration/configuration.md` and `deal-lifecycle/architecture.md`; the form in `system-tests.md` and `TESTING.md#live-verification` |
| D10 — what sellers and buyers are told | `docs/seller-quickstart.md#offering-on-demand-and-spot`; `docs/buyer-quickstart.md#7-on-demand-and-spot` (implementation) |
| D11 — the dispute authority's procedures stay with the authority; SCM's assumptions and runbooks | `docs/operator-handbook.md#serving-rate-deals` (implementation); `deal-lifecycle/architecture.md#current-limits` (receipt key stability, the drained cutover, the authority's policy its own); `ROADMAP.md` Goal 8's accepted limitations |
| D12 — implementation cadence | No permanent destination: it governed this change's rounds only |
| D13 — topology requirements start as prose; a mode earns its own scenario only where the external party runs different code | `system-tests.md#locally-verifiable-and-external-topology-scenarios`; `TESTING.md#live-verification` (the requirements in `e2e-tests/README.md`, "Live verification") |
| D14 — no pre-written fallback | No permanent destination: it decided this change's handling of a failed live comparison, which did not arise |
| Owner's principle (2026-11-20): every umbrella component can be switched off | `docs/guidance/engineering/helm.md#every-component-of-an-umbrella-chart-can-be-switched-off` |
| Owner's principle (2026-11-20): a wrapper on the shared loader starts a third-party process that reads no configuration file | `docs/guidance/engineering/configuration.md#application-settings-stay-out-of-the-environment` |
| Owner's principle (2026-11-20, revised 2026-11-23): where a stack's secret values come from | `configuration.md#secrets-travel-in-a-secret-profile-or-overlay-file` |
| Owner's principle (2026-11-21): degraded service, exit and native sidecars | `docs/guidance/engineering/deployment.md#a-deployment-does-not-wait-on-a-services-dependencies`, with the next section aligned |
| Owner's principle (2026-11-23): a stack's secret files are committed development values or a gitignored copy of a committed `.example`; a chart's defaults carry no secret value | `configuration.md#a-stacks-configuration-lives-in-committed-files`; `helm.md#a-charts-defaults-carry-no-secret-value`; `docs/guidance/engineering/kubernetes.md#configuration-travels-through-mounted-files` (the local cluster's Helm-layer target) |
| Roadmap currency | `docs/development/ROADMAP.md#goal-8--sell-compute-by-the-period-until-either-party-stops`: this change's open-gap row removed; the VM switch-on, the double's `stop` and `penalty`, the VM rate-deal dispute rows and the live verification absorbed into the current state, citing the summary; the hosted-mediation sentences corrected from the summary; the accepted limitations' dispute-policy sentence aligned with D11; the unproven buyer's contested case added to "Work this goal found and leaves unowned" |
| Campaign index currency | `openspec/changes/README.md`, Goal 8: this change's row, the campaign prose recording the live summary's outcome, and the graph annotation; two unowned rows under "Unowned work with no campaign" found at promotion |

## Open Questions

- Whether the payments service will distinguish funds running out from a term end in
  the signed stop cause, which would let the storefront drop its comparison with the
  Agreement's end. Revisit when the payments contract publishes such a cause.
- How the payments service will announce a receipt key rotation, which decides whether
  the drain runbook can be triggered by notice rather than operator coordination.
  Revisit when the payments service publishes a rotation mechanism.
- When a topology applies a ruling policy. Until then the buyer's contested case is
  unproven at live verification, and the change may close out with it so, the gap then
  recorded in Goal 8. Revisit when the payments service's repository offers a policy
  watcher.
