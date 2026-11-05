# Design

## Context

The runbook owes six observations before real-provisioning offers open to general
buyers (`docs/development/VALIDATION_RUNBOOK.md#observations-the-qualification-owes`).
This change makes observations 2, 4, 5 and 6 as scenarios. Observation 1 is the relay
operator's probe (§28), and observation 3 needs an operator-routable test path a
relay-only deployment lacks; both stay outside it.

Facts the decisions rest on:

- **The real-provisioning modules settle on Alkahest.** Both
  `test_real_provisioning_deal.py` modules deal through the typed driver and the dev
  chain. By §29's terms they make none of these observations.
- **The shared compute stages are Alkahest-coupled after fulfillment.** `Stage09b`,
  `09c`, `10a` and `11b` in `compute_deal_stages.py` require `real_escrow_uid`. VM's
  second deal (09g–09m) is an Alkahest deal driven through typed clients.
- **No payment scenario runs locally.** Without a payments target every payment
  scenario is a blocked skip (`helpers/payments.py:configured_payments`). Only
  `test_bare_metal_payment_deal.py` buys through the shipped buyer CLI;
  `test_vm_payment_deal.py` negotiates, approves and commits through typed clients.
- **The payments kit reads transactions, not accounts.** `PaymentsClient` exposes
  approve, transaction snapshots, attachments, events and reverse. The payments service
  also serves the payer's own balance, which the kit does not call. No route lists an
  account's debits.
- **The consumed-UID history is already readable.** The bare-metal working-data
  operator route's `policy` operation returns the host ledger's consumed UIDs.
- **No operator notification exists.** A cleanup refusal is visible only as the reclaim
  job's error, retry fields and log, and as the lease held at `releasing`.
- **An unanswered dispute authority does not stall servicing.** `MediationAdapter._read`
  turns a transport failure into a non-`Accepted` view, and `DealWatch` records it and
  continues; the hosted VM payment scenario already services a deal whose authority
  read is not `Accepted`.

## Goals / Non-Goals

**Goals:**

- Locally verifiable buyer purchases through the shipped buyer in `arkhai.payments.v1`
  in the VM and bare-metal lanes, and external-topology scenarios that extend them to
  make observations 2, 4, 5 and 6 against a configured real-provisioning target and
  payments target.
- The reads those observations need, with a preference for this repository's typed
  clients.
- The configuration a deployment supplies to run them.

**Non-Goals:**

- Funding the buyer or proving the funding: topology.
- Deploying anything, or naming any deployment.
- Observations 1 and 3, and GPU work.
- A default pipeline lane for the external scenarios.
- Changing payment or provisioning behaviour.
- A format for externally supplied evidence.

## Decisions

### D1. External-topology scenarios minimally extend locally verifiable ones

End-to-end scenarios come in two kinds. A locally verifiable scenario runs against this
repository's own Compose or Helm stack, with provisioning in its mock profile and the
payments service replaced by an in-lane double. An external-topology scenario needs
services or hosts from elsewhere: a hosted payments target, real hosts.

An external-topology scenario minimally extends a locally verifiable one. It shares that
scenario's stages wherever possible and adds only what the external parts bring. Setup
or teardown needing knowledge this repository lacks, such as funding buyer accounts at a
payment provider's sandbox, is topology and is left to the deployment.

So the work is:

- **A shared buyer-purchase stage set**, defined once like `compute_deal_stages.py`:
  hold the loops, discover through the CLI, buy through `market buy` or
  `market bare-metal buy` (approval, receipt), converge to active, correlate, end the
  lease, release, capacity restored. It has its own source check, as
  `test_compute_deal_stages.py` is for the Alkahest set.
- **Locally verifiable scenarios** in the VM and bare-metal lanes that run it against
  mock provisioning and the payments double.
- **Three external-topology modules** that subclass the same stages and add the
  real-host observations:
  - observation 2: two concurrent VM purchases;
  - observations 4 then 5: the normal cycle, then the successor and refusal cycle, in
    one module, because the successor needs the first cycle's consumed UID;
  - observation 6: needs both hosts, and runs after the others in a session.

  Each external module is marked in no lane and reports a blocked skip without the
  real-provisioning target and the payments target.

The operator-procedure method stays accepted beside the scenarios, which are the method
a candidate's qualification reaches for first.

