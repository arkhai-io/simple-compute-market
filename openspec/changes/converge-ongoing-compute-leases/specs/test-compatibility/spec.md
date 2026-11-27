## RENAMED Requirements

- FROM: `### Requirement: A dispute on a running rate deal is qualified in the VM lane`
- TO: `### Requirement: A dispute on a running rate deal is qualified in both compute lanes`

## MODIFIED Requirements

### Requirement: Scenarios hold shared services for the whole module

Every end-to-end scenario module a compute pipeline lane selects MUST hold, for the whole
module, its lane's storefront lifecycle loops, provisioning's fulfillment convergence,
its lease watchdog, its event delivery and its capacity-reservation watchdog; a module
the VM lane selects MUST also hold Alice's storefront loops and Alice's provisioning
timers. A lane's selection is its marker expression, not its directory; a module no lane
selects is outside this rule, and so is a module under `scenarios/core/`, which reaches
only the dev chain and messages no storefront or provisioning service. Each hold MUST be the
lane's hold fixture, built on one shared helper per pause kind, taken before the module's
first stage, waiting until each held loop reports itself paused at its gate, and released
in a finaliser whatever the module's outcome, after the module's other cleanup. A stage
MUST assert a hold and MUST NOT pause or resume a service itself. A stage that needs a
site's report or release to reach its storefront MUST step event delivery, not wait for
it. Source checks MUST refuse a scenario or stage that calls a pause route directly, and
a module this rule covers whose resolved fixtures lack one of its lane's holds. Every
lane that holds MUST use the same mechanism.

#### Scenario: A deal scenario fails part-way

- **WHEN** a VM or bare-metal deal scenario fails in a stage after its storefront's loops
  and the lease watchdog were held
- **THEN** both are resumed when the module ends, and the next module finds them running

#### Scenario: The Helm deal test passes

- **WHEN** the in-cluster deal test completes against a persistent Helm release
- **THEN** the seller storefront's lifecycle loops report running afterwards

#### Scenario: A stage pauses a service

- **WHEN** a scenario module or stage calls a storefront or provisioning pause route
  directly
- **THEN** the source check fails, naming the call

#### Scenario: A compute-lane module omits a hold

- **WHEN** the resolved fixtures of a scenario module a compute pipeline lane selects,
  outside `scenarios/core/`, lack its lane's storefront, fulfillment-convergence,
  lease-watchdog, event-delivery or capacity-reservation-watchdog hold, or a module the
  VM lane selects lacks Alice's storefront or provisioning holds
- **THEN** the source check fails, naming the module and the missing hold

#### Scenario: A release reaches the storefront by a step

- **WHEN** a stage ends a lease at the site and then reads the storefront's release
- **THEN** it steps one event-delivery cycle between the two, and the release is read once

#### Scenario: A module no lane selects

- **WHEN** a scenario module in a compute lane's directory is selected by no pipeline
  lane, such as one run by hand against a real host
- **THEN** the hold check does not require its lane's holds of it

#### Scenario: A lane selects a module outside its directory

- **WHEN** a compute lane's marker expression selects a scenario module outside the lane's
  directory
- **THEN** the hold check requires the lane's holds of it, unless it is a chain-only module
  under `scenarios/core/`, such as the Alkahest escrow codec module the VM lane selects

### Requirement: A dispute on a running rate deal is qualified in both compute lanes

Each compute lane MUST run, each on its own rate deal under the lane's `[charged, returned]`
declaration and labelled lane-double evidence, a seller's `delivery_end` filing ruled as
the dispute authority documents a mechanical ruling — a `stop` with `returned`, whose
reversal of the earnings since the end follows it, and a penalty, with no reverse of its
own — and a buyer's filing the storefront contests, ruled by an operator decision with a
`stop` with `returned` and a reverse. Each MUST show
the storefront recording the authority's stop as an end classified `ruling` with no
filing, the payer's returns, the teardown, and, once the case closes, the seller's list
reading the deal `ended` with no open extension.

#### Scenario: A seller's filing on a rate deal is ruled

- **WHEN** the storefront's administrator ends a running on-demand deal and the double's
  rule rules the payee's filing with a stop and a penalty
- **THEN** the storefront records the authority's stop classified `ruling` with no
  further filing, the payer is returned the unstarted remainder and the reversed and
  penalised earnings, and after the case closes the seller's list reads the deal `ended`

#### Scenario: A buyer's contested case on a rate deal is ruled

- **WHEN** the buyer files on a rate deal, the storefront contests, and an operator
  decision rules a stop with `returned` and a reverse
- **THEN** the storefront records the ruled end, the payer is returned what the ruling
  reverses, and after the case closes the seller's list reads the deal `ended`

#### Scenario: The bare-metal lane rules both

- **WHEN** the bare-metal lane runs the seller's filing and the buyer's contested case on
  whole-host rate deals
- **THEN** each shows what the VM lane's shows, through the bare-metal storefront's
  administrator end, the bare-metal buyer's commands and its teardown

### Requirement: Rate deals and dispute filings are verified live against a prepared topology

The VM live verification scenarios MUST each extend their lane twin in the live
verification form, on a deal of their own, with mock provisioning, against Arkhai
payments in test mode and, where they file, a hosted mediation authority:

- the buyer's stop: a payer stop is recorded with cause `payer` and `charged`, and the
  started period is charged;
- funds running out: with the balance the topology funds for N periods, a `terms` stop
  falls at the funded boundary with N periods settled;
- a spot preemption: a payee stop with notice is pending, then final at the authority's
  receipt plus the notice, with `returned` and the unstarted remainder refunded;
