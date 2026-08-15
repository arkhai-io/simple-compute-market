## Context

See `proposal.md#why`. The current code already has the lower-level contract and most of the desired shape:

- `core/src/market_core/domain_contract.py` defines frozen `MarketDomainContract`, supported version validation, stable `DomainIdentity`, declared capability validation, and typed codec/storefront/settlement/fulfillment/compute-provisioning hook sets.
- `core/storefront/src/core_storefront/app_composition.py:build_storefront_app` requires a domain, validates it, and stores it on `app.state.market_domain`.
- The bare-metal root is the working comparison: `build_bare_metal_storefront_app(domain=...)` closes over one selected contract, `build_runtime_from_environment(domain=...)` validates and passes it to `BareMetalStorefrontRuntime` and `SQLiteClient`, and `BareMetalNegotiationService` owns a contract field.
- The VM root supplies a contract to `build_storefront_app`, but domain-sensitive work later calls `market_storefront.domain_runtime.get_market_domain_contract()` again from listing validation, negotiation policy/normalization, settlement-plan construction, and fulfillment dispatch. The VM SQLite singleton, service constructors, lifespan callbacks, and dependency container do not carry the app-selected object.
- `core/storefront/src/core_storefront/app_lifecycle.py` is already callback-driven. VM callbacks can close over a selected contract without teaching core about VM or changing its public callback vocabulary.
- VM publication has two distinct forms. HTTP/admin listing creation and republishing run through `ListingService` and are in this cutover. The standalone `market-storefront publish` command composes installed publication-source entry points through core's explicit `PublicationSourceSelection`; it does not use the VM `get_market_domain_contract()` accessor. This change verifies that command for parity but does not redesign entry-point selection. Per-record selection across VM and bare-metal publication sources belongs to `multi-domain-storefront-composition`.

The boundary is intentionally narrower than multi-domain routing: this change makes a single selected contract explicit everywhere. It does not decide how a future record names one contract from a set.

## Goals / Non-Goals

**Goals:**

- Establish one outermost VM app factory and one validated `compute.v1` contract object per composed application.
- Pass that object explicitly through lifespan construction, container publication, repository construction, listing/publication, negotiation, settlement, and fulfillment.
- Reject incompatible contracts before database construction, background workers, route handling, publication, negotiation state, settlement registration, or provisioning effects.
- Preserve current VM behavior, identifiers, persisted interpretation, package layering, and independent bare-metal composition.
- Leave a small, unambiguous seam that `multi-domain-storefront-composition` can replace with per-record selection rather than another lookup convention.

**Non-Goals:**

- A contract registry, offering-mode selector, domain discriminator column, multi-domain route, cross-domain repository, or mixed-domain worker.
- New `MarketDomainContract` fields, core-to-domain dependencies, or a generic core storefront executable.
- Changes to standalone publication entry-point discovery, domain codecs, settlement mechanism registration, configuration, deployment, or persistence schemas.
- A compatibility layer for callers that omit the contract below the outer composition root.

## Decisions

### 1. Validate once at the VM composition boundary, then preserve object identity

`market_storefront.domain_runtime` will expose a constructor for the ordinary VM storefront contract and a VM-root validator. The validator first calls `market_core.validate_domain_contract`, then requires:

- stable identity `compute.v1` for this single-domain executable;
- the core-supported contract version;
- complete codecs;
- declared and implemented `STOREFRONT`, `SETTLEMENT`, `FULFILLMENT`, and `COMPUTE_PROVISIONING` capabilities; and
- the existing VM publication capability retained from the base domain contract.

The app factory validates before it builds the lifespan or app. Lower layers receive the validated object and MAY assert that a collaborator is bound to the same object/identity, but MUST NOT reconstruct, rediscover, or silently revalidate a replacement. `build_storefront_app` may retain its generic validation as defense in depth; this does not create a second selection point because it returns the supplied object unchanged.

The error contains stable identity plus version or capability. It contains no payload or credential data. Wrong type, identity, version, declaration, implementation, and hook completeness are distinct focused cases. Missing capabilities do not fall back to hard-coded VM functions.

**Alternative — accept any well-formed domain identity.** Rejected for this prerequisite. The HTTP routes, models, capacity and fulfillment services are still VM-specific, so accepting `bare_metal.v1` would promise multiplexing before per-record routing exists. The dependent multi-domain change will deliberately replace this single-domain identity guard.

