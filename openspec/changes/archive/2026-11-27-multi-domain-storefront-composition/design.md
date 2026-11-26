Archived 2026-11-27 as delivered. "Context" through "Migration Plan" below are the design as written on 2026-08-15: "Context" describes the system before the change, and the decisions describe the plan. Notes dated 2026-11-27 say where the code differs today, and "Disposition of the original delta requirements" at the end says where each requirement's rule lives.

## Context

See `proposal.md` for motivation. The implementation must start from these observed boundaries:

- `MarketDomainContract` is already immutable and versioned. `validate_domain_contracts()` rejects unsupported versions, incomplete capabilities, and duplicate stable identities; the buyer already loads several contracts. The storefront shell differs: `core_storefront.app_composition.build_storefront_app()` accepts one contract and stores it as `app.state.market_domain`.
- `storefront-domain-parameterization` will remove the VM module lookup by passing one exact `compute.v1` contract through `build_vm_storefront_app`, lifespan/container construction, `SQLiteClient`, `ListingService`, negotiation start/continue, and `VmSettlementComposition`. This design replaces that one-object injection only after it is accepted; it does not preserve a getter below the registry.
- The common `listings` table stores offer, pricing, settlement, and publication payloads but no domain discriminator. `negotiation_threads` stores provision terms, accepted plan, parties, and agreed state but likewise no discriminator. `escrows` and the settlement runtime retain `negotiation_id`/agreement identity, so an accepted binding can remain authoritative without making settlement mechanisms understand domains.
- VM publication records site/pool/resource/slice state in `derived_compute_listings`. Bare-metal persistence has a different `derived_bare_metal_listings` shape and a separate `bare_metal_agreement_payloads` table. The VM database also creates an older, incomplete bare-metal mapping shape. Request-time lookup of one of those tables would require exactly the VM-versus-bare-metal branching this change forbids.
- The trusted capacity aggregator already routes `reserve(site=...)` to exactly one configured site. Its commit/release paths and `AggregateFulfillmentClient` use a process-local reservation-to-site cache and fan out on a cold cache after restart. That is unacceptable once an accepted record already owns a trusted site; this change must add an exact site-addressed route for every subsequent capacity/fulfillment call.
- VM uses domain kind `compute.v1` but pool/executor offering mode `vm`; bare metal uses domain kind `bare_metal.v1` and mode `bare_metal`. These namespaces are related by explicit registration, not by string conversion.
- The registry filter already admits `listing_resource.offering_mode` values `vm`, `bare_metal`, and `container`. Current VM publication does not emit it. `publish-multidimensional-listing-shape` owns capacity-dimension projection but its current artifacts do not specify mode routing.
- `pool-declared-offering-modes` owns the deliverable-mode tag, explicit requested mode, removal of VM defaults, legacy reservation policy, and independent reservation/scheduling/provisioning enforcement. `pools-7-storefront-fulfillment-cutover` and the bare-metal seller composition own real scheduling, result, recovery, and teardown ports. This change consumes those boundaries and must stop rather than fake one that is absent.

## Goals / Non-Goals

**Goals:**

- Make exact domain selection a serializable, immutable record invariant from publication through teardown.
- Run VM and bare-metal contributions through one shared storefront protocol/runtime without domain conditionals.
- Preserve trusted site ownership and explicit pool mode at every remote physical operation, including after restart.
- Migrate one legacy storefront database transactionally without changing stable market, settlement, or physical-operation identities.
- Support explicit one-registration and multi-registration deployments through the same image, registry, persistence, and routes.
- Provide focused and system evidence for both complete lifecycles and cross-domain isolation.

**Non-Goals:**

- General multi-tenant plugin hot reload, several versions of one stable domain identity in one process, API-credit composition, or many-to-many storefront/authority ownership.
- A buyer package, registry schema-identity cutover, new provider/executor, pool-mode implementation, or physical conflict implementation.
- Live merging of two independently writable databases or converting historical terminal artifacts merely to make them decodable by a current plugin.
- Keeping the current bare-metal and VM HTTP stacks as two implementations behind a dispatcher.

## Decisions

### 1. Gate implementation on accepted prerequisites

The first implementation task is an executable contract check, not a checkbox review:

1. `storefront-domain-parameterization` must have no lower-layer module getter/default and must inject the exact contract at all named VM call sites.
2. `pool-declared-offering-modes` must expose the canonical requested mode and enforcement predicate at reservation, scheduling, and provisioning; both VM fallbacks and its legacy-row ambiguity must be gone.
3. Full lifecycle work additionally checks the accepted bare-metal seller and POOLS-7 scheduling/result/recovery/teardown interfaces. A missing interface blocks that section. An injected fake is allowed only at the repository's normal external I/O test boundary; it cannot stand in for missing production orchestration.

