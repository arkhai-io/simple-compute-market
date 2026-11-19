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
`chosen` entry with the ruling's treatment, and its `penalty`, as reversals of earned
amounts still held across parts in mandate order, capped at what is held — executing
effects the contract defines, while which effects a ruling carries stays the scenario's
programmed rule. `award` stays refused. The VM lane gains two rows on rate deals: a
seller's filing ruled as the producer documents a mechanical ruling, and a buyer's
filing the storefront contests, ruled by an operator decision; each shows the authority's
stop recorded and classified `ruling`, the payer's returns, the teardown and, once the
case closes, the deal listed `ended`. This takes the double's `stop` from
`converge-ongoing-compute-leases`, whose index row and Goal 8 gap keep `penalty`'s use in
its own rows.

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
| Seller's filing | the storefront's payee filing | each part protected; an authority stop `returned`, a reversal since the end, the capped penalty, extensions lifted, the case closed |
| Buyer's contested case | the buyer's filing, contested | the topology policy's ruling: an authority stop `returned` and a reversal |

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
