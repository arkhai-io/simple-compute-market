## ADDED Requirements

### Requirement: Deployable bare-metal storefront composition

The repository MUST provide a runnable bare-metal storefront composition that injects one complete bare-metal market-domain contract into the shared storefront role and obtains optional execution through the common compute-provisioning contract. Generic core storefront modules MUST NOT import or branch on bare-metal implementation models.

#### Scenario: Seller starts a bare-metal storefront

- **WHEN** an operator starts the bare-metal storefront with valid seller, registry, settlement, and provisioning-site configuration
- **THEN** the process exposes the shared seller protocol surface with bare-metal publication, negotiation, settlement, fulfillment, receipt, and result hooks

#### Scenario: VM and bare-metal storefronts share a provisioner

- **WHEN** separately composed VM and bare-metal storefronts use one compute provisioner that has both adapter bundles registered
- **THEN** each storefront retains its own market semantics while the provisioner dispatches from the recorded executor identity

#### Scenario: Non-compute storefront is composed

- **WHEN** an API-credit or another non-compute storefront is assembled
- **THEN** it does not require the bare-metal package, compute-provisioning client, or executor adapters