The check records exact promoted headings, package APIs, and focused evidence in this design before production edits. Later interface drift updates proposal/specs/tasks first.

#### Prerequisite verification record (2026-08-15)

- `storefront-domain-parameterization` is present in the integrated base.  The
  permanent requirements are **Storefront roots inject one validated domain
  contract** in `market-composition` and **Domain runtime composition** in
  `storefront-publication`.  `build_vm_storefront_app`, startup/container,
  `SQLiteClient`, `ListingService`, negotiation, and
  `VmSettlementComposition` all receive the composition-root-owned contract;
  focused evidence is owned by
  `domains/vms/storefront/tests/unit/test_domain_runtime_parameterization.py`
  and the service/controller injection tests named by that accepted change.
- `pool-declared-offering-modes` is present in the integrated base.  The
  permanent requirements are **Pool-declared offering modes** in
  `resource-pool-management`, **Requested offering mode is explicit and
  bounded by the pool** and **Offering mode is enforced through fulfillment**
  in `site-capacity`, plus the fulfillment/physical-provisioning executor
  identity requirements.  The shared `pool_delivers_offering_mode` predicate
  is used by reservation, scheduling, and provisioning; the accepted migration
  rejects ambiguous historical executor identity rather than selecting VM.
- Bare-metal contribution production is owned externally. The parallel producer
  reports commit `18083392` with entry-point group
  `market.storefront_contributions`, contribution id `bare_metal`, and a
  validated exact contract; its dedicated chart is `3b46f6f8`. Those commits
  are not part of this isolated checkout and their full selected-site
  scheduling/result/recovery/teardown acceptance has not been run here.
  Registry, binding, migration, and exact-site shell work proceeds, while the
  one-process live bare-metal proof remains a parent-run prerequisite. No fake,
  no-op, payload inference, or default substitutes for that producer.
  The contribution now registers through the shared shell and composes kit
  publication; its remaining domain-local negotiation service and its own negotiate
  and listing routes are composed onto the kit by
  `bare-metal-and-credits-domain-stacks`, and this change does not gate on it.
- The canonical public discriminator was already
  `listing_resource.offering_mode`; this change persists its exact value in
  `StorefrontDomainBinding` and rejects any normalized-public disagreement.
  Existing registry filters/builders remain the only public schema owner; no
  alternate discriminator was added.
- Inventory found legacy VM `derived_compute_listings`, thread provision/terms
  columns, escrow fulfillment context, VM settlement hooks, and aggregate
  capacity/fulfillment fan-out. The cutover adds common binding/artifact tables,
  freezes contribution discovery, records site/mode/domain on threads and
  fulfillment contexts, uses exact-site methods for accepted work, and keeps
  concrete market meaning behind the selected contract.

*2026-11-27:* the requirement titles this record cites have changed. `market-composition`'s "Storefront roots inject one validated domain contract" was replaced by this change's "Storefront roots inject a frozen domain registry"; `resource-pool-management`'s is now "Pool-declared deliverable offering modes"; `site-capacity`'s is now "Requested offering mode is required and bounded by the pool". `test_domain_runtime_parameterization.py` no longer exists; the VM root's contract validation is covered by `domains/vms/storefront/tests/unit/test_domain_runtime_wiring.py`. Commits `18083392` and `3b46f6f8` are in this repository. Bare metal's domain-local negotiation service was deleted by `bare-metal-mock-provisioned-deal` (archived 2026-10-09), which composed bare-metal negotiation onto the kit runtime; its own listing and negotiate routes remain.

### 2. Use a frozen registration registry; keep mode and domain key distinct

Add a core-owned immutable composition carrier with these semantics:

```text
DomainContractKey
  domain_identity: DomainIdentity
  contract_version: ContractVersion

StorefrontDomainRegistration
  offering_mode: canonical pool/executor mode
  contract: exact validated MarketDomainContract object
  contribution_id: installed storefront contribution identity

StorefrontDomainBinding
  offering_mode
  domain_identity
  contract_major
  contract_minor
```

The serializable binding contains no callable, URL, provider field, or secret. `StorefrontDomainRegistry` validates all registrations with `validate_domain_contracts`, verifies the complete role capability set, rejects duplicate modes/contribution IDs/domain identities, constructs exact lookup maps once, and then exposes read-only resolution.

Resolution compares all binding fields and returns the already registered object. It never calls an entry point during a request and never constructs a contract from stored strings. A stable domain identity is unique in the current core contract, so simultaneously registering two API versions of that identity remains invalid; accepting an old durable version requires installing that exact version as the sole registration for the identity during recovery or completing an explicit domain migration.

*2026-11-27:* no domain migration exists (decision 8).

