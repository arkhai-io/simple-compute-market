## ADDED Requirements

### Requirement: Domain-provided buyer integration

The core buyer role MUST obtain domain command registration, provision-terms construction, negotiation policy hooks, and fulfillment-result decoding through the selected market-domain contract rather than concrete-domain imports or name-based branches.

#### Scenario: Buyer invokes a domain command

- **WHEN** a discovered domain command constructs a purchase request
- **THEN** the domain hooks produce versioned provision terms, the core runs schema-opaque orchestration, and the domain decodes the terminal result

#### Scenario: Core runs without a concrete domain

- **WHEN** no domain plugin is installed
- **THEN** generic discovery and diagnostic commands remain available while domain purchase commands are absent

### Requirement: Shared domain conformance suite

Every shipped buyer domain plugin MUST pass one contract suite covering identity, command registration, terms construction, policy integration, and result decoding.

#### Scenario: Domain integration changes

- **WHEN** VM, bare-metal, or API-credit buyer integration is modified
- **THEN** the shared conformance suite runs against that implementation in addition to its domain-specific behavior tests
