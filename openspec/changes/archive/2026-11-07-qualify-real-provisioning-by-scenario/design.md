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
  shared stage classes. It reads readiness by polling the buyer's fulfillment status on
  the wall clock, never through the administrator's settle wait. It re-drives the run's commit, then the seller refunds, then it
  tears the host down through `BareMetalFulfillmentTransport.teardown` rather than the
  buyer's `market bare-metal teardown`. It is governed by "A configured bare-metal
  payment purchase is qualified end to end".
- **No VM scenario buys through `market buy` in `arkhai.payments.v1`.**
  `test_vm_payment_deal.py` negotiates, approves and commits through typed clients and
  ends by an administrator interruption; its case and refund stages report a blocked
  skip without `MEDIATION.SERVICE_URL`. The VM buyer supports the mechanism.
- **Each storefront's settle wait resolves a reference its own way.** Every storefront
  binds the settlement runtime kit's `SettlementAdminRouteService` with an opaque
  `settle_status(ref)` hook. VM's finds a delivery record by negotiation, then an escrow
  row, then refunded evidence (`payment_repository.py:462-479`); API credits' finds its
  issuance progress by negotiation or `public_ref` (`settlement_repository.py:83-89`);
  bare metal's reads only the `escrows` table (`deal_controls.py:133-136`), which only
  Alkahest verification writes (`settlement_stages.py:495`). So a bare-metal
  `arkhai.payments.v1` deal is invisible to the administrator's settle wait, by its
  negotiation or its transaction, although its settlement record exists from acceptance
  (`negotiation_runtime.py:856-862`) and the buyer status route finds it
  (`api.py:913-915`). Every domain records the same shape of settlement evidence — one
  row per negotiation with its mechanism, a unique `settlement_ref` and a status
  (`vm_settlement_evidence`, `bare_metal_settlement_records`), the shape of
  `market_core.SettlementEvidence` — and all three hooks share the terminal vocabulary
  `ready` and `failed`.
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
- A settle wait that resolves any mechanism's settlement the same way in every
  storefront, which the shared readiness stage relies on (D23).

**Non-Goals:**

- Funding the buyer or proving the funding: topology.
- Deploying anything, or naming any deployment.
- Observations 1 and 3, and GPU work.
- A default pipeline lane for the external scenarios.
- Changing payment or provisioning behaviour.
- A buyer-facing settle status route change, or a settlement evidence store shared across
  domains (D23).
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

### D2. One listing offers every deal mechanism the stack composes

On the real target, the Alkahest real modules and the qualification modules share one
host, pool, resource and capacity source, and a capacity source backs one listing for
good.

- **VM:** both modules create or adopt that listing through one shared helper. Creation
  states a settlement for each deal mechanism (Alkahest, Arkhai payments) the storefront
  reports ready. Contact exchange, which the storefront also composes, settles no deal,
  so a compute listing states none.
- **Bare metal:** the published options already are the composed mechanisms.
- **Adoption** additionally requires the listing to offer the adopting module's own
  mechanism, and otherwise fails naming the listing and its options.

On a stack that composes one deal mechanism this is one listing with one option.

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

**Holds.** Every scenario holds, for the whole module, each shared timer it needs held, as
the spec requires (`openspec/specs/test-compatibility/spec.md`, "Scenarios hold shared
services for the whole module"). A scenario that steps a timer needs it held; one may need
a timer held without stepping it. Observation 6 steps no timer of the bare-metal site, and
the service's state guards keep that site's fulfillment convergence and lease watchdog
from restoring anything a faulty reapply removed, so it holds the storefronts' loops and
the VM site's timers only. Relay-port reconciliation runs ungated on both sites and could
re-release a lease the reapply un-released; the comparison catches that by comparing each
quarantined lease's whole record, release time included, not by a hold (tasks 8.3 gives
the evidence, the idle-stack scope, and the limits: a false failure from a lease an
earlier module left releasing, and no claim that a live tenancy survives). The VM buyer
CLI polls its settlement while the stage steps convergence, as
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
- **The management unit:** passed as a job parameter checked against systemd's
  unit-name syntax for a service (`.service`), from the target's optional
  `management_unit`. The management client is operator-owned, so this repository does
  not know its name. Only a service has the main PID and restart count the read reports
  and the pass criterion compares; for another unit type `systemctl show` reports
  neither, and the typed parse would refuse every result (review 55 F1, settled in its
  triage: restricted to service units rather than reporting those fields as
  unavailable, which would let "adds no restarts" pass vacuously).
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

