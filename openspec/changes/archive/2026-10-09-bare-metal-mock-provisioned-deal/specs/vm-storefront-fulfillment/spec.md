## ADDED Requirements

### Requirement: A step after physical fulfillment defers a VM deal, never fails it

Once physical fulfillment has produced a running VM, a failure of a later step (storing its
credentials or publishing the fulfillment evidence) MUST NOT mark the escrow failed. The
foreground path MUST report the fulfillment as deferred and leave the escrow unfinished.
Restart convergence MUST then complete the deal from the recorded fulfillment, without
beginning a second one. No step after physical fulfillment writes the lease: the deal's
reservation is committed, beginning its lease and recording its escrow, before its
fulfillment begins, on the foreground path and on restart convergence alike, and
provisioning records the lease's target when the fulfillment becomes active.

#### Scenario: Evidence publication fails after provisioning

- **WHEN** the VM is running and publishing its fulfillment evidence fails
- **THEN** the deal is deferred, and restart convergence publishes the evidence

#### Scenario: Restart convergence recovers a reservation never committed

- **WHEN** restart convergence resumes a deal whose reservation was never committed
- **THEN** it commits the reservation with the deal's window and escrow before beginning
  the fulfillment, and a reservation committed earlier keeps the window its first commit
  recorded

### Requirement: A VM deal records only how to reach its VM

The connection details a VM storefront records for a deal MUST be the delivery's SSH
endpoint (host, port, and tenant account), when access became ready, and the provisioned
resource identities, and nothing else: no guest name, address internal to a host, or key
path. A record with no buyer-facing address MUST omit the host rather than name another.

#### Scenario: A VM becomes ready

- **WHEN** a VM fulfillment becomes active
- **THEN** the storefront records the delivered endpoint, readiness, and resource identities as the deal's connection details

### Requirement: The fulfillment context records the exact request, naming no guest

Before the first recoverable external mutation, the VM storefront MUST persist a versioned `vm.storefront.fulfillment-context` envelope on the primary escrow. Version 1 records the exact normalized VM fulfillment request, listing and order references, lease timing inputs, and escrow identity. The request MUST NOT name the guest, which provisioning names. Credentials and other returned secrets MUST NOT be stored in this envelope.

Unsupported kinds or versions MUST remain operator-visible and MUST NOT be guessed or rewritten silently.

#### Scenario: The recorded request is replayed exactly

- **WHEN** the storefront constructs fulfillment context for an accepted VM deal
- **THEN** it records the exact request it sends to physical fulfillment, naming no guest
- **AND** recovery sends that recorded request unchanged
- **AND** the lease's target is the one provisioning recorded, never the storefront's

#### Scenario: Unsupported context remains visible

- **WHEN** recovery loads an unknown fulfillment-context kind or schema version
- **THEN** it leaves the escrow pending and operator-visible
- **AND** does not guess, rewrite, or replay the unknown payload

## MODIFIED Requirements

### Requirement: Full settlement convergence ownership

The VM storefront MUST own convergence from capacity reservation through physical fulfillment, credential delivery, on-chain fulfillment, listing update, escrow readiness, and settlement-claim creation. It MUST commit the deal's reservation before the fulfillment begins, which begins the lease; it writes nothing to the lease afterwards. The claims engine remains responsible for post-fulfillment claim submission and collection; it does not recover physical fulfillment.

The storefront also carries the client plumbing to request early lease termination (see the Physical Provisioning specification's "Explicit early lease termination" requirement) ahead of any buyer-facing flow that decides when to call it. No such flow exists yet; this is infrastructure for one, not a requirement that early termination currently happens anywhere in this convergence ownership.

#### Scenario: Physical success converges commercial delivery

- **WHEN** physical fulfillment reaches an active result
- **THEN** the storefront records credentials, reconciles on-chain fulfillment, updates the listing, marks the escrow ready, and ensures a settlement claim exists
- **AND** each step is safe to revisit after interruption

## REMOVED Requirements

### Requirement: Versioned fulfillment context

**Reason**: Provisioning names the guest from the capacity reservation, so the storefront
no longer generates a VM target, records one in its fulfillment request, or registers its
lease with one; the requirement's scenario describing that target no longer describes the
system.

**Migration**: Replaced by "The fulfillment context records the exact request, naming no
guest" above, which keeps the envelope, its version, and its recovery rules. Stored
requests are rewritten without the target, on the storefront and in provisioning alike, so
a replayed request still matches the copy provisioning holds.
