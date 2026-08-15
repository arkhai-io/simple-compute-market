# Market Composition Specification

## Purpose

Define the dependency direction and role/domain/plugin boundaries that keep market orchestration schema-opaque.
## Requirements

### Requirement: Hosted payer calls bypass storefront without bypassing authority

Composition roots MAY expose exact released-client payer profile/setup/instrument operations and one accepted-obligation funding authorization directly from buyer to hosted authority. Those calls MUST use the selected persistent marketplace signer and authority/environment-scoped opaque binding. Storefronts MUST NOT proxy, choose, or persist payer/instrument state, and buyers MUST NOT call hosted escrow status, reclaim, condition, collection, provider, recovery, or operator surfaces directly.

#### Scenario: Buyer sets a default instrument

- **WHEN** the selected buyer profile performs a released payer instrument operation
- **THEN** the call goes directly to the hosted authority and marketplace state retains only the opaque binding and safe lifecycle projection

#### Scenario: Buyer polls a funded escrow

- **WHEN** a marketplace purchase needs hosted settlement status after start
- **THEN** the buyer uses the authenticated seller storefront rather than the hosted authority

### Requirement: Hosted consumer remains provider-neutral

Marketplace packages, schemas, config, persistence, logs, tests, and deployment MUST use released hosted payer/profile/authorization and conditional-escrow models only. They MUST NOT import Stripe SDK/types, model Customer, PaymentMethod, mandate, charge, debit, bank instruction, transfer, return, refund, dispute, webhook, provider credential/ID, hosted database/migration, reconciliation, or operator recovery behavior.

#### Scenario: Provider behavior changes behind the hosted contract

- **WHEN** the hosted authority changes Stripe adapter implementation without changing its released public contract
- **THEN** marketplace code and configuration require no provider-specific change
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

The hosted-settlement kit MUST contain only the exact manifest-pinned released client dependency, marketplace-to-client configuration conversion, signature injection, safe payer/profile/authorization helpers, and the conditional-escrow adapter. It MUST NOT contain provider logic, copy client wire models or canonicalization, import a service-local module, or own authority persistence/recovery. Core and domain packages MUST depend on the kit/provider-neutral contracts rather than the hosted client or Stripe. Buyer composition MAY use kit-owned direct payer/authorization helpers; storefront composition MUST mediate escrow operations.

#### Scenario: Hosted settlement is installed

- **WHEN** a buyer or storefront enables `fiat.stripe.v1`
- **THEN** it registers the thin kit/client integration in the same settlement runtime or payer namespace and imports no hosted service implementation, marketplace-internal wire copy, or provider code

#### Scenario: Buyer manages payer state

- **WHEN** the Stripe payer command is registered
- **THEN** its implementation is supplied by the hosted kit and persistent identity layer rather than by a domain or core provider model

### Requirement: Thin hosted settlement composition

The marketplace MUST integrate hosted fiat through a foundation-kit adapter registered with the existing settlement runtime. The adapter MAY depend on the released hosted client, core carriers, and settlement runtime, but MUST NOT contain or import the Stripe SDK, EVM/RPC gateway, webhook handling, financial database models, provider credentials/IDs, or duplicate hosted wire/signature implementations.

#### Scenario: VM composition enables hosted settlement
- **WHEN** the pinned hosted client and adapter are configured
- **THEN** VM settlement uses the same obligation records, operation journal, worker, and failure dispatcher as Alkahest with mechanism effects supplied by the adapter

#### Scenario: Other domains are installed
- **WHEN** API-credit or bare-metal packages run without hosted settlement enabled
- **THEN** they acquire no hosted-client or Stripe dependency and their composition remains unchanged

### Requirement: Cross-repository authority boundary

Marketplace code MUST call hosted settlement only through the exact released client; it MUST NOT import, mount, install, or copy the hosted service source, provider adapters, settings, migrations, or financial state. The hosted service MUST remain provider/domain neutral and MUST NOT import marketplace domains. The client package MUST remain the only shared contract and MAY include provider-neutral payer profile, instrument readiness, funding authorization, action metadata, and conditional-escrow wire models.

#### Scenario: Marketplace composes hosted settlement

- **WHEN** a buyer or storefront enables `fiat.stripe.v1`
- **THEN** it supplies typed public config, selected marketplace identity, persistent opaque payer binding where applicable, and domain condition input through the released client without receiving provider credentials or storage access

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

Buyer, registry, storefront, provisioning, and domain composition roots MUST load one selected signer from secret-bound identity configuration and construct only the counterparty verifier registry needed for the role. Hosted buyer composition MUST bind payer/profile and authorization calls to the selected or recorded persistent signer; hosted storefront composition MUST verify accepted buyer identity and use its own signer for mediated escrow calls. Public config, process arguments, logs, and durable public carriers MUST remain credential-free.

#### Scenario: Buyer starts with an Ed25519 profile

- **WHEN** buyer config names an Ed25519 principal and its Secret supplies the matching seed
- **THEN** the buyer composition constructs an Ed25519 signer, selects the matching opaque hosted payer binding, and uses it for payer/authorization calls without loading an EVM private key

#### Scenario: Storefront rotates its signer

- **WHEN** storefront configuration resolves a replacement principal with an old overlapping verifier
- **THEN** the composition signs new hosted escrow requests with the replacement and accepts authenticated peer requests under the declared overlap without changing accepted buyer profile ownership

#### Scenario: Registry serves mixed consumer schemes

- **WHEN** buyer and storefront principals use different supported schemes
- **THEN** the registry verifies both through the marketplace identity kit without selecting a shared secret, wallet, or hosted payer model