**Which stages an observation requires.** A shared stage is declared with an empty body,
so it cannot carry its own declaration. Every stage of a qualification module requires the
module's observation, or its cycle's in the module that runs once per cycle; a stage of
the module's own may narrow that to fewer. A stage the run did not collect counts as not
run, so deselecting a stage cannot turn an observation made.

**Compensation** (review 55 F2, settled in its triage). The qualification purchases are
real payments to a hosted target and deliveries on real hosts, so a module failing part
way must not leave either outstanding. Its cleanup, after a stage fails past the buyer's
approval, refunds an unrefunded payment as the seller and ends a delivered guest or host
through its lease's own lifecycle: a VM guest by expiry, back-dated and stepped, a
bare-metal tenancy by its reclaim, as the real lanes' recovery does. It reuses the
bare-metal lane purchase's compensation, each domain supplying its status read, refund and
release. What it cannot refund or end it reports by negotiation and transaction, for the
operator. A purchase the module ended itself is left: its payment is the qualification's
own, and refunding a completed purchase would be a second, unqualified operation. One the
module had begun ending (its lease's expiry requested, or the buyer's teardown asked for)
is not refunded either, for the same reason, but its delivery is still ended. A module
run once per cycle runs a cycle's compensation as that cycle's last stage, so a failure
in it counts against that cycle's observation, not the next cycle's.

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
    repository;
  - each storefront's buyer-facing settle status route resolving through the
    settlement runtime kit's resolver, as the settle wait does (D23);
  - one settlement evidence store owned by a kit, in place of each domain's table (D23).
- **The real modules' first run.** The row recording that the real modules have never run
  against a target stays unowned. The deployment may run the Alkahest real modules on the
  candidate, but that is not a commitment of this change.

### D15. Post-settlement stages are shared across both stage sets, except the ending

`Stage09b` (settlement readiness), `09c` (the lease record) and `11b` (release, with
capacity restored) are keyed on the deal's settlement reference rather than
`real_escrow_uid`: the Alkahest escrow, or the payments negotiation, each of which every
storefront's settle wait resolves (D23). An earlier stage writes the reference: `07`
for the Alkahest set, the purchase stages for the buyer purchases. So the
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

- **Round 1, local and product, five sessions:**
  - Session 1, implemented: the shared post-settlement stages keyed on the settlement
    reference (D15).
  - Session 2: the settle wait's resolution in the settlement runtime kit, the three
    storefronts' hooks onto it, and their versions and locks (D23).
  - Session 3: the buyer-purchase stage set and its source check; the bare-metal payment
    module restructured onto it, with the buyer-teardown ending (D16).
  - Session 4: the VM `market buy` module with its own resource, host and pool, ending
    by the shared expiry stages (D17); the D2 listing helper and adoption checks.
  - Session 5: the host diagnostics job, with its playbook, action, mock default output,
    `diagnose_host`, `HostDiagnostics` and tests (D5).
- **Round 2, the external extension, one session:** the three qualification modules, the
  `management_unit` and `admission_log` target fields, and the admission-log check (D8,
  D9).

Round 1 is reviewed as a whole before round 2 builds on it. Then validation, pre-closeout
review, the merge, and the operator's run on the post-merge candidate (D7, D19).

The kit work is a session of its own, with its own verification checkpoint, because it is
product code across four packages; it sits in round 1 so it is reviewed beside session 3's
bare-metal purchase, the scenario that first proves it end to end. Session 4 proves the
expiry ending on a payments deal.

