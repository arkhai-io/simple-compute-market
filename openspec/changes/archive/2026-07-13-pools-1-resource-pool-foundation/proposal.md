## Why

Provisioning currently treats every VM host as if it shared one implicit Ansible configuration. That cannot represent multiple operator-managed infrastructure pools, validate provider-specific configuration before use, or preserve stable pool identity for later settlement selection.

PR #134 contains a useful POOLS-1 implementation, but its original branch also includes an obsolete 521-file package and planning rewrite. The resource-pool delta needs to be reconciled onto the current OpenSpec-backed architecture rather than merged wholesale.

## What Changes

- Add persistent resource-pool definitions with stable operator-chosen IDs, lifecycle state, policy tags, and provider-owned configuration.
- Add an Ansible provider configuration implementation while keeping the shared pool contract provider-neutral.
- Assign every provisioning host to a valid pool, defaulting existing and omitted assignments to the system-owned `default` pool.
- Add operator CRUD, canonical YAML export, strict validation, and authoritative reconciliation APIs.
- Add standalone provisioning migration execution, startup schema-drift rejection, and a Helm init container so schema changes are applied before the service starts.
- Reconcile the pool wire models into `arkhai-compute-provisioning`; keep only direct VM administration models and HTTP operations in the VM operator client.
- Preserve the current site-capacity ledger and compute-contract architecture. POOLS-1 records administrative pool membership but does not yet change settlement selection.

## Capabilities

### New Capabilities
- `resource-pool-management`: Operator-managed resource-pool persistence, provider configuration, host assignment, lifecycle, YAML reconciliation, and administrative API behavior.

### Modified Capabilities
- `physical-provisioning`: VM hosts acquire a required resource-pool identity, while physical provisioning execution continues through the existing provider-neutral compute contract.
- `deployment-state`: Provisioning schema migrations run before application startup and the service rejects schema drift rather than mutating its database during startup.
- `site-capacity`: Provisioner-owned pool administration is explicitly non-authoritative for settlement until a later change integrates pool selection through the site-authority boundary.

## Impact

- **Packages:** `provisioning/compute`, `domains/vms/provisioning/client`, and `domains/vms/provisioning/service`.
- **Database:** new `resource_pools` and `ansible_pool_configs` tables; non-null `hosts.pool_id`; ordered migration history advances by one migration.
- **API:** new `/api/v1/pools` administrative surface; host request and response models expose `pool_id`.
- **Deployment:** provisioning Helm deployment gains a migration init container; the service startup path becomes check-only.
- **Compatibility:** old hosts and omitted host assignments map to `default`; pool omission disables rather than deletes; the default pool cannot be disabled.
- **Non-goal:** pool-aware settlement selection remains POOLS-2+ work.