**Rejected:**

- **A buyer-purchase mode inside the existing real modules.** It breaks the requirement
  that a real lane run every shared Alkahest stage, and it turns each module into two
  deals behind a switch.
- **Standalone qualification modules sharing only helpers.** They verify the payment path
  only externally.
- **Modules per domain.** They split observation 6 into two partial halves.

### D2. One listing offers every mechanism the stack composes

On the real target, the Alkahest real modules and the qualification modules share one
host, pool, resource and capacity source, and a capacity source backs one listing for
good.

- **VM:** both modules create or adopt that listing through one shared helper. Creation
  states a settlement for each mechanism the storefront reports ready.
- **Bare metal:** the published options already are the composed mechanisms.
- **Adoption** additionally requires the listing to offer the adopting module's own
  mechanism, and otherwise fails naming the listing and its options.

On a stack that composes one mechanism this is one listing with one option.

**Rejected:**

- **Separate stacks per mechanism.** It forbids running both kinds of module on one
  stack, and is the one-mechanism case of this rule anyway.
- **Publication-derived VM listings.** It is the largest change to the Alkahest module,
  and a later override still rebinds.
- **A second resource on the same host.** It sells the capacity twice.

### D3. Leases end by back-dating and a stepped watchdog cycle

**VM.** Observation 2's leases end by moving the agreed end into the past and stepping
one `check_leases` cycle with the watchdog held. That runs exactly the service code a
wall-clock expiry runs, and the end-to-end discipline steps deterministically, with no
sleeps or waits. The runbook's observation 2 is amended: both leases end through the
lease watchdog's expiry path, never through an early teardown or a buyer end. Lease
durations stay fixed constants.