Alternative considered: use artifact `kind` or `offering_mode` as the only key. Rejected because each is caller/public payload, neither pins the core plugin API version, and VM's domain identity is not its pool mode.

Alternative considered: ordered registrations with a default. Rejected because order changes across configuration renders and a one-element registry would silently recreate the VM fallback.

### 3. Extend the parameterized app/runtime from one contract to one registry

`build_vm_storefront_app(*, domain)` becomes the common compute-family storefront factory accepting `registrations`/the frozen registry. The exact registry is captured by lifespan and passed to the container, repository, listing/publication service, negotiation controller/helpers, settlement composition, recovery workers, and result/teardown adapters. `app.state.market_domain` and compatibility getters are removed; safe status may expose an immutable projection as `app.state.market_domains` but request code receives the registry by dependency injection rather than reading app globals.

The current `market-storefront` executable becomes the compute-family composition root. Installed VM and bare-metal storefront contributions provide full contracts through a dedicated storefront-contribution entry-point group; this is distinct from `market.storefront_domains`, whose concept-level contracts may intentionally omit role hooks. Configuration names each contribution and asserts its mode, identity, and version; the loader verifies those assertions against the returned object.

The bare-metal executable, when retained for a one-domain deployment, is reduced to the same factory with one explicit registration. Its independent `api.py`/server/runtime route orchestration and VM-only handler branches are removed after callers/tests move. This is a clean cutover, not a proxy from one app into another.

*2026-11-27 — not built.* `build_vm_storefront_app(*, registry)` takes the frozen registry and builds the VM application: it resolves the `vm` registration and builds VM services alone (`domains/vms/storefront/src/market_storefront/server.py`), its negotiation runtime and listing service refuse a binding other than that registration's (`negotiation_runtime.py`, `services/listing_service.py`), its publication loop builds the VM source alone (`publication_wiring.py`), and its migration chain holds no bare-metal table (`utils/migrations.py`). The `market-storefront` distribution installs the bare-metal contribution, so its configuration may register it; that registration is validated and reported and serves nothing. The bare-metal executable was not reduced to this factory: it keeps `server.py`, `runtime.py`, and `api.py` with its own listing and negotiate routes, over a registry of its one registration. The kit composition both executables build through, `market_storefront_kit.composition.StorefrontComposition`, takes the registry and one selected binding. One executable serving both domains, and the removal of the dedicated bare-metal storefront, are `unify-vm-and-bare-metal-storefronts`'s.

Alternative considered: mount the existing VM and bare-metal FastAPI apps under two prefixes. Rejected because listing IDs, negotiation continuation, recovery workers, operator pause, and settlement identity would still have two state authorities and would not prove one storefront.

### 4. Persist one common listing binding and copy it to negotiations

Introduce the storefront-owned `storefront_listing_bindings` table:

```text
listing_id                  PRIMARY KEY, references listings
site_id                     trusted configured site
pool_id                     nullable explicit pool identity
physical_resource_id        nullable explicit resource identity
offering_mode               NOT NULL
domain_identity             NOT NULL
contract_major              NOT NULL
contract_minor              NOT NULL
derivation_key              NOT NULL UNIQUE
source_envelope_json         validated VersionedEnvelope, public-safe
last_reconciled_at           NOT NULL
```

`source_envelope_json` carries only domain-owned reconciliation identity needed by publication (for example VM slice quantity or bare-metal machine/physical-host identifiers). It is validated by the bound contract/contribution before persistence and may not contain URLs, credentials, provider config, SSH material, or commercial policy. Pricing, settlement clauses, and public offers remain in `listings`.

The table replaces `derived_compute_listings` and `derived_bare_metal_listings` as the mapping/site-routing authority. Common repository methods load by listing, site, derivation key, status, and source envelope. Domain publishers calculate their versioned source envelope and candidate-specific derivation component; the shared layer length-prefixes/canonicalizes site, mode, exact domain key, and source identity so modes and sites cannot collide.

Add `offering_mode`, `domain_identity`, `contract_major`, `contract_minor`, and `site_id` to `negotiation_threads`. Opening a negotiation uses one `BEGIN IMMEDIATE` transaction to load the listing/binding, resolve the contract, validate the provision envelope, and insert the binding, parties, opening message, and initial domain artifact. The binding columns are never updated. Database triggers reject mutation of binding columns on both tables so raw or alternate repository callers cannot bypass application checks.

Domain artifacts that are not already universal thread/settlement fields use one `storefront_domain_artifacts` table keyed by `(negotiation_id, artifact_slot)`, containing the copied binding and canonical JSON. The shared repository validates binding equality with the thread and invokes only the selected codec for `message`, `terms`, `materialization`, `receipt`, or `result`. This replaces `bare_metal_agreement_payloads`; it does not duplicate `settlement_plan`, settlement-runtime obligations, or provider-owned fulfillment results.

