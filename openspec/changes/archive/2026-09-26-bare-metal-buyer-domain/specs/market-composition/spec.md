## ADDED Requirements

### Requirement: Bare-metal buyer is an independently installable domain plugin

The bare-metal buyer MUST ship as its own wheel and contribute exactly one immutable `MarketDomainContract` through the standard buyer-domain entry-point group. The contribution MUST declare the supported core contract version, unique `bare_metal.v1` identity, strict universal codecs, and a complete buyer capability containing command registration, provision-term construction, policy selection, and result decoding. Installing or removing the wheel MUST add or remove only the bare-metal command namespace; core and other domain behavior MUST remain unchanged.

#### Scenario: Only the bare-metal plugin is installed

- **WHEN** the core buyer and bare-metal buyer wheels are installed without VM or API-credit buyer wheels
- **THEN** `market` discovers a valid `bare_metal.v1` contract and exposes bare-metal commands plus generic core commands without importing another domain

#### Scenario: Several buyer domains are installed

- **WHEN** bare-metal, VM, and API-credit plugins are present together
- **THEN** startup validates all contracts, registers unique namespaces deterministically, and routes a bare-metal command only through the `bare_metal.v1` hooks

#### Scenario: Bare-metal plugin is incompatible

- **WHEN** the wheel declares an unsupported contract version, duplicate domain identity/namespace, missing buyer hook, or wrong identity-injection contract
- **THEN** composition fails before command execution with the offending distribution/domain and supported contract identified

### Requirement: Bare-metal buyer dependencies point downward and across public clients only

The buyer wheel MAY depend on the core buyer role, core/domain carrier, bare-metal domain contract, identity/config/policy kits, shared settlement registrations/adapters, and released public storefront/registry clients. It MUST NOT import the bare-metal storefront, VM or API-credit buyer/storefront implementations, site/resource-pool/fulfillment authority implementations, compute provisioning service or adapter, hosted service implementation/SDK, or test/e2e packages, including under type checking. Seller, site, provisioning, and hosted service behavior MUST cross only their accepted authenticated client contracts.

#### Scenario: Package boundary is inspected

- **WHEN** runtime and type-only imports of the built buyer wheel are analyzed
- **THEN** no seller, provisioning, authority implementation, sibling domain buyer, provider SDK, or test package is reachable

#### Scenario: A prerequisite client surface is absent

- **WHEN** the installed public storefront/domain or settlement client does not expose the accepted result, access, teardown, or mechanism contract required by the plugin
- **THEN** installation/startup or the affected command fails with a prerequisite-version error; the plugin does not import an implementation package or substitute a local transport

### Requirement: Implementation is gated by accepted producer contracts

The bare-metal buyer implementation and acceptance MUST require permanent, shipped, and behaviorally proven contracts for persistent buyer identity injection, exact storefront domain routing, a runnable bare-metal seller, selected-site durable fulfillment/result/teardown, and the selected settlement mechanisms. Active change documents, checked tasks, direct test fixtures, fake lifecycle ports, `fulfillment_available=false` shells, and source-tree imports MUST NOT count as accepted dependencies.

#### Scenario: Runnable seller still lacks fulfillment

- **WHEN** the available bare-metal storefront can negotiate or verify settlement but cannot return authoritative fulfillment result/access and teardown state
- **THEN** the prerequisite gate fails and no test-only success result or direct provisioner client is added to complete the buyer

#### Scenario: Producer contract changes before implementation

- **WHEN** the accepted storefront or settlement carrier differs from the consumer boundary planned by this change
- **THEN** this change's proposal, design, delta requirements, and tasks are reconciled before production code is written
