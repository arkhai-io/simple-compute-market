## ADDED Requirements

### Requirement: Per-domain end-to-end deal path

Every market domain intended for deployment MUST have an end-to-end scenario proving a
complete deal — discovery, negotiation, settlement, delivery, and teardown — against
running services. A domain's scenario MUST exercise shared fixtures rather than a copy of
another domain's scenario, so domain-neutral test machinery is generalized rather than
duplicated per domain.

#### Scenario: A domain is deployed

- **WHEN** a market domain is intended for deployment
- **THEN** an end-to-end scenario proves a complete deal for it against running services

#### Scenario: A second domain needs a deal path

- **WHEN** an end-to-end deal path is added for another domain
- **THEN** shared fixtures are generalized to serve both, rather than the existing
  scenario being copied and edited

#### Scenario: A domain composes kit runtime

- **WHEN** a domain's storefront is composed from kit-owned runtime
- **THEN** its end-to-end scenario exercises that composition, not a domain-local
  implementation

### Requirement: Bare-metal buyer dependencies point downward

The bare-metal buyer wheel MAY depend on the core buyer role, the core and domain
carriers, the bare-metal domain contract, identity, configuration, and policy kits, shared
settlement registrations and adapters, and released public storefront and registry
clients. It MUST NOT import the bare-metal storefront, another domain's buyer or
storefront implementation, a site, resource-pool, or fulfillment authority
implementation, the compute provisioning service, a provider SDK, an e2e helper, or a
test package, and a package-boundary suite MUST enforce this.

#### Scenario: Package boundary is inspected

- **WHEN** runtime and type-only imports of the built buyer wheel are analyzed
- **THEN** no seller, provisioning, authority implementation, sibling domain buyer, provider SDK, e2e helper, or test package is reachable

#### Scenario: A prerequisite client surface is absent

- **WHEN** the installed public storefront, domain, or settlement client does not expose the accepted result, access, teardown, or mechanism contract the plugin requires
- **THEN** installation, startup, or the affected command fails with a prerequisite-version error; the plugin does not import an implementation package or substitute a local transport