**Bare metal.** Each lease ends through the buyer's ordinary `market bare-metal
teardown`, which starts the reclaim. That is a buyer end, not an expiry, which is what
observations 4 and 5 follow. §29 excludes only a forced release, a manual retry, or a
consumed-UID reset.

**Holds.** Every scenario holds its loops for the whole module, as the spec requires. The
VM buyer CLI polls its settlement while the stage steps convergence, as
`test_full_deal_buyer_cli.py` does.

**Rejected:**

- **Waiting out the agreed end in wall time.** It costs runtime and proves nothing the
  back-dated path does not.
- **Releasing the watchdog hold.** It needs a spec exception and races the timer.

### D4. Debits are assessed by a balance sum check

The scenarios use the payments kit's client:

- **Per transaction:** each is bound to its Agreement; the receipt is over that mandate;
  the snapshot names the configured payer and payee; its parts' gross equals the
  Agreement's price for its duration; after the ending the parts show what the ending
  implies.
- **Per account:** the kit gains the payer's own balance read, a route the payments
  service already serves. The scenario asserts that the drop in `available`, from before
  its first purchase to after its last approval, equals the sum of its own transactions'
  debits.

That sum check rests on a precondition: the buyer account is dedicated to the run, which
is a topology guarantee. The scenario cannot check it and states it alongside its result.

Funding and its proof are the deployment's, joined to the run by transaction IDs.

**Rejected:**

- **A payer-scoped debit listing at the payments service.** It would prove exclusivity,
  not just a sum, but needs a payments-service change and a new published schema. It is
  recorded as future work outside this repository.
- **Transaction-scoped attribution only.** It leaves the account level unexamined when a
  sum check costs one call.

### D5. The reads

Observability an observation needs is preferably added to this repository's typed
clients; this is a preference, not a rule.

**Process generations (observation 2): a host diagnostics VM operator job.**

- **Mechanism:** a new action beside `list` on the VM operator surface, backed by a
  `host-diagnostics` playbook in the VM IaC tree, reusing the list-VMs path: job
  submission, the shared fact reader, `JobWatch`, and the mock profile's default output
  rendered from the job's parameters.
- **What it reports:** boot ID, uptime, kernel, the count of running guests, and systemd
  facts (active state, invocation ID, main PID, restart count, active-enter time,
  result) for `libvirtd.service`, `frpc-buyers.service`, and an optional management unit.
- **The management unit:** passed as a job parameter checked against systemd unit-name
  syntax, from the target's optional `management_unit`. The management client is
  operator-owned, so this repository does not know its name.
- **Interface (settled by review 17 F3):** a submission and a typed parse, as every
  operator action is.
  - `diagnose_host(host_id, management_unit=None)` on the operator client returns a
    `JobSubmitResponse`, like `list_vms`, so the job ID stays visible for D8's logs.
  - The caller waits on the job with `JobWatch.until_succeeded`, the harness's watcher
    with its injected clock; the client gains no polling.
  - `HostDiagnostics.from_job_result(result)`, in the operator client package, turns a
    succeeded job's result into the typed facts, or raises a named error naming the
    missing or malformed field. No caller reads the raw fact.
  - Failures stay distinguishable: an unknown host or an invalid unit name is refused
    at submission as the route's error; a failed or cancelled job is `JobWatch`'s
    assertion, carrying the job's error and logs; a malformed fact is the parse's named
    error.
  - Rejected: a bounded submit-and-wait `diagnose_host`. It would be the only client
    operation that waits, duplicate `JobWatch`, and hide the job ID.
- **Pass criterion:**
  - the management unit keeps one invocation ID, stays active and adds no restarts
    across the before, during and after reads;
  - libvirtd adds no restarts and has no failed result, and keeps one invocation ID
    across the reads taken while the first guest runs. It is socket-activated and may
    exit when idle.
- **Without `management_unit`:** that stage skips, naming the field.

**Consumed-UID history (observation 6).** It is read through the existing
working-data operator route before and after the re-registration, and must be
unchanged. That route is independent of provisioning, whose reapplied registration is
under test.

**Observation 5's notification.** The runbook's observation 5 is amended: the actionable
operator notification is the reclaim job's recorded error and scheduled retry, read
through the operator's typed job API, which is also where it was observed. A pushed
operator notification is an unowned roadmap gap.

**Rejected:**

- **A specialised provisioning route for unit generations.** It is new mechanism where an
  existing one serves.
- **A test-side operator route for VM hosts.** It makes the observation depend on an
  optional deployment route and builds nothing for operators.
- **A provisioning read of the UID ledger.** It duplicates an independent read.
- **An operator event store with sinks.** That is a provisioning feature across
  provisioning, `kit/delivery` and its chart, and its own change.

### D6. Observation 4 checks no GPU

The bare-metal scenarios never check for a GPU. §29 already owes a paid purchase with
checked GPU work for each GPU offer, so observation 4's GPU clause is removed rather
than recorded as unproven on every run. The gate on GPU offers is unchanged.

A paid GPU purchase scenario is an unowned roadmap gap, to be verified in a later round.

**Rejected:**

- **Keeping observation 4's GPU clause, recorded as unproven on every run.**
- **Checking GPU work when the host has a GPU.** That contradicts this decision's scope.

### D7. Acceptance, the frozen candidate, and how evidence enters the change

**What closeout requires.** It sorts each outcome by cause:

- A failure or unproven outcome caused by the scenario itself returns the change to
  implementation.
- A failure caused by product behaviour is recorded failed and handed to a new change
  named in the roadmap.
- An unproven outcome caused by topology is recorded unproven, naming the missing input.

Each observation's outcome is the per-observation one D8 defines. Closeout requires every
observation to be made, or failed or unproven with a named cause outside this change. The qualification roadmap row closes only if all four are made.

**The candidate.** It is the `HEAD` closeout will archive, after dev is merged in and the
merge is validated. "Source" is any path that enters a wheel, an image, a chart or the
e2e image, so closeout's documentation-only commits and the archive do not invalidate a
run. A return to implementation makes a new candidate, and all four observations are run
again on it.

**Who runs it.** The deployment's operator deploys the topology and runs the external
modules. Its sanitized findings enter the change as the owner's notes on the candidate's
round and are triaged with that round's validation record. The pipeline and CI
validation run as the change's validation step does. Independent review is by Codex,
through the workflow's review steps.

### D8. Evidence from outside the workflow is free-form

The scenarios assert, skip with a named prerequisite when topology is missing, and log
the identifiers each stage reads: buyer run, Agreement, transaction, reservation, jobs,
relay port and grant.

**Outcomes are per observation, not per module (review 17 F2).** Observations 4 and 5
share a module, and a pytest run that passes with a skipped stage has not run every
check its observation requires. The runbook's rule applies: neither outcome is inferred
from another observation.

- **Made:** every stage the observation requires passed.
- **Failed:** a stage the observation requires failed.
- **Unproven:** no required stage failed, and a stage the observation requires skipped
  naming a prerequisite; the outcome names it.

The conditional stages are required as follows:

- the management-generation reads (`management_unit`) by observation 2;
- the admission-log check (`admission_log`) by every observation that delivers a
  relayed lease: 2, 4 and 5.

So a run against a target naming no management unit records observation 2 unproven,
naming `management_unit`, however its other stages ended. D7's closeout and D12's
roadmap row use this per-observation outcome.

The operator presents its findings to triage in prose, sanitized by the operator. Raw logs
and records stay in the operator's restricted storage and never enter the repository.
The change defines no record format. A format can be added once runs show which
structure the process would benefit from.

**Rejected:** a versioned outcome record per observation, written to a restricted
directory. It is structure to maintain before any run has shown it is needed.

### D9. Grant admission is read from the plugin's log at a target-named path

The admission plugin's decision log is a documented contract
(`tools/frp-grant-admission/README.md#the-log`). `RelayAccess` gains an optional
`admission_log`: an absolute harness-local path, validated like the working-data key
path, to a file of the plugin's log lines that the deployment keeps current.

