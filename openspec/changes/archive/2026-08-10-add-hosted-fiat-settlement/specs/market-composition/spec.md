## ADDED Requirements

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
