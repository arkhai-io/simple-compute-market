# VM Storefront Fulfillment

## Purpose

This specification defines how the VM storefront turns an accepted Agreement and verified settlement evidence into delivered compute capacity and how unfinished delivery converges after process restart.

## Requirements

### Requirement: Accepted-deal delivery priority

Once a deal has been accepted, commercial delivery takes priority over local bookkeeping durability. The storefront MUST retry and loudly report failed local checkpoint writes, but it MUST NOT abandon an otherwise deliverable VM solely because storefront-local persistence failed. Recovery MUST reconcile authoritative external state when local checkpoints are absent or stale.

#### Scenario: Local checkpoint failure does not abandon delivery

- **WHEN** an accepted deal can still provision and deliver a VM but a storefront-local checkpoint write exhausts its retries
- **THEN** the storefront logs the missing checkpoint at high severity
- **AND** continues the live commercial delivery attempt
- **AND** does not tear down or discard the deliverable VM solely because of that write failure

### Requirement: A VM deal's lease begins at its reservation commit

The VM storefront MUST commit the deal's reservation with the Agreement's window before fulfillment begins, which begins the lease; afterwards only end service and the site's activation, through the guarded capacity effects, write to the lease. It MUST hold and commit site capacity under the deal's negotiation (`deal_ref.negotiation_id`) whatever the settlement mechanism, with a placement key naming the hold or the settlement placement, so a deal's site reservation is found by its negotiation and carries no settlement reference.

#### Scenario: A payments deal's capacity is held

- **WHEN** a VM storefront holds capacity for an Arkhai payments deal
- **THEN** the hold names the deal's negotiation ID and the `hold` placement and carries no settlement reference, and fulfillment begins only after the reservation is committed

#### Scenario: A ready VM's lease is activated

- **WHEN** a VM deal's fulfillment becomes ready after its Agreement start
- **THEN** the site records the lease's activation and the lease keeps its committed or truncated end

### Requirement: VM settlement stages own their mechanism's steps

The selected settlement stage MUST own mechanism-specific attestation, readiness and claim binding; the claims engine retains submission and collection, not physical recovery. Common delivery MUST consume the stage's evidence and MUST NOT compare mechanism IDs.

#### Scenario: An Alkahest deal is fulfilled

- **WHEN** physical fulfillment of an Alkahest VM deal reaches an active result
- **THEN** the Alkahest stage binds the fulfillment attestation and claim, the claims engine submits and collects, and common delivery records readiness without naming the mechanism or storing credentials

### Requirement: Full settlement convergence ownership

The VM storefront MUST own capacity reservation, physical fulfillment and listing/delivery progress through the compute family's delivery path, and MUST NOT store access material.

#### Scenario: An escrow-settled deal's reservation is looked up

- **WHEN** an operator or test looks up the site reservation of a VM deal settled through Alkahest
- **THEN** it finds the reservation by the negotiation its hold names, not by the escrow

#### Scenario: Physical success converges commercial delivery

- **WHEN** physical fulfillment reaches an active result
- **THEN** the delivery path activates the lease, starts billing through end service, records availability and updates listing/delivery progress, storing no credential
- **AND** the selected Alkahest continuation reconciles on-chain fulfillment, escrow readiness and settlement claims when applicable
- **AND** every step is safe to revisit after interruption

#### Scenario: Payment physical success requires no chain step

- **WHEN** verified payment evidence produces an active VM
- **THEN** common delivery returns the same domain result without creating an escrow claim or choosing a no-chain path by mechanism ID

#### Scenario: Terminal settlement ends a lease

- **WHEN** a VM deal's settlement reaches a terminal state before its lease end
- **THEN** the storefront requests end service, which truncates or terminates the lease

### Requirement: Foreground and restart convergence

Foreground settlement and restart recovery MUST use the same durable negotiation-scoped evidence, exact delivery context and replay-safe phase boundaries. Unfinished delivery MUST be discoverable by the periodic startup worker, including payment work with no escrow row. Foreground and recovery MUST coordinate with a durable expiring claim; process-local locks MUST NOT be the correctness boundary.

#### Scenario: Concurrent convergence is excluded durably

- **WHEN** a foreground task or worker holds an unexpired processing claim for a delivery
- **THEN** another process does not concurrently converge that delivery
- **AND** an expired claim can be acquired after the previous owner stops making progress

### Requirement: Physical fulfillment resumption