**Rejected:** folding the kit work into session 3, the largest session already, which
mixes a product change with the e2e restructure in one handoff; a round of its own
reviewed before the purchase stages, which costs a review and validation cycle before any
scenario proves it.

### D23. The settle wait's resolution is the settlement runtime kit's

The settle wait (`GET /api/v1/admin/settle/{ref}/wait`) is a kit-owned control
(`market-composition`, "Storefront deal controls are kit-owned route services"), but
what a reference names is decided in each storefront's opaque `settle_status` hook, and
the three decide differently (Context). The kit takes that decision over for every
binder:

- **The kit owns resolution:** a reference names a settlement by its `settlement_ref`,
  then by its negotiation, whatever the mechanism. A reference that resolves to nothing
  is a poll that found nothing terminal, and the wait polls to its deadline as now.
- **The kit owns terminality:** `ready` and `failed` end the wait. Polling, the failed-read
  rule and the deadline are unchanged.
- **The domain supplies what is its own:** two lookups returning
  `market_core.SettlementEvidence` or nothing — by settlement reference and by
  negotiation — and its delivery status for a resolved settlement.

```python
SettlementAdminRouteService(
    verify=verify, preview_fulfillment=preview,
    settlements=SettlementLookup(
        by_reference=db.load_vm_settlement_evidence_by_ref,   # str -> SettlementEvidence | None
        by_negotiation=db.load_vm_settlement_evidence,        # str -> SettlementEvidence | None
    ),
    delivery_status=vm_delivery_status,  # SettlementEvidence -> {"status": "ready"|"failed"|..., ...}
)
```

The names are illustrative; planning fixes them. The resolver is a public kit operation,
so a later caller resolves a reference the same way without the wait.

All three binders move, and the opaque `settle_status`/`is_terminal` form is removed:

- **VM:** its evidence lookups, a by-reference query added. Its delivery status reads the
  delivery record by the evidence's negotiation, and reports refunding or refunded
  evidence when there is none. The escrow-row fallback goes: Alkahest evidence carries
  the escrow as its `settlement_ref`, and a delivery record exists only for a negotiation
  with evidence.
- **Bare metal:** its settlement records, both queries existing. Its delivery status
  keeps the live fulfillment read, its mapping to `ready` and `failed`, and the
  servicing-obligation wake, which now runs only for evidence whose source names an
  `obligation_ref`: the Alkahest path, since a payments deal adopts no settlement-runtime
  obligation.
