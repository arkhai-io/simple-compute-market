## MODIFIED Requirements

### Requirement: The canonical compute deal's shared stages are defined once

The compute family's canonical complete deal, settled through Alkahest, MUST take each
stage its lanes run identically from one shared definition, whether the lane delivers
through the provisioning mock profile or through a real host. A lane MUST subclass a
shared stage without replacing its body and MUST supply its differences through
fixtures and a per-domain driver. A lane MAY insert stages of its own; a stage whose
body differs between lanes is not shared.

The stages from fulfillment onwards — convergence to active, settlement readiness, the
lease record, lease expiry, teardown dispatch and teardown completion — MUST be keyed on
the deal's settlement reference, which the driver supplies, rather than on an Alkahest
escrow, so the buyer purchase settled through `arkhai.payments.v1` runs the same
definitions.

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
  reference, and keeps its own stages before fulfillment

#### Scenario: A deal outside the canonical deal

- **WHEN** a compute scenario settles another way before fulfillment, or a domain outside
  the compute family runs a complete deal
- **THEN** it keeps its own stages up to fulfillment, and a domain outside the compute
  family keeps all of its own stages

#### Scenario: A compute domain differs in negotiation

- **WHEN** a compute domain would need its own negotiation stage
- **THEN** the difference is resolved in its storefront composition, not in the stage

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
and each stage MUST log the identifiers it reads.

#### Scenario: A VM lane purchase completes

- **WHEN** the VM lane runs its buyer purchase
- **THEN** `market buy` approves the payment, the seller delivers after a verified
  receipt, and back-dating the lease and stepping one watchdog cycle tears the guest down
  and releases its capacity

#### Scenario: A bare-metal lane purchase ends by the buyer

- **WHEN** the bare-metal lane runs its buyer purchase and the buyer runs
  `market bare-metal teardown`
- **THEN** the reclaim runs and the whole host's capacity is restored

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
  whose remote port is the leased port and whose `kid` is the relay's active grant key

#### Scenario: A topology input is absent

- **WHEN** the target names no management unit or no admission log
- **THEN** the stage that needs it skips naming the field, and every other stage runs

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

#### Scenario: No target is configured

- **WHEN** the real-provisioning target or the payments target is absent
- **THEN** each qualification module reports a blocked skip and writes nothing to the
  stack

### Requirement: A real resource's listing offers every composed mechanism

On a real-provisioning target, the listing on the target's resource MUST offer a
settlement option for each mechanism the storefront composes and reports ready, created
or adopted through one shared helper. A module adopting the listing MUST require it to
offer that module's own mechanism and otherwise MUST fail naming the listing and its
options, changing nothing.

#### Scenario: An Alkahest module and a qualification module share a stack

- **WHEN** both run against one stack composing Alkahest and Arkhai payments, in either
  order
- **THEN** both adopt the same listing, and no second listing is created

#### Scenario: The listing lacks the module's mechanism

- **WHEN** a module finds the resource's listing offering no option of its mechanism
- **THEN** it fails naming the listing and its options before any deal

### Requirement: The real-provisioning target names diagnostics and admission inputs

Target version 2 MUST accept an optional `management_unit` on a VM host, a systemd unit
name, and an optional `admission_log` on relay access, an absolute harness-local path.
An invalid unit name or a relative path MUST be refused naming the field.

#### Scenario: A relative admission log path

- **WHEN** a relay access names `admission_log` as a relative path
- **THEN** the target is refused before any stage, naming the field
