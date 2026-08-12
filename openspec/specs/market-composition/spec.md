# Market Composition Specification

## Purpose

Define the dependency direction and role/domain/plugin boundaries that keep market orchestration schema-opaque.
## Requirements
### Requirement: Schema-opaque core orchestration
Core role packages MUST own discovery, negotiation, settlement, and servicing control flow without importing a concrete market domain or settlement mechanism.

#### Scenario: Installing core without a domain plugin
- **WHEN** the core buyer CLI runs without a domain entry-point plugin
- **THEN** it exposes generic discovery behavior and no concrete market verbs

### Requirement: Domain-owned deterministic semantics
A domain package MUST own the listing, message, terms, materialization, receipt, result vocabulary, and pure interpretation required for independent implementations of that market to agree.

#### Scenario: Adding a market domain
- **WHEN** a new listing schema is introduced
- **THEN** its deterministic codecs and reference semantics can be installed without modifying core orchestration

### Requirement: From-below kit dependencies
Kit and domain concept modules MUST NOT depend on core composition packages; role implementations MAY depend on both the relevant core role and domain/kit contracts.

#### Scenario: Architecture boundary tests run
- **WHEN** imports are checked for core, kit, and domain concept packages
- **THEN** core has no domain imports and from-below modules have no upward composition imports

### Requirement: Role-owned executable composition
The buyer executable MUST be core-owned and load domain plugins, and registry behavior MUST be core-owned and schema-configured. The current VM and API-credit storefront executables and the VM provisioning executable are domain-owned composition roots; making those executables generic is proposed work, not current baseline behavior.

#### Scenario: A buyer domain plugin is installed
- **WHEN** the core `market` executable starts
- **THEN** that plugin registers its domain verbs through entry-point composition

#### Scenario: Seller starts a current storefront
- **WHEN** a VM or API-credit storefront is launched
- **THEN** the domain-owned composition root assembles the shared storefront role with that domain's runtime and infrastructure adapters

### Requirement: Versioned market-domain contract
Core role packages MUST expose one versioned market-domain contract for deterministic codecs and role integration hooks, and concrete domain packages MUST implement that contract without core importing their implementations.

#### Scenario: Shipped domains are loaded
- **WHEN** VM, bare-metal, and API-credit plugins are discovered independently
- **THEN** each satisfies the same supported contract version and registers a unique domain identity without modifying core

#### Scenario: Unsupported contract version is installed
- **WHEN** a domain plugin declares a contract version the role does not support
- **THEN** startup fails with the domain identity and supported version range before serving requests

### Requirement: Explicit optional domain capabilities
A domain MUST declare optional capabilities and supply the typed hook set required by each declaration; absence of a capability MUST be valid and MUST NOT require placeholder or no-op implementations.

#### Scenario: API-credit domain has no compute provisioner
- **WHEN** the API-credit domain is composed without a compute-provisioning capability
- **THEN** buyer and storefront roles remain usable and expose no compute-provisioning hooks for that domain

#### Scenario: Declared capability is incomplete
- **WHEN** a domain declares a capability but omits a required hook
- **THEN** composition rejects the plugin with an actionable capability validation error

### Requirement: Kit-owned single settlement runtime
The mechanism-neutral commercial-settlement lifecycle MUST live in a foundation kit and
MUST be composed by role/domain roots. It MUST use one stable per-obligation identity and
one operation journal for materialization, authoritative status reconciliation, condition
checking, collection, expired reclaim, retries, and uncertain acknowledgements. A domain
MUST supply accepted-plan semantics, fulfillment, configuration, status projection, and
real failure actions; a mechanism kit MUST supply the conditional-escrow adapter. Neither
core carrier packages nor the runtime kit may import a concrete domain or deployed
service.

#### Scenario: A domain settles a deal

- **WHEN** a composing domain accepts and fulfills a settlement obligation
- **THEN** lifecycle transitions and idempotency come from the shared runtime, while the
  domain supplies only its plan, fulfillment, projection, configuration, and actions

#### Scenario: A second settlement mechanism is installed

- **WHEN** a composition registers another conditional-escrow adapter
- **THEN** it uses the same obligation records, operation leases, worker, and aggregate
  status rather than introducing a mechanism-specific lifecycle

#### Scenario: Settlement is interrupted and resumed

- **WHEN** a process stops after an operation is reserved or its acknowledgement is
  uncertain
- **THEN** recovery reloads the exact obligation and stable operation identity and
  reconciles or retries without guessing an obligation or duplicating a financial effect

#### Scenario: A domain has no fulfillment authority

- **WHEN** a domain can verify settlement but cannot produce a real immutable fulfillment
  reference
- **THEN** composition exposes that verified-only boundary and does not install a no-op
  executor, synthetic fulfillment, or collectable claim

### Requirement: No parallel settlement lifecycle

A production composition MUST NOT retain an escrow-UID claim engine, dual-write claim
projection, domain-local settlement orchestration copy, or compatibility alias that can
advance the same obligation outside the shared runtime.

#### Scenario: Legacy claim state is migrated

- **WHEN** existing claim rows are converted into stable obligation records
- **THEN** every immutable snapshot is validated before one atomic conversion, conflicts
  roll back the conversion, and subsequent writes use only the shared runtime

#### Scenario: Domain compensation differs

- **WHEN** VM provisioning, API-credit issuance, or another domain effect fails
- **THEN** the shared ordered dispatcher invokes that domain's registered real actions at
  the existing side-effect boundary and does not interpret domain payloads or invent a
  generic money-movement action

