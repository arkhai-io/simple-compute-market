## Why

The deployable compute provisioner still lives under `domains/vms` even though it owns shared job, capacity, lease, fulfillment, and VM/bare-metal executor orchestration. POOLS-3 has also landed mechanism-neutral provider contracts plus a concrete VM-service-local fulfillment coordinator and provider registration. After the shared site and wire contracts are stable, moving that composition root to `provisioning/compute` makes ownership explicit and lets each compute domain retain only its concrete semantics, executor adapter, and fulfillment-provider implementation.

## What Changes

- Move generic API assembly, job lifecycle, executor-neutral lease lifecycle, watchdog scheduling, capacity mounting, fulfillment coordination, health surfaces, and executor/provider registration to `provisioning/compute/service`.
- Define the compute provisioner composition root and load VM and bare-metal routers, action factories, executors, fulfillment providers, readiness checks, and optional operator surfaces as domain adapters.
- Keep VM KVM/Ansible behavior, `AnsibleFulfillmentProvider`, VM fulfillment requirements, playbooks, direct VM routes, and result interpretation in `domains/vms`.
- Keep bare-metal access grant/reclaim behavior, routes, and result interpretation in `domains/bare_metal`.
- Add supported API and worker console entry points, package metadata, Dockerfile/image, and deployment configuration for the extracted service.
- Migrate all callers and images, then remove the old VM-owned generic service paths and compatibility shims.
- **BREAKING**: generic provisioning package/import ownership and deployment image names change in one clean cutover.
- State: **Unblocked, not started.** `market-platform-compute-10-site-lifecycle`
  and `market-platform-compute-20-provisioning-contract` archived
  2026-07-13. `tasks.md` is still fully unchecked as of 2026-07-17 —
  verified against the task list, not assumed.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `physical-provisioning`: Cross-domain compute orchestration runs from a compute-owned service that composes domain-owned VM and bare-metal executor adapters.
- `deployment-state`: The extracted package and image expose supported launch commands, own their runtime dependencies, and preserve service-owned migration and persistence behavior.

## Non-Goals

- Do not move deterministic VM or bare-metal schemas, policies, playbooks, or operator-specific implementations into the generic provisioner.
- Do not add provisioning methods to market domains that do not use compute provisioning.
- Do not redesign the compute wire during package movement; that contract lands first.
- Do not preserve old VM-owned generic packages, aliases, or images after every in-repository caller migrates.
- Do not add multi-site deployment proof; this change establishes one extracted service with both current compute adapters.
- Do not redesign POOLS-3's one-pool/one-provider resource model or add multiple provider bindings for one physical resource; that is separate follow-on work.

## Absorbed from POOLS-5 (closed 2026-07-17)

`pools-5-shared-provisioning-package` is closed and archived at
`openspec/changes/archive/2026-07-17-pools-5-shared-provisioning-package/`.
It never reached its activation condition, and this change already claimed
ownership of resolving its package-boundary question, so its scope is
folded in here rather than tracked in two places. Concretely:

- **Resolved by `pools-7-storefront-fulfillment-cutover`'s design review
  (2026-07-17), ahead of this change's own extraction work:**
  `PhysicalSettlementScheduler` and `DeterministicRoundRobinPolicy` move
  from VM-service-local code into `compute_provisioning` — not into
  `kit/resource-pools`, which would close a circular dependency
  (`compute_provisioning` already depends on `kit/resource-pools`; the
  scheduler needs real runtime imports from `compute_provisioning`'s
  settlement types, unlike `FulfillmentProvider`'s string-quoted forward
  references). `FulfillmentProvider`/`ProviderRegistry`/error taxonomy
  remain in `kit/resource-pools`, per `pools-3`'s original placement.
  `pools-2`'s scheduling/request contracts (`PhysicalSettlementRequest`,
  `SettlementResource`, `SettlementCandidate`, `SettlementRequirement`,
  `SettlementSchedulingPolicy`) already lived in `compute_provisioning`
  before this. See `pools-7`'s `design.md`, "`PhysicalSettlementScheduler`
  and `DeterministicRoundRobinPolicy` move to `compute_provisioning`."
  This is the same kind of narrow, deliberate override of waiting for this
  change's activation that `pools-3` already made once for
  `FulfillmentProvider`/`ProviderRegistry` — resolving where a class lives
  is not this change's service-extraction scope, and this proposal's task
  list (§1) should verify the moved location during "Verify Prerequisites
  and Current Ownership" rather than treat it as still open.
- **Concrete, verified, gate-independent finding:** `provisioning/compute/
  src/compute_provisioning/pools.py` and `pool_config_handler.py` are
  byte-identical duplicates of the files in `kit/resource-pools/src/
  market_resource_pools/`. `compute_provisioning/__init__.py` does not
  import its own local copies — it re-exports `PoolCreate`, `PoolReplace`,
  `PoolUpdate`, `PoolConfigHandler`, `PoolConfigValidationProblem`, etc.
  from `market_resource_pools` instead. A repository-wide grep (2026-07-17)
  found no submodule import of `compute_provisioning.pools` or
  `compute_provisioning.pool_config_handler` anywhere. These two files are
  dead, unreferenced duplicates — see `tasks.md` §2 for the cleanup task.
  This is independent of the open decision above: removing dead duplicate
  files is not a package-boundary extraction and does not require this
  change's activation gate to be cleared.

## Dependencies and Related Changes

- Requires `market-platform-compute-10-site-lifecycle` and `market-platform-compute-20-provisioning-contract` to be implemented, synchronized, and archived.
- Treats the landed POOLS-3 fulfillment service, provider registry, Ansible provider, and capacity rebind behavior as prerequisite implementation to preserve and relocate by ownership.
- Preserves POOLS-4's storefront-owned capacity-identity boundary: compute listings and claims remain explicitly `pool_id`- or `resource_id`-scoped, `resource_id` wins when both are present, and missing/malformed orders fail before capacity probing or reservation.
- Resolves the package-boundary question formerly recorded by `pools-5-shared-provisioning-package` (closed 2026-07-17; see "Absorbed from POOLS-5" above); `pools-7-storefront-fulfillment-cutover` remains responsible for storefront wiring and durable fulfillment recovery.
- Absorbs the launch/package outcome formerly tracked by `add-provisioning-cli`.
- Uses the lifecycle-event dependency direction established by the compute provisioning contract; no separate callback-client extraction remains planned.
- `market-platform-compute-40-multi-domain-proof` supplies the broader end-to-end architecture proof after cutover.

## Impact

- Affected paths: `domains/vms/provisioning/service`, `domains/vms/provisioning/client`, `domains/bare_metal`, `provisioning/compute`, `kit/resource-pools`, deployment manifests, package metadata, Dockerfiles, and images.
- Wire and persistence: preserved from the prerequisite contracts; startup and package ownership change.
- Deployment: service image and launch commands change, requiring coordinated manifest and operator updates.
- Packaging: generic distributions move from VM ownership to the top-level compute provisioning category.