**Alternative — expand core validation with a VM role profile.** Rejected. Generic core validation should not learn the VM executable's required identity or capability set.

### 2. Build the default app through an explicit factory

`market_storefront.server` will introduce `build_vm_storefront_app(*, domain: MarketDomainContract, ...)`. The production `app` is built by constructing the existing VM storefront contract once at the module's outer composition statement and passing it to the factory. `run_serve` continues to launch that default app and the command/config surface is unchanged.

The app factory constructs a lifespan factory whose callback closures capture `selected_domain`. The callbacks pass it into:

1. `get_sqlite_client(domain=selected_domain)`;
2. `ListingService(domain=selected_domain, ...)`;
3. the negotiation adapter bound into `NegotiationService`;
4. settlement composition construction;
5. container population; and
6. startup-task assembly.

The controller dependency container publishes `resolved_market_domain` for request adapters and diagnostics, alongside the existing lifespan-owned singleton services. Domain-sensitive helpers MUST receive it as an argument from the controller/service closure; they MUST NOT read it from the container as a replacement global lookup. The container slot exists to make app/request wiring explicit and inspectable, not to create a new service locator.

At startup, container population rejects a contract mismatch and happens before background tasks. Shutdown clears lifespan-owned contract and service slots in the same place as other resolved dependencies if the existing lifecycle cleanup pattern is extended; tests must prove a second composed app cannot inherit a prior app's contract.

**Alternative — mutate a module-level `CURRENT_DOMAIN`.** Rejected because it retains the hidden process-wide selection that blocks multiple roots and makes tests order-dependent.

**Alternative — add a new aggregate `VmStorefrontRuntime` immediately.** Rejected as unnecessary indirection for a behavior-preserving cutover. Existing service and settlement composition objects remain the durable collaborators; explicit constructor parameters make the boundary visible without pre-designing the later contract registry.

### 3. Repository construction requires the contract and exposes it read-only

`market_storefront.utils.sqlite_client.SQLiteClient` will require a validated contract at construction and retain it on a read-only property for composition assertions and domain artifact normalization. The settings-bound singleton factory becomes `get_sqlite_client(*, domain)` with no default. If a singleton already exists under a different object or identity, the factory fails rather than reusing it.

The repository does not add a domain column and does not infer a domain from stored JSON. Current VM tables remain single-domain and their existing codec interpretation is unchanged. Tests that directly construct `SQLiteClient` use the ordinary VM contract fixture explicitly; a shared test helper may remove repetitive setup, but production constructors receive no default.

**Alternative — read `app.state.market_domain` inside the repository.** Rejected because persistence should not depend on FastAPI and background/CLI callers need the same constructor contract.

**Alternative — store only a domain identity string.** Rejected because normalization and role hooks need the validated capability object; re-resolving from a string recreates the lookup problem.

### 4. Publication and listing services use the injected codecs

`ListingService` adds a required `domain` argument and stores it. `_parse_offer_and_escrows` validates the normalized offer with `self._domain.codecs.listing`; create and republish keep the existing settlement option and registry publication behavior. The service constructor rejects a domain that disagrees with its repository.

The HTTP/admin publication path therefore uses the same object as the app and repository. `publication_wiring.py` and `cli_publish.py` remain unchanged unless implementation inspection identifies a direct call to the removed VM accessor; their existing core entry-point selection is explicit and separately validated. Focused publication command tests remain parity evidence, not a reason to widen this change into per-source contract routing.

**Alternative — leave listing validation on the VM Pydantic model only.** Rejected because it would bypass the contract seam precisely where future per-record composition needs it.

### 5. Negotiation receives the contract as a required keyword

`start_sync_negotiation`, `continue_sync_negotiation`, `_normalize_vm_message_terms`, `_default_seller_round_hook`, and accepted-plan helpers that call domain capabilities receive an explicit `domain`. `NegotiateController` receives the resolved contract through its dependency constructor and passes it on. The `NegotiationService` continuation callback is a closure/`partial` bound to the same contract.

The existing optional `seller_round_hook` remains a policy test seam. It does not replace domain injection: envelope normalization and accepted-plan construction always use the supplied domain. Direct unit/integration callers pass the contract fixture explicitly; no helper defaults to `get_market_domain_contract`.

