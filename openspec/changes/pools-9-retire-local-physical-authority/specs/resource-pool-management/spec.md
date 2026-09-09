## ADDED Requirements

### Requirement: A pool's executor is fixed at creation

A Resource Pool's provider MUST NOT change after the pool is created. Create
accepts a provider and its configuration; replace and patch MUST reject a request
supplying a provider differing from the pool's own, and MUST NOT delete the
existing provider's configuration as part of rejecting it.

A pool's provider is the routing context every member inherits, so swapping it in
place silently reinterprets which executor the pool's existing inventory belongs
to — the same class of ambiguity this change removes from the storefront side. The
supported path for moving inventory to a different executor is to create a second
pool declaring the intended provider and migrate members across, which leaves both
routing contexts explicit and every member's provider unambiguous at each point.

Provider configuration remains replaceable and patchable within the declared
provider.

#### Scenario: Replace supplies a different provider

- **WHEN** a replace request supplies a provider differing from the pool's own
- **THEN** the request is rejected
- **AND** the pool's provider and its existing provider configuration are unchanged

#### Scenario: Replace supplies the same provider with new configuration

- **WHEN** a replace request supplies the pool's own provider with different configuration
- **THEN** the configuration is replaced and the provider is unchanged

#### Scenario: Inventory moves to a different executor

- **WHEN** an operator needs a member delivered by a different provider
- **THEN** the supported path is a second pool declaring that provider, with the member migrated across
- **AND** no in-place provider change occurs on either pool