`escrows` and settlement-runtime records retain their existing agreement/negotiation reference. `fulfillment_context` stores a safe copy of the binding/site beside its physical IDs for restart equivalence; every load compares it to the authoritative thread before use. This avoids domain columns in mechanism-owned operation journals while detecting partial/corrupt correlation.

### 5. Route each phase from its authoritative record

The selector sequence is fixed:

1. **Publication:** iterate frozen registrations; get that registration's publication source; require the source candidate's pool to declare `registration.offering_mode`; normalize the listing; persist listing + common binding; publish `listing_resource.offering_mode` from the binding.
2. **New negotiation:** load listing binding; reject closed/withdrawn mode; resolve exact contract; compare provision envelope kind/version; transactionally copy the binding; invoke the selected policy.
3. **Continuation/acceptance:** load thread binding, not the listing or request; normalize messages/Terms and build the accepted plan through that contract.
4. **Settlement/materialization:** load the accepted thread; resolve its contract; verify/build/adopt the immutable plan; write binding/site into safe fulfillment context.
5. **Capacity:** pass the recorded offering mode as the explicit requested mode and the recorded trusted site as a targeted call. Pool declaration enforcement remains authority-owned and is rechecked there.
6. **Scheduling/fulfillment:** call the recorded site's client directly; pass the existing generic `market` namespace and a versioned domain fulfillment envelope prepared by the selected contract. The provisioning service retains its own immutable market/request and recorded executor identity.
7. **Status/result:** address the recorded site and fulfillment ID; validate the generic result envelope; decode `domain_result` only with the accepted contract's result codec. A mismatched kind is data-integrity failure, never a dispatch hint.
8. **Teardown/recovery:** use the same thread binding, site, reservation/fulfillment IDs, and operation journal. The provisioning authority dispatches by its recorded offering mode; the storefront does not recalculate it from the current pool or listing.

A registration or pool mode can disappear for new work, but accepted binding identity never changes. Startup fails readiness when a nonterminal/recoverable record cannot resolve. Terminal history with an unavailable old codec remains inspectable as safe opaque status; any operation requesting domain decoding reports the missing exact binding rather than guessing.

*2026-11-27:* two steps differ. Publication does not iterate the registrations: each publisher names the contributions whose sources it builds (`core_storefront.publication_plugins.build_registry_publication_sources`), and the VM loop names its own alone. Startup does not read stored bindings against the registry: a record whose binding the registry cannot resolve fails with a binding error when an operation next resolves it.

### 6. Make trusted site routing durable, not cache-dependent

Extend the aggregate capacity and fulfillment clients with explicit site-targeted methods/parameters for commit, release, truncate, schedule, begin, status, result, and begin-teardown. When `site_id` is present, the client selects exactly that configured client, verifies its pinned authority principal, and propagates refusal/error. It does not call `_route_order`.

The process-local reservation cache may remain an optimization only for genuinely unbound legacy/general calls. Multi-domain listing/accepted flows always pass the durable `site_id`; tests make another site capable and assert it receives zero calls. A remotely returned `site` value is compared with the configured selection but never establishes trust.

Alternative considered: warm the cache from the database on restart. Rejected because a cache lookup still permits fan-out behavior on miss/corruption, whereas exact site is already durable authority state.

### 7. Keep pool capability and physical conflict as independent checks

A publisher reads the accepted pool-declaration projection and suppresses modes not declared. A new negotiation rechecks listing openness, while reservation/scheduling/provisioning independently enforce the explicit mode under `pool-declared-offering-modes`. Cross-mode Physical Resource conflict continues to run separately: a pool may declare both VM and bare metal while the site correctly refuses an exclusive whole-host reservation conflicting with live VM slices.

Mode withdrawal closes publications/new work. It does not rewrite accepted bindings, but it can prevent a held request from advancing when the pool prerequisite specifies that behavior. Recovery may observe/reclaim/teardown existing effects; it may not submit a fresh create that the current authority rejects.

### 8. Migrate one quiesced legacy database with explicit provenance

*2026-11-27 — removed code.* The command below and `market_storefront.domain_migration` were built, shipped in marketplace 0.3.0, and removed by `add-database-migration-commands` (archived 2026-11-09), with their tests and the requirement "Legacy storefront domain migration is transactional": the migration's only input is a storefront database from before marketplace 0.3.0, which every storefront's migration baseline refuses. The binding tables are created by that baseline. The rest of this decision is kept as the record of what was built.

Add a migration command consistent with existing configuration migration practice:

