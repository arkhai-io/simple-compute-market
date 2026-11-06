## ADDED Requirements

### Requirement: A lease view shows when the lease was activated

The compute contract's lease view MUST carry a nullable `activated_at_utc`, the instant the site's activation recorded, null for a lease whose activation the site has not recorded. It MUST NOT default or infer the instant. Null on a lease that predates the site's activation column MUST NOT be read as evidence that the lease was not delivered. The contract MUST offer no operation that activates a lease: activation is written only through the site's capacity API.

#### Scenario: An activated lease is read

- **WHEN** a VM or bare-metal caller reads an activated lease through the shared client
- **THEN** the lease view carries the instant the site recorded, without the caller importing a VM-specific model

#### Scenario: A lease with no recorded activation is read

- **WHEN** a caller reads a lease the site has not activated, including one that predates activation
- **THEN** its `activated_at_utc` is null, not a default or another instant of the lease
- **AND** for a lease that predates activation, the null says nothing about whether it was delivered

#### Scenario: A caller looks for an activation operation on the contract

- **WHEN** a caller wants to activate a lease
- **THEN** no lease route of the compute contract accepts it, and the caller activates through the site's capacity API