- the term end: the part ends at the Agreement's end with `returned`;
- a seller's filing: the storefront's own `delivery_end` filing as the payee is accepted
  with each part protected, and the authority's ruling is read — an authority stop with
  `returned` and its reversal of any earnings since the end, the capped penalty, each
  reversal attributed to its effect by the id its payload names, its extensions lifted
  and the case closed;
- a buyer's contested case: the buyer's filing is contested by the storefront, and the
  ruling the topology's declared policy makes — an authority stop with `returned`, with
  its reversal of any earnings since the ruled end, and a reversal — is read;
- a revision: after the seller's filing is ruled and closed, the storefront records an
  earlier seller failure and files the payee's revision, and the authority's ruling is
  read — basis `payee_filed`, a delivery end at the earlier instant, a stop whose
  reversal covers only the earnings between the two ends, no second penalty, its
  extensions lifted and the case closed — compared with row 3's lane twin through one
  shared assertion. Its topology MUST provide a dispute authority whose advertisement,
  read through the mediation client, rules a payee's revision mechanically; without it
  the observation is unproven, naming that requirement.

Each MUST be labelled live evidence with public-safe provenance. The revision's evidence
MUST be supplied by the coordinator that deploys the change and the dispute authority
and runs the scenario, as a sanitized summary naming no host, project or path, each
observation made, failed or unproven.

#### Scenario: Funds run out on a live target

- **WHEN** the funds-exhausted scenario runs against a topology that funded its payer for
  N periods
- **THEN** it reads the funded boundary from the signed snapshot, polls until the part's
  stop, and compares the stop's cause, instant and settled amount with its lane twin's
  assertion

#### Scenario: The seller's filing is ruled live

- **WHEN** the seller-filing scenario's storefront files as the payee on a running rate deal
- **THEN** it reads the authority's ruled entry and the payment snapshot through the public
  clients and compares the stop and its reversal, the penalty and the closed case with
  its lane twin's assertion

#### Scenario: A revision is ruled live

- **WHEN** the revision scenario's storefront files the payee's revision against an
  authority advertising mechanical revisions
- **THEN** it reads the authority's ruled entry and the payment snapshot through the
  public clients and compares the basis, the delivery end, the stop's reversal, the
  absence of a second penalty and the closed case with row 3's lane twin's assertion

#### Scenario: The authority does not rule revisions

- **WHEN** the revision scenario runs against a dispute authority whose advertisement does
  not name mechanical revisions
- **THEN** the revision observation is unproven, naming the requirement, and is never
  reported made

## ADDED Requirements

### Requirement: The remaining rate rows are qualified on lane time

The compute lanes MUST run, each row on its own deal, under the shipped presets with a
default buyer and the lane's `[charged, returned]` declaration, with every lane timer
held, ruling programmed at the mediation double from the producer's published traces,
and labelled lane-double evidence:

- in both compute lanes: the buyer's end while the payment authority is unreachable,
  its stop journaled and retried under one key, its `end_delivery` receipt kept and its
  `delivery_end(cause=payer)` filed with it, billing running until the stop lands; the
  site's end of a lease the storefront has not heard of, the site's report held by
  event delivery while the buyer's `market end` files its case, then delivered, the
  storefront's payee revision ruled mechanically and netted, and the release proven
  apart; the buyer's earlier stop during a spot notice; the on-demand notice refused at
  `deals preempt`, naming `delivery_end`; a seller that never files, its storefront's
  loops held throughout, the buyer's stop and its case filed through the harness's
  dispute adapter being the whole remedy; and a contested case in which the storefront's
  `available` record and the buyer's watchdog observation both reach the case record;
- in the VM lane: a lost filing answer and a held ruling's resend on a rate deal, and
  earlier evidence after a filed end revised as the producer's trace rules it; an
  undelivered rate deal past its delivery deadline, filed at the Agreement's start and
  its return ruled; both orders of an activated deal never available; a late start and
  an end inside a period at the maximum term; a spot seller's emergency filing and the
  ends of the penalty's cap; and a case over a rate part already paid out, the filing
  accepted with the part `not_held` and no money moved.

A row that needs a setup part MUST run on a lane option whose clause prices a setup
amount, its lane storefront declaring `setup = true` in its lane configuration only: the
baseline's setup variant, the setup returned when a deal is never delivered or never
available, and the cap's end where the setup charge alone is held.

#### Scenario: The site's report arrives after the buyer's case

- **GIVEN** a delivered rate deal, its storefront's loops and event delivery held
- **WHEN** the site terminates the lease, the buyer runs `market end`, the scenario steps
  one event-delivery cycle and then `deal-servicing`
- **THEN** the buyer's `delivery_end(cause=payer)` case is filed with the storefront's
  concurrence, the storefront records the site's earlier end and files the payee's
  `delivery_end` for it as a new case, and the programmed revision ruling returns only
  the earnings between the two ends with no second penalty

#### Scenario: The seller never files

- **GIVEN** a delivered rate deal whose storefront's loops stay held for the whole row
- **WHEN** the buyer stops at the payments double and files its case through the
  harness's dispute adapter, and an operator ruling is programmed
- **THEN** the payer is returned what the ruling reverses, and neither double records any
  event from the storefront

#### Scenario: A setup charge is returned for a deal never delivered

- **GIVEN** an on-demand deal on the lane's setup-priced option whose delivery deadline
  passes undelivered
- **WHEN** the scenario sets lane time past the deadline, steps `deal-servicing` and the
  programmed ruling is applied
- **THEN** the storefront's filing says `delivered: false`, and the payer is returned the
  setup charge with the rate's earnings
