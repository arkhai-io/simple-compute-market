## ADDED Requirements

### Requirement: Disabling a relay drains it

Disabling a relay MUST drain it: it stops new work on the relay and lets the work already holding a lease on it run to its end, for a VM guest and a bare-metal grant alike. While a relay is disabled, no host in a pool referencing it MAY be among the hosts taking new delivery that the compute composition reports to the site authority, so no claim is admitted against, placed on, or projected enabled for those hosts' declarations; and fulfillment preparation MUST refuse to lease a port on it. A create whose lease was allocated before the disable, and every teardown and reclaim of a delivery leased on the relay, MUST run.

Once a relay is disabled, no lease MUST be allocated on it, whoever asks: the allocator MUST refuse a new owner on a disabled relay, reading the relay under a lock that a concurrent disable cannot pass, so that a disable committed while an acceptance is in flight either waits for it or is seen by it. An owner already holding an active lease on the relay MUST still receive that lease when allocation is repeated. The set of a disabled relay's active leases therefore only shrinks.

Disabling MUST be reversible. Enabling the relay again MUST return its pools' hosts to new delivery and allow allocation on it, whether or not it has drained; disabling removes no proxy, releases no lease, and changes neither the token nor a grant key.

Removing the relay server is its operator's, outside this repository, once the relay has drained. Nothing in the provisioning service deletes a relay: a drained relay's row is kept, disabled, as the record its leases, retired keys, and pool references point at, and it keeps holding its rendezvous, so a server later reinstated at the same rendezvous is the same relay, enabled again.

#### Scenario: A relay is disabled while it carries deliveries

- **GIVEN** a relay holding active leases for a VM guest and a bare-metal grant
- **WHEN** an operator disables the relay
- **THEN** no new claim is admitted against or placed on a declaration of a host in a pool referencing it, those declarations are projected not enabled, and the guest's teardown and the grant's reclaim run when their leases end and release their ports

#### Scenario: A claim reaches fulfillment on a disabled relay

- **WHEN** fulfillment preparation runs for a pool whose relay is disabled
- **THEN** it refuses before leasing a port, naming the relay

#### Scenario: A new owner asks the allocator for a port on a disabled relay

- **GIVEN** a disabled relay, and an owner already holding an active lease on it
- **WHEN** allocation is requested on the relay for a new owner, standalone or in a caller's transaction, and again for the existing owner
- **THEN** the new owner is refused and no lease is recorded for it, and the existing owner receives the lease it already holds

#### Scenario: A relay is disabled while an acceptance is in flight

- **WHEN** a relay's disable commits while a fulfillment acceptance that read the relay enabled has not yet committed
- **THEN** either the disable waits until the acceptance commits, its lease among the relay's active leases, or the acceptance is refused and the relay holds no lease from it; the relay is never reported drained and then holds a new lease

#### Scenario: A relay disabled by mistake is enabled again before it drains

- **GIVEN** a disabled relay still holding active leases
- **WHEN** an operator enables it again
- **THEN** its pools' hosts take new delivery again, allocation on it resumes, and the deliveries it carried were never interrupted

#### Scenario: The definition document stops listing a drained relay

- **WHEN** a relay definition document that listed a relay is reconciled without it
- **THEN** the relay is left as it is, neither deleted nor changed

### Requirement: A relay reports whether it has drained

Every relay read the administrator receives MUST report the relay's number of active leases as `active_lease_count`, and whether it has drained as `drained`: true exactly when the relay is disabled and holds no active lease. An enabled relay MUST NOT be reported drained. Whether a released lease's grant has expired MUST NOT bear on it: a released lease has no proxy left to admit, and once the relay's server, or on a shared relay its keys, is removed, no grant it signed admits anything. The relay's operator relies on `drained` to know the relay may be removed.

Both fields MUST be required in the typed relay response, with no default, so that a client reading a service that does not report them fails to parse the response rather than reading an unknown as drained or not drained.

#### Scenario: A disabled relay still carries a lease

- **WHEN** the administrator reads a disabled relay holding one active lease
- **THEN** the read reports `active_lease_count` 1 and `drained` false

#### Scenario: A disabled relay's last lease is released

- **WHEN** the administrator reads a disabled relay after its last active lease is released, while that lease's grant has not yet expired
- **THEN** the read reports `active_lease_count` 0 and `drained` true

#### Scenario: An enabled relay holds no lease

- **WHEN** the administrator reads an enabled relay holding no active lease
- **THEN** the read reports `drained` false

#### Scenario: A client reads a service that does not report the drain

- **WHEN** the typed relay response parses a relay read carrying neither `active_lease_count` nor `drained`
- **THEN** parsing fails, and no drained value is reported

## MODIFIED Requirements

### Requirement: A relay binding is fixed for a lease's life

The relay a delivery reaches its buyer through MUST be recorded on its port lease at allocation, and that record — not the pool's current configuration — MUST be the authority for which relay that delivery uses, for a VM guest and a bare-metal grant alike. Teardown, reclaim, and reconciliation MUST read the lease. Resolving the relay from pool configuration at teardown would target the wrong relay after any rebinding, releasing a port that was never bound there and leaving bound the one that was.

A pool's relay reference determines which relay a newly created delivery receives. It MUST NOT change the relay of a delivery that already exists.

A host's pool assignment, a pool's relay reference, and a relay's address or port MUST NOT change while any affected host holds an active lease, unless the relay is the same on both sides of the change. The buyer holds a rendezvous address and a port; both are delivered, and a remote port is not portable between relays, so a rebinding that moved existing deliveries would strand every buyer on the affected hosts and request ports the new relay may already have leased.