When durable fulfillment identity exists, recovery MUST query that fulfillment directly and MUST NOT schedule or begin a replacement. Nonterminal provider state remains pending; an active result MUST yield readiness and resource identities, never stored credentials; provider failure MUST enter the compute delivery path's end hand-off. Without fulfillment identity, recovery MUST reuse the persisted exact request and idempotent reservation/scheduling/begin contracts. Settlement evidence MUST be revalidated by its selected stage before protected effects.

#### Scenario: Recovery before fulfillment acceptance

- **WHEN** an unfinished delivery has persisted context but no fulfillment ID
- **THEN** recovery reuses the exact stored request and target
- **AND** reconciles reservation, scheduling and begin-fulfillment through their idempotent contracts

#### Scenario: Recovery after fulfillment acceptance

- **WHEN** an unfinished delivery has a durable fulfillment ID
- **THEN** recovery polls that fulfillment directly
- **AND** does not schedule a replacement resource or begin a second fulfillment

### Requirement: Aggregate site routing

Restart recovery MUST use the same aggregate capacity and fulfillment clients as foreground settlement. Cold-cache recovery MAY fan out across configured sites using the existing broad fallback policy shared by both aggregate clients. Typed fallback classification is an aggregation-wide concern and is not changed only for fulfillment recovery.

#### Scenario: Cold-cache recovery finds the owning site

- **WHEN** the storefront restarts without an in-memory reservation-to-site route
- **THEN** aggregate recovery fans out across configured sites using the established fallback policy
- **AND** caches and reuses the site that owns the durable reservation or fulfillment

### Requirement: The storefront does not select buyer access infrastructure

The VM storefront MUST NOT supply relay configuration with a fulfillment request. It MUST NOT hold a relay address, a relay credential, or a relay's port allocation window in its settings, and the request it sends MUST carry no `connectivity` field, which provisioning refuses.

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

### Requirement: A step after physical fulfillment defers a VM deal, never fails it

Once physical fulfillment has produced a running VM, a failure of a later bookkeeping step (recording readiness, activating the lease when the site cannot be reached, starting billing, or publishing the fulfillment evidence) MUST NOT mark the deal's delivery failed. The foreground path MUST report the fulfillment as deferred and leave delivery unfinished, and restart convergence MUST complete the deal from the recorded fulfillment, without beginning a second one. The only lease writes after physical fulfillment are the site's activation and end service's truncation or termination. An activation the site refuses because the lease was released or expired MUST enter the end hand-off instead.

#### Scenario: Evidence publication fails after provisioning

- **WHEN** the VM is running and publishing its fulfillment evidence fails
- **THEN** the deal is deferred, and restart convergence publishes the evidence

#### Scenario: Restart convergence recovers a reservation never committed

- **WHEN** restart convergence resumes a deal whose reservation was never committed
- **THEN** it commits the reservation with the deal's Agreement window and negotiation before beginning
  the fulfillment, and a reservation committed earlier keeps the window its first commit
  recorded

#### Scenario: Activation loses to expiry

- **WHEN** a running VM's activation is refused and the lease reads as released
- **THEN** the deal goes to the end hand-off rather than being deferred again

### Requirement: A VM deal records only how to reach its VM

The connection details a VM storefront records for a deal MUST be the delivery's SSH endpoint (host, port, and tenant account), when access became ready, and the provisioned resource identities, and nothing else: no credential, guest name, address internal to a host, or key path. A record with no buyer-facing address MUST omit the host rather than name another. `settle` and `settle-status` MUST obtain credentials live through the compute delivery path's access check and MUST declare themselves credential-capable, so an exact retry reads again rather than replaying a recorded body.

#### Scenario: A VM becomes ready

- **WHEN** a VM fulfillment becomes active
- **THEN** the storefront records the delivered endpoint, readiness, and resource identities as the deal's connection details, and no credential

#### Scenario: The buyer polls settlement status

- **WHEN** the buyer reads `settle-status` for an available deal
- **THEN** the response's credentials come from a live read of the fulfillment result

#### Scenario: A former credential response is retried

- **WHEN** an exact retry of an earlier `settle-status` request arrives after a locally admitted end
- **THEN** it is refused, and no stored credential or recorded body is returned

#### Scenario: A storefront upgrades with recorded credential responses

