## Context

The provisioning service already owns direct VM host administration and executes VM actions through the provider-neutral compute contract. The site-capacity ledger owns physical resources, reservations, committed allocations, and release state. Resource pools sit between those concerns: operators need a durable administrative grouping and provider configuration, but POOLS-1 must not move settlement selection or duplicate site-capacity state.

PR #134 implemented the core pool behavior on an ancestor branch. Since then, the repository removed the generic `provisioning_client` package, moved shared action and lease contracts into `compute_provisioning`, adopted a site-authority ledger, and converted planning to OpenSpec. The implementation therefore preserves the pool behavior while reconciling package ownership, service composition, migration ordering, and normative artifacts.

## Goals / Non-Goals

**Goals:**
- Persist stable resource-pool identities and provider-owned configuration.
- Make host-to-pool assignment explicit and referentially valid.
- Provide strict, deterministic operator CRUD and YAML reconciliation.
- Establish extension boundaries for future providers without adding provider-specific fields to shared wire models.
- Apply schema changes before service startup and reject schema drift.
- Preserve clean package direction and the current site-capacity/compute-contract implementation.

**Non-Goals:**
- Select a pool during settlement or alter capacity reservation semantics.
- Move physical-resource, allocation, lease, or release ownership out of the site boundary.
- Implement Kubernetes, cloud, or other new providers.
- Recreate the removed generic provisioning client.
- Merge PR #134's unrelated package, documentation, or repository-wide changes.

## Decisions

### 1. Persist pool identity separately from provider configuration

`resource_pools` stores provider-neutral identity and lifecycle fields: `id`, `label`, `provider`, `enabled`, and `policy_tags`. `ansible_pool_configs` stores the Ansible implementation's playbook path, inventory group, and extra variables behind a one-to-one foreign key.

This keeps the core pool row stable when additional provider handlers arrive and avoids nullable columns for every possible provider. Provider handlers own validation, normalization, reads, replacement, and deletion of their configuration.

### 2. Put executor-neutral pool wire models in `compute_provisioning`

Pool request, response, validation, and reconciliation-diff models do not describe VM operations. They are therefore exported from `arkhai-compute-provisioning`. The VM operator client may re-export them for ergonomic API use, but its `models.py` remains limited to direct VM administration shapes.

The provisioning service imports pool models from `compute_provisioning`; no removed `provisioning_client` path or compatibility alias is retained.

### 3. Maintain an always-enabled system default

Migration creates a deterministic `default` Ansible pool before adding `hosts.pool_id`. Existing rows and omitted host assignments use that ID. The default pool must be present in authoritative YAML and cannot be disabled through create, replace, patch, delete, or import behavior.

This preserves existing single-pool behavior while making pool identity non-null. It also prevents new hosts from silently landing in an unusable default.

### 4. Treat DELETE as disable and YAML import as authoritative reconciliation

Individual pool deletion sets `enabled=false`; rows are never hard-deleted because hosts and future settlement records may retain their IDs. Canonical YAML import validates the entire document before opening its write transaction, rejects unknown fields and duplicate IDs, requires the default pool, normalizes every provider configuration, then atomically creates, updates, disables, or leaves pools unchanged.

Validation-only requests return all detectable structured problems and the proposed diff without writes. Export emits the complete canonical document and can be validated or re-imported without semantic change.

### 5. Record membership now; defer settlement selection

`hosts.pool_id` establishes operator-managed membership and is exposed through host create, update, and response models. Existing capacity-ledger selection remains unchanged in POOLS-1. A later POOLS change can consume pool identities and policy tags when choosing settlement resources.

This avoids coupling pool persistence to the executor-adapter interface: adapters validate and execute actions, while pool handlers validate and persist administrative configuration.

### 6. Run migrations before the application process

The provisioning image exposes `python -m db.migrate`; Helm invokes it in an init container with the same image and database configuration. Application startup calls `check_schema_version` only. Migration IDs remain globally ordered: the compute-contract migration precedes the resource-pool migration.

This cleanly distinguishes `Init:Error` migration failures from application crashes and prevents a service process from starting against an older schema.

## Risks / Trade-offs

- **Pool metadata is not yet used by settlement.** The persistence and API are intentionally preparatory; tests and specs state that operational capacity selection remains unchanged.
- **The default pool is a system invariant.** Operators lose the ability to disable it, but this avoids implicit assignment to an unusable pool. Its provider configuration remains replaceable through valid full or partial updates.
- **Provider changes replace configuration.** The old provider configuration is removed within the same database transaction before the new normalized configuration is written. Provider handlers must therefore use the supplied unit of work rather than external side effects.
- **Authoritative omission disables pools.** This is deliberate reconciliation behavior and is surfaced in the dry-run diff. It never deletes rows.
- **Package versions advance.** `arkhai-compute-provisioning` and the VM operator client receive minor version bumps; downstream locks and build ordering must resolve the compute wheel before the client wheel.

## Migration Plan

1. Build and publish `arkhai-compute-provisioning` with pool contracts and handler protocol.
2. Build and publish the VM operator client against that contract.
3. Deploy the provisioning image with the migration init container.
4. The migration creates pool tables, seeds `default` from active provisioning settings, backfills host membership, and records the ordered migration ID.
5. The service starts only after the schema version check passes.
6. Optionally import canonical operator YAML; validate-only first when changing active definitions.

Rollback keeps the additive tables and `hosts.pool_id` in place. Rolling application code back is safe only to a version whose startup schema check accepts the newer migration history; database downgrade is not automated.
