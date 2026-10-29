## MODIFIED Requirements

### Requirement: The canonical compute deal's shared stages are defined once

The compute family's canonical complete deal, settled through Alkahest, MUST take each
stage its lanes run identically from one shared definition, whether the lane delivers
through the provisioning mock profile or through a real host. A lane MUST subclass a
shared stage without replacing its body and MUST supply its differences through
fixtures and a per-domain driver. A lane MAY insert stages of its own; a stage whose
body differs between lanes is not shared.

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

#### Scenario: A real lane runs the canonical deal

- **WHEN** a lane delivers through a real host
- **THEN** it runs every shared stage, none of which calls a mock gate, and its driver
  implements no mock-gate part

#### Scenario: A deal outside the canonical deal

- **WHEN** a compute scenario settles another way, or a domain outside the compute family
  runs a complete deal
- **THEN** it keeps its own stages

#### Scenario: A compute domain differs in negotiation

- **WHEN** a compute domain would need its own negotiation stage
- **THEN** the difference is resolved in its storefront composition, not in the stage

## ADDED Requirements

### Requirement: A real-provisioning VM scenario proves delivery on a real host

A VM scenario MUST exist that runs the canonical compute deal against a provisioning
service outside its mock profile and a real KVM host, and proves what the mock profile
cannot: that the service is not mocked; that the create and teardown jobs ran and
succeeded; that the buyer, holding only the key it negotiated, reaches the VM with the
delivered access as the delivered user and finds the negotiated vCPU count, memory
within a stated tolerance, and at least the negotiated disk; that another key is
refused; and that once the lease expires and its capacity is released the VM no longer
exists on the host and the delivered access no longer connects.

The scenario MUST register the pool, executor host, and capacity declaration it deals
on from its target description, and MUST be able to deal on a shape that declares no
GPUs. It MUST keep every worker hold and explicit advance that exists outside the mock
profile, and MUST wait for a real job, found through its fulfillment's capacity
reservation, by reading its state, within a stated bound, where a mock lane would
release a gate. It MUST register the host with the connection its target describes,
replacing the connection of a host an earlier run left behind. It MUST generate the buyer's key for the run and
MUST trust the guest's host key on first use for the run only, failing if a later
connection in the run presents another. It belongs to no default lane and MUST skip,
naming the profile it needs, when no target description is present.

#### Scenario: A real deal is delivered

- **WHEN** the scenario runs with a target describing a prepared KVM host
- **THEN** the create job runs on that host, the fulfillment reaches `active`, and the
  buyer's connection with the delivered access shows the delivered user, the negotiated
  vCPU count, memory within tolerance, and at least the negotiated disk

#### Scenario: Only the negotiated key is admitted

- **WHEN** the scenario connects to the delivered VM with a key it did not negotiate
- **THEN** the connection is refused

#### Scenario: Teardown removes the VM and its access

- **WHEN** the lease is expired and the watchdog and convergence cycles are advanced
  until its capacity is released
- **THEN** the teardown job has succeeded, the VM no longer exists on the host, and the
  delivered access fails to connect within the stated bound

#### Scenario: The service is mocked

- **WHEN** the provisioning service answers from its mock profile
- **THEN** the scenario fails at its first stage rather than reporting mock delivery as
  real

#### Scenario: No target is present

- **WHEN** the run does not select the target profile, or its file is absent
- **THEN** the scenario skips with a message naming the profile and file it needs

### Requirement: A real-provisioning target is a typed, versioned settings section

The real-provisioning scenario's target MUST be read from a versioned settings section
loaded from a profile file the repository ignores, beside a committed example whose
values are visibly fictitious. The section MUST be validated before any stage runs: a
missing or misspelled field MUST fail naming the field, an unknown version MUST be
refused, and an access mode the version does not admit MUST be refused. Version 1
describes exactly one host — its identity, connection address, connection user and
port, the path at which the provisioning service reads the key it reaches the host
with, its tenant address, and the capacity it sells — and admits only direct access.
The capacity is what the host offers for sale, not its hardware, stated in the VM
capacity dimensions `vcpu_count`, `ram_gb`, and `disk_gb`; the scenario declares it
unchanged and deals on a shape equal to it. The section MUST NOT carry the private key
the provisioning service reaches hosts with.

#### Scenario: A field is misspelled

- **WHEN** the target section names a field the model does not define, or omits one it
  requires
- **THEN** the scenario fails before its first stage, naming the field

#### Scenario: A newer target reaches an older reader

- **WHEN** the section's version is one the scenario does not know
- **THEN** the scenario refuses it rather than interpreting it

#### Scenario: Relay access is requested under version 1

- **WHEN** a version 1 section names an access mode other than direct
- **THEN** the scenario refuses it
