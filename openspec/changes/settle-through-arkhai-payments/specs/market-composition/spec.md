## REMOVED Requirements

### Requirement: Hosted payer calls bypass storefront without bypassing authority

**Reason**: The hosted Stripe payer-profile, instrument-setup, and funding-authorization API is removed.

**Migration**: Buyer approval and status use the `arkhai.payments.v1` kit and its account-scoped credentials; the storefront does not proxy buyer credential setup.

### Requirement: Hosted consumer remains provider-neutral

**Reason**: The hosted Stripe client and conditional-escrow integration are removed.

**Migration**: The Arkhai payments kit consumes its own published HTTP contract and does not import Stripe or hosted-service code.

### Requirement: Kit-owned single settlement runtime

**Reason**: One shared conditional-escrow runtime does not define the API for charge-first and escrow settlement stages.

**Migration**: Each domain composes its supported settlement stage with its provisioning stage; Alkahest retains escrow-specific lifecycle behavior within its mechanism boundary.

### Requirement: No parallel settlement lifecycle

**Reason**: The requirement enforces one generic escrow lifecycle and its legacy claim-state migration.

**Migration**: Keep one selected settlement stage for each accepted Agreement and remove obsolete hosted routes and aliases; do not create an adapter contract shared by distinct settlement mechanisms.

### Requirement: Thin hosted consumer boundary

**Reason**: The thin `kit/hosted-settlement` boundary is deleted with `fiat.stripe.v1`.

**Migration**: Use the dedicated `kit/arkhai-payments` package for the Arkhai payments API.

### Requirement: Thin hosted settlement composition

**Reason**: The hosted Stripe adapter and hosted client configuration are removed.

**Migration**: Compose `arkhai.payments.v1` as a peer mechanism with a domain-owned provisioning stage.

### Requirement: Cross-repository authority boundary

**Reason**: Its rules describe the removed hosted Stripe service and client.

**Migration**: Use the Arkhai payments authority boundary below; the payments service owns its ledger, credentials, and provider operations.

### Requirement: Bare-metal adopts the shared hosted lifecycle

**Reason**: The shared hosted settlement transport and routes are removed from bare-metal.

**Migration**: Bare-metal composes its supported settlement stage with selected-site provisioning and requires matching mechanism evidence before creating access.

### Requirement: API-credit hosted composition uses shared seams

**Reason**: The hosted Stripe transport, shared settlement routes, and API-credit hosted lifecycle are removed.

**Migration**: API-credit composes its supported settlement stage with credits issuance and requires matching mechanism evidence before issuing credits.

### Requirement: Independent request authentication

**Reason**: The removed hosted client/service signing contract does not describe Arkhai payments authentication.

**Migration**: Use owner-scoped WorkOS API credentials for payment calls and verify Arkhai's signed receipts with the identity kit.
## MODIFIED Requirements


### Requirement: Schema-opaque core orchestration

Core role packages MUST own discovery and negotiation control flow without importing a concrete market domain or settlement mechanism. Core MUST expose the accepted Agreement and settlement-option carriers but MUST NOT impose a shared settlement-stage API or escrow lifecycle on mechanism and domain compositions.

#### Scenario: Installing core without a domain plugin

- **WHEN** the core buyer CLI runs without a domain entry-point plugin
- **THEN** it exposes generic discovery and negotiation behavior and no concrete market verbs or settlement implementation
### Requirement: Composition roots inject signers

Buyer, registry, storefront, provisioning, and domain composition roots MUST load one selected signer from secret-bound identity configuration and construct only the counterparty verifier registry needed for the role. Arkhai payment calls MUST use the appropriate owner's WorkOS user-scoped API credential separately from the marketplace signer. Public config, process arguments, logs, and durable public carriers MUST remain credential-free.

#### Scenario: Buyer starts with an Ed25519 profile

- **WHEN** buyer config names an Ed25519 principal and its Secret supplies the matching seed
- **THEN** buyer composition constructs an Ed25519 signer for marketplace requests without loading an EVM private key

#### Scenario: Storefront rotates its signer

- **WHEN** storefront configuration resolves a replacement principal with an old overlapping verifier
- **THEN** the composition signs new marketplace requests with the replacement and accepts authenticated peer requests under the declared overlap without changing accepted buyer ownership

#### Scenario: Registry serves mixed consumer schemes

- **WHEN** buyer and storefront principals use different supported schemes
- **THEN** the registry verifies both through the marketplace identity kit without selecting a shared secret, wallet, or hosted payer model

#### Scenario: VM composition selects Arkhai payments

- **WHEN** the VM buyer and storefront select `arkhai.payments.v1` with their marketplace signers and owner-scoped payment credentials
- **THEN** the payment calls use the Arkhai account credentials without loading an Alkahest wallet or chain configuration

#### Scenario: A chain mechanism is selected

- **WHEN** a composition selects an Alkahest or other EVM effect
- **THEN** its concrete mechanism resolves the required wallet, chain, and provider dependencies without exposing them to scheme-neutral core orchestration

#### Scenario: Arkhai payments is published

