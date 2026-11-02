## ADDED Requirements

### Requirement: Arkhai physical qualification uses ordinary buyer settlement

Arkhai real-hardware qualification MUST use the shipped buyer and external payments authority, correlate each signed TEST payment to its physical delivery, and keep buyer credentials separate from operator observations. It MUST report unrun prerequisites and MUST NOT label an unexecuted payment-specific pytest driver passed.

#### Scenario: A real Arkhai rental is qualified

- **WHEN** a configured campaign executes a VM or bare-metal rental using `arkhai.payments.v1`
- **THEN** the buyer negotiates and pays through the shipped client, verifies pinned delivered SSH and the negotiated shape, and observes ordinary teardown, fresh access denial and restored capacity with correlated payment, reservation and job identities

#### Scenario: An operator supplies independent physical observations

- **WHEN** qualification needs host inventory, management continuity or cleanup observations unavailable to the tenant
- **THEN** those observations use a separate operator authority and neither its key nor its management route is available to the ordinary buyer

#### Scenario: A prerequisite or driver is unrun

- **WHEN** a payment, physical target or required observation is missing or a named alternative driver was not executed
- **THEN** qualification records that observation as unproven and does not substitute mock, native component or historical evidence for the missing real lifecycle

#### Scenario: An operator supplements finite host network-policy evidence

- **WHEN** an operator probes the paid deployment's shared host network policy from a separate CPU guest bound to the same pinned guest base, default bridge, virtio NIC, and loaded policy structure
- **THEN** the recorded result is limited to the finite network paths and rules exercised; it does not replace paid-buyer evidence for customer identity, credentials, privilege, grant, GPU work, payment, delivery, teardown, access revocation, or restored capacity, and it does not establish universal network isolation

### Requirement: Equivalent physical proof preserves lifecycle invariants

An alternative payment-specific qualification method MUST retain the original physical acceptance observations: relay and direct VM access, concurrent-deal and management continuity, lease expiry, repeat registration/adoption, bare-metal cleanup and refusal recovery. It MUST recover only its own rentals and preserve relay quarantine and consumed tenant identities.

#### Scenario: Two VM deals share a host

- **WHEN** the second CPU-only VM is created and torn down while the first buyer session is active
- **THEN** the first session and management connection remain usable, both delivered shapes match their agreements, an unrelated key is refused, and ordinary expiry removes each guest and ends access

#### Scenario: Direct access is qualified

- **WHEN** the equivalent VM cycle uses direct access
- **THEN** it runs in a drained controlled pool without exposing host management or rebinding a pool that retains active reservations or relay holdings, and its result is distinguished from external relay acceptance

#### Scenario: Bare-metal cleanup refuses an unsafe descendant

- **WHEN** an ordinary reclaim encounters the nonce-scoped foreign-owned test descendant
- **THEN** capacity remains unavailable, retry and actionable notification are observed, and fixture-only repair permits the same nonterminal job to complete without resetting tenant identity history or bypassing cleanup

#### Scenario: A campaign is repeated

- **WHEN** registrations and listings are reconciled for another qualified cycle
- **THEN** canonical identities are retained, no duplicate allocator is created, and consumed UIDs and unexpired relay quarantine remain protected