```text
market-storefront config migrate --scope storefront-domains \
  --legacy-contribution <id> --legacy-offering-mode <mode> \
  --legacy-domain <identity> --legacy-contract-version <major.minor> \
  --check | --write --backup
```

The check is read-only and redacts payloads. The write requires a restrictive same-directory backup, validates the whole candidate population before replacement, uses one transaction for schema/data activation, records the migration ID, fsyncs, and is idempotent.

Migration phases:

1. Load the exact installed legacy contribution and verify all four assertions.
2. Validate every legacy listing, derived mapping, nonterminal/accepted thread, domain artifact, settlement-plan correlation, escrow/fulfillment context, and identifier relationship with that contract.
3. Convert the selected source's `derived_compute_listings` or `derived_bare_metal_listings` rows into common bindings and versioned source envelopes. Detect missing site, delimiter collisions, duplicate listing/source identity, and the VM database's incomplete bare-metal table instead of guessing fields.
4. Backfill listing and thread bindings. Threads inherit only from their exact listed offer; orphaned/mismatched rows abort. Recoverable physical context receives the same binding/site while all existing IDs and opaque mechanism/provider state remain unchanged.
5. Copy bare-metal artifact rows to the generic artifact table where applicable. Install immutability triggers and mark legacy mapping/artifact tables retired only after all equivalence checks pass.

A database with no discriminator never infers VM from missing values, one installed plugin, `vm_host`, payload shape alone, or a default executor. A source containing records from more than one domain is not eligible for the single-source migration and aborts. The tool does not merge two databases; an independent role must be quiesced, close publication, and finish or transfer responsibility under an explicitly designed later migration before its database can be retired.

Rollback before activation restores the backup plus prior package/config together. Once a new bound negotiation/reservation/fulfillment exists, rollback is forward recovery under the recorded schema and exact contributions.

### 9. Treat `offering_mode` as the one public offering-mode field

The registry already validates and filters `listing_resource.offering_mode`; no second `offering_mode`, `domain`, or executor field is added to the public listing. The public field is a projection of the durable binding and cannot select a contract on ingress. The domain provision envelope remains the buyer's assertion checked against the server record.

If `publish-multidimensional-listing-shape` publishes this field before implementation, reuse its builder and fixtures. That change continues to own capacity-dimension projection; this change owns binding equality and lifecycle routing.

### 10. Package one composition and render explicit registrations

Add a versioned public configuration root such as:

```toml
[StorefrontDomains]
schema_version = 1
enabled = ["vm", "bare_metal"]

[StorefrontDomains.registrations.vm]
contribution = "vms"
offering_mode = "vm"
domain_identity = "compute.v1"
contract_version = "1.0"

[StorefrontDomains.registrations.bare_metal]
contribution = "bare_metal"
offering_mode = "bare_metal"
domain_identity = "bare_metal.v1"
contract_version = "1.0"
```

*2026-11-27:* the format built is an array of tables, `[[storefront_domains]]`, each with exactly `contribution`, `offering_mode`, `domain_identity`, and `contract_version`; there is no `schema_version`, `enabled` list, or `registrations` table (`core_storefront.domain_plugins.parse_storefront_contribution_selections`). Helm passes each agent's `config` through a closed schema generated from the storefront's settings models.

Order is for deterministic status/publication iteration only, never fallback or precedence. Generated config and Helm schemas reject duplicates, unknown keys, empty registrations, and provider/secret fields. Trusted site URLs and public principals remain in their existing public connection configuration; signer credentials remain Secret-mounted.

The packaged settings file contains no `storefront_domains` entry. Dynaconf
merges arrays across the packaged and operator layers, so even a one-element
packaged default would be appended to the explicit deployment list and make a
valid multi-domain selection ambiguous. Helm, Compose, or another operator
overlay supplies the complete non-empty list.

The storefront wheel/image installs the shared role plus exact VM and bare-metal contribution wheels from `.dist`. The same command handles one or two registrations. Compose and Helm render one process, one SQLite volume, `Recreate`, one set of workers, and no waits for disabled contributions. Readiness reports registration and pool/site blockers without artifact payloads.

### 11. Divide proof by the lowest meaningful test level

- Core unit tests cover registry validation/resolution, binding serialization/equality, immutable database writes, derivation-key collision resistance, and no-hook calls on error.
- Domain unit/conformance tests run the same listing/message/Terms/materialization/receipt/result matrix for VM and bare metal.
- Storefront integration tests use the canonical typed storefront and provisioning clients against real applications/databases. They cover publication, negotiation, settlement, exact site calls, restart, result, teardown, and transactional migration.
- Package/render tests use staged wheels and the real image/config/Helm/Compose surfaces.
- One system scenario runs a single multi-domain storefront through both complete lifecycles at one accepted authority, including cross-domain substitutions and independent failure. It does not duplicate Compute-40's later two-authority topology proof or `bare-metal-buyer-domain`'s buyer CLI acceptance.
  *2026-11-27 — not built.* No such scenario exists, and none can be written while no storefront process serves both domains (decision 3). A VM deal and a bare-metal deal each run in their own lane. The one-process scenario is `unify-vm-and-bare-metal-storefronts`'s lane scenario.