For each delivered lease, the scenario reads the relay's leases
(`GET /api/v1/relays/{relay_id}/leases`) and finds that lease's record. It requires an
`admit` line with:

- `verified` true;
- `jti` equal to the reservation;
- `remote_port` equal to the record's `remote_port`;
- `kid` equal to the record's `grant_key_id`, the key that signed the lease's latest
  grant.

The relay's active key is not the comparison (review 17 F4): rotation keeps a retired
key's grants valid on unreleased leases, so an admission before a rotation is correct
under a key that is no longer active. A job retried across a rotation may leave an
earlier `admit` under the old key; the lease's recorded key names the latest grant,
which is the one the check finds.

Without the field, that stage skips, naming it.

Like `cleanup_qualification`, the field is added to target version 2 without a version
bump. An older checkout refuses it by name.

**Rejected:** a top-level `relays` list. It is a second place that names relays.

### D10. The dispute authority is pinned and need not answer

An `arkhai.payments.v1` listing publishes a payment option only with an accepted dispute
authority, and every mandate names that authority's account. The deployment pins an
authority identity (interface, origin, account, record key) whose account is real at the
payments target. No authority service or double is deployed by this change.

The local lane pins one nobody answers, through `add-mvp-payments-lane-double`. That
exercises the same path on every pipeline run.

The buyer's teardown files a delivery-end case, which records `Unknown`. The scenarios
treat that filing as outside their observations and never fail on it.

A hosted, controllable dispute authority remains an unowned roadmap gap.

### D11. In-cluster payments over HTTPS with a deployment's CA

The kit already accepts an `https://<service>.<namespace>.svc.cluster.local[:port]`
origin and refuses plain HTTP outside loopback. It builds non-loopback connections with
`trust_env`, so `SSL_CERT_FILE` applies.

This change adds:

- **A kit test** pinning that rule.
- **A chart option** on the storefront and bare-metal storefront charts that mounts a
  deployment-supplied CA bundle (a Secret or ConfigMap key) into the storefront container
  and sets `SSL_CERT_FILE`. The bundle holds the deployment's CA plus public roots, and the
  option names no CA itself.

The e2e helper's readiness probe must verify against the same explicit CA. The local lane
needs that first, so `add-mvp-payments-lane-double` owns it.

### D12. Roadmap ownership

- **The qualification row.** Goal 1's row on real provisioning not yet being qualified
  gains this change as owner, and narrows to name observations 1 and 3 as still owed
  elsewhere. At closeout it closes only if observations 2, 4, 5 and 6 are each made, by
  D8's per-observation outcome; otherwise
  its prose states each outcome and its owner.
- **New unowned gaps:**
  - a paid purchase with checked GPU work for each GPU offer;
  - no pushed operator notification for a cleanup refusal or held teardown;
  - a payer-scoped debit listing at the payments service, as future work outside this
    repository.
- **The real modules' first run.** The row recording that the real modules have never run
  against a target stays unowned. The deployment may run the Alkahest real modules on the
  candidate, but that is not a commitment of this change.

