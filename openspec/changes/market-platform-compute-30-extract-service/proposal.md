## Why

The deployable compute provisioner still lives under `domains/vms` even though it owns shared job, capacity, lease, fulfillment, and VM/bare-metal executor orchestration. POOLS-3 has also landed mechanism-neutral provider contracts plus a concrete VM-service-local fulfillment coordinator and provider registration. After the shared site and wire contracts are stable, moving that composition root to `provisioning/compute` makes ownership explicit and lets each compute domain retain only its concrete semantics, executor adapter, and fulfillment-provider implementation.

## What Changes

- Move generic API assembly, job lifecycle, executor-neutral lease lifecycle, watchdog scheduling, capacity mounting, fulfillment coordination, health surfaces, and executor/provider registration to `provisioning/compute/service`.
- Define the compute provisioner composition root and load VM and bare-metal routers, action factories, executors, fulfillment providers, readiness checks, and optional operator surfaces as domain adapters.
- Preserve POOLS-6's landed multidimensional capacity, reservation, settlement-requirement, candidate-availability, migration, and compatibility behavior across the package move.
- Treat POOLS-7 as related, non-blocking work: consume `kit/physical-settlement` when it has landed, or relocate the current settlement composition without implementing POOLS-7's durability and storefront-cutover redesign when it has not.
- Keep VM KVM/Ansible behavior, `AnsibleFulfillmentProvider`, VM fulfillment requirements, playbooks, direct VM routes, and result interpretation in `domains/vms`.
- Keep bare-metal access grant/reclaim behavior, routes, and result interpretation in `domains/bare_metal`.
- Add supported API and worker console entry points, package metadata, Dockerfile/image, and deployment configuration for the extracted service.
- Migrate all callers and images, then remove the old VM-owned generic service paths and compatibility shims.
- **BREAKING**: generic provisioning package/import ownership and deployment image names change in one clean cutover.
- State: **Unblocked, not started.** `market-platform-compute-10-site-lifecycle`
  and `market-platform-compute-20-provisioning-contract` archived
  2026-07-13. POOLS-6 pass 1 landed on 2026-07-20. POOLS-7 is related and
  overlaps package/composition paths, but neither change is an activation
  prerequisite for the other; landing order is reconciled at implementation
  kickoff. `tasks.md` remains fully unchecked.

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

## POOLS-5 Boundary Follow-up (closed 2026-07-17)

`pools-5-shared-provisioning-package` is archived at
`openspec/changes/archive/2026-07-17-pools-5-shared-provisioning-package/`.
Two outcomes remain relevant:

- POOLS-7's design review resolved the eventual shared destination for
  `PhysicalSettlementScheduler`, `DeterministicRoundRobinPolicy`, the
  domain-neutral settlement contracts, and its new durable lifecycle and
  recovery implementation as **`kit/physical-settlement`**. That package is
  POOLS-7 scope and does not exist until POOLS-7 implements it.
  `FulfillmentProvider`/`ProviderRegistry` and their error taxonomy remain in
  `kit/resource-pools`. Compute-30 does not reopen this boundary or implement
  POOLS-7's durability redesign.
- The two byte-identical, unreferenced copies
  `compute_provisioning/pools.py` and `pool_config_handler.py` remain a
  Compute-30 cleanup item. Their live implementations and public re-exports
  already come from `market_resource_pools`.

At implementation kickoff, Compute-30 checks POOLS-7's landing status. If
POOLS-7 has landed, the extracted service composes `kit/physical-settlement`.
If it has not, Compute-30 relocates current generic settlement composition as
part of the service extraction while preserving behavior; POOLS-7 later moves
that code into the approved kit. Whichever change lands second reconciles the
resulting package paths, migrations, composition, and tests. This is a merge
coordination rule, not a prerequisite in either direction.

## Dependencies and Related Changes

- Requires `market-platform-compute-10-site-lifecycle` and `market-platform-compute-20-provisioning-contract` to be implemented, synchronized, and archived.
- Treats the landed POOLS-3 fulfillment service, provider registry, Ansible provider, and capacity rebind behavior as implementation to preserve and relocate by ownership.
- Preserves POOLS-4's storefront-owned capacity-identity boundary: compute listings and claims remain explicitly `pool_id`- or `resource_id`-scoped, `resource_id` wins when both are present, and missing/malformed orders fail before capacity probing or reservation.
- Preserves POOLS-6 pass 1's generic `dimensions`/`available` capacity model, multidimensional ledger accounting, legacy GPU-unit compatibility, and additive migration history.
- Treats `pools-7-storefront-fulfillment-cutover` as related, non-blocking work. POOLS-7 owns `kit/physical-settlement`, durable settlement/fulfillment recovery, pull-based result/status queries, and storefront cutover; push delivery remains the separate `provisioning-result-push-delivery` change.
- Absorbs the launch/package outcome formerly tracked by `add-provisioning-cli`.
- Uses the lifecycle-event dependency direction established by the compute provisioning contract; no separate callback-client extraction remains planned.
- `market-platform-compute-40-multi-domain-proof` supplies the broader end-to-end architecture proof after cutover.

## Impact

- Affected paths: `domains/vms/provisioning/service`, `domains/vms/provisioning/client`, `domains/bare_metal`, `provisioning/compute`, `kit/resource-pools`, and, when already present from POOLS-7, `kit/physical-settlement`, plus deployment manifests, package metadata, Dockerfiles, and images.
- Wire and persistence: preserve the landed multidimensional capacity and migration contracts and whichever pre- or post-POOLS-7 settlement lifecycle exists at kickoff; startup and package ownership change.
- Deployment: service image and launch commands change, requiring coordinated manifest and operator updates.
- Packaging: generic distributions move from VM ownership to the top-level compute provisioning category.