No test uses sleeps for recovery, raw HTTP where a canonical client exists, route-internal calls for cross-service proof, no-op fulfillment, or a boolean success flag in place of observed result/teardown/capacity restoration.

## Risks / Trade-offs

- **The common mapping migration is broader than adding discriminator columns.** Keeping the two mapping tables would force per-mode lookup branches forever. Whole-population validation and an atomic common table cost more now but remove the second authority cleanly.
- **Existing cold-cache fan-out is currently documented as safe.** It is idempotent but violates exact trusted routing and leaks operation existence across authorities. Explicit site-addressed methods preserve the existing general behavior while making accepted compute records strict.
- **A configured contract may be removed while terminal history remains.** Nonterminal/recoverable rows block readiness. Terminal rows stay safely queryable without decoding; operators install the old exact contribution when domain decoding is required.
- **Bare-metal seller/POOLS-7 acceptance may lag.** Registry, persistence, and routing work must not claim full completion until real production hooks and lifecycle evidence exist. Tasks mark those gates explicitly.
- **The existing package path is historically VM-owned.** Reusing the `market-storefront` composition minimizes deployment churn, but permanent architecture must describe its compute-family role and domain contributions rather than its directory history.
- **Publication work overlaps an active dimensions change.** Both must share the canonical builder/fixture; whichever lands second rebases rather than creating another field or duplicate tests.

## Implementation Inventory

- Shared registry/shell/persistence: `core/storefront/src/core_storefront/{domain_registry.py,app_composition.py,sqlite_client.py,sqlite_migrations.py,negotiation_sync.py,publication_runner.py}` and `core/storefront/src/core_storefront/services/negotiation_service.py`, plus `core/storefront/tests/unit/` focused files.
- Parameterized VM composition and common routes: `domains/vms/storefront/src/market_storefront/{domain_runtime.py,server.py,startup.py,container.py,settlement_composition.py,publication_wiring.py}`, `utils/{sqlite_client.py,migrations.py,sync_negotiation.py,config.py}`, relevant `controllers/` and `services/{listing_service.py,publication_service.py,capacity_client.py,fulfillment_service.py,fulfillment_resume_runtime.py}`, and their unit/integration suites.
- VM publication mapping: `domains/vms/domain/src/arkhai_vms/{domain_runtime.py,storefront_adapter.py}`, `domains/vms/listings/reconciler.py`, and publication/reconciler fixtures.
- Bare-metal contribution/cutover: `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/{domain_runtime.py,runtime.py,server.py,api.py,sqlite_client.py,migrations.py,negotiation_service.py,settlement_service.py,publication.py}`, its `pyproject.toml`, and storefront tests. Domain codecs remain in `domains/bare_metal/src/arkhai_bare_metal/`.
- Shared client/contract fixtures only if observable carriers change: `core/storefront-client/src/storefront_client/{models.py,client.py,fixtures/}` and producer/consumer integration suites.
- Packaging/deployment: `core/storefront/pyproject.toml`, both storefront `pyproject.toml`/Makefiles, `domains/Makefile`, storefront Dockerfile/build inputs, `compose.vms.yml`, relevant domain Compose configuration, `helm/charts/storefront/{values.yaml,values.schema.json,templates/configmap.yaml,templates/deployment.yaml}`, parent `helm/{values.yaml,values.schema.json}`, fixtures, and E2E staged state/scenarios.

*2026-11-27:* paths above that have moved or gone: `core_storefront/sqlite_migrations.py` is `core_storefront/migrations.py`; `core_storefront/negotiation_sync.py`, `market_storefront/utils/sync_negotiation.py`, and `arkhai_bare_metal_storefront/negotiation_service.py` no longer exist; the VM reconciler is `domains/vms/listings/src/arkhai_vms_listings/reconciler.py`.

## Migration Plan

1. Complete and record prerequisite contract checks.
2. Land frozen registry and common binding models with inert schema additions.
3. Add the explicit migration/check command and prove fresh, legacy VM, legacy bare-metal, conflict, rollback, and idempotent rerun.
4. Route publication/new negotiation through persisted bindings; keep effects quiesced until every open/nonterminal record resolves.
5. Route settlement, capacity, fulfillment, result, recovery, and teardown through accepted binding and exact site; remove old getters, parallel routes, tables, and fallbacks in the same cutover.
6. Build/install/render staged artifacts, run complete one-domain regressions and the dual-domain system scenario, then activate one combined deployment.
7. Promote accepted requirements/rationale, update Goal 3, complete hygiene and compression, and archive only after strict validation.

