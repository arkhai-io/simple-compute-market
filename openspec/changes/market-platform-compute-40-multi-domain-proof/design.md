## Context

After contract adoption and service extraction, unit tests can still miss concrete-name branching, default VM dispatch, provider/executor conflation, process-global callback routing, or cross-mode accounting errors. POOLS-3 supplies mechanism-neutral provider contracts and an initial VM Ansible provider, but does not prove a bare-metal fulfillment-provider path. The proof should validate two current compute domains against one authority without expanding into multi-site or non-compute scheduling.

## Goals / Non-Goals

**Goals:**

- Exercise VM and bare-metal adapters concurrently in one extracted service.
- Prove allocation-keyed executor dispatch, provider/executor separation, and deal-owner event routing.
- Prove shared-host VM/bare-metal conflict behavior.
- Enforce generic import boundaries.
- Produce deterministic, focused end-to-end evidence.

**Non-Goals:**

- Add a new resource domain or executor implementation.
- Prove multiple physical sites.
- Introduce packing, fractional claims, or cross-seller markets.
- Change established public contracts solely for test convenience.
- Add multi-provider access bindings or represent one physical resource as aliases in multiple scheduling pools.

## Decisions

### Use VM and bare metal as the two concrete proofs

They already have distinct action, result, release, and physical-accounting semantics. Inventing a fake second executor would not expose real coupling. API credits participates in the common market-domain conformance suite but not this optional compute-provisioning proof.

### Test one authority and two storefront ownership contexts

Seed one physical host with shareable VM capacity and an exclusive bare-metal target. Create allocations carrying distinct deal/storefront ownership. Every fixture uses POOLS-4's canonical capacity identity: no unscoped claim is allowed, and a fixture carrying both `pool_id` and `resource_id` must resolve by `resource_id`. The topology may use two composed storefront instances or two explicit event sinks, but ownership must come from each allocation rather than one global setting.

### Dispatch only from recorded executor identity

Submission and release select adapters from the committed allocation's executor kind/action kind. Requests cannot override an existing allocation to another executor. Unknown or unavailable adapters fail before infrastructure action while preserving repairable allocation state.

### Keep provider resolution independent and orthogonal

A POOLS-3 provider identifies an infrastructure execution mechanism independently from the committed allocation's VM or bare-metal domain semantics. POOLS-3's provider-only path is not yet the storefront executor-dispatch path, so this proof does not require provider resolution or provider-backed bare-metal fulfillment. Instead it verifies that registering the current VM-specific `AnsibleFulfillmentProvider` has no effect on adapter selection from committed executor identity. A future mechanism could support more than one domain explicitly, but joining these paths remains POOLS-7 scope. This proof does not add several provider bindings to one physical resource; if that later model is introduced, every binding must retain the same authoritative physical-resource identity for conflict accounting.

### Assert cross-mode conflicts before execution

A committed/held VM slice prevents an exclusive bare-metal reservation on the same Physical Resource, and the reverse conflict also holds. Provider references, access methods, or aliases cannot create independent capacity identities that bypass this exclusion. Rejected reservations submit no executor job. Releasing the conflicting allocation advances capacity version and permits a later eligible reservation.

### Combine architecture and behavior checks

Static import-boundary tests reject concrete VM/bare-metal imports from generic site and compute modules. Contract tests cover executor and provider registration/dispatch as independent namespaces. A focused scenario covers the full allocation, job, event, lease, and release transition for each adapter.

### Keep the proof deterministic

Use controlled executor backends and observable job/event barriers rather than timing sleeps. Real-network or hardware suites may supplement but do not replace deterministic contract evidence.

## Risks / Trade-offs

- **Mock executors can conceal concrete integration failures.** Mitigation: reuse production adapter construction and payload validation, with focused real backend tests retained in each domain.
- **Two storefront processes may make the scenario expensive.** Use the smallest topology that proves distinct ownership; do not add a second site.
- **The proof may discover prerequisite contract defects.** Update the owning prerequisite change/spec rather than adding local test-only exceptions.
- **Import checks can overfit paths.** Assert dependency direction and forbidden package ownership, not a frozen repository layout.