### Requirement: Thin hosted consumer boundary
The VM storefront MAY compose `market_hosted_settlement` over the released
`hosted_settlement_client`, but marketplace packages MUST NOT contain Stripe,
EVM/RPC, webhook, financial database, provider identity, or duplicate
wire/signature implementations. Stripe funds remain platform-custodied; EAS
and arbiter compatibility evaluates only a release predicate and is not
on-chain custody.

#### Scenario: Hosted settlement is installed
- **WHEN** the storefront enables `fiat.stripe.v1`
- **THEN** it registers the thin adapter in the same settlement runtime and
  imports no hosted service implementation or marketplace-internal auth into
  the released client contract

### Requirement: Thin hosted settlement composition

The marketplace MUST integrate hosted fiat through a foundation-kit adapter registered with the existing settlement runtime. The adapter MAY depend on the released hosted client, core carriers, and settlement runtime, but MUST NOT contain or import the Stripe SDK, EVM/RPC gateway, webhook handling, financial database models, provider credentials/IDs, or duplicate hosted wire/signature implementations.

#### Scenario: VM composition enables hosted settlement
- **WHEN** the pinned hosted client and adapter are configured
- **THEN** VM settlement uses the same obligation records, operation journal, worker, and failure dispatcher as Alkahest with mechanism effects supplied by the adapter

#### Scenario: Other domains are installed
- **WHEN** API-credit or bare-metal packages run without hosted settlement enabled
- **THEN** they acquire no hosted-client or Stripe dependency and their composition remains unchanged

### Requirement: Cross-repository authority boundary

The hosted repository MUST own the public HTTP contract/client, Stripe and EAS integrations, connected-account bindings, provider identities, webhook inbox, financial state, condition registry, image/chart, admin tooling, and release process. This repository MUST own market negotiation, accepted plans, fulfillment state, generic lifecycle, VM policy/UX, and the thin adapter. The boundary MUST use released wheels and versioned image/OpenAPI artifacts only; it MUST NOT use a shared database, source path, editable dependency, copied model, or in-repository hosted-service Deployment.

#### Scenario: Hosted contract changes
- **WHEN** the service publishes a new incompatible contract
- **THEN** marketplace CI and readiness reject it until the exact client/manifest pin and conformance fixtures are updated together

### Requirement: Independent request authentication

The hosted client and service MUST use their released body-bound request-signing contract. Existing marketplace registry, storefront, and signed-operation authentication modules and development behavior MUST remain unchanged and MUST NOT become a cross-repository source dependency.

#### Scenario: Hosted request is signed
- **WHEN** the adapter invokes the external authority
- **THEN** signing binds operation, resource, canonical body hash, and timestamp under the released client contract without importing an internal marketplace auth module


### Requirement: From-below identity capability

Canonical principal, signer/verifier dispatch, authenticated-envelope, replay, and rotation contracts MUST live in a foundation kit. Core roles MAY consume that kit, and domain and settlement implementations MAY receive its opaque interfaces, but identity code MUST NOT depend on role composition, a concrete domain, a settlement mechanism, a hosted provider, or chain runtime. Core orchestration MUST carry complete scheme-tagged principals opaquely and MUST NOT interpret identifiers as wallet addresses, provider accounts, or mechanism configuration.

#### Scenario: A new market domain is installed

- **WHEN** the domain composes buyer and storefront roles without blockchain functionality
- **THEN** it can use the shared Ed25519 identity capability without importing an EVM or hosted-provider package

#### Scenario: Core carries a non-chain principal

- **WHEN** registry, negotiation, service-peer, or settlement orchestration receives an Ed25519 principal
- **THEN** it preserves the complete scheme and identifier as the authenticated actor without deriving a wallet, provider account, or chain setting

### Requirement: Composition roots inject signers

Role and domain composition roots MUST construct signers from separately resolved identity credentials and inject them into registry, negotiation, service-peer, and settlement clients. Core/domain APIs MUST NOT select behavior by raw private-key fields or duplicate signer implementations. Concrete domain or settlement adapters MUST own any chain wallet, RPC, or provider dependency and resolve it only after selecting the corresponding mechanism. A hosted-settlement adapter MUST delegate hosted principals, canonical bytes, headers, proofs, and response verification to the exact manifest-pinned released hosted client and MUST verify its advertised identity capability before publishing the hosted option.

#### Scenario: VM composition selects hosted fiat

- **WHEN** the VM root receives an Ed25519 signer and a manifest-compatible hosted adapter
- **THEN** the same scheme-neutral core lifecycle runs without an Alkahest client, wallet derivation, or chain preflight

#### Scenario: A chain mechanism is selected

- **WHEN** a composition selects an Alkahest or other EVM effect
- **THEN** its concrete mechanism adapter resolves the required wallet, chain, and provider dependencies without exposing them to scheme-neutral core orchestration

#### Scenario: Hosted fiat is published

- **WHEN** a composition installs the hosted adapter with a manifest-pinned hosted client
- **THEN** the adapter verifies the required identity capability and delegates the hosted wire contract to that client rather than copying canonicalization, headers, signatures, or response verification

## Evidence

- Import boundaries: `core/tests/unit/test_carrier_purity.py` and `domains/vms/storefront/tests/unit/test_architecture_imports.py`.
- Core CLI fallback and shipped plugin contracts: `core/buyer/tests/unit/test_cli.py`, `domains/vms/buyer/tests/test_plugin_export.py`, and `domains/apicredits/buyer/tests/test_plugin_export.py`.
- Distribution entry points: `core/buyer/pyproject.toml`, `domains/vms/buyer/pyproject.toml`, and `domains/apicredits/buyer/pyproject.toml`.
