## Context

The bare-metal domain currently provides versioned listing, message, terms, materialization, receipt, and result codecs; a publication source; and a compute-provisioning adapter. The VM and API-credit domains additionally have runnable storefront packages that inject complete seller hooks into the core storefront role. The core application builder accepts one `MarketDomainContract`, so a bare-metal publication plugin is not equivalent to a complete bare-metal seller application.

The compute provisioner can load VM and bare-metal adapters concurrently. Storefront capacity aggregation can address several configured site authorities, but the current VM fulfillment path still uses one provisioning service URL. POOLS-7 owns the durable selected-site scheduling and fulfillment contract that this composition must ultimately consume.

## Goals / Non-Goals

**Goals:**

- Provide a runnable, independently packaged bare-metal storefront.
- Reuse schema-opaque core storefront orchestration and inject bare-metal codecs and hooks explicitly.
- Complete negotiation, settlement, fulfillment, result, and teardown behavior for bare-metal agreements.
- Bind configured site identities to trusted provisioning connections and retain the selected site through fulfillment.
- Establish the prerequisite needed for Compute-40 to prove a many-to-many VM/bare-metal storefront and provisioning topology.

**Non-Goals:**

- Multiplex several market domains in one storefront process.
- Duplicate the VM storefront and rename VM models to bare metal.
- Implement POOLS-7 persistence/recovery, result push delivery, or the final topology proof.
- Infer executor selection from fulfillment-provider identity.
- Store provisioning URLs or credentials in buyer-controlled agreement payloads or opaque `deal_ref` data.

## Decisions

### Compose one domain per storefront process

The bare-metal storefront will pass one completed bare-metal `MarketDomainContract` to the core storefront application builder. A seller may run VM and bare-metal storefront processes together or expose them through one gateway, but each process retains one deterministic domain contract and independent seller state.

This follows the existing VM/API-credit composition model and keeps domain dispatch out of generic request handlers. A single multi-domain process was rejected because it would require domain selection, persistence partitioning, policy dispatch, and lifecycle routing changes throughout the shared storefront role before there is evidence that process consolidation is operationally valuable.

### Add a concrete composition package, not a second core role

`domains/bare_metal/storefront` will become the concrete composition/package boundary. It may depend on `core/storefront`, shared clients and kits, and `arkhai-bare-metal`; core and kit packages must not import it. Schema-opaque behavior discovered during implementation belongs in core storefront seams, while bare-metal validation and policy remain in the domain composition.

Copying the VM executable wholesale was rejected because it would preserve VM assumptions and create two implementations of common seller lifecycle behavior.

### Complete the domain contract through explicit seller hooks

The initial negotiation policy supports SSH access with a buyer-supplied public key. Buyer-controlled `access_ref` is rejected rather than treated as an access, credential, or routing authority; seller/provisioner-issued access references belong in fulfillment results. Additional access methods require explicit method-specific validation before being enabled.

Commercial pricing remains in the shared listing's accepted-escrow/rate data rather than being added to `BareMetalListing`. The bare-metal policy receives the seller reference amount calculated at the generic commercial boundary, validates the domain payload, and then applies shared escrow-shape and listed-price mechanics. The composition unwraps the shared `ProvisionTerms` envelope into a validated `BareMetalMessage`; a local hook protocol carries that message because broadening the existing scalar-oriented shared hook before another domain needs the shape would be premature.

The composition will supply:

- publication from authoritative site projections;
- deterministic negotiation policy from `BareMetalMessage` and `BareMetalListing` to `BareMetalTerms`;
- settlement verification and plan construction;
- fulfillment translation from agreed materialization to generic scheduling/fulfillment calls;
- normalized bare-metal receipts and access results;
- teardown/reclaim using the recorded fulfillment and executor identity.

The shared storefront remains opaque to machine IDs, SSH access details, and bare-metal action payloads. Bare-metal hooks validate those values before crossing the compute contract.

### Treat selected-site routing as trusted storefront state

Operator configuration binds stable `site_id` values to provisioning authority URLs and credentials. Capacity placement selects one site before reservation; the resulting reservation/fulfillment state retains that trusted site binding. Fulfillment, polling, and teardown route through that binding rather than a process-global provisioning URL.

The exact durable repository and public scheduling calls are supplied by POOLS-7. Before that dependency lands, composition tests may use injected fake ports, but production cutover cannot claim completion.

A URL or admin key embedded in buyer-controlled terms or copied through opaque deal metadata is not an ownership authority. Reverse delivery and credential lookup remain separately owned by the result-delivery change.

### Reuse shared storefront persistence and versioned envelopes

Negotiation, agreement, settlement, and lifecycle correlation use the shared storefront persistence contracts and versioned domain envelopes. Domain-specific physical/access payloads remain opaque serialized values or references owned by the bare-metal codec. Any new table must represent a bare-metal authority that cannot be represented by the shared lifecycle and requires an explicit migration.

### Package and deploy the role independently

The repository will build and test a bare-metal storefront distribution and image independently from the VM storefront. Deployment configuration selects the bare-metal role, database, registry identity, seller identity, and one or more trusted site bindings. VM and bare-metal storefront roles may share a compute provisioner but do not share a writable storefront database.

Deployment rendering must prove that disabling either storefront does not leave waits or service references to that role. A gateway may present both roles under one operator-controlled host, but gateway consolidation is not required.

### Use pull reconciliation as the baseline