- **WHEN** a VM storefront starts on a database whose replay records hold bodies carrying `tenant_credentials`
- **THEN** every recorded body loses its `tenant_credentials` member, whatever route wrote it, and each record keeps its status and remains a completed outcome

### Requirement: The fulfillment context records the exact request, naming no guest

Before the first recoverable external mutation, the VM storefront MUST persist a versioned `vm.storefront.fulfillment-context` envelope linked to its negotiation and verified SettlementEvidence. Version 1 records the exact normalized VM fulfillment request, listing and order references, lease timing inputs, and the opaque settlement reference. The request MUST NOT name the guest, which provisioning names. Credentials and other returned secrets MUST NOT be stored in this envelope, and payment context MUST NOT be stored as an escrow row.

Unsupported kinds or versions MUST remain operator-visible and MUST NOT be guessed or rewritten silently.

#### Scenario: The recorded request is replayed exactly

- **WHEN** the storefront constructs fulfillment context for an accepted VM deal
- **THEN** it records the exact request it sends to physical fulfillment, naming no guest
- **AND** recovery sends that recorded request unchanged
- **AND** the lease's target is the one provisioning recorded, never the storefront's

#### Scenario: Unsupported context remains visible

- **WHEN** recovery loads an unknown fulfillment-context kind or schema version
- **THEN** it leaves delivery pending and operator-visible
- **AND** does not guess, rewrite, or replay the unknown payload

### Requirement: VM role tables gate evidence-based delivery

VM buyer and seller roles MUST declare their supported settlement stages once and dispatch accepted Agreements through those tables. Each stage MUST verify its authoritative source and supply validated delivery facts in SettlementEvidence. Planners MUST read those facts, not decode payment receipts, compare IDs or require Alkahest token policy for every mechanism.

#### Scenario: Lease encoding differs between stages

- **WHEN** Alkahest and payment stages authorize equivalent VM capacity
- **THEN** each stage supplies its required lease/condition encoding and the shared planner builds the physical request without a mechanism switch

### Requirement: VM evidence and delivery progress are not payment escrows

VM settlement evidence and payment delivery checkpoints/claims MUST be domain-owned negotiation-scoped records, not `escrows` rows with absent or sentinel chain fields. Incompatible evidence/delivery schemas MUST require explicit database reset rather than legacy-row copying or compatibility fallback. Real Alkahest escrow and obligation state MAY remain in their existing owners.

#### Scenario: Payment delivery is pending

- **WHEN** a verified payment is waiting for physical fulfillment
- **THEN** its evidence, immutable context, phase progress and convergence claim are recoverable without any payment escrow row

#### Scenario: Evidence is reused for another accepted state

- **WHEN** the same negotiation evidence is written with a different mechanism, Agreement digest or established settlement reference
- **THEN** the repository rejects the conflicting write before protected delivery

#### Scenario: A fresh VM schema boots

- **WHEN** its introducing migrations bootstrap a new database and rerun
- **THEN** evidence/delivery tables exist idempotently without a copy-then-drop migration

#### Scenario: Verified VM evidence is malformed

- **WHEN** a write proposes verified evidence without a SHA-256 Agreement digest, authoritative source, or supported validated `vm.delivery-facts` version 1 payload
- **THEN** storage refuses before freezing an authoritative record or creating delivery progress

### Requirement: VM buyers can end delivery through end service

The VM storefront MUST accept the accepted buyer's `end_delivery` peer message through the shared lifecycle route and realize it through end service, including before fulfillment begins. When the end is due it MUST invoke the site's termination or undelivered-hold release path immediately, not truncate to now and wait for a watchdog. Its signed response MUST distinguish a recorded end from proven capacity release.

#### Scenario: A buyer ends before provisioning

- **WHEN** a committed VM deal's buyer sends `end_delivery` while no resource has been dispatched
- **THEN** the storefront records the end, releases any undelivered hold and prevents later reconciliation from starting delivery

#### Scenario: A buyer ends a running VM

- **WHEN** the accepted buyer sends `end_delivery` for a running VM
- **THEN** end service requests termination at its recorded site and reports teardown progress until the site's capacity-released callback proves capacity return

### Requirement: VM lease ends keep the requested instant

The VM storefront MUST send and record lease ends to at least one-second precision, and MUST still read lease ends already recorded to the minute.

#### Scenario: A lease is truncated mid-minute

- **WHEN** end service truncates a VM lease to 12:00:30
- **THEN** the site receives 12:00:30, not 12:00 or 12:01
