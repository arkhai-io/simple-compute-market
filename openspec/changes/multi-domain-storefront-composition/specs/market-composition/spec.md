## MODIFIED Requirements

### Requirement: Role-owned executable composition
The buyer executable MUST be core-owned and load domain plugins, and registry behavior MUST be core-owned and schema-configured. Storefront executables MUST assemble the shared storefront role from explicitly registered domain contracts and infrastructure adapters. A compute-family storefront MAY register several domains in one process; a one-domain storefront MUST be the same composition with one explicit registration, not a singleton or alternate role implementation.

#### Scenario: A buyer domain plugin is installed
- **WHEN** the core `market` executable starts
- **THEN** that plugin registers its domain verbs through entry-point composition

#### Scenario: Seller starts a current storefront
- **WHEN** a VM or API-credit storefront is launched
- **THEN** the domain-owned composition root assembles the shared storefront role with that domain's runtime and infrastructure adapters

#### Scenario: A compute-family storefront starts
- **WHEN** VM and bare-metal storefront registrations are configured
- **THEN** one shared role shell validates both exact contracts and exposes one protocol surface whose record-bound selection remains schema-opaque

#### Scenario: A one-domain storefront starts
- **WHEN** an operator configures exactly one supported registration
- **THEN** the same registry, persistence, and selector are used without installing a default-domain or singleton compatibility path

## ADDED Requirements

### Requirement: Storefront domain registrations are explicit and immutable
A storefront domain registration MUST bind one canonical pool offering mode to one exact immutable `MarketDomainContract` identity and supported contract version. Before serving or publishing, composition MUST validate every registered contract and required storefront capability, reject duplicate offering modes or domain identities, and freeze the resulting registry. Core and kit packages MUST NOT import the registered domain implementations.

#### Scenario: VM and bare metal register successfully
- **WHEN** `vm` and `bare_metal` each map to one complete, supported, uniquely identified contract
- **THEN** startup exposes both registrations and neither registration can be replaced or mutated while the process is serving

#### Scenario: Two registrations claim one offering mode
- **WHEN** two configured contracts both claim `vm`, or one domain identity is registered more than once
- **THEN** startup fails with the conflicting mode and domain identities before database recovery, publication, or request handling begins

#### Scenario: A registered contract is unsupported or incomplete
- **WHEN** a registration supplies an unsupported market-contract version or lacks a declared publication, storefront, settlement, or fulfillment hook required by the role
- **THEN** startup fails with the exact registration and missing or unsupported contract detail

### Requirement: Domain selection comes only from immutable record binding
Every domain-sensitive storefront operation MUST select the registered contract from the immutable offering-mode, domain-identity, and contract-version binding recorded for the authoritative listing or accepted negotiation. A request payload, artifact `kind`, current publication setting, installed entry point, registry order, or singleton MUST NOT select or replace that contract. Unknown, missing, or mismatched bindings MUST fail closed without invoking any domain policy, settlement, capacity, fulfillment, result, or teardown effect.

#### Scenario: Request kind contradicts the listing binding
- **WHEN** a buyer sends a bare-metal provision envelope to a listing bound to the VM contract
- **THEN** the storefront rejects the request before domain decoding, thread creation, capacity reservation, or other side effect

#### Scenario: A nonterminal record names an unregistered binding
- **WHEN** startup or recovery encounters a routable record whose exact domain identity/version is absent from the frozen registry
- **THEN** the storefront reports the unknown binding and refuses readiness or recovery rather than trying another version or the only installed domain

#### Scenario: Registration order changes after restart
- **WHEN** the same two exact registrations are supplied in a different configuration order after restart
- **THEN** every persisted record resolves to the same contract and no lifecycle identity or result changes

### Requirement: Shared storefront control flow does not branch on compute domains
Publication, negotiation transport and persistence, settlement servicing, recovery, status/result routing, and teardown control flow MUST remain common across registered compute-family domains. Domain differences MUST enter only through the selected contract's typed codecs and capabilities or through already-defined generic capacity/fulfillment ports; shared handlers MUST NOT contain VM-versus-bare-metal route copies or conditionals.

#### Scenario: A third conforming compute mode is registered later
- **WHEN** a future compute-family contract satisfies the same registration and generic port requirements
- **THEN** the shared role can select it by a new explicit registration without adding another copy of the request, persistence, recovery, or teardown flow