#### Scenario: VM composition selects hosted fiat

- **WHEN** the VM root receives an Ed25519 signer and a manifest-compatible hosted adapter
- **THEN** the same scheme-neutral core lifecycle runs without an Alkahest client, wallet derivation, or chain preflight

#### Scenario: A chain mechanism is selected

- **WHEN** a composition selects an Alkahest or other EVM effect
- **THEN** its concrete mechanism adapter resolves the required wallet, chain, and provider dependencies without exposing them to scheme-neutral core orchestration

#### Scenario: Hosted fiat is published

- **WHEN** a composition installs the hosted adapter with a manifest-pinned hosted client
- **THEN** the adapter verifies the required identity capability and delegates the hosted wire contract to that client rather than copying canonicalization, headers, signatures, or response verification

### Requirement: Explicit settlement configuration registration

Composition roots MUST register installed settlement mechanisms with canonical ID, typed config schema, preflight, client factory, option builder, buyer compatibility, and optional operator commands. Core role packages MUST consume only the shared registration/status contract and MUST NOT branch on mechanism IDs or import concrete mechanism configuration.

#### Scenario: Composition omits hosted client

- **WHEN** a domain composition installs only Alkahest
- **THEN** common settlement status, publication, and buyer selection expose only that registration without hosted placeholders or no-op hooks

### Requirement: Shared resources are injected on demand

Identity, wallet, and chain resources MUST be composed independently of settlement mechanism configuration and injected only into registrations that declare them. Installing a non-EVM mechanism MUST NOT require placeholder wallet or chain resources.

#### Scenario: Fiat-only VM storefront starts

- **WHEN** VM composition installs hosted non-EVM settlement with Ed25519 identity and no Alkahest registration
- **THEN** startup, readiness, publication, and servicing succeed without constructing a wallet or chain client

### Requirement: Storefront roots inject one validated domain contract

A domain-owned storefront composition root MUST receive one immutable versioned `MarketDomainContract`, validate it against the executable's supported domain identity and required declared capabilities before constructing role services, repositories, background workers, or the HTTP application, and inject that same contract through every domain-sensitive role boundary. Publication, negotiation, settlement-plan construction, fulfillment dispatch, and persisted domain-artifact normalization MUST NOT discover or replace the contract through module-global state.

#### Scenario: VM storefront starts with its supported contract

- **WHEN** the VM storefront root receives a supported `compute.v1` contract with its complete codec and storefront, publication, settlement, fulfillment, and compute-provisioning hook sets
- **THEN** startup constructs its repository, application, routes, services, and workers around that exact contract object

#### Scenario: Inapplicable contract is supplied

- **WHEN** the VM storefront receives a wrong type, identity, version, undeclared capability, or incomplete required hook set
- **THEN** validation fails before persistence, registry, background-task, or network side effects

#### Scenario: A preceding single-domain database is reopened

- **WHEN** the parameterized executable opens existing VM storefront state with the supported `compute.v1` contract
- **THEN** no schema migration or carrier conversion is required and listing, negotiation, obligation, settlement, fulfillment, and operation identifiers retain their interpretation

### Requirement: Kit-owned capacity and publication lifecycle

The storefront-side multi-site capacity source, exact site projection,
capacity-event reconciliation loop, registry publication, durable publication
result recording, and close/reopen mechanics MUST be owned by one foundation
kit. A composing domain MUST contribute only schema-opaque publication
candidates, listing codecs, candidate reconciliation policy, and durable
binding lookup hooks. The kit MUST NOT import a concrete domain, provider, or
deployed service, and a composing domain MUST NOT retain a parallel capacity or
publication lifecycle.

Every capacity-backed publication candidate MUST carry one exact durable
binding of trusted `site_id`, pool-declared `offering_mode`, and opaque
domain-owned `source_id`. The public offer's mode MUST equal the binding's
mode. Reservation, commit, release, close, reopen, and restart recovery MUST
reload and compare the same binding and MUST NOT infer a home site, default an
offering mode, choose an authority from response data, or fan out after a
binding is recorded.

#### Scenario: A domain publishes a capacity-backed candidate

- **WHEN** the domain derives a schema-valid candidate from a trusted site
  projection
- **THEN** the kit publishes it only after the domain hook confirms that its
  exact site, source, and advertised offering mode equal durable local state

#### Scenario: Capacity changes after publication

- **WHEN** a configured site emits a consuming, releasing, or mixed-direction
  capacity delta
- **THEN** the kit obtains exact site-keyed projections, asks the domain hooks
  for the affected candidates, and executes deterministic close-before-reopen
  reconciliation

#### Scenario: Recovery loses an in-memory routing cache

- **WHEN** commit, release, or fulfillment resumes after restart
- **THEN** the effect is sent only to the site in the persisted binding, and a
  missing or unconfigured binding fails closed without authority fan-out

#### Scenario: A pool cannot deliver the advertised mode

- **WHEN** a candidate's selected Resource Pool does not declare the candidate
  offering mode or its listing codec projects another mode
- **THEN** publication is rejected before registry or capacity effects

## Evidence

- Import boundaries: `core/tests/unit/test_carrier_purity.py` and `domains/vms/storefront/tests/unit/test_architecture_imports.py`.
- Core CLI fallback and shipped plugin contracts: `core/buyer/tests/unit/test_cli.py`, `domains/vms/buyer/tests/test_plugin_export.py`, and `domains/apicredits/buyer/tests/test_plugin_export.py`.
- Distribution entry points: `core/buyer/pyproject.toml`, `domains/vms/buyer/pyproject.toml`, and `domains/apicredits/buyer/pyproject.toml`.
