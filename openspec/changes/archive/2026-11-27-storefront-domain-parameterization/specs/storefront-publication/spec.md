> Permanent destination: `openspec/specs/storefront-publication/spec.md`.

## ADDED Requirements

### Requirement: One startup-selected domain governs a storefront record

For a single-domain storefront process, the contract selected and validated at startup MUST be the sole authority for domain listing normalization, publication projection, negotiation message and terms normalization, accepted settlement-plan construction, fulfillment invocation, and repository rehydration. The role shell MUST fail before the relevant state transition or side effect when the selected contract lacks the required capability.

#### Scenario: Listing is created and published

- **WHEN** the VM storefront accepts a listing and projects it for registry publication
- **THEN** the injected contract validates and normalizes the listing used by both persistence and publication, with no second domain lookup

#### Scenario: Negotiation receives a provision envelope

- **WHEN** the storefront begins or continues a VM negotiation
- **THEN** the injected contract validates the envelope kind and payload before the injected storefront policy runs and the same contract constructs any accepted settlement plan

#### Scenario: Settlement reaches fulfillment

- **WHEN** a verified accepted VM obligation becomes eligible for fulfillment
- **THEN** the fulfillment capability on the startup-selected contract is invoked with the existing stable agreement, obligation, and fulfillment identities

#### Scenario: A required hook is unavailable

- **WHEN** a domain-sensitive path is composed without its required codec or role capability
- **THEN** the storefront is rejected during composition rather than publishing, negotiating, materializing settlement, or provisioning through an assertion, no-op, or fallback

### Requirement: Repository and application domain identity agree

A single-domain storefront application, its lifespan-owned runtime/container, and every repository or role service created for that application MUST retain the same validated contract identity and object. A repository MUST NOT infer domain semantics from row shape, configuration defaults, process-global accessors, or imports of another concrete domain.

#### Scenario: Application lifespan constructs collaborators

- **WHEN** FastAPI enters the VM storefront lifespan
- **THEN** the application state, resolved container, SQLite client, listing service, negotiation callback, settlement composition, and startup workers observe the exact contract selected by the app factory

#### Scenario: Stored artifact is reloaded

- **WHEN** the VM repository reloads a domain artifact needed by publication, negotiation, settlement, or fulfillment
- **THEN** normalization uses its injected contract and does not choose a domain from incidental payload fields or a module singleton

#### Scenario: Runtime components disagree

- **WHEN** composition would connect a repository or service bound to a different contract object or stable identity than the application
- **THEN** composition fails closed before serving requests rather than allowing mixed-domain interpretation

### Requirement: Current single-domain publication behavior remains stable

Parameterizing the VM storefront MUST preserve its current `compute.v1` listing schema, settlement alternatives and deterministic option identities, registry publication ownership, negotiation outcomes, accepted plans, fulfillment ordering, and operator-visible errors. The default executable MUST select the current VM contract explicitly at its outermost root.

#### Scenario: Default VM executable is launched

- **WHEN** an operator starts the unchanged VM storefront command without a new domain-selection input
- **THEN** the executable explicitly constructs and injects the current validated `compute.v1` contract and exposes the same routes and behavior as before

#### Scenario: Existing Alkahest listing is republished

- **WHEN** an existing VM listing is reloaded and published after the internal cutover
- **THEN** its public domain payload, accepted escrow projection, owner principal, listing identity, and settlement semantics remain unchanged

#### Scenario: Bare-metal storefront runs independently

- **WHEN** the bare-metal storefront is built with its existing explicit contract parameter
- **THEN** its runtime, repository, negotiation, and application behavior remain unchanged and it does not import or depend on the VM composition root