Rebinding is therefore drain-then-change: disabling a pool already excludes it from new scheduling without invalidating existing workloads, so an operator disables, waits for leases to clear, rebinds, and re-enables. A change on the relay's side — its address or port, or its token — drains the relay instead, since it affects every pool referencing it: the operator disables the relay, waits until it reports drained, makes the change, and re-enables it. A refusal under this rule MUST state the drain at the scope that clears it: the pool for a pool's relay reference or a host's pool, the relay for a relay's address, port, or token.

#### Scenario: A pool's relay reference is changed while VMs are running

- **WHEN** an operator changes a pool's relay reference and a host in that pool holds an active lease
- **THEN** the change is rejected, naming the host and the lease it holds

#### Scenario: A bare-metal pool's relay reference is changed during a lease

- **WHEN** an operator changes the relay reference of a bare-metal pool whose host holds an active grant's lease
- **THEN** the change is rejected, naming the host and the lease it holds

#### Scenario: A pool's relay reference is changed after draining

- **WHEN** the same change is made once no host in the pool holds an active lease
- **THEN** it is accepted, and subsequently created deliveries are allocated on the new relay

#### Scenario: A host moves between pools sharing one relay

- **WHEN** a host is reassigned to a pool referencing the same relay as its current pool, whichever provider each pool uses
- **THEN** the move is accepted regardless of active leases, because no delivered connection string changes

#### Scenario: A relay is repointed while it carries leases

- **WHEN** a relay's address or port is updated and it holds an active lease
- **THEN** the update is rejected, and the refusal tells the operator to disable the relay, wait until it reports drained, make the change, and re-enable it

#### Scenario: A pool's relay reference change is refused

- **WHEN** a change to a pool's relay reference is rejected because a host in the pool holds an active lease
- **THEN** the refusal tells the operator to disable the pool, wait for its leases to be released, make the change, and re-enable it

#### Scenario: A VM is torn down after its pool was rebound

- **WHEN** teardown or reclaim runs for a delivery whose pool now references a different relay
- **THEN** the relay recorded on the delivery's lease is used, and the port is released against it

### Requirement: Relay admission tokens are resolved at execution

A relay's admission token MUST NOT be written into an accepted operation's persisted parameter snapshot, and MUST NOT appear in any job status or job list response. Job parameters are persisted unencrypted and are returned by the job endpoints, so a token placed among them is neither protected at rest nor withheld from a read.

An accepted operation MUST carry the relay reference and the leased remote port. The relay's address and admission token MUST be resolved immediately before the job's variables are written, so that a token rotated after acceptance takes effect on the next execution, including a retry of a job accepted before the rotation.

A relay that is absent, or holds no token at execution, MUST fail the job as a configuration error rather than a retryable one, because a retry against unchanged configuration fails identically. A disabled relay MUST NOT fail a job that holds a lease on it, whether the job adds the delivery's proxy or removes it: disabling a relay drains it, and a drain lets every leased delivery run to its end.

The rendered variables file holds the decrypted token and MUST have the same lifetime and access restrictions as other decrypted secret material on the execution path.

#### Scenario: A job's status is retrieved

- **WHEN** a job dispatched against a relay-backed pool is retrieved through the job endpoints
- **THEN** no admission token appears in the returned parameters

#### Scenario: Stored job parameters are inspected

- **WHEN** the persisted parameters of an accepted operation are read directly from the database
- **THEN** they carry the relay reference and remote port, and no token

#### Scenario: A token is rotated between acceptance and execution

- **WHEN** a relay's token is rotated after a job is accepted and before it executes
- **THEN** the job executes with the rotated token

#### Scenario: A relay becomes unusable between acceptance and execution

- **WHEN** the referenced relay is absent or holds no token when the job executes
- **THEN** the job fails as a configuration error and is not retried

#### Scenario: A relay is disabled between acceptance and execution

- **WHEN** the relay a job's lease names is disabled after the job is accepted and before it executes
- **THEN** the job executes, whether it creates the delivery or tears it down

### Requirement: Disabling a host keeps new deliveries off it

Disabling a registered host MUST keep new deliveries off it: no capacity
declaration naming it, in a backed pool whose provider needs a host, MAY be
admitted against, placed on, or projected enabled while it is disabled. Work
already placed on it MUST be unaffected: an assignment made before the host was
disabled keeps the host, its create waits at dispatch until the host is enabled
again, and teardown and operator jobs run against the host. Enabling the host MUST
lift that restriction: its declarations are then offered as any other declaration
is, subject to their own `enabled`, their pool and its relay, fit, and
availability. The host authority MUST report the hosts it registers and has
enabled, as their identifiers, to the compute composition. The composition MUST
supply the site authority, for admission and its projections, and settlement
scheduling the hosts taking new delivery: those hosts, less every host placed in,
or with a declaration in, a pool referencing a disabled relay ("Disabling a relay
drains it").

#### Scenario: A host is disabled

- **WHEN** an operator disables a host named by an enabled declaration in a backed
  pool whose provider needs a host
- **THEN** a new claim is neither admitted against nor placed on that declaration,
  and the declaration is projected not enabled

#### Scenario: A disabled host already holds an assignment

- **GIVEN** an assignment placed on a host before it was disabled
- **WHEN** the assignment's create is dispatched while the host is disabled
- **THEN** the create is refused and retried, and is submitted once the host is
  enabled again

#### Scenario: A disabled host is enabled again

- **GIVEN** an enabled declaration, in an enabled backed pool whose provider needs
  a host, naming a disabled host
- **WHEN** an operator enables the host
- **THEN** the declaration is again admitted against, placed on, and projected
  enabled as any other eligible declaration is

#### Scenario: A declaration is itself disabled when its host is enabled again

- **GIVEN** a disabled declaration naming a disabled host
- **WHEN** an operator enables the host
- **THEN** the declaration is still neither admitted against, placed on, nor
  projected enabled
