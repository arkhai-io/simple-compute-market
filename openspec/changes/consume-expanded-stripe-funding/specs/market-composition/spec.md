## ADDED Requirements

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

## MODIFIED Requirements

### Requirement: Thin hosted consumer boundary

The hosted-settlement kit MUST contain only the exact manifest-pinned released client dependency, marketplace-to-client configuration conversion, signature injection, safe payer/profile/authorization helpers, and the conditional-escrow adapter. It MUST NOT contain provider logic, copy client wire models or canonicalization, import a service-local module, or own authority persistence/recovery. Core and domain packages MUST depend on the kit/provider-neutral contracts rather than the hosted client or Stripe. Buyer composition MAY use kit-owned direct payer/authorization helpers; storefront composition MUST mediate escrow operations.

#### Scenario: Hosted settlement is installed

- **WHEN** a buyer or storefront enables `fiat.stripe.v1`
- **THEN** it registers the thin kit/client integration in the same settlement runtime or payer namespace and imports no hosted service implementation, marketplace-internal wire copy, or provider code

#### Scenario: Buyer manages payer state

- **WHEN** the Stripe payer command is registered
- **THEN** its implementation is supplied by the hosted kit and persistent identity layer rather than by a domain or core provider model

### Requirement: Cross-repository provider authority

Marketplace code MUST call hosted settlement only through the exact released client; it MUST NOT import, mount, install, or copy the hosted service source, provider adapters, settings, migrations, or financial state. The hosted service MUST remain provider/domain neutral and MUST NOT import marketplace domains. The client package MUST remain the only shared contract and MAY include provider-neutral payer profile, instrument readiness, funding authorization, action metadata, and conditional-escrow wire models.

#### Scenario: Marketplace composes hosted settlement

- **WHEN** a buyer or storefront enables `fiat.stripe.v1`
- **THEN** it supplies typed public config, selected marketplace identity, persistent opaque payer binding where applicable, and domain condition input through the released client without receiving provider credentials or storage access

### Requirement: Composition roots inject signers and public verifier registry

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
