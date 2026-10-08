# VM Storefront Fulfillment

## Purpose

This specification defines how the VM storefront turns an accepted commercial escrow into delivered compute capacity and how unfinished delivery converges after process restart.

## Requirements

### Requirement: Accepted-deal delivery priority

Once a deal has been accepted, commercial delivery takes priority over local bookkeeping durability. The storefront MUST retry and loudly report failed local checkpoint writes, but it MUST NOT abandon an otherwise deliverable VM solely because storefront-local persistence failed. Recovery MUST reconcile authoritative external state when local checkpoints are absent or stale.

#### Scenario: Local checkpoint failure does not abandon delivery

- **WHEN** an accepted deal can still provision and deliver a VM but a storefront-local checkpoint write exhausts its retries
- **THEN** the storefront logs the missing checkpoint at high severity
- **AND** continues the live commercial delivery attempt
- **AND** does not tear down or discard the deliverable VM solely because of that write failure

### Requirement: Versioned fulfillment context

Before the first recoverable external mutation, the VM storefront MUST persist a versioned `vm.storefront.fulfillment-context` envelope on the primary escrow. Version 1 records the exact normalized VM fulfillment request, generated VM target, listing and order references, lease timing inputs, and escrow identity. Credentials and other returned secrets MUST NOT be stored in this envelope.

Unsupported kinds or versions MUST remain operator-visible and MUST NOT be guessed or rewritten silently.

#### Scenario: Generated VM target is preserved exactly

- **WHEN** the storefront constructs fulfillment context for an accepted VM deal
- **THEN** it generates a non-empty VM target once
- **AND** records that exact target in the versioned fulfillment request
- **AND** sends the same target to physical fulfillment
- **AND** uses the same target when registering the VM lease

#### Scenario: Unsupported context remains visible

- **WHEN** recovery loads an unknown fulfillment-context kind or schema version
- **THEN** it leaves the escrow pending and operator-visible
- **AND** does not guess, rewrite, or replay the unknown payload

### Requirement: Full settlement convergence ownership

The VM storefront MUST own convergence from capacity reservation through physical fulfillment, credential delivery, lease registration required by the current teardown path, on-chain fulfillment, listing update, escrow readiness, and settlement-claim creation. The claims engine remains responsible for post-fulfillment claim submission and collection; it does not recover physical fulfillment.

The storefront also carries the client plumbing to request early lease termination (see the Physical Provisioning specification's "Explicit early lease termination" requirement) ahead of any buyer-facing flow that decides when to call it. No such flow exists yet; this is infrastructure for one, not a requirement that early termination currently happens anywhere in this convergence ownership.

#### Scenario: Physical success converges commercial delivery

- **WHEN** physical fulfillment reaches an active result
- **THEN** the storefront records credentials, refreshes the capacity lease, registers the VM lease, reconciles on-chain fulfillment, updates the listing, marks the escrow ready, and ensures a settlement claim exists
- **AND** each step is safe to revisit after interruption

### Requirement: Foreground and restart convergence

The foreground settlement task and the restart worker MUST use the same durable escrow state and replay-safe phase boundaries. The foreground path may continue to wait synchronously, but unfinished primary escrows MUST be discoverable by a dedicated periodic worker registered at storefront startup.

The worker MUST use durable cross-process coordination with an expiring claim. A process-local lock MUST NOT be the correctness boundary.

#### Scenario: Concurrent convergence is excluded durably

- **WHEN** a foreground task or worker holds an unexpired processing claim for an escrow
- **THEN** another process does not concurrently converge that escrow
- **AND** an expired claim can be acquired after the previous owner stops making progress

### Requirement: Physical fulfillment resumption

When a durable fulfillment ID exists, recovery MUST query that fulfillment directly and MUST NOT schedule or begin a replacement fulfillment. Nonterminal provider state remains pending. Active results MUST be fetched and durably recorded. Provider failure MUST use the existing storefront failure policy.

When fulfillment identity is absent, recovery MUST use the persisted exact request and the idempotent reservation, scheduling, and begin-fulfillment contracts rather than generating replacement request values.

#### Scenario: Recovery before fulfillment acceptance

- **WHEN** an unfinished escrow has persisted context but no fulfillment ID
- **THEN** recovery reuses the exact stored request and target
- **AND** reconciles reservation, scheduling, and begin-fulfillment through their idempotent contracts

#### Scenario: Recovery after fulfillment acceptance

- **WHEN** an unfinished escrow has a durable fulfillment ID
- **THEN** recovery polls that fulfillment directly
- **AND** does not schedule a replacement resource or begin a second fulfillment

### Requirement: Aggregate site routing

Restart recovery MUST use the same aggregate capacity and fulfillment clients as foreground settlement. Cold-cache recovery MAY fan out across configured sites using the existing broad fallback policy shared by both aggregate clients. Typed fallback classification is an aggregation-wide concern and is not changed only for fulfillment recovery.

#### Scenario: Cold-cache recovery finds the owning site

- **WHEN** the storefront restarts without an in-memory reservation-to-site route
- **THEN** aggregate recovery fans out across configured sites using the established fallback policy
- **AND** caches and reuses the site that owns the durable reservation or fulfillment

### Requirement: The storefront does not select buyer access infrastructure

The VM storefront MUST NOT supply relay configuration with a fulfillment request. It MUST NOT hold a relay address, a relay credential, or a relay's port allocation window in its settings, and it MUST NOT populate them into the request's connectivity metadata.

Which relay serves a host is a durable property of the deployment that owns the host, recorded against the relay that the host's pool references. A storefront naming a relay per request would make a fleet-wide fact depend on a caller's configuration, and would allow two requests against one host to disagree about how that host is reached.

The buyer-facing address and port are returned to the storefront in the fulfillment result. The storefront learns how a VM is reached after it is provisioned rather than dictating it beforehand, and never holds the credential admitting a client to the relay.

#### Scenario: A storefront is configured with legacy relay keys

- **WHEN** a storefront's provisioning settings carry a relay address, domain, or dashboard credential
- **THEN** those settings are not read and no relay configuration is placed in the fulfillment request

#### Scenario: A VM is provisioned through a relay

- **WHEN** a relay-backed fulfillment succeeds
- **THEN** the storefront obtains the buyer's connection address and port from the fulfillment result

#### Scenario: Two requests target one host

- **WHEN** two fulfillment requests are served by the same host
- **THEN** both are reached through the relay referenced by that host's pool, and no request can select a different one

### Requirement: Ambiguous on-chain submission safety

The pinned Alkahest dependency does not expose discovery of an unknown attestation by `refUID`. The storefront MUST NOT probe guessed or undocumented client methods. A future supported query implementation MAY be injected through the VM settlement adapter's explicit query capability.

When no supported query capability is configured, the storefront MUST NOT blindly resubmit after an unknown transaction outcome. The escrow remains pending, the condition is logged at high severity for operator reconciliation, and commercial delivery already completed MUST NOT be undone. Automatic discovery of an unknown existing attestation is incomplete with `alkahest-py==1.1.2` and is deferred until a supported dependency or `kit/alkahest` abstraction exists.

#### Scenario: Ambiguous submission without query support

- **WHEN** on-chain submission may have succeeded but its fulfillment UID was not persisted
- **AND** no supported attestation query capability is configured
- **THEN** recovery leaves the escrow pending and reports operator action
- **AND** does not call `do_obligation` again

#### Scenario: Supported query capability adopts an attestation

- **WHEN** a supported injected query capability returns an existing matching fulfillment UID
- **THEN** recovery adopts that UID without submitting another obligation
