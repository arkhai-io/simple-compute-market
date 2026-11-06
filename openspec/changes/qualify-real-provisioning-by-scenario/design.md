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
- **Every compute lane runs a payments double.** The VM, bare-metal and API-credit lanes
  run `tools/payments-lane-double`, an HTTPS mirror of the payments service's API over
  the payments kit's engine, reached under a committed lane CA
  (`openspec/specs/test-compatibility/spec.md`, "Lanes run payment scenarios against an
  in-lane payments double").
- **The bare-metal lane already buys through the shipped buyer.**
  `test_bare_metal_payment_deal.py` buys through `market bare-metal buy` in
  `arkhai.payments.v1` against the double. Its steps are module test functions, not
  shared stage classes. It re-drives the run's commit, then the seller refunds, then it
  tears the host down through `BareMetalFulfillmentTransport.teardown` rather than the
  buyer's `market bare-metal teardown`. It is governed by "A configured bare-metal
  payment purchase is qualified end to end".
- **No VM scenario buys through `market buy` in `arkhai.payments.v1`.**
  `test_vm_payment_deal.py` negotiates, approves and commits through typed clients and
  ends by an administrator interruption; its case and refund stages report a blocked
  skip without `MEDIATION.SERVICE_URL`. The VM buyer supports the mechanism.
- **A listing's binding to its resource outlives the listing**, so each scenario on a
  shared stack lists its own resource. A backed declaration whose provider needs a host
  is offered only while it names a registered, enabled host (`helpers/hosts.py`).
- **The payments kit reads transactions and the caller's own balance.**
  `PaymentsClient` exposes approve, transaction snapshots, attachments, events, reverse
  and `get_balance(account)`. The service and the double answer a balance only for the
  caller's own account. No route lists an account's debits.
- **Trust and secrets are configuration.** A payments client trusts a private CA through
  its configuration's `ca_bundle_path`; the storefront charts mount a deployment's
  `caBundle` and derive that path, and a storefront's payments key is `api_key` in its
  secret overlay. `SSL_CERT_FILE` is set nowhere.
- **An external run's payments target is runner configuration.** The runner reads
  `PAYMENTS` from a profile, the buyer's token from a secret profile; with `LANE_OWNED`
  unset an unready target is a blocked skip (`docs/development/TESTING.md`, "Private
  Service Dependencies"). Each storefront chart's `helm test` runs `check-payments` from
  the storefront's own container.
- **The consumed-UID history is already readable.** The bare-metal working-data
  operator route's `policy` operation returns the host ledger's consumed UIDs.
- **No operator notification exists.** A cleanup refusal is visible only as the reclaim
  job's error, retry fields and log, and as the lease held at `releasing`.
- **An unanswered dispute authority does not stall servicing.** `MediationAdapter._read`
  turns a transport failure into a non-`Accepted` view, and `DealWatch` records it and
  continues. The lanes' registries recommend a dispute authority under `.invalid`, and
  the VM lane's storefront holds a credential for it, so servicing reads a VM payment
  deal `running`.

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
- Chart or kit changes for in-cluster payments: the storefront charts' CA option and the
  kit's transport rule already serve a deployment.

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
  mock provisioning and the payments double: the existing bare-metal payment purchase,
  restructured onto it (D16), and a new VM purchase (D17).
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

**VM.** Observation 2's leases, and the VM lane purchase's lease, end by moving the
agreed end into the past and stepping one `check_leases` cycle with the watchdog held.
That runs exactly the service code a wall-clock expiry runs. It is the end-to-end
application of `TESTING.md`'s rule that tests wait on events, never on durations (D21):
the scenario steps to the state rather than spending the time the lease passes through.
The runbook's observation 2 is amended: both leases end through the lease watchdog's
expiry path, never through an early teardown or a buyer end. Lease durations stay fixed
constants.

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
- **Per account:** the scenario reads the payer's own balance through the kit's
  `get_balance`, with the buyer's token. It asserts that the drop in `available`, from
  before its first purchase to after its last approval, equals the sum of its own
  transactions' debits.

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
- **Interface:** a submission and a typed parse, as every operator action is.
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
observation to be made, or failed or unproven with a named cause outside this change. The
qualification roadmap row closes only if all four are made.

**The candidate.** It is the `HEAD` closeout will archive, after dev is merged in and the
merge is validated. "Source" is any path that enters a wheel, an image, a chart or the
e2e image, so closeout's documentation-only commits and the archive do not invalidate a
run. A return to implementation makes a new candidate, and all four observations are run
again on it.

**Who runs it.** The deployment's operator deploys the topology, checks each storefront's
payments access (D19), and runs the external modules. Its sanitized findings enter the
change as the owner's notes on the candidate's round and are triaged with that round's
validation record. The pipeline and CI validation run as the change's validation step
does. Independent review is by Codex, through the workflow's review steps.

### D8. Evidence from outside the workflow is free-form

The scenarios assert, skip with a named prerequisite when topology is missing, and log
the identifiers each stage reads: buyer run, Agreement, transaction, reservation, jobs,
relay port and grant.

**Outcomes are per observation, not per module.** Observations 4 and 5 share a module,
and a pytest run that passes with a skipped stage has not run every check its
observation requires. The runbook's rule applies: neither outcome is inferred from
another observation.

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

The relay's active key is not the comparison: rotation keeps a retired key's grants
valid on unreleased leases, so an admission before a rotation is correct under a key
that is no longer active. A job retried across a rotation may leave an earlier `admit`
under the old key; the lease's recorded key names the latest grant, which is the one the
check finds.

Without the field, that stage skips, naming it.

Like `cleanup_qualification`, the field is added to target version 2 without a version
bump. An older checkout refuses it by name.

**Rejected:** a top-level `relays` list. It is a second place that names relays.

### D10. The dispute authority is pinned and need not answer

An `arkhai.payments.v1` listing publishes a payment option only with an accepted dispute
authority, and every mandate names that authority's account. The deployment pins an
authority identity (interface, origin, account, record key) whose account is real at the
payments target. No authority service or double is deployed by this change.

The lanes' registries already recommend one nobody answers, under `.invalid`, so the
locally verifiable purchases exercise the same path on every pipeline run.

The buyer's teardown files a delivery-end case, which records `Unknown`. The scenarios
treat that filing as outside their observations and never fail on it.

A hosted, controllable dispute authority remains an unowned roadmap gap.

### D12. Roadmap ownership

- **The qualification row.** Goal 1's row on real provisioning not yet being qualified
  gains this change as owner, and narrows to name observations 1 and 3 as still owed
  elsewhere. At closeout it closes only if observations 2, 4, 5 and 6 are each made, by
  D8's per-observation outcome; otherwise its prose states each outcome and its owner.
- **New unowned gaps:**
  - a paid purchase with checked GPU work for each GPU offer;
  - no pushed operator notification for a cleanup refusal or held teardown;
  - a payer-scoped debit listing at the payments service, as future work outside this
    repository.
- **The real modules' first run.** The row recording that the real modules have never run
  against a target stays unowned. The deployment may run the Alkahest real modules on the
  candidate, but that is not a commitment of this change.

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
  scenario whose lease ends by expiry: the Alkahest set and the VM buyer purchases.
- **Buyer teardown:** the bare-metal buyer purchases run one stage of their own, shared
  by the bare-metal lane purchase and the observation 4 and 5 module, which runs
  `market bare-metal teardown` and ends in the state `11b` starts from.

**The handoff into the shared stages** (review 31 F2). `09c` and `11b` stay one body
each. What differs between the sets is which earlier stage writes the state they read,
and each input stays independent of the lease it is checked against:

| State | Read by | Alkahest set | Buyer purchases |
|---|---|---|---|
| `fulfillment_id` | `09a`, converged to `active` | `08b`, from the settlement's dispatch | the purchase stages, from the deal's fulfillment as the buyer's run and the seller's status report it |
| `_create_job_completed` | `09a` | the mock gate's `08b2`, or a real lane's job watch | the same: the purchase stages arm `07a` before the buy and drain through `08b2` in a mock lane, and a real lane watches its create job |
| `expected_host_id` | `09c`, compared with the lease's host | `08a`, from its evaluate-settle preview | the purchase stages, from the driver's declared host: the one host the scenario registered enabled for its resource, or the target's host on a real lane |
| `teardown_fulfillment_id` | `11b`, advanced to `torn_down` | the ending: expiry's `10b`, from the lease | the expiry ending's `10b` (VM); the buyer-teardown stage, from the deal's fulfillment as delivery status reports it (bare metal) |
| `_teardown_job_completed` | `11b` | the mock gate's `11a2`, or a real lane's job watch | the same: the buyer-teardown ending arms `09c2` and drains through `11a2` in a mock lane, and a real lane watches its job |
| the re-reservation's name | `11b` | from the settlement reference | from the settlement reference |

`_evaluate_settle_host_id` becomes `expected_host_id`, and every stage reading it — `08c`'s
mock evaluation and the real lanes' check of the previewed host included — reads the
renamed field. `11b`
keeps its held watchdog and its own `check_leases` that must report the release: the
existing bare-metal payment purchase already releases through convergence to `torn_down`
and a `check_leases` call after the buyer's teardown. If implementation finds a buyer
teardown releasing the lease outside `check_leases`, so that `11b` cannot run unchanged,
the change returns to design rather than splitting the stage in planning or
implementation.

**Rejected:**

- **Sharing `10a` to `11a` across endings by changing only the reference field.** A
  buyer teardown is a different trigger, and the requirement forbids a shared stage
  whose body differs between lanes.
- **Splitting `09c` and `11b` at the differing inputs** (review 31 F2). Each assertion
  would keep its meaning, but the stages would be defined twice when only their inputs'
  producers differ.
- **Dropping `09c`'s host check on the buyer path.** It hollows the assertion out.

### D16. The existing bare-metal payment purchase is the bare-metal base

`test_bare_metal_payment_deal.py` becomes the bare-metal lane's locally verifiable
purchase. Its discovery, buy, correlation and delivery steps are extracted into the
shared buyer-purchase stages, and it runs them:

```
hold loops                          shared purchase set
discover (purchase profile)         shared purchase set
market bare-metal buy, correlate    shared purchase set
09a/09b/09c converge, ready, lease  shared post-settlement (D15)
re-drive the run's commit           this module's own
market bare-metal teardown          shared bare-metal ending
seller refund                       this module's own
11b release, capacity restored      shared post-settlement
```

The observation 4 and 5 module subclasses the same shared stages and adds its real-host
stages in place of the re-drive and the refund.

The buyer's teardown runs before the seller refund, so the lane proves the ending
observations 4 and 5 use, the buyer CLI's teardown of an unrefunded paid deal. The
refund and the teardown stay separate operations, and the module's compensating cleanup
is unchanged. The permanent requirement "A configured bare-metal payment purchase is
qualified end to end" is modified accordingly.

The refund after the teardown has held funds to reverse:

- **No stop.** The bare-metal storefront submits no payments event but the refund's
  reverse; the buyer's teardown ends delivery, not the payment.
- **The hold outlasts the scenario.** The double holds a once part as one lot from
  approval until its hold window passes, `P7D` in the lane, and its reverse takes any
  held lot.
- **No conflict with the earlier end.** The refund records its own end request under
  its own source; the servicing journal accepts it beside the buyer's, and the end
  service does not apply the physical end again.

The CLI teardown's delivery-end filing to the unanswerable authority records `Unknown`
and leaves the run successful (D10). The order is not conditional: if implementation
finds the reverse after the teardown refused, the change returns to design rather than
reordering the scenario or narrowing what it proves.

**Rejected:**

- **A second bare-metal module running only the shared set.** Two purchases per lane run,
  each with its own host, pool and resource, and two definitions of the same purchase
  steps, against the requirement that they are defined once.
- **Pointing the observation 4 and 5 module at the existing module's functions.** They
  are pytest functions, not subclassable stages, and its ending is not the one those
  observations use.
- **No bare-metal base.** The buyer CLI's teardown would be verified only externally.
- **Refunding before the teardown when a reverse after it is refused** (review 31 F1).
  The lane would prove the CLI teardown only on a refunded deal while the acceptance
  boundary still promised an unrefunded one, and the code produces no such refusal.
- **Narrowing the scenario to a refunded-deal teardown.** It loses the local proof of the
  ending observations 4 and 5 use.

### D17. The VM lane purchase is a new module with its own resource and host

A new VM module runs the shared purchase set through `market buy` in
`arkhai.payments.v1`, and ends by the shared expiry stages and `11b` (D3, D15). Like
`test_vm_payment_deal.py`, it declares its own resource, registered host and pool in
`host_registry.py` and creates its listing with a payments settlement, since a listing's
binding to its resource outlives the listing.

`test_vm_payment_deal.py` keeps its typed commit, replay and servicing coverage and its
administrator-interruption ending.

Planning checks, with `11b`'s entry under D15, that an expiry ending of a payments deal
completes while the pinned authority is unreachable; no lane shows it today.

**Rejected:**

- **Moving `test_vm_payment_deal.py` onto `market buy`.** It loses the typed coverage it
  exists for, and its ending is not expiry.
- **Reusing `test_vm_payment_deal.py`'s resource.** Its binding outlives that scenario's
  listing.

### D18. In-cluster payments need no chart or kit work

A deployment's storefronts reach an in-cluster payments service over HTTPS through what
already exists: the storefront charts' CA bundle option (`caBundle`, from which the chart
derives `[Settlement.arkhai_payments].ca_bundle_path`) and the storefront's `api_key` in
its secret overlay (`openspec/specs/deployment-state/spec.md`, "A storefront chart trusts
a deployment-supplied CA bundle", "A storefront's secrets reach it through its secret
overlay"). The kit's transport rule — HTTPS with a host, plain HTTP only on loopback —
has no host-specific case, is pinned by its configuration test, and is exercised on
every lane run by the double's non-loopback origin. This change adds no chart option, no
kit test and no `deployment-state` requirement.

**Rejected:**

- **A kit test naming a `svc.cluster.local` origin.** It pins nothing the lane origin
  does not.
- **A chart option setting `SSL_CERT_FILE`.** The `deployment-state` specification
  forbids it: it would replace the whole process's trust store.

### D19. The external run's payments target and its first check

The external modules read the runner's existing `PAYMENTS` section: a profile naming the
target, receipt identity, accounts and `CA_BUNDLE_PATH`, and a secret profile holding the
buyer's token, with `LANE_OWNED` unset so an unready target is a blocked skip. They add no
payments setting. D4's balance read uses that token.

Before running them, the operator runs each storefront chart's `helm test`, whose
`-payments-check` pod runs `check-payments` with the storefront's own image, mounts and
secret overlay. Runbook §25 and §29 state the step. A failed check is a topology cause
under D7, and no module stage repeats it.

**Rejected:**

- **A module stage reading the seller's balance from the runner.** It proves the runner's
  configuration, not the storefront's, which is the check the storefront payments check
  exists to replace.
- **No check.** A broken storefront payments interface would first show as a failed
  purchase, harder to classify.

### D20. The local payments target is delivered

`add-mvp-payments-lane-double` delivered the locally verifiable purchases' payments
target, and nothing gates this change: the in-lane double over the kit's engine, the
kit's balance read, lane CA trust through `ca_bundle_path`, the unanswerable dispute
authority the lane registries recommend, the VM storefront's credential for it, the
runner's lane profiles, and `check-payments` in every storefront with its chart test.
`add-arkhai-payments-lane-double` later extends that double with mediation, rate parts
and controls.

**Rejected:** depending on all of `add-arkhai-payments-lane-double`, which waits on Goal
8's gated surfaces this change never uses, and building the double here, a second
acceptance boundary.

### D21. Stepping rather than waiting is the existing testing rule

`TESTING.md`'s "Tests wait on events, never on durations" already states that a test
does not spend the time a scenario passes through. D3's back-dating and stepped watchdog
cycle is its application to a lease's end, and the new `TESTING.md` section on scenario
kinds states it as such. It is not promoted as a separate principle.

**Rejected:** promoting "a scenario never waits out the wall clock for a state it can
step to" on its own, which would state the rule twice in one document.

### D22. Implementation cadence

- **Round 1, local and product, three sessions:**
  - Session 1: the shared post-settlement stages keyed on the settlement reference (D15);
    the buyer-purchase stage set and its source check; the bare-metal payment module
    restructured onto it, with the buyer-teardown ending (D16).
  - Session 2: the VM `market buy` module with its own resource, host and pool, ending
    by the shared expiry stages (D17); the D2 listing helper and adoption checks.
  - Session 3: the host diagnostics job, with its playbook, action, mock default output,
    `diagnose_host`, `HostDiagnostics` and tests (D5).
- **Round 2, the external extension, one session:** the three qualification modules, the
  `management_unit` and `admission_log` target fields, and the admission-log check (D8,
  D9).

Round 1 is reviewed before round 2 builds on it. Then validation, pre-closeout review,
the merge, and the operator's run on the post-merge candidate (D7, D19).

Session 1 keeps the cross-lane refactor with the scenario that first proves it, and
session 2 proves the expiry ending on a payments deal. If planning finds session 1 small,
sessions 1 and 2 may be one.

## Principles stated for promotion

These go to the new `TESTING.md` section, with the repository-wide rule in
`ARCHITECTURE.md`'s testing philosophy:

1. End-to-end scenarios are locally verifiable or external-topology, and each kind has
   stated coverage.
2. An external-topology scenario minimally extends a locally verifiable one and shares
   its stages.
3. Setup or teardown needing knowledge this repository lacks is topology.
4. External-topology evidence is supplied by whoever deploys the topology.
5. Evidence from outside the workflow is free-form, sanitized by its supplier.

## Open Questions

- **A payer-scoped debit listing at the payments service.** It would let the scenario
  prove exclusivity, not just a sum. Revisit when the payments service publishes one.
- **Structure for externally supplied evidence.** Revisit after a few runs show which
  structure the process would benefit from.
- **Host diagnostics for bare metal.** It is VM-only now. Revisit, and lift it to the
  compute family, when bare metal needs it.
