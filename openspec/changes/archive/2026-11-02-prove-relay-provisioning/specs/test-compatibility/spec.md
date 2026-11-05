## MODIFIED Requirements

### Requirement: A real-provisioning VM scenario proves delivery on a real host

A VM scenario MUST exist that runs the canonical compute deal against a provisioning
service outside its mock profile and a real KVM host, and proves what the mock profile
cannot: that the service's VM execution is not mocked; that the create and teardown
jobs ran and succeeded; that the buyer, with the key it negotiated, reaches the VM with
the delivered access as the delivered user and finds the listing shape's vCPU count,
memory within a stated tolerance, and at least its disk; that an unrelated public
key is refused for the delivered user; and that once the lease expires and its
capacity is released the host's VM list no longer names the guest and the delivered
access no longer connects. It makes no claim about the guest's other configured
credentials.

The scenario MUST run under either access mode its target names. Under relay access it
MUST require the delivered address to be the relay's and the port the leased one. In
either mode, between its first deal's access checks and that deal's expiry, it MUST
hold an established session to the first guest while a second deal on the same listing
is created and torn down, and MUST fail if that session ends or stalls beyond a stated
bound; it MUST check the host's connectivity through the provisioning service before
and after each create and teardown; and under relay access it MUST read the relay's
holdings to show the second deal's port released and held by no other lease.

The scenario MUST register the pool, executor host, and capacity declaration it deals
on from its target description, publishing the target's listing shape, and MUST be able
to deal on a shape that declares no GPUs. It MUST keep every worker hold and explicit
advance that exists outside the mock profile, and MUST wait for a real job, found
through its fulfillment's capacity reservation, by reading its state, within a stated
bound, where a mock lane would release a gate. It MUST register the host with the
connection its target describes, replacing the connection of a host an earlier run left
behind, and MUST write nothing to the stack before its target is validated, its VM
execution is found real, and, under relay access, its relay is found enabled with a
token and an active grant key. It MUST NOT submit settlement unless the settlement
preview chose the target host. When it fails after a fulfillment is dispatched and
before its own teardown completes, it MUST truncate each of its live deals' leases so
the provisioning service tears the guests down, and MUST fail naming the fulfillment,
reservation, jobs, guest, and host where removal is not confirmed; it MUST NOT release
reservations beyond its own. It MUST generate the buyer's key for the run and MUST trust
the guest's host key on first use for the run only, failing if a later connection in the
run presents another. It belongs to no default lane and MUST skip, naming the profile
it needs, when its target names no VM host.

#### Scenario: A real deal is delivered

- **WHEN** the scenario runs with a target describing a prepared KVM host
- **THEN** the create job runs on that host, the fulfillment reaches `active`, and the
  buyer's connection with the delivered access shows the delivered user, the listing
  shape's vCPU count, memory within tolerance, and at least its disk

#### Scenario: A relayed deal is delivered

- **WHEN** the target describes the host with relay access
- **THEN** the delivered access names the relay's address and the port leased for the
  guest, and connects

#### Scenario: A session survives a second deal

- **WHEN** a session to the first guest is open while a second deal's guest is created
  and then torn down
- **THEN** the session stays established throughout, the second guest is reached at its
  own port, and its port is shown released afterwards

#### Scenario: An unrelated key is refused

- **WHEN** the scenario connects to the delivered VM as the delivered user with a public
  key it did not negotiate
- **THEN** the connection is refused

#### Scenario: Teardown removes the VM and its access

- **WHEN** the lease is expired and the watchdog and convergence cycles are advanced
  until its capacity is released
- **THEN** the teardown job has succeeded, a VM list job on the host succeeds without
  naming the guest the create job reported, and the delivered access fails to connect
  within the stated bound

#### Scenario: The run fails with a guest on the host

- **WHEN** a stage fails after a fulfillment is dispatched and before the scenario's
  own teardown of it completes
- **THEN** the scenario truncates that deal's lease so the provisioning service tears
  the guest down, and fails naming the fulfillment, reservation, jobs, guest, and host
  where it cannot confirm the guest's removal

#### Scenario: The settlement preview chooses another host

- **WHEN** the settlement preview chooses a host other than the target's
- **THEN** the scenario does not submit settlement

#### Scenario: The service's VM execution is mocked

- **WHEN** the provisioning service reports no VM executor, or reports it mocked
- **THEN** the scenario fails at its first check, before any registration or deal
  mutation, rather than reporting mock delivery as real