*2026-11-27:* steps 1, 2, 4, and 5 were carried out for the VM storefront, and step 7's promotion on 2026-08-15. Step 3's command is removed (decision 8). Step 6's dual-domain scenario and combined activation did not happen (decisions 3 and 11).

## Design Promotion Record

| Decision | Disposition | Permanent location |
|---|---|---|
| Frozen configured contributions; mode and domain identity remain distinct; durable resolution returns only the exact startup object | permanent | `openspec/specs/market-composition/spec.md#requirement-storefront-roots-inject-a-frozen-domain-registry`, companion `architecture.md#frozen-storefront-registry-and-executable-ownership`, and `docs/development/ARCHITECTURE.md#capacity-publication-and-multi-domain-storefront-composition` |
| Common listing binding, exact public mode, collision-safe provenance, and site-pinned routing | permanent | `openspec/specs/storefront-publication/spec.md#requirement-durable-bindings-govern-multi-domain-publication`, `#requirement-trusted-listing-mappings-route-to-one-site`, and companion `architecture.md#immutable-domain-ownership-and-publication` |
| Listing binding is copied transactionally into the thread and controls continuation/acceptance | permanent | `openspec/specs/negotiation-protocol/spec.md#requirement-negotiation-inherits-an-immutable-listing-domain-binding` and companion `architecture.md#record-bound-domain-dispatch` |
| Accepted binding controls settlement, fulfillment, result recovery, and teardown through domain-neutral carriers | permanent | `openspec/specs/settlement-servicing/spec.md#requirement-accepted-domain-binding-governs-the-servicing-lifecycle` and companion `architecture.md#accepted-domain-continuity` |
| Combined artifact/config topology | permanent | `openspec/specs/deployment-state/spec.md#requirement-multi-domain-storefront-configuration-is-explicit`, companion `architecture.md#multi-domain-storefront-activation`, and `openspec/specs/market-composition/configuration.md#combined-compute-family-storefront` |
| Preview-first transactional legacy migration | superseded | Promoted as `deployment-state`'s "Legacy storefront domain migration is transactional"; removed with the command by `add-database-migration-commands` |
| Focused cross-domain boundary matrix and real one-process proof jurisdiction | permanent | `openspec/specs/test-compatibility/spec.md#requirement-multi-domain-storefront-selection-has-focused-compatibility-coverage`, companion `architecture.md#multi-domain-storefront-evidence-ownership`, and `openspec/specs/market-composition/testing.md#multi-domain-storefront-composition` |
| Goal 3's registry and record binding delivered; the bare-metal buyer and producer since delivered; a storefront process serving both domains not built, and owned by `unify-vm-and-bare-metal-storefronts` | permanent | `docs/development/ROADMAP.md#goal-3--one-storefront-serving-several-compute-family-domains` |
| Process-global contract getters, one-element/default selection, payload-kind routing, cross-site accepted-record fan-out, and parallel VM/bare-metal shared control flow | superseded | Replaced by the permanent registry/binding requirements above |
| A no-op bare-metal fulfillment hook or VM-shaped compatibility adapter | rejected | `test-compatibility`'s "Multi-domain storefront selection has focused compatibility coverage", scenario "Full live proof is requested" |
| Change-local implementation/debugging commentary | temporary | Retained only in this design and task history |
| The derivation key includes the offering mode and the exact domain identity and contract version | permanent | `openspec/specs/storefront-publication/spec.md#requirement-commercial-mapping-identity`, by the archive |

## Delta scope

The deltas are the corrective pair written on 2026-11-27, each a MODIFIED requirement rebuilt from the permanent text as it stood that day.

- `storefront-publication`, "Commercial mapping identity": adds that a derivation key includes the offering mode and the exact domain identity and contract version. Every other sentence, and every scenario, is the permanent text. `core_storefront.domain_registry.build_storefront_derivation_key` builds the key so. The original delta's scenario "One pool exposes two offering modes" is not carried: no test asserts that two modes over one source identity yield different keys, and no deployment reaches it, since each storefront builds its own publication source alone. `unify-vm-and-bare-metal-storefronts` adds that scenario, with its test, when it makes one pool publishable under two modes.
- `test-compatibility`, "Multi-domain storefront selection has focused compatibility coverage": drops migration from the coverage it requires, since the migration and its tests are removed; restates the scenario "One and two registrations use the same shell" without the claim of common routes, each storefront executable mounting its own; and restates the scenario "Full live proof is requested", whose condition was the bare-metal contribution or the selected-site lifecycle being unavailable, as what blocks a one-process proof today: no storefront process serves a second registration.

