## MODIFIED Requirements

### Requirement: Dependency boundary

`market_fulfillment` is a higher kit layer than the site and resource-pool authorities. It may depend on `market_site`, `market_resource_pools` and its wire contracts `market_resource_pools_contracts`, the core carrier package `market_core`, which provides `VersionedEnvelope`, and the foundation migration kit `market_schema_migrations`, through which it exports its schema's migrations. Those lower layers MUST NOT import `market_fulfillment`, including under `TYPE_CHECKING`.

Carrier modules for IDs, envelopes, requests, requirements, resources, and provider protocols MUST remain independent of concrete service implementations. Scheduler modules MAY depend on site and resource-pool service interfaces required to enumerate and bind eligible resources.

#### Scenario: Type-only reverse import is introduced

- **WHEN** `market_site` or `market_resource_pools` imports `market_fulfillment` under `TYPE_CHECKING`
- **THEN** the repository dependency-boundary validation rejects the import as an upward dependency

#### Scenario: A concrete VM adapter implements fulfillment

- **WHEN** the VM provisioning composition registers an Ansible provider
- **THEN** the adapter depends on `market_fulfillment` and VM/Ansible packages while the fulfillment kit remains free of VM vocabulary

## REMOVED Requirements

### Requirement: Existing lease continuity during fulfillment cutover

**Reason**: The cutover it governs (`20260724_001_legacy_vm_leases_to_fulfillment`) is part of compute provisioning's v0.3.0 floor: every database the chain adopts has already run it, and the chain refuses any older database as unsupported, so the cutover and the backfill it ran are deleted with the pre-floor history.

**Migration**: An operator holding a provisioning database from before the marketplace v0.3.0 release starts the service from a fresh database.