### D13. Implementation cadence

Implementation needs `add-mvp-payments-lane-double` landed on dev and merged in.

- **Round 1, local and product, two sessions:**
  - Session 1: the shared post-settlement stages (D15), the buyer-purchase stage set and
    its source check, the local payment scenarios in the VM and bare-metal lanes, and the
    D2 listing helper and adoption checks.
  - Session 2: the host diagnostics job, with its playbook, action, mock default output,
    `diagnose_host`, `HostDiagnostics` and tests.
- **Round 2, the external extension, one session:** the three qualification modules, the
  `management_unit` and `admission_log` target fields and the admission-log check, and the
  chart CA option with the kit's HTTPS test.

Then validation, pre-closeout review, the merge, and the operator's run on the post-merge
candidate (D7). Round 1 is reviewed before round 2 builds on it.

### D14. The local payments target is a prerequisite change

The locally verifiable base needs a payments target in the lane. The payments service is
outside this repository and has no mock mode, so the stand-in is a double of its public
HTTP contract.

`add-mvp-payments-lane-double` owns that double and its lane wiring. It covers only the
once-only surface:

- approve, attach, receipt, snapshot and reverse over the kit's engine;
- the payer balance read;
- a lane HTTPS origin and CA;
- fixture accounts and a seeded balance;
- a pinned dispute authority nobody answers;
- the harness probe's CA trust.

It gates this change's implementation. `add-arkhai-payments-lane-double` later extends
it with mediation, rate parts and controls, revising its own D1 and D7.

**Rejected:**

- **Depending on all of `add-arkhai-payments-lane-double`.** It waits on Goal 8's gated
  surfaces this change never uses.
- **Building the double here.** That is a second acceptance boundary, and it collides
  with that change's ownership.
- **A local base settled on Alkahest.** The extension would then not be minimal.

### D15. Post-settlement stages are shared across both stage sets, except the ending

`Stage09b` (settlement readiness), `09c` (the lease record) and `11b` (release, with
capacity restored) are keyed on the deal's settlement reference rather than
`real_escrow_uid`: the Alkahest escrow, or the payments negotiation that
`wait_for_settlement` already accepts. Each driver supplies its reference. So the
Alkahest set and the buyer-purchase set run one definition of each, and a compute
scenario settling another way keeps only its own pre-settlement stages.

How a lease ends is not shared across endings, because each ending's trigger and the
states it asserts differ:

- **Expiry:** `10a`, `10b` and `11a` back-date the lease, step one watchdog cycle to
  `releasing` and `teardown_dispatch_pending`, and advance convergence to
  `tearing_down`. They are keyed on the settlement reference too, and run by every
  scenario whose lease ends by expiry: the Alkahest set and the VM buyer purchase.
- **Buyer teardown:** the bare-metal buyer purchase runs its own stage, which runs
  `market bare-metal teardown` and ends in the state `11b` starts from.

Whether `11b`'s entry prerequisites fit unchanged after a buyer teardown is checked
against the code in planning; the boundary is the one stated here.

**Rejected:** sharing `10a` to `11a` across endings by changing only the reference
field (review 17 F1). A buyer teardown is a different trigger, and the requirement
forbids a shared stage whose body differs between lanes.

## Principles stated for promotion

These go to the new `TESTING.md` section, with the repository-wide rule in
`ARCHITECTURE.md`'s testing philosophy:

1. End-to-end scenarios are locally verifiable or external-topology, and each kind has
   stated coverage.
2. An external-topology scenario minimally extends a locally verifiable one and shares
   its stages.
3. Setup or teardown needing knowledge this repository lacks is topology.
4. External-topology evidence is supplied by whoever deploys the topology.
5. A scenario never waits out the wall clock for a state it can step to through the same
   service code.
6. Evidence from outside the workflow is free-form, sanitized by its supplier.

## Open Questions

- **A payer-scoped debit listing at the payments service.** It would let the scenario
  prove exclusivity, not just a sum. Revisit when the payments service publishes one.
- **Structure for externally supplied evidence.** Revisit after a few runs show which
  structure the process would benefit from.
- **Host diagnostics for bare metal.** It is VM-only now. Revisit, and lift it to the
  compute family, when bare metal needs it.
