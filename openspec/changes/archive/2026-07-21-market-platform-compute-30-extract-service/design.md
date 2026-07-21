## Context

Shared app, lifecycle, and startup helpers already exist under `provisioning/compute`, but the deployable service, composition container, generic controllers, job lifecycle, fulfillment coordination, and image remain hosted under `domains/vms/provisioning/service`. POOLS-3 added a concrete VM-service-local `FulfillmentService`, mechanism-neutral provider contracts in `kit/resource-pools`, an Ansible provider in the VM package, and durable capacity rebinding. POOLS-6 pass 1 subsequently added multidimensional capacity accounting, settlement requirements/candidates, and additive migration state across these same packages. Compute-30 now classifies and moves the current mechanism-neutral orchestration by ownership without redesigning those behaviors.

Compute-30 will land before POOLS-7. POOLS-7 is related but non-blocking: it later creates `kit/physical-settlement`, adds durable settlement/fulfillment recovery, and cuts the storefront over to that lifecycle against the extracted service layout.

## Goals / Non-Goals

**Goals:**

- Establish `provisioning/compute/service` as the deployable composition root.
- Move only executor-neutral orchestration and operator surfaces.
- Register VM and bare-metal executor and fulfillment-provider implementations as explicit adapter contributions.
- Move the current generic scheduler and fulfillment coordination while retaining concrete provider behavior in its domain package.
- Produce supported package, API/worker commands, image, and deployment cutover.
- Remove obsolete VM-owned generic paths after migration.

**Non-Goals:**

- Move VM or bare-metal deterministic semantics and executor implementations into generic code.
- Redesign the established site or compute-provisioning contracts.
- Add new executor kinds, multi-site topology, or placement policy.
- Add multiple provider/access bindings to one physical resource or redesign POOLS-3 pool membership.
- Implement POOLS-7's durable settlement lifecycle, recovery, `kit/physical-settlement` package, result queries, or storefront cutover.
- Redesign or independently guarantee transitional single-quantity capacity aliases while moving the service.
- Retain indefinite aliases or duplicate images.

## Decisions

### Use a compute-owned composition root

The destination root owns FastAPI assembly, shared middleware, generic routers, startup/shutdown ordering, background task lifecycle, dependency factories, generic fulfillment coordination, and adapter/provider registration. It imports adapter entry points or receives registrations at assembly; generic modules do not import concrete executor or provider implementations.

### Define an adapter registration bundle

Each executor/domain adapter may contribute:

- executor/action validators and job factories;
- release executor;
- result and credential codec;
- zero or more fulfillment-provider registrations;
- readiness checks;
- executor-specific router mounts;
- optional direct operator surfaces.

Registration rejects duplicate executor/action kinds, duplicate fulfillment-provider identities, and missing required lifecycle hooks at startup. A provider contribution supplies an infrastructure execution mechanism; it does not claim an executor kind.

### Move generic surfaces by ownership

Move generic job read/control, executor-neutral lease lifecycle, watchdog control, general health/version, capacity authority mounting, event delivery, `PhysicalSettlementScheduler`, `DeterministicRoundRobinPolicy`, `FulfillmentService`, and provider-registry composition into the extracted service. Keep the current domain-neutral settlement request/resource contracts in the base `compute_provisioning` package until POOLS-7 moves them into `kit/physical-settlement`. Keep KVM host/VM routes, `AnsibleFulfillmentProvider`, `VmFulfillmentRequirements`, Ansible VM playbook construction, VM result parsing, and VM release implementation in the VM package. Keep POOLS-4/6 listing identity validation, multidimensional capacity-claim construction, VM fulfillment-plan construction, and storefront failure-policy/event handling in the VM storefront: these translate a market listing into a capacity claim and are not generic provisioner composition. Keep bare-metal access grant/reclaim and concrete lease mapping in bare metal.

### Land before POOLS-7 without absorbing its scope

