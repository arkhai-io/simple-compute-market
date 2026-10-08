## ADDED Requirements

### Requirement: API-credit roots compose peer settlement mechanisms

API-credit buyer and storefront composition roots MUST install Alkahest and `fiat.stripe.v1` through the shared settlement configuration registry and common conditional-settlement runtime. Core and API-credit domain packages MUST remain mechanism/provider opaque; hosted integration MUST come from the shared hosted kit and released client, and Alkahest integration from its kit. An enabled hosted-only composition with Ed25519 role identities MUST start, publish, negotiate, authorize, issue, and service without constructing a wallet, chain client, EVM address, or Alkahest SDK object.

#### Scenario: Hosted-only API-credit storefront starts

- **WHEN** configuration enables only ready hosted settlement with an Ed25519 seller signer
- **THEN** startup registers publication and servicing without resolving wallet/chain configuration or importing a VM/bare-metal package

#### Scenario: Both mechanisms are enabled

- **WHEN** API-credit buyer and seller have valid peer configuration
- **THEN** shared selection/publication/runtime dispatches each accepted obligation to its pinned mechanism with no fallback

### Requirement: API-credit domain injects settlement and fulfillment semantics

The mechanism-neutral runtime MUST own obligation/operation lifecycle while the API-credit domain supplies deterministic interpretation of service, quantity, key mode/key ID, canonical principals, amount, expiry, condition, issuance input, portable evidence, and public receipt/result. Shared hosted buyer transport and storefront servicing MUST be below domain packages or injected through common contracts; API credits MUST NOT import VM transport, provisioning, physical resource, site, executor, or lease semantics.

#### Scenario: Hosted API-credit obligation is prepared

- **WHEN** seller-accepted terms pin a hosted option
- **THEN** the domain produces one deterministic durationless issuance fulfillment input and the shared runtime handles hosted materialization/status/reclaim/collection

#### Scenario: Shared hosted transport changes

- **WHEN** route signing or transient action behavior is updated without changing its public contract
- **THEN** VM and API-credit consumers use the shared implementation rather than maintaining domain copies

### Requirement: API key identity remains domain-owned

Settlement and identity kits MAY carry an opaque API-credit fulfillment/result reference but MUST NOT interpret or persist bearer credentials. The API-credit storefront/credits authority own key ID, secret delivery, canonical key ownership, grant, and consumption behavior. Hosted payer profiles and marketplace principals MUST NOT be used as API bearer credentials; API key IDs/secrets MUST NOT enter hosted authorization, condition evidence beyond public key ID/ownership, or generic settlement logs.

#### Scenario: New key is issued under hosted settlement

- **WHEN** the API-credit fulfillment returns buyer credentials
- **THEN** only the authenticated API-credit buyer result path can retrieve them while common runtime and hosted authority retain secret-free references
