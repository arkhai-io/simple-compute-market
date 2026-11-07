## MODIFIED Requirements

### Requirement: The canonical compute deal's shared stages are defined once

The compute family's canonical complete deal, settled through Alkahest, MUST take each
stage its lanes run identically from one shared definition, whether the lane delivers
through the provisioning mock profile or through a real host. A lane MUST subclass a
shared stage without replacing its body and MUST supply its differences through
fixtures and a per-domain driver. A lane MAY insert stages of its own; a stage whose
body differs between lanes is not shared.

The stages from fulfillment onwards — convergence to active, settlement readiness, the
lease record, the lease's ending and teardown completion — MUST be keyed on the deal's
settlement reference, which an earlier stage writes, rather than on an Alkahest escrow, so
the buyer purchase settled through `arkhai.payments.v1` runs the same definitions. How a
lease ends is not shared across endings: the lease-watchdog expiry and the teardown
dispatch it starts are shared by every scenario whose lease ends by expiry, and a
scenario whose lease ends another way, such as by the buyer's teardown, runs its own
ending stage, which ends in the state teardown completion starts from. A shared stage
from fulfillment onwards MUST read each input it checks from state an earlier stage
wrote independently of the lease under check: the expected host from the Alkahest
settlement preview or from the driver's declared host, and the teardown's fulfillment
from whichever ending ran.

A shared stage MUST NOT depend on the mock profile. Holding a provisioning job before
its result, releasing it, and evaluating a mock rule are mock gates: they are stages of
their own, run only by lanes that deliver through the mock profile, and are supplied by
a driver part that only mock drivers implement. A stage that would call a gate is split
at the gate, and its gate-free part stays shared.

#### Scenario: A shared stage changes

- **WHEN** a shared stage's preview, advance, or assertion changes
- **THEN** every compute lane that runs the canonical deal runs the changed stage without
  a per-domain edit

#### Scenario: A domain's part of a shared stage

- **WHEN** a shared stage needs supply seeding, provision terms, the lease view,
  settlement-preview expectations, the settlement's dispatch, result and access
  assertions, or the claim that re-reserves released supply and its release
- **THEN** the domain's driver supplies it and the stage's body is unchanged

#### Scenario: A mock lane holds a job

- **WHEN** a lane that delivers through the mock profile holds its create or teardown
  job before the result, or evaluates the mock rule for it
- **THEN** it does so in a mock-only stage, through its driver's mock-gate part, between
  the shared stages it surrounds

#### Scenario: The preflight before settlement fails

- **WHEN** the lane's last stage before settlement — the mock rule's evaluation in a
  mock lane, the check of the previewed host in a real lane — fails
- **THEN** the shared settlement stage skips and submits nothing

#### Scenario: A real lane runs the canonical deal

- **WHEN** a lane delivers through a real host
- **THEN** it runs every shared stage, none of which calls a mock gate, and its driver
  implements no mock-gate part

#### Scenario: A buyer purchase reaches fulfillment

- **WHEN** a compute buyer purchase settled through `arkhai.payments.v1` has dispatched
  its fulfillment
- **THEN** it runs the shared stages from fulfillment onwards, keyed on its settlement
  reference, and keeps its own stages before fulfillment; its lease's ending is the
  shared expiry stages when the lease ends by expiry, as the VM purchase's does, and a
  stage of its own when it ends by the buyer's teardown, as the bare-metal purchase's
  does
- **AND** the lease record's host is checked against its driver's declared host, and
  teardown completion advances the fulfillment its ending reported, so each shared
  stage's body is the Alkahest set's

#### Scenario: A deal outside the canonical deal

- **WHEN** a compute scenario settles another way before fulfillment, or a domain outside
  the compute family runs a complete deal
- **THEN** it keeps its own stages up to fulfillment, and a domain outside the compute
  family keeps all of its own stages

#### Scenario: A compute domain differs in negotiation

- **WHEN** a compute domain would need its own negotiation stage
- **THEN** the difference is resolved in its storefront composition, not in the stage

### Requirement: A configured bare-metal payment purchase is qualified end to end

With a ready payments target configured, the bare-metal lane MUST qualify one fixed-term whole-host purchase settled through `arkhai.payments.v1`: discovery, negotiation, payment approval, receipt-gated mock delivery, re-drive of the original run's settlement, the buyer's physical teardown through `market bare-metal teardown`, and seller refund, with the teardown and the refund as separate operations. Its discovery, purchase, correlation, delivery and teardown steps MUST be the shared buyer-purchase stages, and its re-drive and refund its own inserted stages. In the bare-metal lane the target is the lane's payments double, whose result is never hosted-ledger evidence. Mock access is evidence of composition, never of real SSH access or revocation. The scenario MUST leave no payment hold, allocated host, mock rule, or held loop behind, whether it passes or fails, except a payment it cannot refund, which it MUST report by its negotiation and transaction together with any host its seller may still deliver for it, and a host whose fulfillment it cannot read or tear down, which it MUST report as a failed cleanup step. Without a configured target, or with an unready external one, it MUST report a named blocked prerequisite; an unready lane-owned target MUST fail setup by name. It MUST never fall back to Alkahest or count an unrun purchase as qualification.

