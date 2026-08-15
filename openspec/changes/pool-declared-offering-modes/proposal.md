## Why

Capacity recorded an executor identity but could still infer `vm` from matched-resource attributes or substitute it during release. Resource Pools did not explicitly authorize which offering modes their provider configuration could deliver, so inventory facts and compatibility defaults could widen delivery authority.

## What Changes

- Add a domain-neutral `deliverable_modes` Resource Pool policy declaration with exact-set validation, projection, administration, and deterministic derivation for existing pools.
- Require every capacity probe and reservation claim to carry an explicit canonical `executor_kind`; persist that identity instead of deriving it from resources, market names, or executor defaults.
- Enforce the same pool-declaration membership predicate independently before reservation, scheduling, and provider dispatch.
- Backfill legacy reservation, settlement, and executor identities only from unambiguous durable evidence; quarantine missing or conflicting active identities rather than selecting a compatibility executor.
- Preserve cross-mode physical accounting as an independent constraint: authorization to deliver a mode never authorizes overlapping shareable and exclusive allocations.
- **BREAKING**: absent declarations authorize no offering mode, claims without `executor_kind` are rejected, and narrowing a pool declaration can block later execution of an existing hold.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `resource-pool-management`: Resource Pools declare exact provider-deliverable offering modes through the existing policy-tag channel; malformed declarations fail closed and existing declarations are derived without widening.
- `site-capacity`: capacity requests carry a durable requested executor identity, pool authorization is checked at every execution boundary, and legacy rows without one proved identity are quarantined.

## Non-Goals

- Do not define domain-specific offering-mode names in the resource-pool kit.
- Do not infer provider capability from reservation history, Physical Resource attributes, market names, or registered executors.
- Do not add a second pool-configuration or policy-precedence channel.
- Do not merge pool capability authorization with cross-mode physical accounting.
- Do not change provider implementations, settlement mechanism behavior, or deployment topology.

## Impact

- Affected code: `kit/resource-pools`, `kit/site`, `kit/fulfillment`, compute provisioning migrations and dispatch paths, and VM/bare-metal composition callers that construct capacity claims.
- Affected persistence: pool policy metadata and existing capacity reservation, fulfillment-settlement, and executor-job identities. The migration derives exact pool declarations and backfills or quarantines legacy executor identity.
- Affected wire behavior: capacity probe/reserve claims require `executor_kind`; pool projections and administrative exports expose `deliverable_modes` through existing generic policy tags.
- Affected tests: resource-pool hint/service suites, site ledger, fulfillment scheduling, provisioning migration/integration suites, and deployed refusal evidence.
- Not affected: settlement funding mechanisms, negotiation protocols, provider-specific request/result schemas, packaging boundaries, or deployment topology.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — Resource Pool authority over deliverable modes and separation from physical accounting.
- [x] Existing subsystem specifications — `openspec/specs/resource-pool-management/spec.md` and `openspec/specs/site-capacity/spec.md`.
- [ ] New subsystem specification — none.

### Knowledge to promote

- Exact pool-declared capability, validation, and derivation — `openspec/specs/resource-pool-management/spec.md`.
- Explicit requested identity, legacy quarantine, and three-boundary enforcement — `openspec/specs/site-capacity/spec.md`.
- Authority placement and capability-versus-conflict distinction — `docs/development/ARCHITECTURE.md` and this change's `design.md`.

## Dependencies and Related Changes

- Uses the existing Resource Pool policy-tag projection, precedence, YAML reconciliation, and administration surfaces.
- Uses `executor_kind` as the canonical site/fulfillment executor identity; it does not introduce a second vocabulary.
- Coordinates with `market-platform-compute-40-multi-domain-proof`, which requires removal of the same release fallback but does not own this production migration.
- Independent of settlement mechanism selection and hosted funding work.