**Alternative — derive the contract from `sqlite_client.market_domain` inside negotiation helpers.** Rejected as an implicit coupling that obscures the function's semantic dependency. The controller may assert repository agreement, but the helper signature names the dependency.

### 6. Settlement composition owns the contract it uses

`VmSettlementComposition` adds a `domain` field. `build_vm_settlement_composition(..., domain=...)` requires the injected contract, verifies agreement with the repository, and binds domain-dependent callbacks to it. `_settlement_plan_obligations` and `fulfill_vm_settlement` receive or close over that contract; neither imports `domain_runtime`.

Settlement registry/configuration, `SettlementSQLiteRepository`, mechanism clients, operation journals, plan/obligation IDs, readiness, failure actions, and workers are unchanged. The injected settlement and fulfillment hooks are the same callables the default VM contract exposes today.

**Alternative — keep two helper-level module lookups because the returned contract is immutable.** Rejected. Immutability prevents mutation, not divergent selection, and the future selector cannot override a hidden lookup.

### 7. Startup carries the selected contract but does not reinterpret it

The lifespan callback into `startup.py` receives the selected contract and asserts that the populated container, SQLite client, listing service, negotiation service adapter, and settlement composition are bound to it before settlement preflight or workers start. Startup does not call a domain factory and does not branch on identity. Existing step ordering, provisioning preflight, resource seeding, watchdogs, settlement servicing, fulfillment resume, site projections, and capacity polling stay byte-for-behavior equivalent.

This assertion is the final fail-closed guard against a wiring error; compatibility validation remains owned by the composition boundary.

### 8. Bare metal is evidence and a downstream consumer shape, not an edit target

The bare-metal `server.py`, `runtime.py`, `sqlite_client.py`, and `negotiation_service.py` already demonstrate explicit contract carriage. Focused tests compare the VM shape to these invariants and keep bare metal green. This change does not unify the two runtime classes or import one from the other.

If implementation discovers a defect in a genuinely shared `core_storefront` seam, the proposal/design/tasks must be amended before editing shared core or bare-metal files. A convenience refactor is not sufficient cause.

### 9. No migration, carrier, configuration, deployment, or packaging contract changes

The contract is process-local immutable composition state. It is not serialized. Therefore:

- no database migration or backfill is added;
- no listing, negotiation, settlement, fulfillment, or HTTP field changes;
- no configuration key or environment variable selects a domain;
- no Helm, Compose, settings, Docker, lockfile, or wheel dependency changes are expected;
- existing databases open under the injected default contract with stable identifiers; and
- rollback before `multi-domain-storefront-composition` is a code/wheel revert.

After a dependent change persists domain/offering-mode discriminators, rollback semantics belong to that dependent change and MUST NOT be represented as covered here.

## Exact implementation map

| Boundary | Expected files | Planned responsibility |
|---|---|---|
| Contract construction/validation | `domains/vms/storefront/src/market_storefront/domain_runtime.py` | Build ordinary VM contract; validate exact single-domain VM identity/version/capability profile; remove getter-style selection API |
| App and lifespan root | `domains/vms/storefront/src/market_storefront/server.py` | Add parameterized app/lifespan factory; construct default once; bind callback closures |
| Container/startup | `domains/vms/storefront/src/market_storefront/container.py`, `startup.py` | Publish same contract for dependency wiring; reject mismatch before workers; no semantic lookup |
| Repository | `domains/vms/storefront/src/market_storefront/utils/sqlite_client.py` | Require, retain, expose, and enforce singleton agreement with injected contract |
| Listing/publication | `domains/vms/storefront/src/market_storefront/services/listing_service.py` | Use injected listing codec and repository-agreement guard |
| HTTP negotiation adapter | `domains/vms/storefront/src/market_storefront/controllers/negotiate_controller.py` | Inject contract dependency and pass it to start/continue helpers |
| Negotiation semantics | `domains/vms/storefront/src/market_storefront/utils/sync_negotiation.py` | Replace module getter calls with required contract parameter/closures |
| Settlement and fulfillment | `domains/vms/storefront/src/market_storefront/settlement_composition.py` | Retain domain on composition; use its plan/fulfillment hooks |
| Focused proof | `domains/vms/storefront/tests/unit/test_domain_runtime_wiring.py`, `test_server_app_composition.py`, `test_migrations.py`, `test_publications_wiring.py`, `test_sync_negotiation_seller_round_hook.py`, `test_settlement_composition.py`, `test_architecture_imports.py` | Injection identity, invalid matrix, parity, no migration, package direction |
| Route/package proof | `domains/vms/storefront/tests/integration/test_listings_api.py`, `test_negotiations_api.py`, `test_settle_controller.py`; `domains/vms/storefront/Makefile`, root `Makefile` existing targets | Existing observable paths and installed-wheel checks; target definitions change only if required to include already-existing tests |
| Reference only | `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/{domain_runtime.py,server.py,runtime.py,sqlite_client.py,negotiation_service.py}` | Preserve current explicit parameterized shape; no planned edits |

