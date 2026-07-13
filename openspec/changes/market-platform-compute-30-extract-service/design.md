## Context

Shared app, lifecycle, and startup helpers already exist under `provisioning/compute`, but the deployable service, composition container, generic controllers, job lifecycle, and image remain hosted under `domains/vms/provisioning/service`. The prerequisite changes make site authority independent and replace the VM-owned shared wire, allowing package movement without redesigning behavior concurrently.

## Goals / Non-Goals

**Goals:**

- Establish `provisioning/compute/service` as the deployable composition root.
- Move only executor-neutral orchestration and operator surfaces.
- Register VM and bare-metal implementations as explicit adapters.
- Produce supported package, API/worker commands, image, and deployment cutover.
- Remove obsolete VM-owned generic paths after migration.

**Non-Goals:**

- Move VM or bare-metal deterministic semantics and executor implementations into generic code.
- Redesign the established site or compute-provisioning contracts.
- Add new executor kinds, multi-site topology, or placement policy.
- Retain indefinite aliases or duplicate images.

## Decisions

### Use a compute-owned composition root

The destination root owns FastAPI assembly, shared middleware, generic routers, startup/shutdown ordering, background task lifecycle, dependency factories, and adapter registration. It imports adapter entry points or receives registrations at assembly; generic modules do not import concrete executor implementations.

### Define an adapter registration bundle

Each executor/domain adapter may contribute:

- executor/action validators and job factories;
- release executor;
- result and credential codec;
- readiness checks;
- executor-specific router mounts;
- optional direct operator surfaces.

Registration rejects duplicate executor/action kinds and missing required lifecycle hooks at startup.

### Move generic surfaces by ownership

Move generic job read/control, executor-neutral lease lifecycle, watchdog control, general health/version, capacity authority mounting, and event delivery. Keep KVM host/VM routes, Ansible VM playbook construction, VM result parsing, and VM release implementation in the VM package. Keep bare-metal access grant/reclaim and concrete lease mapping in bare metal.

### Keep one service process and persistence owner

The extracted service retains the current databases and migration histories under service ownership. Existing identifiers and tables remain compatible. This change moves package/category ownership, not database authority or cross-service relational boundaries.

### Ship the package and deployment in the same change

Provide installable metadata, console commands for API and worker roles where applicable, a destination Dockerfile/image, dependency resolution without parent-directory source assumptions, and migrated manifests. A package move without an operable image is not complete.

### Clean cutover

Update repository callers, test fixtures, image references, and deployment configuration before deleting the VM-owned generic package and transitional re-exports. Direct domain operator APIs keep their routes unless the prerequisite contract deliberately changed them.

### Verification and rollback

First prove route and startup parity in-process; then run VM and bare-metal provisioning/lifecycle tests against the destination app; finally exercise the destination image and focused end-to-end flow. Rollback redeploys the prior service/image against the unchanged compatible database. No old import aliases remain in the completed tree.

## Risks / Trade-offs

- **Composition can become a generic dependency container with hidden domain knowledge.** Mitigation: register narrow adapter bundles and assert import boundaries.
- **Startup parity can fail despite route-unit tests.** Mitigation: preserve ordered startup contracts and test background task creation/cancellation and image startup.
- **Packaging all adapters may pull heavy VM dependencies into every deployment.** Initial trade-off accepted for one compute image; adapter extras or separate images can be proposed once an operator requires them.
- **Clean cutover requires coordinated manifests and packages.** Accepted because maintaining the old ownership would undermine the extraction; rollback uses the previous coherent release set.