Compute-30 targets the current pre-POOLS-7 tree. It moves existing scheduler and fulfillment behavior as-is rather than creating POOLS-7's shared kit, durable settlement aggregate, recovery workers, result/status query API, or storefront call path. This deliberately creates one short-lived intermediate placement: domain-neutral settlement contracts remain in `compute_provisioning`, while scheduler and coordinator implementations live in `provisioning/compute/service`. POOLS-7 then moves the reusable contracts and implementation into its approved `kit/physical-settlement` boundary and updates the extracted service's composition, migrations, workers, packaging, and tests.

The two changes are not behavioral prerequisites. The selected order only avoids concurrent edits to the old VM-owned composition root. After Compute-30 lands, POOLS-7's planning artifacts must be reconciled to the new paths before POOLS-7 implementation begins.

### Keep executor and provider identity orthogonal

The committed allocation's `executor_kind` selects VM or bare-metal domain semantics for submission and release. A claim's `pool_id` or `resource_id` constrains capacity selection and is not a provider identity. The settlement resource's `provider` independently selects an infrastructure mechanism in POOLS-3's provider-only fulfillment path. During extraction the executor and provider registries remain separate; provider registration MUST NOT claim, infer, or override executor identity. Joining executor dispatch to provider-backed storefront fulfillment remains POOLS-7 scope rather than a compute-30 contract redesign. POOLS-3 currently permits one provider identity for a pooled resource; supporting several access mechanisms for one physical resource requires a later provider-binding model rather than duplicate resource aliases or multiple scheduling-pool memberships.

### Keep one service process and persistence owner

The extracted service retains the current databases and ordered migration histories under service ownership, including POOLS-6's multidimensional capacity columns and migration. Existing identifiers and tables retain their current behavior across the move. This change moves package/category ownership, not database authority or cross-service relational boundaries. POOLS-3's capacity rebind remains durable, while its process-local fulfillment identity map remains process-local during this extraction; database-backed fulfillment identity and dispatch recovery stay in POOLS-7.

Compute-30 does not make the transitional `total_units`/`units` mirrors or legacy claim aliases a new compatibility promise. It simply does not redesign the capacity wire during extraction. A later capacity-contract cutover may remove those forms by updating all controlled callers together.

### Ship the package and deployment in the same change

Provide installable metadata, console commands for API and worker roles where applicable, a destination Dockerfile/image, dependency resolution without parent-directory source assumptions, and migrated manifests. A package move without an operable image is not complete.

### Clean cutover

Update repository callers, test fixtures, image references, and deployment configuration before deleting the VM-owned generic package and transitional re-exports. Direct domain operator APIs keep their routes unless the prerequisite contract deliberately changed them.

### Verification and rollback

First prove route and startup parity in-process; then run VM and bare-metal provisioning/lifecycle tests against the destination app, including POOLS-6 multidimensional reservation and scheduling coverage; finally exercise the destination image and focused end-to-end flow. Rollback redeploys the prior service/image against the unchanged database and migration history. No old import aliases remain in the completed tree.

## Risks / Trade-offs

- **Composition can become a generic dependency container with hidden domain knowledge.** Mitigation: register narrow adapter bundles and assert import boundaries.
- **Startup parity can fail despite route-unit tests.** Mitigation: preserve ordered startup contracts and test background task creation/cancellation and image startup.
- **Packaging all adapters may pull heavy VM dependencies into every deployment.** Initial trade-off accepted for one compute image; adapter extras or separate images can be proposed once an operator requires them.
- **Clean cutover requires coordinated manifests and packages.** Accepted because maintaining the old ownership would undermine the extraction; rollback uses the previous coherent release set.
- **Executor and provider registries can be accidentally conflated.** Mitigation: validate each namespace independently and test that provider identity cannot select or override an allocation's executor adapter.
- **POOLS-7 planning points at the old VM-owned service and will become stale after extraction.** Mitigation: keep POOLS-7 out of Compute-30's implementation scope, then reconcile its paths, migration owner, composition, packaging, and tests immediately after Compute-30 lands and before POOLS-7 implementation.
- **The pre-POOLS-7 settlement placement is intentionally temporary.** Mitigation: keep the move mechanical and preserve import boundaries so POOLS-7 can extract the reusable implementation without another behavioral redesign.