## Risks / Trade-offs

- **Hidden lookup survives in an indirect helper.** Mitigation: search the VM production package for `get_market_domain_contract` and remove every semantic call; architecture tests forbid reintroduction outside the outer default constructor.
- **Container storage becomes a renamed global singleton.** Mitigation: service/helper signatures require the contract; only dependency wiring and diagnostics read the container slot. Tests inject two distinct compatible objects and prove no cross-app leakage.
- **Direct test callers become noisy.** Accepted. A single explicit fixture is preferable to a production default that hides the dependency.
- **Strict object-identity checks complicate wrappers.** The root deliberately owns one immutable object per app. Future multi-domain composition may compare stable identity/version within its registry, but this single-domain prerequisite uses identity checks to expose accidental reconstruction.
- **Wrong-domain validation duplicates future selector logic.** Temporary and explicit: the VM executable is still VM-specific. The dependent change replaces the guard when it supplies exact per-record routing and persistence.
- **Behavior-preserving refactor accidentally changes worker ordering or settlement closures.** Mitigation: retain existing lifecycle callback order and mechanism/runtime factories; focused tests inspect binding while current integration suites own observable behavior.
- **Standalone publication is mistaken for app-root publication.** Mitigation: document the separate process boundary and verify existing command tests. Do not redesign core entry-point selection here.

## Migration and rollback

1. Introduce the validator and parameterized app/lifespan composition while preserving the default `compute.v1` construction.
2. Thread the contract through repository, listing/publication, negotiation, and settlement/fulfillment; update every caller in the same cutover.
3. Remove the getter-style VM domain selection API and prove no production callsite or compatibility alias remains.
4. Run focused and package/integration parity evidence before promotion.
5. Deploy as an ordinary code/wheel replacement. There is no operator migration command, quiescence requirement, data backfill, or config change.
6. Before any dependent multi-domain persistence is deployed, rollback is the preceding code/wheel set against the same database. After such persistence exists, use that dependent change's rollback plan.

## Dependencies and sequencing

- No prerequisite change blocks implementation.
- `multi-domain-storefront-composition` MUST begin only after this change's clean cutover, focused proof, permanent promotion, and roadmap closeout are accepted. It consumes the explicit contract parameter and replaces single-domain validation with exact per-record selection.
- `kit-storefront-composition-seam` also depends on this change and MUST receive a contract through the injected seam rather than moving module lookup into kit.
- Changes touching the VM root, negotiation, settlement composition, or publication while this work is implemented must preserve the required parameter and coordinate their constructor/callback signatures.

## Permanent promotion map

| Accepted decision | Permanent location |
|---|---|
| Domain-owned storefront roots select and inject one validated contract; core remains schema-opaque | `openspec/specs/market-composition/spec.md` and `docs/development/ARCHITECTURE.md#composition-from-above-and-below` |
| Module-global domain resolution and lower-layer fallback are forbidden | `openspec/specs/market-composition/spec.md` |
| One contract governs publication, negotiation, settlement, fulfillment, and repository normalization for a single-domain record | `openspec/specs/storefront-publication/spec.md` |
| Invalid identity/version/capability fails before startup work or side effects | `openspec/specs/market-composition/spec.md` and `openspec/specs/storefront-publication/spec.md` |
| Injection identity, compatibility matrix, parity, and package-direction test ownership | `openspec/specs/test-compatibility/spec.md`; `docs/development/TESTING.md` only if durable methodology changes |
| No schema/config/deployment migration and code-only pre-dependent rollback | Active change only as transition detail; no permanent documentation unless implementation finds a durable operational rule |
| Prerequisite completion and remaining multi-domain discriminator/routing gap | `docs/development/ROADMAP.md` multi-domain storefront goal |
