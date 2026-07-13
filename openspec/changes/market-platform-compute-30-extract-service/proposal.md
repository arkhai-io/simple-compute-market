## Why

The deployable compute provisioner still lives under `domains/vms` even though it owns shared job, capacity, lease, and VM/bare-metal executor orchestration. After the shared site and wire contracts are stable, moving that composition root to `provisioning/compute` makes ownership explicit and lets each compute domain retain only its concrete semantics and executor adapter.

## What Changes

- Move generic API assembly, job lifecycle, executor-neutral lease lifecycle, watchdog scheduling, capacity mounting, health surfaces, and executor registration to `provisioning/compute/service`.
- Define the compute provisioner composition root and load VM and bare-metal routers, action factories, executors, readiness checks, and optional operator surfaces as domain adapters.
- Keep VM KVM/Ansible behavior, playbooks, direct VM routes, and result interpretation in `domains/vms`.
- Keep bare-metal access grant/reclaim behavior, routes, and result interpretation in `domains/bare_metal`.
- Add supported API and worker console entry points, package metadata, Dockerfile/image, and deployment configuration for the extracted service.
- Migrate all callers and images, then remove the old VM-owned generic service paths and compatibility shims.
- **BREAKING**: generic provisioning package/import ownership and deployment image names change in one clean cutover.
- State: **Blocked on `market-platform-compute-20-provisioning-contract`.**

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

## Dependencies and Related Changes

- Requires `market-platform-compute-10-site-lifecycle` and `market-platform-compute-20-provisioning-contract` to be implemented, synchronized, and archived.
- Absorbs the launch/package outcome formerly tracked by `add-provisioning-cli`.
- Uses the lifecycle-event dependency direction established by the compute provisioning contract; no separate callback-client extraction remains planned.
- `market-platform-compute-40-multi-domain-proof` supplies the broader end-to-end architecture proof after cutover.

## Impact

- Affected paths: `domains/vms/provisioning/service`, `domains/vms/provisioning/client`, `domains/bare_metal`, `provisioning/compute`, deployment manifests, package metadata, Dockerfiles, and images.
- Wire and persistence: preserved from the prerequisite contracts; startup and package ownership change.
- Deployment: service image and launch commands change, requiring coordinated manifest and operator updates.
- Packaging: generic distributions move from VM ownership to the top-level compute provisioning category.