#### Scenario: Bare-metal payment purchase is qualified

- **WHEN** the bare-metal payment scenario runs with a ready configured payments target
- **THEN** the shared purchase stages discover a distinct backed whole-host listing, negotiate
  and approve one hourly payment option with a wallet-free profiled Ed25519 buyer,
  and observe receipt-gated durable mock delivery
- **AND** recovery reads the original run and resolves its retained signer, repeats the
  canonical lifecycle commit for the same negotiation, and requires the original
  transaction, fulfillment identity, and durable result
- **AND** the buyer requests physical teardown through `market bare-metal teardown`,
  converging mock reclaim, then the pinned seller separately refunds the payment, still
  held, before selected-site capacity release is confirmed

#### Scenario: A stage fails after the payment is approved

- **WHEN** a stage of the bare-metal payment scenario fails after the buyer approved the payment
- **THEN** the scenario's cleanup refunds the deal's payment if it is not already refunded,
  then reads the deal's fulfillment and tears down a host it finds not yet torn down,
  reading the deal's identifiers from the original run when the purchase command failed
- **AND** a host delivered while the refund was being requested is found and torn down,
  and one whose fulfillment cannot be read or torn down is reported as a failed step
- **AND** a refund the seller refuses because the payment is not yet verified, or the
  payments service or storefront is unavailable, is retried for a bounded time, and a
  refund that still fails fails the scenario naming the negotiation and transaction
- **AND** a failed cleanup step is reported without preventing the later ones, and the
  held loops are resumed whatever an earlier step did

#### Scenario: No payments target is configured

- **WHEN** the bare-metal payment scenario runs with no payments target configured, or an unready external one
- **THEN** it reports a named blocked prerequisite and makes no purchase

#### Scenario: The lane's own payments target is unready

- **WHEN** the bare-metal lane's payments double is not ready
- **THEN** lane setup fails naming it, before any purchase

## ADDED Requirements

### Requirement: An external-topology scenario extends a locally verifiable scenario

An end-to-end scenario that needs services or hosts this repository does not deploy — a
hosted payments target, a real host — MUST extend a locally verifiable scenario that
runs against this repository's own stack. It MUST share that scenario's stages wherever
their bodies agree and add only the stages its external parts require. Setup or teardown
that needs knowledge this repository lacks, such as funding a payer account, MUST be
left to the deployment and MUST NOT be performed by the scenario.

#### Scenario: An external-topology scenario is added

- **WHEN** a scenario needing a real host or a hosted payments target is added
- **THEN** a locally verifiable scenario running the same shared stages runs in a
  pipeline lane, and the external scenario adds only the stages its external parts need

#### Scenario: The deployment has not funded the payer

- **WHEN** an external-topology payment scenario runs and the payer cannot approve
- **THEN** the scenario fails or skips naming the payer, and performs no funding itself

### Requirement: A compute buyer purchase settled through Arkhai payments runs in each compute lane

The VM and bare-metal lanes MUST each run a buyer purchase that discovers, negotiates and
pays through the shipped buyer CLI (`market buy`, `market bare-metal buy`) in
`arkhai.payments.v1` against the lane's payments double, delivers through mock
provisioning, and ends: the VM lease through back-dating and a stepped lease-watchdog
cycle, the bare-metal lease through the buyer's `market bare-metal teardown`. The
purchase stages MUST be defined once and shared by every scenario that buys this way,
and each stage MUST log the identifiers it reads. The bare-metal lane's purchase is its
qualified payment purchase, which runs the shared stages and inserts its own; the VM
lane's purchase lists a resource of its own on a registered host, since a listing's
binding to its resource outlives the listing.

#### Scenario: A VM lane purchase completes

- **WHEN** the VM lane runs its buyer purchase
- **THEN** `market buy` approves the payment, the seller delivers after a verified
  receipt, and back-dating the lease and stepping one watchdog cycle tears the guest down
  and releases its capacity

#### Scenario: A bare-metal lane purchase ends by the buyer

- **WHEN** the bare-metal lane runs its buyer purchase and the buyer runs
  `market bare-metal teardown`
- **THEN** the reclaim runs and the whole host's capacity is restored

#### Scenario: The bare-metal purchase's steps change

- **WHEN** a discovery, purchase, correlation, delivery or buyer-teardown step of the
  bare-metal lane's purchase changes
- **THEN** it changes in the shared stage, and the observation 4 and 5 module runs the
  changed stage without an edit of its own

#### Scenario: A purchase is checked against its payment records

- **WHEN** a buyer purchase completes
- **THEN** each transaction is bound to its Agreement, its receipt covers that mandate,
  its snapshot names the configured payer and payee with gross equal to the Agreement's
  price, and the payer's available balance fell by exactly the scenario's own debits

#### Scenario: The buyer's delivery-end filing reaches no authority

- **WHEN** the bare-metal buyer's teardown files a delivery-end case with a pinned
  dispute authority that does not answer
