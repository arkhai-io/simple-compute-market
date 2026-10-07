## MODIFIED Requirements

### Requirement: Complete bare-metal seller lifecycle
A bare-metal storefront MUST validate listing, negotiation-message, agreed-terms, settlement materialization, receipt, and access-result artifacts through its installed domain contract. The listing binding MUST freeze the trusted `site_id`, Physical Resource identity, `bare_metal` offering mode, and contract identity/version; the accepted negotiation MUST copy that binding before persisting domain artifacts. Settlement and fulfillment MUST reload that binding and MUST NOT infer a site, executor, URL, credential, or domain from buyer payload data. Fulfillment MUST start when settlement verifies the escrow, through the kit settlement-servicing worker's ready hook, which the storefront composes for every registered settlement mechanism, and MUST NOT wait for a buyer request to begin it or be retried by any other path.

#### Scenario: Buyer accepts a bare-metal listing
- **WHEN** authenticated negotiation accepts valid terms for a trusted listing
- **THEN** the thread persists the canonical buyer and seller principals, exact listing/site/domain binding, agreement payloads, and settlement plan atomically

#### Scenario: Accepted bare-metal agreement is fulfilled
- **WHEN** settlement verifies the escrow
- **THEN** the storefront wakes the settlement-servicing worker for that obligation, whose ready hook dispatches by mechanism to the bare-metal fulfillment, which reserves at the recorded site, commits the reservation with the agreed lease window, schedules the accepted Physical Resource, invokes the recorded bare-metal executor, and persists its reservation, settlement-resource, fulfillment, receipt, and result correlations
- **AND** the commit begins the lease with the window the site records, which the materialization and the delivered evidence state, and provisioning records the lease's target when the fulfillment becomes active, so lease expiry and termination find it

#### Scenario: Fulfillment start is interrupted
- **WHEN** settlement was verified but fulfillment did not start
- **THEN** the settlement-servicing worker's next cycle for that obligation starts it, without a second reservation or a buyer request

#### Scenario: Buyer supplies conflicting routing material
- **WHEN** a request or domain artifact asserts a provisioning URL, credential, different site, Physical Resource, machine, or physical-host identity
- **THEN** the storefront rejects the conflict before a state-changing authority call

#### Scenario: Storefront restarts during fulfillment
- **WHEN** a process restarts after reservation, scheduling, begin, result, or teardown acknowledgement
- **THEN** it reloads the same immutable binding and durable lifecycle references rather than reserving, provisioning, or releasing through another site

#### Scenario: Bare-metal result is returned
- **WHEN** the recorded fulfillment succeeds
- **THEN** the storefront records one buyer-safe `BareMetalReceipt` and `BareMetalResult` (the tenant account, when access became ready, and the lease end) without an endpoint, a private key, provider payload, authority URL, or credential
- **AND** where to connect is served only live, through the access route, while the lease is active

#### Scenario: Bare-metal lease is torn down
- **WHEN** the buyer requests teardown for the completed fulfillment
- **THEN** the storefront terminates the lease at the recorded site, the site's lease lifecycle converges teardown through the recorded fulfillment and releases the capacity reservation exactly once after authoritative teardown success, and the storefront records the release only on the site's capacity-released callback