#### Scenario: No target is present

- **WHEN** the run does not select the target profile, its file is absent, or it names
  no VM host
- **THEN** the scenario skips with a message naming the profile and file it needs,
  having written nothing to the stack

### Requirement: A real-provisioning target is a typed, versioned settings section

The real-provisioning scenarios' target MUST be read from a versioned settings section
loaded from a profile file the repository ignores, beside a committed example whose
values are visibly fictitious. The section MUST be validated before any stage runs: a
missing or misspelled field MUST fail naming the field, an unknown version MUST be
refused, and a field that does not belong to a host's domain or access mode MUST be
refused. Version 2 describes a list of hosts, at most one per domain, each with its
domain, its identity, the connection the provisioning service reaches it at (address,
user, port, and the path at which the service reads its key), its access — a relay
named by its identifier, or direct access with a tenant address — and the capacity it
sells; a VM host also states the listing shape its scenario publishes, which MUST fit
twice within its capacity, and a bare-metal host its physical machine identity and its
SSH host public key. A relay named by a host is resolved in the provisioning service
that host's scenario runs against. The section MUST NOT carry the private key the
provisioning service reaches hosts with, nor any relay token or key.

#### Scenario: A field is misspelled

- **WHEN** the target section names a field the model does not define, or omits one it
  requires
- **THEN** the scenario fails before its first stage, naming the field

#### Scenario: A newer target reaches an older reader

- **WHEN** the section's version is one the scenario does not know
- **THEN** the scenario refuses it rather than interpreting it

#### Scenario: Relay access is requested under version 1

- **WHEN** a section states version 1, whatever access mode it names
- **THEN** it is refused with a message naming the version 2 profile and how its fields
  map

#### Scenario: A listing shape does not fit twice

- **WHEN** a VM host's listing shape exceeds half its capacity on any dimension
- **THEN** the target is refused, naming the dimension

#### Scenario: Relay access names a tenant address

- **WHEN** a host under relay access states a tenant address, or one under direct access
  names a relay
- **THEN** the target is refused, naming the field

## ADDED Requirements

### Requirement: A real-provisioning bare-metal scenario proves relay access on a real host

A bare-metal scenario MUST exist that runs the canonical compute deal against a
provisioning service outside its mock profile and a real host reached through a relay,
and proves: that the service's bare-metal execution is not mocked; that the grant and
reclaim jobs ran on the target host and succeeded; that the buyer, with a key generated
for the run and negotiated in the deal, reaches the host as the delivered tenant at the
relay's address and the leased port; that an unrelated key is refused; that after the
lease expires and its capacity is released the delivered access no longer connects and
the relay's holdings show the port released; and that the host's connectivity through
the provisioning service holds before and after the grant and the reclaim. It MUST
register its pool, host, and declaration from its target, MUST write nothing before its
target, its execution, and its relay are checked, MUST NOT submit settlement unless the
settlement preview chose the target host, MUST pin the host's key from its target, MUST
truncate its lease on a failure after dispatch so reclaim runs and name what it cannot
confirm, and belongs to no default lane, skipping when its target names no bare-metal
host.

#### Scenario: A relayed bare-metal deal is delivered

- **WHEN** the scenario runs with a target describing a prepared bare-metal host under
  relay access
- **THEN** the grant job succeeds and the buyer connects as the delivered tenant at the
  relay's address and the leased port, while an unrelated key is refused

#### Scenario: Reclaim ends the relayed access

- **WHEN** the lease is expired and the cycles are advanced until its capacity is
  released
- **THEN** the reclaim job has succeeded, the delivered access no longer connects, and
  the relay's holdings show the lease released

#### Scenario: The service's bare-metal execution is mocked

- **WHEN** the provisioning service reports no bare-metal executor, or reports it mocked
- **THEN** the scenario fails at its first check, before any registration or deal
  mutation

### Requirement: Real-lane SSH access goes through one helper

Every end-to-end scenario that opens SSH to a delivered resource MUST do so through one
shared helper, which offers a key generated for the run, trust on first use for a run or
a pinned host key, a session held open with a liveness check, and the classification of
a refused connection.

#### Scenario: A scenario opens SSH

- **WHEN** any end-to-end scenario connects to a delivered guest or host
- **THEN** it uses the shared helper, and no scenario builds its own SSH command