- **WHEN** a composition installs the Arkhai payments kit
- **THEN** it uses the published HTTP and receipt contracts without duplicating their wire encoding, canonicalization, or signature verification

### Requirement: Explicit settlement configuration registration

Composition roots MUST register installed settlement mechanisms with canonical ID, typed config schema, preflight, client factory, option builder, buyer compatibility, and optional operator commands. Core role packages MUST consume only the shared registration/status contract and MUST NOT branch on mechanism IDs or import concrete mechanism configuration.

#### Scenario: Composition omits payments client

- **WHEN** a domain installs only the Alkahest registration and omits the Arkhai payments kit
- **THEN** common status, publication, and buyer selection expose only the installed Alkahest registration without hosted placeholders or no-op hooks

### Requirement: Shared resources are injected on demand

Identity, wallet, and chain resources MUST be composed independently of settlement mechanism configuration and injected only into registrations that declare them. Installing a non-EVM mechanism MUST NOT require placeholder wallet or chain resources.


#### Scenario: Payment-only VM storefront starts

- **WHEN** VM composition installs only `arkhai.payments.v1` with its required payment-service credential
- **THEN** startup, readiness, publication, and payment servicing succeed without constructing an Alkahest wallet or chain client

## ADDED Requirements

### Requirement: Arkhai payment request and receipt authentication

Headless calls to the Arkhai payments service MUST authenticate with WorkOS user-scoped API keys issued for the caller's Arkhai account. Arkhai payment receipts MUST use the service's Ed25519 `arkhai.payments.receipt.v1` signature framing and be verified through the identity kit. Marketplace registry, storefront, and negotiation request authentication MUST remain on their existing contracts and MUST NOT become a cross-repository source dependency.

#### Scenario: Arkhai payment request is authenticated

- **WHEN** a buyer or seller kit calls the Arkhai payments service
- **THEN** the request uses the owner's WorkOS user-scoped API credential, and the caller verifies a returned receipt with the published signature contract rather than copying marketplace request-signing code

### Requirement: Arkhai payments registers as a peer settlement mechanism

A domain composition that supports Arkhai payments MUST register `arkhai.payments.v1` beside `alkahest.v1` through the shared typed settlement registration surface. Selection MUST pin one exact mechanism and option, and core MUST dispatch without a mechanism-specific branch. A domain MUST NOT require or install the Arkhai payments client when that registration is absent.

#### Scenario: A domain registers both peer mechanisms

- **WHEN** a domain installs `alkahest.v1` and `arkhai.payments.v1`
- **THEN** both options appear through their registrations and each accepted Agreement dispatches to its selected settlement stage

#### Scenario: A domain omits Arkhai payments

- **WHEN** a domain installs Alkahest without the Arkhai payments kit
- **THEN** it publishes no Arkhai payment option and acquires no Arkhai payment-service dependency
### Requirement: Deals compose negotiate, settle, and provision stages

A deal MUST flow from negotiation to a selected settlement stage and then to domain provisioning. Negotiation MUST pass its exact accepted Agreement to the selected settlement stage. That stage MUST return its own settlement evidence; the domain's provisioning stage MUST consume that evidence and translate it into the domain's internal paid or ready form. A domain MUST compose only mechanism stages it supports, and each stage MUST understand its predecessor's output rather than a shared escrow adapter API. Settlement and provisioning MAY be fused when one mechanism provides both, as `contact-exchange.v1` does.

#### Scenario: Arkhai payment gates domain provisioning

- **WHEN** the seller settles an accepted Agreement through `arkhai.payments.v1`
- **THEN** VM, bare-metal, or API-credit provisioning remains blocked until the seller verifies a signed receipt matching the transaction ID and Agreement deal hash

#### Scenario: A domain composes two settlement mechanisms

- **WHEN** a domain advertises both Alkahest and Arkhai payment options
- **THEN** its composition routes each accepted Agreement to the selected mechanism stage and passes that stage's evidence to compatible provisioning without a new core mechanism conditional

#### Scenario: A settlement mechanism also provides the service

- **WHEN** a deal selects `contact-exchange.v1`
- **THEN** the composed mechanism may fuse settlement and provisioning into one stage that consumes the negotiation output

### Requirement: Arkhai payments authority remains external

`kit/arkhai-payments` MUST consume the published HTTP and JSON Schema contract from `arkhai-io/arkhai-payments` and MUST generate its Python wire models from that contract rather than importing the service implementation or copying a TypeScript contract. The payments service MUST remain the authority for its ledger, account credentials, fees, hold release, dispute attachment, and payment-provider operations. Marketplace roles MUST NOT own ledger state or implement cash movement, Stripe top-ups, payouts, or provider recovery. The kit MUST keep no settlement servicing state or daemon; headless callers supply owner-scoped credentials for requests and verify service-signed receipts through the identity kit.

#### Scenario: Payments service owns the ledger

- **WHEN** a marketplace domain composes `arkhai.payments.v1`
- **THEN** it uses the external payments API and signed receipt as authority and keeps no local ledger, payment-provider integration, or settlement daemon
