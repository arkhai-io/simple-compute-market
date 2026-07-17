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

- **Open decision, carried forward unresolved:** whether
  `PhysicalSettlementScheduler` (`domains/vms/provisioning/service`,
  VM-service-local), `FulfillmentProvider`/`ProviderRegistry`
  (`kit/resource-pools`), and the `SettlementRecord`/settlement-resource
  shapes they operate on should consolidate into `compute_provisioning`
  once this extraction lands, or stay split the way they are today.
  `pools-2`'s scheduling/request contracts (`PhysicalSettlementRequest`,
  `SettlementResource`, `SettlementCandidate`, `SettlementRequirement`,
  `SettlementSchedulingPolicy`) already live in `compute_provisioning`;
  `pools-3`'s `FulfillmentProvider`/`ProviderRegistry`/error taxonomy live
  in `kit/resource-pools` instead — a deliberate override of POOLS-5's gate
  made during `pools-3` (see that change's `design.md`, "Domain-neutral
  contracts vs. domain-specific payloads"). This proposal's task list (§1)
  should reconcile that split as part of "Verify Prerequisites and Current
  Ownership," not treat it as pre-decided.
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