## Disposition of the original delta requirements

The six delta files written with the proposal are deleted. They were not merged: on 2026-08-15 the permanent specifications received the shorter requirement set the Design Promotion Record names, written by hand, and the archive would have refused three of the original requirements as already present and added the rest beside the text that restates them. Each original requirement, and where its rule lives:

| Capability | Original delta requirement | Where its rule lives |
|---|---|---|
| `deployment-state` | ADDED "Multi-domain storefront configuration is explicit" | The permanent requirement of the same title, reworded. Its clause that startup rejects a recoverable binding the configuration does not supply was not carried, and startup makes no such check (decision 5) |
| `deployment-state` | ADDED "Storefront domain-binding migration is transactional and explicit" | Nowhere. Promoted as "Legacy storefront domain migration is transactional" and removed by `add-database-migration-commands` |
| `deployment-state` | ADDED "Multi-domain packaging and rollout are coordinated" | Its packaging half is in "Multi-domain storefront configuration is explicit"; forward recovery after effects is in the companion's "Multi-domain storefront activation". Its rollout half prescribed the removed migration and lives nowhere |
| `market-composition` | MODIFIED "Role-owned executable composition" | Not applied. The permanent requirement stands as it was: VM, bare-metal, and API-credit storefront executables are domain-owned composition roots. The modification's claim that a one-domain storefront is no alternate role implementation is not true of them |
| `market-composition` | ADDED "Storefront domain registrations are explicit and immutable" | "Storefront roots inject a frozen domain registry" |
| `market-composition` | ADDED "Domain selection comes only from immutable record binding" | "Storefront roots inject a frozen domain registry", with `negotiation-protocol`'s and `settlement-servicing`'s requirements below. Its scenario "Registration order changes after restart" is held by `core/storefront/tests/unit/test_domain_registry.py` and stated nowhere |
| `market-composition` | ADDED "Shared storefront control flow does not branch on compute domains" | Nowhere, and not true: each storefront keeps its own route set. For VM and bare metal it is `unify-vm-and-bare-metal-storefronts`'s to make true |
| `negotiation-protocol` | ADDED "Negotiation inherits an immutable listing-domain binding" | The permanent requirement of the same title, condensed |
| `negotiation-protocol` | ADDED "Continuation and acceptance use the recorded thread binding" | The last sentence of "Negotiation inherits an immutable listing-domain binding" and its scenario "Configuration changes during an accepted thread" |
| `negotiation-protocol` | ADDED "Accepted domain binding cannot be rewritten" | The same scenario; the immutability itself is `storefront-publication`'s "Durable bindings govern multi-domain publication" and the binding triggers of the storefront baseline |
| `settlement-servicing` | ADDED "Accepted domain binding governs the entire servicing lifecycle" | "Accepted domain binding governs the servicing lifecycle" |
| `settlement-servicing` | ADDED "Recovery resolves domain and site from durable state" | That requirement's scenarios "Teardown repeats after restart" and "Contract is unavailable after acceptance" |
| `settlement-servicing` | ADDED "Cross-domain failures and teardown remain isolated" | Not stated separately; that requirement's scenario "VM and bare-metal obligations service concurrently" is the nearest |
| `storefront-publication` | MODIFIED "Commercial mapping identity" | Its clause is kept, rebuilt, as one of the corrective pair. Its scenario "One pool exposes two offering modes" is not carried and is left to `unify-vm-and-bare-metal-storefronts` ("Delta scope", above) |
| `storefront-publication` | ADDED "Published offering mode is exact and pool-authorized" | "Durable bindings govern multi-domain publication" |
| `storefront-publication` | ADDED "Listing and mapping bindings are immutable" | "Durable bindings govern multi-domain publication" |
| `storefront-publication` | ADDED "Trusted site routing applies across all offering modes" | "Trusted listing mappings route to one site", beside "Site-pinned claim routing" |
| `test-compatibility` | ADDED "Multi-domain storefront selection has focused compatibility coverage" | The permanent requirement of the same title, which the corrective pair modifies |
| `test-compatibility` | ADDED "One storefront proves complete VM and bare-metal lifecycles" | Nowhere as a requirement: unmet. The scenario "Full live proof is requested" says what blocks it, and `unify-vm-and-bare-metal-storefronts`'s lane scenario is the proof |
| `test-compatibility` | ADDED "Pool mode and trusted site isolation are proven together" | Nowhere under this capability; the behaviours are `site-capacity`'s and `storefront-publication`'s own evidence |
| `test-compatibility` | ADDED "Multi-domain package and deployment evidence uses staged artifacts" | The scenario "Installed-artifact deployment is inspected" of "Multi-domain storefront selection has focused compatibility coverage" |
