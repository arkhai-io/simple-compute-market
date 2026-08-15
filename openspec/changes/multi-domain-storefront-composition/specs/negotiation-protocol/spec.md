## ADDED Requirements

### Requirement: Negotiation inherits an immutable listing-domain binding
Creating a negotiation MUST load the authoritative listing and transactionally copy its offering mode, domain identity, and contract version into the new thread before the selected domain policy runs. The opening provision envelope kind/version and normalized payload MUST match that exact registered binding. Caller-supplied discriminator fields MUST be treated only as assertions to validate, never as routing authority.

#### Scenario: A VM opening matches a VM listing
- **WHEN** a buyer opens a negotiation using the supported VM provision envelope against a listing durably bound to the exact VM contract
- **THEN** the thread records that binding atomically with its opening state and the VM policy receives the normalized VM message

#### Scenario: An opening envelope names another domain
- **WHEN** a buyer sends a valid bare-metal envelope to a VM-bound listing
- **THEN** the storefront rejects it before creating a thread, persisting a message, reserving capacity, or invoking either domain policy

#### Scenario: Thread creation fails after binding validation
- **WHEN** persistence of the opening message, parties, or copied binding fails
- **THEN** no partial thread or domain artifact remains and a retry starts from the unchanged listing

### Requirement: Continuation and acceptance use the recorded thread binding
Every continuation, policy decision, Terms reduction, and settlement-plan construction MUST resolve the exact contract from the thread's recorded binding. The current listing state, current registration order, request artifact kind, or another installed contract MUST NOT change an existing thread's domain. A contradictory artifact or missing registration MUST fail without appending protocol state.

#### Scenario: Listing configuration changes during negotiation
- **WHEN** publication configuration or pool mode declarations change after a thread begins
- **THEN** a valid continuation uses the thread's original contract while new opening policy follows the current listing availability

#### Scenario: Continuation artifact contradicts the thread
- **WHEN** a continuation for a bare-metal-bound thread contains a VM message kind
- **THEN** the storefront rejects it without appending a round or changing terminal/agreed state

#### Scenario: Acceptance survives restart
- **WHEN** a process restarts after successful acceptance but before settlement starts
- **THEN** Terms and the settlement plan are rebuilt or loaded through the exact recorded contract and retain the original negotiation and party identities

### Requirement: Accepted domain binding cannot be rewritten
Once a negotiation exists, its offering mode, domain identity, and contract version MUST be immutable. Idempotent persistence of the identical binding is permitted; any attempt to alter one component MUST fail even when no settlement or fulfillment side effect has begun.

#### Scenario: Operator changes the configured contract for a mode
- **WHEN** a stored nonterminal or accepted thread names an earlier exact contract binding and startup configuration maps the same mode differently
- **THEN** the storefront requires the recorded contract registration for that thread and does not rewrite it to the new mapping
