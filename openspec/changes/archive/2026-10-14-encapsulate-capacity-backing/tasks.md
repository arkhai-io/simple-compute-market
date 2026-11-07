# Tasks — encapsulate capacity backing

Design decided 2026-10-14 and planned the same day; Sections 2–7 implemented, awaiting code review, the two blocked locks, and the end-to-end run. Prerequisite of
`unbacked-bare-metal-listings`. Planning's two findings and its refinements are in
`design.md`, "Planning decisions (task 1.6)".

Sections 2 and 3 change kit interfaces and update every importer in the same task, so
the tree builds and every suite passes at the end of each section. Sections 4–6 then
move each domain's behaviour onto the delegate and can land in any order.

## 1. Design

- [x] 1.1 **Decision gate.** Inventory every production switch on capacity backing —
      label comparisons, binding-class tests, hard-coded backed assumptions, and
      mechanism fulfilment declarations — across core, kit, provisioning, and every
      domain, classified by what each decides. Record it in `design.md`. Decided with
      the maintainer: nine behaviours become delegate operations; comparing bound and
      source backing is a divergence, not an operation; API credits moves onto the
      delegate in this change; the storefront's copy of the vocabulary validates
      through the delegate while its database check stays ("What the delegate
      decides", "API credits moves onto the delegate in this change", "The
      storefront's copy of the vocabulary goes; its database check stays").
- [x] 1.2 **Decision gate.** Derive the delegate's operations from the inventory, so
      that no caller compares the label or tests the binding class, and name the
      delegate. Record it in `design.md`. Decided with the maintainer:
      `CapacityBacking` in `kit/resource-pools-contracts`, one class with `BACKED` and
      `UNBACKED` instances, whose operations take the caller's work as callables
      ("The delegate's operations").
- [x] 1.3 **Decision gate.** Decide the unified behaviour for each divergence between
      VM, bare metal, and API credits, and where bare metal's refusal of unbacked
      pools is expressed while this change keeps it. Record each as its own decision. Decided
      with the maintainer, one decision per divergence ("Divergence: …" in `design.md`):
      admitting unbacked supply (bare metal's refusal stays, explicit and temporary,
      removed by `unbacked-bare-metal-listings`), binding construction, the published
      label, backing disagreement on refresh and reopen, source-check availability,
      reconciliation scope, hold placement, capacity-effect guard coverage, and
      whether a mechanism delivers through capacity.
- [x] 1.4 **Decision gate.** Decide how the `CapacityBinding` and `UnbackedBinding`
      classes relate to the delegate, and record it. Decided with the maintainer: one
      `PublicationBinding` class carrying the delegate replaces both; a refused
      admission answers 409 ("One binding class carries the delegate").
- [x] 1.5 **Decision gate.** Decide how the site's resource publication views receive
      the pool's delegate, and record it. Decided with the maintainer: not in this
      change; no site view reads backing today, so the plumbing and its delegate
      operation move to `unbacked-bare-metal-listings` ("Site publication views stay
      outside this change").
- [x] 1.6 Plan the implementation, naming the files each decision touches, the focused
      and integration suites, and the permanent documentation destinations, and
      reconcile the plan with the bordering changes `proposal.md` names. Planned as
      Sections 2–9. The operation contracts, what planning confirmed, and the
      reconciliation with each bordering change are in `design.md`, "Planning
      decisions (task 1.6)".
- [x] 1.7 **Decision gate.** Decide how bare metal's three capacity effects pass the
      guard, since bare metal composes no `CapacityRuntime`. Decided with the
      maintainer: the guarded effects move into `CapacityEffects`, which the runtime
      composes and bare metal composes over its own aggregate client ("Bare metal's
      effects go through `CapacityEffects`, not a runtime").
- [x] 1.8 **Decision gate.** Decide an API-credit listing's derivation identity.
      Decided with the maintainer: its listing ID, so several listings may share a
      quota resource as today ("An API-credit listing's derivation identity is its
      listing ID"). Also decided: fix the two API-credit defects in the files this
      change rewrites ("Two API-credit defects are fixed where this change already
      edits").

## 2. The delegate

- [x] 2.1 `kit/resource-pools-contracts/src/market_resource_pools_contracts/backing.py`
      (new): `CapacityBacking`, one class with private configuration and `label`;
      module-level `BACKED` and `UNBACKED`; `CapacityNotAdmittedError`; the registry
      `capacity_backing(label)`, refusing an unknown label with the resolver's
      `INVALID_CAPACITY_BACKING` code, plus `capacity_backing_labels()`,
      `labels_reconciled_by_availability()`, `legacy_producer_backing()`, and
      `admitted_backing()`. Operations, to the contracts in `design.md`:
      `declaration_problems(advertisable, deliverable)`, `require_admission(effect)`,
      `place_hold(place)` (a coroutine), `judge(declared, available)` and
      `judge_async`, and `admissible_settlement(clauses, fulfils_through_capacity)`
      returning kept clauses and dropped mechanisms. The policy-tag names, the problem
      codes, and `PoolDeclarationProblem` move from `hints.py` into a new
      `vocabulary.py` that both modules import and `hints.py` re-exports unchanged, so
      `hints.py` can call the delegate without an import cycle. Neither module imports
      beyond the standard library and the package, so the allowlist holds.
      *Done.* `backing.py` and `vocabulary.py`; the one private fact every operation follows from is whether an admission authority stands behind the supply.
- [x] 2.2 `kit/resource-pools-contracts/src/market_resource_pools_contracts/hints.py`:
      rename the `CapacityBacking` literal `CapacityBackingLabel`; drop
      `CAPACITY_BACKED`, `CAPACITY_UNBACKED`, and `CAPACITY_BACKING_VALUES` in favour of
      the registry; `pool_declaration_problems` resolves the label through
      `capacity_backing` and calls the delegate's `declaration_problems` for the two
      cross-tag rules, keeping its problem codes and messages; `PoolDeclarations` carries
      `backing: CapacityBacking` and loses its `backed` property. Update the module
      docstring to say the delegate decides the cross-tag rules. Re-export from
      `__init__.py`. Bump the package version.
      *Done.* Version 0.2.0; the problem codes and messages are unchanged.
- [x] 2.3 `kit/resource-pools/src/market_resource_pools/site_declarations.py`:
      `ResolvedPool` carries `backing: CapacityBacking`, loses `backed`, and the
      compatibility rule resolves pools with `legacy_producer_backing()`.
      `service.py`'s `_require_backing_unchanged` and `_backing_change_problems` keep
      comparing stored labels — immutability is label equality, not a backing decision.
      Bump the package version.
      *Done.* Version 0.7.0.
- [x] 2.4 Every importer of the dropped names, mechanically, in the same commit:
      `provisioning/compute/service/src/compute_provisioning_service/db/migrations.py`
      (the backfill writes `legacy_producer_backing().label`);
      `domains/apicredits/service/src/apicredits_service/db/database.py` and
      `db/migrations.py` (the system pool's seeded and migrated label, from
      `BACKED.label`); `e2e-tests/tests/e2e/roles/scenarios/vms/host_registry.py`;
      and `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/site_reading.py`,
      whose refusal becomes `pool.backing is not BACKED` — the one comparison left in
      the tree, with the comment saying it stands until bare metal publishes unbacked
      supply, not naming the change.
      *Done.* VM's `listing_sources.py` and `reconciler.py` read `backing.label` here and move onto the delegate in Section 4.
- [x] 2.5 Tests. `kit/resource-pools-contracts/tests/unit/test_backing.py` (new): each
      operation for both delegates, including `judge`'s short-circuit (an unbacked
      delegate never calls `available`; a backed one never calls it after a declared
      refusal), `place_hold` not calling `place` when unbacked, the registry refusing an
      unknown label, and the registry's label set equal to the resolver's accepted
      values. `test_hints.py` and `kit/resource-pools/tests/unit/test_site_declarations.py`
      assert on `backing` rather than `backed`. Provisioning's
      `test_pool_advertisement_backing_migration.py` and `test_capacity_api.py`,
      and the credits service's `test_pool_declarations_migration.py`, likewise.
      *Done.* `test_backing.py` covers every operation for both delegates and the registry.
- [x] 2.6 Validation: `make -C kit test-resource-pools-contracts test-resource-pools`,
      `make test-provisioning`, `cd domains/apicredits/service && make test`,
      `make test-bare-metal`, and `make check-architecture`.
      *Done.* Contracts 165, resource pools 138, provisioning 675 + 456, credits service 70, bare metal green; `make check-architecture` passes.

## 3. Bindings and capacity effects

- [x] 3.1 `kit/capacity-publication/src/market_capacity_publication/capacity.py`:
      replace `_ListingIdentity`, `CapacityBinding`, and `UnbackedBinding` with one
      frozen `PublicationBinding(site_id, offering_mode, source_id, backing)`;
      `publication_binding(capacity_backing=label, ...)` resolves the delegate through
      the registry and raises `CapacityBindingError` for an unknown label; add
      `backing_changed(binding, source_backing)`. Add `CapacityEffects(client)` over an
      `AggregateCapacityClient`, acting only at the sites it names: `require_binding`
      calls `binding.backing.require_admission(effect)` and then refuses an unknown
      site with `CapacityBindingError`; `reserve`, `commit`, `release`, and
      `truncate_lease` move here unchanged otherwise. `CapacityRuntime` builds one over
      its own aggregate and delegates its effect methods and `require_binding` to it.
      Export `CapacityEffects` and `backing_changed`; stop exporting the two classes.
      *Done.* `CapacityEffects` addresses the aggregate's own effects by site (`design.md`, "Implementation notes"). Version 0.7.0.
- [x] 3.2 `kit/capacity-publication/src/market_capacity_publication/admin_routes.py`:
      answer `CapacityNotAdmittedError` with 409, keeping 500 for `CapacityBindingError`;
      update the hook comment. `publication.py`: docstrings only — the persisted-binding
      comparison now covers backing through the field.
      *Done.*
- [x] 3.3 `kit/capacity-publication/pyproject.toml`: add
      `arkhai-kit-resource-pools-contracts`; bump the version and every `==` pin of it
      (the VM, bare-metal, and API-credit storefronts).
      *Done.*
- [x] 3.4 Every importer of the two classes, mechanically, in the same commit:
      construct `PublicationBinding(..., BACKED)` or call `publication_binding`, and
      replace `isinstance(binding, (CapacityBinding, UnbackedBinding))` identity checks
      with `isinstance(binding, PublicationBinding)`. VM: `negotiation_runtime.py`,
      `services/listing_service.py`, `services/vm_fulfillment_service.py`,
      `services/listing_source_check.py`, `controllers/admin_controller.py`,
      `services/publication_service.py`, `services/capacity_client.py`. Bare metal:
      `publication_service.py`. API credits: `services/capacity_client.py`,
      `services/publication_service.py`. The backing switches among them keep their
      current behaviour here, expressed against the delegate's label until Sections
      4–6 replace them, so no section leaves a suite red.
      *Done.* Bare metal's binding took its final form here (5.2).
- [x] 3.5 `core/storefront/src/core_storefront/domain_registry.py`: delete
      `CAPACITY_BACKING_VALUES`; `StorefrontListingBinding.__post_init__` validates
      through `capacity_backing(label)`, keeping `StorefrontDomainRegistryError` as the
      refusal. Remove the re-export from `__init__.py`. `pyproject.toml`: add
      `arkhai-kit-resource-pools-contracts`, bump the version and
      `kit/capacity-publication`'s `==` pin. VM's `publication_binding.py` validates
      through the registry instead of the removed copy.
      *Done.* `arkhai-core-storefront` 0.12.0.
- [x] 3.6 `kit/site-client/src/market_site_client/fixtures/resource_pools.py`: delete
      `_BACKING_VALUES`; validate the label through the registry; choose the default
      deliverable set through `declaration_problems`, per `design.md`. Add the contracts
      dependency and bump the version.
      *Done.* A label no delegate is registered for is projected as given, delivering nothing, so consumer tests can build an unresolvable pool. Version 0.10.0.
- [x] 3.7 Tests. `kit/capacity-publication/tests/unit/test_capacity.py`: one binding
      class; two bindings differing only in backing are unequal; an unbacked binding
      is refused by every effect before any site call with `CapacityNotAdmittedError`;
      `CapacityEffects` over a fake aggregate acts only at its named sites;
      `backing_changed`. `test_admin_routes.py`: a refused admission answers 409.
      `test_publication.py` and `test_registry_convergence.py`: the new class.
      `core/storefront/tests/integration/test_domain_binding_migrations.py`: the SQL
      `CHECK`'s value set equals `capacity_backing_labels()`, parsed from the applied
      migration's DDL. `kit/site-client/tests/unit/test_resource_pool_fixture.py`:
      both defaults. Every VM, bare-metal, and API-credit test constructing the
      removed classes, mechanically.
      *Done.* Capacity publication 69, core storefront 192, site client 49.
- [x] 3.8 Validation: `make -C kit test-capacity-publication test-site-client`,
      `make test-core`, `make test-storefront`, `make test-bare-metal`,
      `make test-apicredits`, `make lock`, and `make check-architecture`.
      *Done*, with `make lock` deferred to 7.2.

## 4. VM onto the delegate

- [x] 4.1 **Published label.** `domains/vms/listings/src/arkhai_vms_listings/models.py`
      types `capacity_backing` as `CapacityBackingLabel | None`.
      `domains/vms/listings/pyproject.toml` moves `arkhai-kit-resource-pools-contracts`
      from the `pools` extra to the base dependencies; bump the version. The buyer's
      `test_no_resource_pools_dependency.py` still passes.
      *Done.* `arkhai-vms-listings` 0.5.0.
- [x] 4.2 **Feasibility.** `arkhai_vms_listings/reconciler.py`: `_judge_members`
      becomes the two halves of `judge` over the declaration's delegate; a
      `declared_only` caller calls the declared half alone. The string comparison at
      the `backed` assignment goes.
      *Done.*
- [x] 4.3 **Reconciliation scope.** `reconciler.py`: `_bound_vm_listings` and
      `stale_open_listing_ids` take a scope — availability or source — in place of
      `backed_only`; availability binds `labels_reconciled_by_availability()` as SQL
      parameters. Update the five availability call sites
      (`services/publication_service.py` twice, `failure_actions.py`,
      `controllers/admin_controller.py` twice) and the source call sites
      (`services/publication_loop.py`'s `_close_stale` and `open_listing_resource_keys`).
      *Done.* `ReconciliationScope.SOURCE` and `.AVAILABILITY`.
- [x] 4.4 **Backing comparison.** `arkhai_vms_listings/listing_comparison.py`'s
      `BACKING_DISAGREES` outcome runs first through `backing_changed`; the legacy
      `BACKING_UNDISCLOSED` refresh stays as the published-label rule.
      `services/publication_loop.py`, `reconciler.py`'s `closed_available_listing_ids`,
      and `services/listing_source_check.py` pass the binding and the source's delegate.
      *Done.* `compare_listing` compares the two delegates by identity, since the buyer-imported package cannot depend on the kit (`design.md`, "Implementation notes").
- [x] 4.5 **Source check.** `services/listing_source_check.py`: the declared re-derivation
      and the pinned-site availability read become `judge_async`'s halves; the class
      test goes.
      *Done.*
- [x] 4.6 **Settlement admissibility.** `settlement_stages.py`: each of the three seller
      stages declares `fulfils_through_capacity` as a required field.
      `settlement_composition.py`: delete `VM_MECHANISM_FULFILLS_THROUGH_CAPACITY`,
      `UndeclaredMechanismFulfillmentError`, `mechanism_fulfills_through_capacity`,
      `admissible_settlement_clauses`, and the composition's `mechanism_fulfillment`
      field and parameter. `services/listing_service.py`: listing creation runs
      `admissible_settlement` for every listing, reading each clause's stage, and the
      site-configured check becomes `judge`'s available half; `_unbacked_settlement_terms`
      and the `== "backed"` branch go. `services/publication_terms.py` follows.
      *Done.* Any listing left with no publishable option is refused, whatever its backing (`design.md`, "Implementation notes").
- [x] 4.7 **Hold.** `negotiation_runtime.py`'s `_place_capacity_hold` places through
      `binding.backing.place_hold`; a hold not placed records the same
      `capacity_hold_not_applicable` event with the binding's label.
      *Done.*
- [x] 4.8 **Effects.** `services/fulfillment_resume_runtime.py`: the recovery reserve and
      commit call the runtime with the listing's binding from
      `capacity_binding_for_listing`, not the aggregate. `services/vm_fulfillment_service.py`:
      the class test goes; the effects' guard refuses. `controllers/admin_controller.py`:
      `_reservation_binding` synthesizes `admitted_backing()` for a reservation with no
      listing; `reserve_capacity` lets `CapacityNotAdmittedError` reach the kit route
      (409) and keeps its unconfigured-site message for `CapacityBindingError` only.
      *Done.* The resume pass's effects go through `CapacityEffects` over the aggregate it already holds.
- [x] 4.9 **Legacy and dead code.** `domain_migration.py` binds a legacy listing with
      `legacy_producer_backing()`. `services/listing_sources.py`'s unused
      `current_source_backing` goes. `services/capacity_client.py`'s
      `capacity_binding_for_listing` docstring states the guard, not the class.
      *Done.*
- [x] 4.10 Tests (all under `domains/vms/storefront/tests/` unless noted):
      `unit/test_unbacked_settlement_options.py` (rewritten over stage declarations; a
      stage without the declaration cannot be constructed);
      `unit/test_listing_source_check.py` (backing changed → declared mismatch; unbacked
      makes no site call); `unit/test_listing_comparison.py`;
      `unit/test_two_phase_reserve.py` (the `capacity_hold_not_applicable` event,
      asserted for the first time); `unit/test_fulfillment_resume_runtime.py` (recovery
      of an unbacked listing's deal is refused before any site call);
      `integration/test_admin_api.py` (an unbacked listing's admin reserve answers 409;
      the no-listing reservation binds as admitted); `integration/test_reconciler_derivation.py`
      and `integration/test_publication_loop.py` (availability scope at reconciler level,
      not only end to end); `domains/vms/domain/tests/test_storefront_adapter.py`.
      *Done.* Unit 988 passed. Integration matches the `dev` baseline exactly: the same 7 failures on both trees (2 Alkahest, 5 publication-loop pricing refreshes), run without `torch` and one test per process (7.2).
- [x] 4.11 Validation: `make test-storefront`, `make test-vms-domain`,
      `make test-vms-buyer`, `make -C domains test-compute`, and
      `make check-architecture`.
      *Done* as 4.10 records; `make test-storefront` and `make test-vms-buyer` need `download.pytorch.org` (7.2).

## 5. Bare metal onto the delegate

- [x] 5.1 **Published label.** `domains/bare_metal/src/arkhai_bare_metal/schema.py`:
      `BareMetalListing.capacity_backing` is `CapacityBackingLabel`.
      `publication.py`'s `available_bare_metal_listings` sets it from the candidate's
      delegate. `pyproject.toml`: add `arkhai-kit-resource-pools-contracts`; bump.
      *Done.* `arkhai-bare-metal` 0.12.0.
- [x] 5.2 **Binding.** `storefront/.../publication_service.py`: one
      `bare_metal_listing_binding(db, listing_id)` builds the binding through
      `publication_binding` from the durable record, and `binding_for_listing` uses it;
      the refusal of a label other than backed goes. `sqlite_client.py`'s
      `upsert_bare_metal_listing` records the candidate's delegate's label rather than
      `"backed"`.
      *Done.* The builder lives in `listing_binding.py`, breaking an import cycle (`design.md`, "Implementation notes").
- [x] 5.3 **Backing comparison.** `arkhai_bare_metal/storefront_publication.py`: remove
      `capacity_backing` from `TERM_RESOURCE_FIELDS`; `compare_bare_metal_listing` gains
      a backing-changed outcome, checked first through `backing_changed`, which closes
      an open listing and refuses any refresh or reopen.
      `storefront/.../publication.py`'s `_reconcile_existing` handles it as it handles
      an identity change.
      *Done.* `BACKING_CHANGED`; the storefront supplies the kit's `backing_changed`, so the domain package stays free of the kit.
- [x] 5.4 **Judgement.** `storefront_publication.py`'s `_classify` splits into a declared
      half (enablement, shape digest, region, pool admission) and an available half
      (the view's `available`), joined by the resolved pool's `judge`. Publication and
      `inventory_guard.py`'s `recheck_bare_metal_listing_source` share it; the guard
      runs `backing_changed` first and reports a mismatch as declared.
      *Done.* Classification and the recheck take each pool's delegate; the storefront check compares backing first.
- [x] 5.5 **Stages.** `storefront/.../settlement_stages.py`: rename `SellerStage.physical`
      `fulfils_through_capacity`; update `settlement_composition.py`'s table,
      `negotiation_runtime.py`'s admission gating, and `settlement_service.py`'s
      evidence gating. Bare-metal publication applies `admissible_settlement` to every
      candidate through the stage table; no listing it publishes changes, since every
      candidate is backed.
      *Done.* Admissibility runs in `publication_payload_builder`.
- [x] 5.6 **Effects.** `fulfillment_service.py`'s settlement reserve and commit, through
      its `_effect` helper, and `deal_controls.py`'s administrator reserve each build a
      `CapacityEffects` over the runtime's aggregate where the effect runs and call it
      with the listing's binding; nothing reserves or commits through the aggregate.
      Recovery's site read and reservation-map write, and the release callback's map
      removal, stay on the aggregate: they are not effects.
      *Done.* Planned as one `CapacityEffects` built in `site_clients.py` and held by
      `runtime.py`; composed at each effect instead, for the reason in design.md's
      Implementation notes. Fulfillment maps the kit's refusals to its own 409.
- [x] 5.7 Tests (under `domains/bare_metal/`): `tests/test_storefront_publication.py`
      (backing is not a term; a changed backing refuses refresh; the classification
      halves); `tests/test_inventory_guard.py` (a changed backing is a declared
      mismatch); `tests/test_schema.py`; `storefront/tests/test_publication_cycle.py`
      (a pool re-created with the opposite backing closes its listing and never
      reopens it, made reachable by rewriting the binding's label in the fixture
      database, since pool reading still refuses unbacked pools; the unbacked-pool
      refusal stays tested); `storefront/tests/test_fulfillment_service.py` and
      `test_deal_controls.py` (effects through `CapacityEffects`; an unbacked binding
      is refused before any site call; admin reserve answers 409);
      `storefront/tests/test_selection_dispatch.py` and `test_domain_runtime.py` (the
      renamed attribute); `storefront/tests/test_site_clients.py` (the map still
      routes fulfillment after a reserve through the effects).
      *Done.* Bare-metal storefront 311 passed, domain 134, buyer 11, adapter 40.
- [x] 5.8 Validation: `make test-bare-metal`, `make test-provisioning-adapter`, and
      `make check-architecture`.
      *Done.*

## 6. API credits onto the delegate

- [x] 6.1 **Service projection.** `domains/apicredits/service/src/apicredits_service/main.py`
      passes a pool directory to `make_capacity_router`, built from its stored pools as
      provisioning's `load_capacity_pool_metadata` does; the container exposes the
      session factory it needs. Test in `service/tests/integration/`: the
      resource-pool projection carries the system pool's declarations, and
      `read_site_declarations` resolves it backed.
      *Done.* `load_pool_directory` in `db/database.py`; credits service 71 passed. Version 0.6.0.
- [x] 6.2 **Durable binding.** `storefront/.../utils/sqlite_client.py` sets its domain
      registry as bare metal's does. `services/listing_service.py`'s
      `publish_from_quota` reads the quota resource's pool from the site's resource-pool
      projection through `read_site_declarations`, refuses a pool that is unresolvable,
      disabled, or does not advertise `api_credits`, applies `admissible_settlement`
      with each stage's declaration, and writes the listing and its
      `StorefrontListingBinding` together through `upsert_listing_with_binding` — site,
      `api_credits`, the quota resource as `source_id`, its pool, the domain identity
      and version, and the pool's label — with the listing ID as the derivation source
      identity. `storefront/pyproject.toml`: add `arkhai-kit-resource-pools` and
      `arkhai-kit-resource-pools-contracts`; bump.
      *Done.* `listing_binding.py`. No domain registry is set on the client: core's binding write needs none (`design.md`, "Implementation notes"). Storefront 0.9.0, domain 0.6.0.
- [x] 6.3 **Binding reads.** Delete `capacity_binding_from_listing_resource`
      (`services/capacity_client.py`); `services/publication_service.py`'s
      `binding_for_listing`, `settlement_stages.py`'s payment hold, and
      `services/fulfillment_service.py`'s release build the binding through
      `publication_binding` from the durable record.
      *Done.*
- [x] 6.4 **Stages and hold.** `settlement_stages.py`: both seller stages declare
      `fulfils_through_capacity=True`; the payment stage's hold places through
      `binding.backing.place_hold`.
      *Done.*
- [x] 6.5 **Reconciliation and reopen.** `storefront/.../services/publication_service.py`:
      availability closes and reopens judge each listing through its binding's
      delegate, with `arkhai_apicredits/listings/reconciler.py`'s pure rules as the
      available half, and reopen runs `backing_changed` against the pool's current
      declaration first. The pure rules key on the binding's site and source rather
      than the published `listing_resource`, so the domain package stays free of the
      delegate.
      *Done.* The domain rules take a `judge`; reopen reads each site's pool projection once.
- [x] 6.6 **Source check.** `storefront/.../listing_source_check.py` (new): the declared
      half confirms the quota resource is still in its bound pool, the pool is enabled
      and advertises `api_credits`, and `backing_changed` is false; the available half
      requires one available unit; `judge_async` joins them; an unreachable or
      unverifiable site is `unverifiable`. Wire it as `check_listing_source` in
      `negotiation_runtime.py`'s `NegotiationDomainHooks`.
      *Done.* Reads the listing's site through the aggregate, as bare metal does.
- [x] 6.7 **Quota guard.** `storefront/.../negotiation_runtime.py`'s
      `_default_seller_round_hook` resolves the listing's binding and hands the domain
      round hook a snapshot source that reads the quota snapshot as `judge_async`'s
      available half, yielding nothing where availability does not bound the listing.
      `arkhai_apicredits/negotiation/storefront_round.py` omits `available_resources`
      when the source yields nothing, and `negotiation/policies.py`'s
      `credit_quota_guard` reports itself not applicable without a snapshot. The
      domain package gains no dependency.
      *Done.*
- [x] 6.8 **Fresh database.** `storefront/.../utils/sqlite_client.py`'s
      `_ensure_domain_indexes` refuses to start when a listing has no binding, naming
      the listing and that a fresh database is required, beside the existing schema
      refusal.
      *Done.*
- [x] 6.9 **Defects.** `cli.py` constructs `ListingService` with its settlement
      composition; `controllers/listings_controller.py` passes `settlement_clauses`
      through.
      *Done.*
- [x] 6.10 Tests (under `domains/apicredits/`): `storefront/tests/integration/test_publish_reconcile.py`
      (creation writes the binding with the pool's label; two listings over one quota
      resource each bind; an unbacked credits pool yields no listing; submitted clauses
      reach the listing; the reconciler reads the binding, not the payload);
      `storefront/tests/unit/test_listing_source_check.py` (new; the three spec
      scenarios and a changed backing); `storefront/tests/unit/test_concept_modules.py`
      (the guard is not applicable without a snapshot);
      `storefront/tests/integration/test_sync_negotiation.py` (the hold through the
      delegate); `storefront/tests/unit/test_server_composition.py` (the fresh-database
      refusal); a CLI test for the constructed service. Fixtures that write listings
      with plain `upsert_listing` (`integration/credit_negotiation.py`,
      `test_payment_recovery.py`, `test_payment_settlement.py`,
      `unit/test_settlement_fulfillment.py`) write a binding.
      *Done.* Storefront 135 passed.
- [x] 6.11 Validation: `make test-apicredits`, `cd domains/apicredits/service && make test`,
      and `make check-architecture`.
      *Done.*
- [x] 6.12 **Review corrections.** `listing_binding.py`'s `api_credit_listing_source`
      returns the binding with its bound pool, and `quota_pool` takes that pool: the
      source check and reopen refuse a resource moved to another pool.
      `negotiation_runtime.py`'s quota snapshot reads only the bound site.
      `publication_service.py`'s `close_token_listings_on_source_mismatch` closes, on
      every reconcile pass and first, each open listing its bound pool no longer
      supports, under the rule reopen refuses by; an unreadable site closes nothing.
      Tests: the moved pool in `test_listing_source_check.py` and
      `test_publish_reconcile.py`; the source pass with quota left, through a release,
      and an unreadable site, in `test_publish_reconcile.py`; the pass's order in
      `unit/test_capacity_reconcile_converges.py`; two sites sharing a resource ID in
      `test_sync_negotiation.py`; the projection through the typed reader client over
      the real service in `service/tests/integration/test_signed_authority.py`.
      *Done.* Storefront 141 passed; service 72 passed.

## 7. Whole-tree validation

- [x] 7.1 No backing switch remains: a search of production code for `CapacityBinding`,
      `UnbackedBinding`, `backed_only`, `.backed`, `CAPACITY_BACKED`, `== "backed"`, and
      `"unbacked"` finds only bare metal's pool-reading refusal and the applied
      migrations' literals. Record the search and its result here.
      *Done.* The search finds bare metal's pool-reading refusal (`site_reading.py`, comparing the delegate), the delegate's own registry, the applied migrations' `'backed'` literals in core and bare metal, and one example script's demo candidate (`domains/vms/storefront/examples/payment_smoke.py`). Nothing else.
- [x] 7.2 `make test` and `make check-packaging`.
      *Done.* `make check-packaging` passes in full on the final head. Every test target
      this container can install passes. The VM storefront and buyer, whose torch index
      this environment cannot reach, ran in hand-built environments: storefront unit 989,
      buyer 197, integration with the same 7 failures as `dev` there. Unrun: `kit/policy`,
      unchanged.
- [x] 7.3 The three end-to-end lanes on the branch head: VM (including
      `test_vm_introduction.py`, which exercises unbacked VM supply), bare metal
      (`test_bare_metal_publication.py`, `test_bare_metal_introduction.py`, and the
      typed-client deal), and API credits (`test_credits_payment_deal.py` and
      `test_credits_deal_buyer_cli.py`, over a listing that now records a binding).
      *Done.* E2E workflow run 38605210429 on `5aef4dd`, all three lanes green, 183
      passed and 3 skipped: VM 131 passed, `test_vm_introduction.py` 6; bare metal 51
      passed, `test_bare_metal_publication.py` 11, `test_bare_metal_introduction.py` 5,
      `test_bare_metal_mock_deal.py` 35; API credits `test_credits_deal_buyer_cli.py`
      passed, while `test_credits_payment_deal.py`'s three scenarios skip because the
      lane supplies no payments authority. The only later commit drops an unused
      dependency declaration and touches no runtime path.

## 8. Promotion

This runs after code review, to reduce churn.

- [x] 8.1 `openspec/specs/resource-pool-management/spec.md`: sync the delta.
      `architecture.md`, "Advertisement, delivery, and backing": the delegate, what it
      decides, and why it lives beside the label.
      *Done.* Spec synced at archive; companion paragraphs on the delegate, its kit scope, and its registry questions.
- [x] 8.2 `openspec/specs/storefront-publication/spec.md`: sync the delta.
      `architecture.md`, "Reconciliation" and "Settlement option reconciliation": the
      backing comparison first, reconciliation scope through the delegate, and
      admissibility over each stage's declaration.
      *Done.* Spec synced at archive; companion "Immutable domain ownership and publication", "Reconciliation", and "Settlement option reconciliation".
- [x] 8.3 `openspec/specs/market-composition/spec.md`: sync the delta.
      `architecture.md`, "Settlement runtime composition": `fulfils_through_capacity` as
      the stage-table convention each domain reads; "Package ownership": the edge from
      `kit/capacity-publication` and `core/storefront` to the contracts.
      *Done.* Spec synced at archive; companion "Package ownership", "Settlement runtime composition", and "Storefront composition kit" (its `CapacityBinding` paragraph replaced, `CapacityEffects` added).
- [x] 8.4 `openspec/specs/api-credits/spec.md`: sync the delta. `architecture.md`,
      "Explicit database reset": the listing-binding refusal; "Implementation
      composition": the durable binding keyed by listing and the source check; the
      bound pool as the listing's provenance, which the source check, reopen, and the
      reconciliation source pass enforce; that pass running on every reconcile, and
      why an in-place declaration edit closes its listings only on the next pass; and
      negotiation's quota snapshot read from the bound site alone.
      *Done.* Spec synced at archive; companion "Listing bindings and the bound pool" under "Implementation composition", and "Explicit database reset".
- [x] 8.5 `docs/development/ARCHITECTURE.md`: "Kit areas" — the delegate in
      `kit/resource-pools-contracts` and the markets it serves; "Capacity publication
      and multi-domain storefront composition" — `PublicationBinding` with its delegate
      replaces the `CapacityBinding` paragraph, and `CapacityEffects` is the one guarded
      boundary; "Storefront capacity boundary" — backing decisions go through the
      delegate. `docs/development/RELEASING.md`'s dependency rows for every package
      whose dependencies changed.
      *Done.* "Kit areas", "Capacity publication and multi-domain storefront composition", and "Storefront capacity boundary". `RELEASING.md`'s rows were updated in Section 7.

## 9. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [x] 9.1 **Comment hygiene.** Run `make check-comment-hygiene` and resolve every
      match. Then read directly every docstring and comment this change added or
      touched — especially bare metal's remaining unbacked-pool refusal, the delegate's
      module docstring, and `CapacityEffects` — for narration of the change, a named
      change directory, or a "until X lands" reason, which the target cannot catch.
      *Done.* The target passes; the named docstrings and every added comment describe current invariants.
- [x] 9.2 **Import placement.** Check each import this change added or touched for a
      reason to stay local; move the rest to module level and confirm against the real
      suites. In particular, `apicredits_storefront/services/listing_service.py`'s
      function-local imports in `publish_from_quota` are touched by 6.2, and VM's
      `capacity_client.py` imports `container` locally; attempt each move and record
      any circular import found.
      *Done.* Moved to module level: the API-credit listing service's four imports, VM admin controller's reconciler imports, and VM `capacity_client.py`'s `container`, none circular. The API-credit CLI's stay in the command: settings resolve when the config module is first imported, so `--config` must run first; a comment says so.
- [x] 9.3 **Documentation compliance.** Re-check every accepted decision against
      `openspec/README.md`'s placement rules: normative behaviour in the four specs,
      rationale in their companions, the delegate's home and the effects boundary in
      `ARCHITECTURE.md`, and nothing durable left only in `design.md`.
      *Done.* Normative behaviour in the four deltas, rationale in their companions, the delegate's home and the effects boundary in `ARCHITECTURE.md`; implementation details left in code and `design.md` are marked so in the promotion record. Checked here; the maintainer reviews it with the archive.
- [x] 9.4 **Narrative compression.** Compress completed-task notes to final behaviour,
      material evidence, deferred work, and destinations, moving rationale into
      `design.md` first.
      *Done.* Notes were kept short as tasks closed; 7.2's compressed.
- [x] 9.5 **Roadmap currency.** This change is the prerequisite of Goal 7's
      `unbacked-bare-metal-listings`. Update Goal 7's current state in
      `docs/development/ROADMAP.md` to say backing is decided by one delegate and bare
      metal's remaining gap is publishing unbacked supply, and name the update in the
      design-promotion record.
      *Done.* Goal 7's current state names the delegate and bare metal's one remaining refusal.
- [x] 9.6 **Campaign index currency.** Update this change's row and the Goal 7
      dependency graph in `openspec/changes/README.md`, and the two unowned rows that
      cite this change (the shared compute-family pipeline, API-credit thread
      bindings) so they say what this change did. Name the update in the
      design-promotion record.
      *Done.* This change's row archived, the Goal 7 graph and critical path, the two unowned rows, and `unbacked-bare-metal-listings`' dependency status.
- [x] 9.7 **Documentation citations.** Run
      `make check-doc-citations CHANGE=encapsulate-capacity-backing` and resolve every
      match.
      *Done.* Passes after archive.
- [x] 9.8 **Packaging.** Run `make check-packaging` and resolve every failure, then
      `make check-architecture-change CHANGE=encapsulate-capacity-backing` and confirm
      this change owns no exception or override row.
      *Done.* `make check-packaging` passes; `check-architecture-change` finds no row this change owns.
- [x] 9.9 **End-to-end pipeline.** Confirm the E2E workflow passes all three lanes on
      the final head, and record the run, its result, and the scenarios 7.3 names. If
      it cannot run for a reason unrelated to this change, record the blocker and its
      owning change, and treat the validations it gates as unrun.
      *Done.* See 7.3.
- [x] 9.10 **Promotion.** Add the design-promotion record to `design.md`, mapping every
      accepted decision to its permanent heading from Section 8, and confirm no
      production source cites `openspec/changes/encapsulate-capacity-backing`.
      *Done.* `design.md`, "Design promotion record"; no production source cites the change.