- **API credits:** its evidence by reference and by negotiation, its delivery status its
  issuance progress. Its Alkahest evidence records the escrow as its `settlement_ref`
  (`apicredits_storefront/settlement_stages.py:576`, the reference being the
  settlement's mechanism reference), so an escrow resolves by reference as it does
  through `public_ref` today.

Wire paths and responses are unchanged, as are schemas and migrations; every storefront
answers for a superset of the references it answered before. An older bare-metal
storefront still times out on a payments deal, which fails a new harness visibly. The kit
takes a breaking minor version, the storefronts are bumped, and every exact pin on the
kit is raised with its locks.

So `09b` keeps one body for every compute scenario (D15), the bare-metal purchase reads
readiness through the settle wait rather than a wall-clock poll of the buyer's status, and
an operator can settle-wait a bare-metal payments deal.

**Rejected:**

- **Patching only the bare-metal hook.** It fixes the scenario's case and leaves three
  domain-local resolutions of one kit-owned control.
- **Moving VM and bare metal only, API credits keeping the opaque hook.** Two constructor
  forms, and a domain-local lookup kept in the third binder.
- **Also resolving each buyer-facing settle status route through the kit** in this
  change. Those routes carry their own authentication and replay semantics that no
  scenario here exercises; once the resolver exists it is a call-site change, recorded as
  an unowned gap (D12).
- **A kit-owned settlement evidence store** replacing the domains' tables. It is a data
  migration across two status vocabularies and needs a design of its own; recorded as an
  unowned gap (D12).
- **`09b`'s readiness read as a driver part, or a bare-metal readiness stage of its
  own.** Either takes the readiness oracle out of the shared body, against D15, needs a
  wait that is not a poll, and leaves the operator-facing defect.
- **Splitting the kit work into a prerequisite change.** It halts sections 3 onwards for a
  whole change's cycle, for an understood fix whose first end-to-end proof is this
  change's bare-metal purchase.

## Implementation findings

What implementation found that the decisions above do not state, kept here when the task
notes were compressed at closeout.

- **The buyer-purchase stage set (D15, D17).** `07a`'s prerequisite was `real_escrow_uid`,
  which a purchase never writes; it is `_settlement_imminent`, written by `07` beside the
  escrow and by `Purchase02` once the option is found, so no rule is armed for a deal that
  will not settle. `08c` (the mock job evaluation) is not run by a purchase: its preview is
  `08a`'s, by escrow. `seller_listing_id` is written by each module's own listing stage,
  as `ComputeDealState` gives listing stages to the domain. `market buy` takes no listing
  and polls its settlement until delivery, so `Purchase03` runs the command in the
  background and waits for `payment_approved`, then the driver's `committed_event`; a
  shared `Purchase09` after `09c` checks the run's end through the driver; `Purchase04`
  ties the purchase to its listing by the Agreement naming the discovered listing and
  option, since `market buy` selects its listing by discovery. Rejected: making the run's
  exit bound (`PURCHASE_RUN_EXIT_SECONDS`) a driver part — it bounds a wait for a command
  that has already read its settlement ready. The VM lane purchase buys as the lane's own
  buyer, profiled with no wallet and Arkhai payments as its only settlement, so its
  storefront client reads the deal's settle status.
- **D15's return-to-design case did not arise.** Read from the code: the seller's
  end-delivery route drives the physical end synchronously, bare metal's `apply_end`
  terminates the lease at provisioning, and `LeaseLifecycle.terminate_lease` requests
  release as expiry does, so the buyer's teardown leaves the lease `releasing` for `11b`.
  The pipeline confirmed it.
- **D17's expiry ending on a payments deal needs no authority.** The lease watchdog and
  convergence are mechanism-neutral, the VM storefront's capacity-released callback records
  the release locally, and the settlement-servicing loop that reads the authority is held
  and never stepped by these stages.
- **D23's bindings.** VM's delivery status reports the evidence's own status (`pending`,
  `verified`, `refunding`, `refunded`: none terminal) when no delivery record exists; bare
  metal's wake reads `source.obligation_ref` and calls the worker's `wake` directly. API
  credits' schema admits `failed` evidence, which ends a wait; nothing writes it, and a
  failed settlement is one never to be delivered, so the comment states it as intended.
  None of the three admin wait routes takes an injected clock and the route refuses a zero
  timeout, so a storefront test proves a non-terminal answer below the route — through the
  route service with a ticking clock, or the delivery status read directly — and through
  the typed client waits only on what ends at the first poll ("Tests wait on events, never
  on durations"). The bare-metal "wakes no obligation" test guards the payments path rather
  than discriminating the wake's new condition, which the Alkahest lease-active test covers.
- **D2's listing helper.** A create request with settlement clauses builds options only for
  its clauses' mechanisms, so a listing offering two mechanisms needs a clause for each; the
  Alkahest real module states its terms as a clause in place of `accepted_escrows`, the
  storefront resolving the escrow address and the token's decimals itself. Readiness is
  read only on the creation path, so adoption never depends on it, and the created
  listing's mechanisms are compared as sets, since one mechanism may publish several
  options.
- **D5's host diagnostics.** The VM role's prerequisites skip starting libvirtd for
  `diagnose`, and the script reads the units before `virsh` counts guests, since a read
  that started an idle socket-activated daemon would show a new invocation; the count
  itself still starts it, which the pass criterion allows for. A failed `systemctl show` or
  `virsh` fails the job rather than reading as empty or zero guests, and a number systemd
  does not report is printed as text so the typed parse refuses it by name. The unit-name
  check sits on the wire model (`HostDiagnosticsRequest`), per `ARCHITECTURE.md`'s order of
  checks, so the route answers 422 before its service runs and the typed client refuses
  before sending. Disposed of at the round-1 triage: a mistyped or absent management unit
  reads back `inactive` with an empty invocation, since `systemctl show` answers for an
  unloaded unit, and the stage's message says a not-started unit may be a wrong name rather
  than the job reporting `LoadState`, which is beyond D5's field list; the provisioning
  service's published `adapters` extra keeps its older bound, since deployments install from
  its lock. Declined: escaping control characters other than tab, CR and LF (systemd's
  properties here are words, IDs, numbers and timestamps), and a machine-splittable error
  path (unit names contain dots; the field path is for a reader).
- **D8's outcomes.** A module's stages are read from its classes, not the run's items, so a
  deselected or uncollected stage reads "did not run". Any failed phase fails a stage, its
  teardown's included, so a failure in the module's cleanup fails its last declared stage:
  conservative. The outcomes are logged from the report hook after the last item's teardown
  report, with a session-end fallback for a run stopped early, because a fixture inside the
  last item had read a failed teardown as made. A module run once per cycle runs each
  cycle's compensation as that cycle's last stage, because pytest finalizes a cycle's
  module fixtures in the next cycle's first setup, which would count a normal-cycle cleanup
  failure against observation 5; that cleanup first repairs a planted fixture still in
  place, so the reclaim can complete. Compensation carries the stages' job identifiers into
  the real lane's recovery, so it tells the create job from a teardown job. The refusal
  cycle skips, not fails, when the normal cycle's cleanup was not verified, so observation 5
  is never failed by inference from observation 4.
- **D9's reader.** A direct target delivers no relayed lease, so the check passes; only a
  relayed target without `admission_log` skips. The deployment's copy may trail the relay's
  log, so the check re-reads it within a bound before failing; an unreadable file fails at
  once, and lines that are not decisions are skipped.
- **Observation 2's second purchase** runs the shared stage definitions on its own state,
  driver and CLI profile through `run_stage`, since the purchase source check allows each
  shared stage once per module. It does not run `11b`, which requires the whole resource
  free while the first guest still holds its slice; its own stage completes the second
  guest's teardown, re-reserving one guest's shape, as the Alkahest real module's second
  deal does. Each guest is probed for a GPU (review 61 F1): a display or 3D controller from
  NVIDIA or AMD, the rule host preparation applies, and an unavailable, unreadable or
  malformed device list fails the probe rather than reading as no GPU.
- **Observation 6 takes no second hold of a site.** The bare-metal site may be the VM
  site's own service, whose timers the module already holds, and a second hold of that
  service would resume it when the first hold ended. It settles both storefronts with a
  publication cycle before its "before" read, so a listing the earlier modules left closed
  is reopened there rather than read as changed.
- **The real bare-metal listing's terms are the deployment's.** The real purchase checks
  only what any backed whole-host payments listing states (backed, pinned publisher, USD/6
  by the hour); the lane's driver adds the terms its own pool override writes.
- **Dispute coverage is a run setting** (pre-closeout triage 78, revisited). The harness
  stated a fixed 15-day compute dispute coverage, so a run against a test authority
  advertising a short minimum filing window could not buy under a short hold.
  `PAYMENTS.DISPUTE_WINDOW_SECONDS` sets it for every compute payments option the harness
  states and the purchase checks expect, defaulting to 15 days (the mediation contract's
  14-day default minimum plus a day, covering the 300-second delivery deadline); no lane
  profile sets it, and the authority's own minimum is enforced at publication. The real
  bare-metal machine's listing is the deployment storefront's and is unaffected.

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
- **A rule for unifying a behaviour that differs between domains binding one kit-owned
  control.** D23 applies it, but as stated it is not yet actionable upon review, so it is
  not promoted. Revisit at a guidance review, or when another such difference is found,
  once it is refined into a rule a reviewer can apply.
