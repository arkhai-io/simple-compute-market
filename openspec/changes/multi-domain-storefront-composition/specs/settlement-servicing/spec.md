## ADDED Requirements

### Requirement: Accepted domain binding governs the entire servicing lifecycle
Settlement verification, plan construction, materialization, condition/effect servicing, fulfillment scheduling and acceptance, status/result projection, recovery, and teardown MUST resolve the exact contract bound to the accepted negotiation. The storefront MUST carry the recorded offering mode into the explicit capacity/fulfillment request required by pool enforcement and MUST preserve the domain's versioned materialization, receipt, and result envelopes. A live listing lookup or a request-supplied domain MAY NOT redirect accepted work.

#### Scenario: VM and bare-metal obligations service concurrently
- **WHEN** one process services an accepted VM negotiation and an accepted bare-metal negotiation
- **THEN** each operation uses only its recorded contract, offering mode, trusted site, domain envelope, and durable operation identities

#### Scenario: A result kind mismatches the accepted domain
- **WHEN** provisioning returns a well-formed bare-metal result envelope for a VM-bound fulfillment
- **THEN** the storefront records a domain/result mismatch, exposes no result through the VM codec, and does not retry through bare metal

#### Scenario: Pool declaration narrows after acceptance
- **WHEN** a mode is withdrawn after an accepted Capacity Reservation or fulfillment exists
- **THEN** recovery and teardown continue under the immutable accepted binding while no fresh reservation or provider dispatch bypasses the pool authority's current enforcement

### Requirement: Recovery resolves domain and site from durable state
Every restart or timer-driven recovery path MUST recover the negotiation's exact domain binding and the recorded trusted site before invoking a domain codec or a state-changing remote call. A missing contract registration, unsupported recorded version, missing site trust binding, or inconsistent copied lifecycle context MUST produce an actionable blocked state with no fallback to another domain, version, site, provider, or executor.

#### Scenario: Restart occurs after fulfillment acceptance
- **WHEN** the storefront restarts after a bare-metal fulfillment ID is persisted but before its active result is observed
- **THEN** recovery polls the recorded site's fulfillment, decodes only with the recorded bare-metal contract, and does not redispatch create

#### Scenario: Restart finds an unknown domain version
- **WHEN** a recoverable accepted row names a domain version absent from the frozen registry
- **THEN** readiness or recovery fails with that exact binding and no settlement, fulfillment, result, or teardown side effect is attempted

#### Scenario: Durable contexts disagree
- **WHEN** an escrow or servicing context names a binding different from its negotiation
- **THEN** recovery reports data-integrity conflict and leaves both records and remote authorities unchanged

### Requirement: Cross-domain failures and teardown remain isolated
A failure, retry lease, result, reclaim decision, or teardown operation for one domain MUST NOT change another domain's listing, negotiation, obligation, capacity binding, fulfillment aggregate, or operation journal. Teardown MUST address the fulfillment identity and trusted site recorded for the accepted negotiation and rely on the provisioning authority's already recorded executor kind; it MUST NOT select an executor from current publication mode.

#### Scenario: VM fulfillment fails while bare metal is active
- **WHEN** a VM provider reports terminal create failure while an unrelated bare-metal lease remains active
- **THEN** only the VM-bound lifecycle transitions or compensates and the bare-metal result and teardown state remain unchanged

#### Scenario: Bare-metal teardown is repeated after restart
- **WHEN** recovery repeats teardown for one accepted bare-metal fulfillment
- **THEN** it addresses the same site and fulfillment identity, observes or advances the same durable teardown, and never invokes the VM executor