- **THEN** the scenario neither fails on the filing nor reads it as delivery, access-end
  or refund evidence

### Requirement: Real-provisioning qualification scenarios make the owed observations

External-topology modules MUST extend the buyer purchase to make the runbook's
observations 2, 4, 5 and 6 against a configured real-provisioning target and payments
target. Each MUST belong to no default lane, MUST report a blocked skip without both
targets, MUST skip a stage whose topology input is absent naming that input, and MUST
never wait out the wall clock for a state it can step to.

- Observation 2 MUST buy two CPU-only VMs, hold a heartbeat on the first guest across
  the second's create and teardown, end both leases through the watchdog's expiry path,
  and read the host's diagnostics before, during and after.
- Observations 4 and 5 MUST run the normal bare-metal cycle and then the successor and
  refusal cycle in one module, ending each lease by the buyer's teardown, and check no
  GPU.
- Observation 6 MUST reapply both hosts' canonical registrations and run a publication
  cycle, reading the consumed-UID history through the working-data operator route before
  and after.

A module whose stage fails after the buyer approved a payment MUST, in its cleanup, refund
that payment if it is not refunded, unless the module had begun ending the purchase
itself, and MUST end a delivered guest or host through its lease's own lifecycle; it MUST
report by negotiation and transaction any payment it cannot refund and any delivery it
cannot end. A purchase the module ended itself is left as it is.

#### Scenario: The first session survives the second guest

- **WHEN** the observation 2 module creates and then tears down the second guest
- **THEN** the first guest's heartbeat shows no gap over five seconds and both leases end
  through back-dating and stepped watchdog cycles

#### Scenario: A host service restarts during observation 2

- **WHEN** the host's diagnostics show the management unit's invocation changed, or
  libvirtd's restart count grew, between the reads
- **THEN** the observation 2 module fails naming the unit

#### Scenario: Grant admission is read from the plugin's log

- **WHEN** a relayed lease is delivered and the target names the relay's admission log
- **THEN** the module requires an `admit` line, verified, whose `jti` is the reservation,
  and whose remote port and `kid` are the remote port and grant key that the relay's
  leases read records for that same lease, not the relay's active key

#### Scenario: A topology input is absent

- **WHEN** the target names no management unit or no admission log
- **THEN** the stage that needs it skips naming the field, every other stage runs, and
  each observation that requires the skipped stage is recorded unproven naming the
  field, even when its other stages pass

#### Scenario: The refusal is observed

- **WHEN** the successor cycle's reclaim meets the planted foreign descendant
- **THEN** the reclaim job is queued for retry with its error recorded and a next retry
  time set, its log names the descendant, the lease stays `releasing`, and after
  fixture-only repair the same job completes

#### Scenario: Registration is reapplied

- **WHEN** the observation 6 module reapplies the canonical registrations and runs a
  publication cycle
- **THEN** existing listings are adopted with identities, states and pauses intact, no
  duplicate host, pool, resource, allocator or listing appears, unexpired relay
  quarantine is retained, and the consumed-UID history is unchanged

#### Scenario: A qualification stage fails after the payment is approved

- **WHEN** a stage of a qualification module fails after the buyer approved a purchase's
  payment, before the module ended that purchase
- **THEN** the module's cleanup refunds the payment as the seller, retrying while its
  receipt may still verify, unless the module had begun ending the purchase, then ends
  any guest or host delivered for it through its lease's expiry or reclaim
- **AND** a refund that stays refused, or a delivery that cannot be read or ended, fails
  the cleanup naming the purchase's negotiation and transaction

#### Scenario: No target is configured

- **WHEN** the real-provisioning target or the payments target is absent
- **THEN** each qualification module reports a blocked skip and writes nothing to the
  stack

### Requirement: A real resource's listing offers every composed deal mechanism

On a real-provisioning target, the listing on the target's resource MUST offer a
settlement option for each deal mechanism the storefront composes and reports ready,
Alkahest and Arkhai payments, created or adopted through one shared helper; contact
exchange settles no deal and is stated on no compute listing. A module adopting the
listing MUST require it to offer that module's own mechanism and otherwise MUST fail
naming the listing and its options, changing nothing.

#### Scenario: An Alkahest module and a qualification module share a stack

- **WHEN** both run against one stack composing Alkahest and Arkhai payments, in either
  order
- **THEN** both adopt the same listing, and no second listing is created

#### Scenario: The listing lacks the module's mechanism

- **WHEN** a module finds the resource's listing offering no option of its mechanism
- **THEN** it fails naming the listing and its options before any deal

### Requirement: The real-provisioning target names diagnostics and admission inputs

Target version 2 MUST accept an optional `management_unit` on a VM host, a systemd
service unit name, and an optional `admission_log` on relay access, an absolute
harness-local path. An invalid unit name or a relative path MUST be refused naming the
field.

#### Scenario: A relative admission log path

- **WHEN** a relay access names `admission_log` as a relative path
- **THEN** the target is refused before any stage, naming the field