The composition will use POOLS-7 scheduling, fulfillment status, result, and teardown calls. Push delivery is optional acceleration and is not required to complete a bare-metal agreement. This keeps correctness independent of reverse reachability.

## Risks / Trade-offs

- **[POOLS-7 APIs change while composition work proceeds]** → Keep site routing and fulfillment behind injected ports; bind production wiring only after the POOLS-7 public contract is accepted.
- **[Refactoring VM storefront code expands scope]** → Move only behavior proven schema-opaque by both compositions and preserve VM behavior with focused regression tests.
- **[Bare-metal access data leaks through generic state or logs]** → Treat SSH keys and access grants as domain-sensitive values, redact diagnostics, and persist only the minimum durable input/result references required for recovery.
- **[Two storefront processes increase operational surface]** → Reuse shared image/chart conventions and permit one gateway/operator profile without coupling writable state.
- **[Site identity can be confused with remote assertions]** → Resolve site only from configured bindings and persist the selected binding with lifecycle state.
- **[A publication-only implementation is mistaken for completion]** → Acceptance includes negotiation, settlement, fulfillment, result, teardown, packaging, and deployment evidence.

## Migration Plan

1. Correct permanent baseline wording so it describes the current VM/API-credit executable state and the existing bare-metal publication capability without claiming a complete bare-metal storefront.
2. Establish the bare-metal storefront package and composition tests behind injected lifecycle ports.
3. Add domain policy, settlement, and result hooks while preserving shared wire envelopes.
4. Integrate the accepted POOLS-7 selected-site fulfillment and teardown APIs.
5. Add package/image/deployment configuration and render tests.
6. Run a complete bare-metal seller lifecycle against one site, then hand the 2×2 topology proof to Compute-40.

Rollback disables the bare-metal storefront role and closes its published listings. Shared compute/site authorities and VM storefront behavior remain unchanged. Any persistent schema addition must be backward-compatible during rollback or have an explicit down-migration/data-retention procedure.

## Implementation Inventory

### Reuse from core without moving VM code

The bare-metal composition will import shared behavior directly from these `core/storefront` boundaries:

- application construction and lifecycle: `app_composition.py`, `app_lifecycle.py`, `app_startup.py`, `openapi.py`, and `auth.py`;
- schema-opaque negotiation and servicing mechanics: `negotiation_sync.py`, `services/negotiation_service.py`, `heartbeats.py`, `settlement_lifecycle.py`, and `stage_log.py`;
- advisory capacity and publication primitives: `capacity.py`, `capacity_remote.py`, `aggregation.py`, `site_projections.py`, and the `publication_*` and `registry_publication.py` modules;
- generic protocol carriers and SQLite base/migration utilities where their contracts are sufficient.

`AggregateCapacityClient` is reusable for independent site snapshots, but it is not durable selected-site fulfillment routing. The bare-metal composition will retain site choice through its own injected lifecycle port until POOLS-7 supplies the production contract.

### Keep VM semantics in the VM composition

The following VM services are not reused or imported: `vm_fulfillment_service.py`, `vm_fulfillment_planner.py`, `vm_job_spec_service.py`, `provisioning_orchestration_service.py`, `resource_capacity_validator.py`, `listing_service.py`, `publication_service.py`, `admin_settle_service.py`, `claims_runtime.py`, and the VM `utils/settlement_jobs.py`, `sync_negotiation.py`, persistence, and migration modules. They encode VM host selection, VM capacity claims, `executor_kind="vm"`, VM access/SSH state, VM negotiation terms, or VM settlement hooks.

The VM controllers, middleware wrappers, container, startup, CLI, and `server.py` are composition wiring rather than shared role APIs. Bare metal will provide small independent equivalents around core factories instead of importing `market_storefront`. Core settle models containing `vm_host`, `vm_target`, `ssh_public_key`, or tenant credentials are not adopted as bare-metal domain carriers; any common settle endpoint must first become a schema-opaque envelope proven by both compositions.

### Refactor threshold

No VM module moves into core merely to establish the new package. A behavior may be extracted only after a focused VM regression test and a bare-metal consumer prove it is schema-opaque. The first package/composition increment therefore uses existing core seams, bare-metal-owned policy/adapters, and injected fake lifecycle ports. Alkahest helpers may be imported from `core_storefront` if the selected bare-metal settlement mechanism uses them; VM wrappers are never imported.

The initial application shell injects and validates the current publication-only bare-metal contract. It does not install placeholder seller capabilities: negotiation, settlement, and fulfillment are added atomically only with their real hooks in the following tasks. The shell's injectable domain, lifespan, and router seams allow those increments without replacing the application boundary.

## Open Questions

- Does the initial deployment use a dedicated bare-metal storefront image or one shared storefront image with separate composition entry points? Packaging evidence should decide before implementation tasks for deployment begin.
- What buyer-visible representation should carry short-lived access results once POOLS-7 finalizes credential/result retrieval semantics?

## Permanent Documentation Promotion

| Decision | Permanent destination |
|---|---|
| One domain contract per storefront process and separate seller compositions | `openspec/specs/market-composition/spec.md` and `architecture.md` |
| Complete bare-metal seller hooks and schema-opaque core boundary | `openspec/specs/storefront-publication/spec.md` and `architecture.md` |
| Independently deployable bare-metal role and trusted site bindings | `openspec/specs/deployment-state/spec.md` and `architecture.md` |
| Pull-based selected-site lifecycle and remaining result-delivery limitation | `openspec/specs/physical-provisioning/architecture.md` and `openspec/specs/fulfillment/architecture.md` |
