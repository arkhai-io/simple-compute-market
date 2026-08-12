## ADDED Requirements

### Requirement: Scheme-neutral storefront authorization

A storefront MUST authenticate publisher, buyer, administrator, and configured service-peer requests through the shared versioned identity contract and MUST authorize complete principals against explicit roles and durable subject bindings. It MUST NOT fall back from missing principal headers to an address in the body, configuration, query, listing, or negotiation record.

#### Scenario: Body claims the expected buyer address

- **WHEN** a request body names the expected buyer but its proof is missing or belongs to another principal
- **THEN** the storefront rejects the request before negotiation, settlement, fulfillment, or operator state changes

#### Scenario: Provisioning peer uses Ed25519

- **WHEN** an allowlisted Ed25519 service principal submits a valid signed response or callback
- **THEN** the storefront authenticates the configured peer and site binding without requiring an EVM identity

### Requirement: Storefront principal is reused without exposing its key

Publication, hosted account ownership, negotiation, and hosted settlement calls MAY use one configured seller principal, but each authority MUST receive only a signer operation or signed proof and MUST enforce its own role binding. Storefront persistence and projections MUST NOT contain the seller's private credential or a Stripe provider identity.

#### Scenario: Storefront publishes a hosted option

- **WHEN** the configured seller principal owns the ready hosted account and signs registry publication
- **THEN** the option contains only the allowed opaque account reference and settlement fields while both authorities bind the same public principal

### Requirement: Storefront identity state migrates atomically

Storefront databases MUST migrate buyer, seller, administrator, service-peer, negotiation, heartbeat, claim, settlement, replay, and audit identities to canonical principal form without changing listing, negotiation, obligation, fulfillment, or operation identities. An unsafe population MUST roll back completely.

#### Scenario: Active hosted obligation is migrated

- **WHEN** a storefront with a funded nonterminal obligation upgrades from address-only identity rows
- **THEN** the obligation retains its authoritative lifecycle and operation journal while its parties become canonical `eip191` principals
