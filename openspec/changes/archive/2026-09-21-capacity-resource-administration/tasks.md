# Implementation Tasks

Sections are sized to land independently in roughly a day each and are ordered so the
authority is populated before the fallback that currently stands in for it is
removed. Sections 1–3 are additive and safe to deploy on their own; Section 4 is the
cutover.

**Implementation order (amended 2026-09-21).** Section numbers are kept for
reference stability; implement in this order, which follows the real dependencies:
1 → 4b → 4c → 5 → 2 → 3 → 4 → 6 → 7 → 8. Section 4b changes the registration
contract every later section writes through (`pool_id` required, `total_units`
optional, in-session registration), and Section 2's derivation writes through
Section 5's in-session reconciliation path.

**Dependency.** Sections 2 and 4 consume the declaration's `host_id` and the host
registry's `host_id` key from `unify-host-identity`, archived before this change
resumed. Names in notes written before it follow its mapping: `name` → `host_id`,
the `vm_host` attribute → the declaration's `host_id`, `kvm_host` → `ssh_host`.

**Status (2026-09-21).** Every section is implemented and tested, including both
reviews' corrections (7b, 7c); `make test` and the end-to-end pipeline passed on the
owner's run on the final code, after 7c. The chart wiring is render-tested but not
deployed (6.5). Each task's note records its final behaviour and evidence;
the decisions behind them are in `design.md`. Each task's note records its final behaviour and evidence; the
decisions behind them are in `design.md`.

## 1. Capacity declaration carrier and administration surface

- [x] 1.1 Confirm by inspection, before writing anything, that the findings in
      `design.md`'s "Context" still hold: the startup step list, the absence of any
      capacity-resource seeding, `_project_host`'s fallback shape, and `Host`'s
      column set. Record any drift in `design.md` rather than working around it.
      Done 2026-09-21 during design review; drift recorded under `design.md`'s
      "What changed since the investigation". Re-run the same checks at the start of
      implementation if other changes have landed since.
- [x] 1.2 Define the capacity-definitions document shape (a declaration per Physical
      Resource carrying `resource_id`, a required `pool_id`, `resource_type`,
      optional `resource_subtype`, capacity dimensions, categorical attributes, and
      `enabled`), mirroring the pool-definitions document's structure and validation
      posture: duplicate ids and malformed dimensions are validation problems reported
      together, not first-failure exceptions. New module
      `kit/site/src/market_site/capacity_definitions.py`, parallel to
      `kit/resource-pools/src/market_resource_pools/service.py`'s document handling.
      **Amended 2026-09-21 (design decided):**
      - *Shape:* the root field `resources`, holding entries with the registration
        contract's field names. `resource_id`, `pool_id`, `resource_type` and a
        non-empty `capacity` are required. `resource_subtype`, `host_id`,
        `attributes` and `enabled` (default true) are optional. `total_units` is not
        accepted, and unknown root or entry fields are problems.
      - *Validation:* duplicate `resource_id` or `host_id` among entries, and
        attribute keys in the reserved set from 1.6, are problems. Problems are
        `path`/`code`/`message`, all reported together.
      - *Contents of the module:* the parsed `CapacityDefinition`, the validation
        result, the plan (`created`/`updated`/`unchanged`), and
        `reconcile_capacity_definitions_in_session(db, ledger, document, *,
        pool_exists, apply)`.
      - *Reconciliation:*
        - compare each entry with the stored declaration through the ledger's
          payload;
        - register only created and updated entries, through
          `register_resource_in_session`;
        - collect every `CapacityConflictError`, `ValueError`, and unknown-pool
          refusal as a problem;
        - raise with all problems if any exist, so the caller's transaction rolls
          back.
        With `apply=False`, the function plans and reports without registering.
      - *Wire models:* the import request, response, diff and problem models live in
        the same module. Export them all from
        `kit/site/src/market_site/__init__.py`.
      **Done 2026-09-21:** `kit/site/src/market_site/capacity_definitions.py`:
      `parse_capacity_definitions`, `reconcile_capacity_definitions_in_session`,
      and the wire models, exported from `market_site`. The classifier is the
      ledger's `declaration_change_in_session`, beside what registration writes.
      Reconciliation classifies inside its `try`, since a YAML `.nan` or `.inf`
      passes the structural check and is refused by capacity normalization.
      `kit/site` now declares `pyyaml>=6.0` rather than relying on it through
      `kit/resource-pools`; covered by the unpublished 0.4.0.
- [x] 1.3 Promote `PUT /api/v1/capacity/resources/{resource_id}` from a compatibility
      endpoint to a documented operator administration surface: correct the route
      docstring in `kit/site/src/market_site/router.py`, which currently describes it
      as a compatibility path for domains registering logical capacity, and state the
      multidimensional contract and full-replacement semantics.
- [x] 1.4 Verify `ResourceRegisterRequest` already expresses everything a declaration
      needs and add nothing that is not required; `capacity` and `attributes` are
      already free-form maps. If a client method is added, add it to both the async
      and sync variants in the same change and cover it with the parity contract test
      `TESTING.md` requires. **Amended 2026-09-21:** the two field changes this change
      does make (`pool_id` required, `total_units` optional) are Section 4b's.
      `SiteCapacityAdminClient` has no sync variant, so parity does not apply to it.
      **Amended 2026-09-21:** the reserved-key refusal (1.6) adds no field and
      lives in the ledger, so the `PUT` body, the document, and in-process callers
      share one rule. `ResourceRegisterRequest` is unchanged.
      **Done 2026-09-21:** `ResourceRegisterRequest` unchanged; the refusal is
      in the ledger (1.6).
- [x] 1.5 Focused tests: declaration accepted with several dimensions, declaration
      accepted with a single dimension, omitted dimensions treated as undeclared.
      **Amended 2026-09-21:** in `kit/site/tests/unit/test_capacity_definitions.py`,
      also:
      - every validation rule in 1.2, with one document carrying several problems
        reported together;
      - an unchanged entry planned as unchanged, writing nothing and emitting no
        event (assert on `events_after`);
      - an entry omitting `host_id` clearing the stored one;
      - a stored-state refusal on a later entry leaving earlier entries unapplied
        (session rolled back by the caller);
      - `apply=False` registering nothing.
      **Done 2026-09-21:** 14 tests in
      `kit/site/tests/unit/test_capacity_definitions.py`. Breaking the unchanged
      classification (always "updated") fails the reimport test here and in
      5.11's.
- [x] 1.6 Refuse reserved attribute keys at registration. A module constant in
      `kit/site/src/market_site/ledger.py` names the declaration fields
      (`resource_id`, `pool_id`, `host_id`, `resource_type`, `resource_subtype`).
      `register_resource_in_session` raises `ValueError` naming the key, which the
      `PUT` route already maps to 422. 1.2's validation reuses the constant.
      Existing tests that write such keys change:
      - `kit/site/tests/unit/test_ledger.py`'s
        `test_attribute_view_prefers_real_pool_id_over_attributes_json` stores its
        stale attribute directly, as its neighbour stores a `NULL` pool;
      - `domains/vms/storefront/tests/integration/test_capacity_reservation_boundary.py`
        registers without its `vm_host`/`pool_id` attributes.
      Tests:
      - **Unit** (`test_ledger.py`): each reserved key refused, with nothing
        written.
      - **Integration** (`provisioning/compute/service/tests/integration/test_capacity_api.py`):
        a `PUT` through `SiteCapacityAdminClient` with `host_id` in attributes
        raises `SiteCapacityAdminClientError` with status 422. The client
        constructs this body, so it is not a raw-HTTP exception.
      **Done 2026-09-21:** `DECLARATION_FIELD_KEYS` in `ledger.py`; refused
      before any write. Two further test helpers in `test_ledger.py`
      (`_register_dual_mode_host`, `_shared_host_ledger`) registered a
      bare-metal resource with `host_id` in attributes, a leftover from before
      the column. They pass it as the field now. No production writer used a
      reserved key.
- [x] 1.7 Make declaration fields win over attributes in `resource_feasibility_view`
      (`kit/site/src/market_site/ledger.py`): spread attributes first, then write
      the facts, then `pool_id` as now. **Unit**
      (`kit/site/tests/unit/test_resource_satisfies_requirement.py`): a view whose
      column host is `kvm1` and whose attributes name `kvm9` matches `kvm1` and not
      `kvm9`; the same for `resource_id` and `resource_type`.
      **Done 2026-09-21:** Attributes are spread first and every fact written
      after, so derived totals win too.
- [x] 1.8 Add migration `20260921_003_capacity_declaration_attributes` to
      `provisioning/compute/service/src/compute_provisioning_service/db/migrations.py`,
      ordered after `20260921_002` and before Section 3's entry. It removes the
      reserved top-level keys from stored `capacity_buckets.attributes`, rewriting by
      path and never recursively, planned in full before the first write, and logs
      each removed key with its resource at INFO. An attribute `host_id` is removed,
      not promoted (`design.md`). **Unit**, starting from
      `tests/unit/fixtures/schema_through_20260911_001.sql` with the chain applied
      through `20260921_002`:
      - reserved keys removed;
      - other keys, including nested ones with a reserved name, untouched;
      - idempotent rerun;
      - a clean database unchanged.
      **Done 2026-09-21:** Three tests in
      `tests/unit/test_capacity_declaration_attributes_migration.py`. The
      malformed-row test applies the chain first, because the host-identity
      entry reads attributes before this one does, then un-records this entry
      and reruns. `test_database.py`'s registry list and count are updated.
- [x] 1.9 **Review: one declaration type.** Add `CapacityDeclaration` and
      `CapacityDeclarationFields` in `kit/site/src/market_site/declarations.py`
      (`design.md`, "A capacity declaration is one type"). The ledger registers
      through `register_declaration_in_session` and maps model↔row only in
      `_write_declaration`/`_stored_declaration`; `declaration_change_in_session`
      takes a declaration and compares models. `ResourceRegisterRequest` extends the
      shared fields; the router passes the body through. The derivation builds the
      model. `DECLARATION_FIELD_KEYS` becomes `CapacityDeclaration.IDENTITY_FIELDS`.
      **Done 2026-09-21:** `tests/unit/test_declarations.py` (amount rules, at least
      one dimension, reserved keys, unknown fields, immutability, and a guard that
      the identity set names only model fields). A string amount is now refused at
      registration as well as in documents; no caller passed one.
- [x] 1.10 **Review: split `parse_capacity_definitions`** into `_load_entries`,
      `_validate_entry` (strict model validation, errors mapped to path and code),
      and `_cross_entry_problems` (read from the raw entries, so a duplicate is
      reported beside an entry's other problems). **Done 2026-09-21:** each has its
      own tests in `test_capacity_definitions.py`. A reserved attribute is now
      reported at `resources[i].attributes` with the keys in its message, not one
      path per key.

## 2. Derivation from legacy host capacity

- [x] 2.1 Implement the host-to-declaration derivation as one reusable unit consumed
      by both the migration (Section 3) and INI host application (task 2.5) — one
      implementation, two callers, not two code paths that can drift. **Amended
      2026-09-21:** the second caller was a startup step; see `design.md`'s "Legacy
      host capacity is derived at seed time and once at upgrade". Pure planning
      function in a new
      `provisioning/compute/service/src/compute_provisioning_service/services/capacity_derivation.py`,
      writing through `CapacityLedgerService.register_resource_in_session`.
      **Done 2026-09-21:** `services/capacity_derivation.py`:
      `plan_derived_declarations` (pure) and
      `LegacyHostCapacityDerivation.derive_in_session`, which flushes the
      caller's pending writes before reading (the service's sessions do not
      autoflush) and registers through `register_resource_in_session`.
      **Superseded in part 2026-09-21:** the migration no longer calls this
      unit; it derives in frozen migration-local SQL held equal by a parity test
      (7b.4). INI application still uses it.
- [x] 2.2 Derive only for hosts with `gpu_count > 0` and no correlated declaration.
      Never overwrite, never merge. Report the derived set at INFO, matching how both
      existing seeding steps report theirs. **Amended 2026-09-21 (gate resolved):**
      "correlated" means some declaration carries this host's `host_id`, per
      `design.md`'s "A declaration names its host through `host_id`". Derived shape
      per `design.md`'s table.
      **Done 2026-09-21:** A host whose `host_id` another declaration already
      uses as its `resource_id` is skipped with a WARNING rather than
      overwritten (`design.md`, for owner review).
- [x] 2.3 Carry `gpu_model` into the declaration's attributes rather than dropping
      it — categorical, matched by equality, so it belongs in attributes and not in
      the capacity map.
      **Done 2026-09-21:** `gpu_model` becomes the only attribute, and only when
      recorded.
- [x] 2.4 Focused tests: derivation for a host with legacy data; no derivation when a
      declaration exists; operator declaration retained unchanged when it disagrees
      with the legacy value; idempotent across repeated runs. **Added 2026-09-21:**
      no derivation when a declaration's `resource_id` differs from its `host_id`
      (the e2e shape);
      none for a zero-GPU host; a derived declaration's pool and enabled state follow
      the host.
      **Done 2026-09-21:** 13 unit tests in
      `tests/unit/services/test_capacity_derivation.py`, on the service's
      non-autoflushing session factory;
      `test_hosts_added_but_not_flushed_are_derived` fails without the flush.
- [x] 2.5 Wire derivation into `HostService.seed_from_ini`
      (`domains/vms/provisioning/adapter/src/vm_provisioning_adapter/services/host_service.py`)
      through an injected derivation port supplied by
      `provisioning/compute/service/src/compute_provisioning_service/container.py`,
      running inside the host upsert's session and transaction. Do not wire it into
      `create_host`/`update_host`. Both callers of `seed_from_ini` — the
      `seed-inventory` startup step and `POST /api/v1/hosts/import` — gain derivation
      through this one change.
      **Done 2026-09-21:** `HostCapacityDerivation` is a Protocol in the
      adapter's `host_service.py`, required by `HostService` and
      `build_vm_runtime`, so a composition cannot omit it. The container injects
      `LegacyHostCapacityDerivation`, declared with the ledger ahead of
      `vm_runtime`. The four test construction sites pass a real derivation over
      their own session factory. Covered by the adapter's unpublished 0.3.0.
- [x] 2.6 **Integration.** `POST /api/v1/hosts/import` of an INI with `gpus=` derives
      declarations visible through `GET /api/v1/capacity/resources` via the typed
      client; `POST /api/v1/hosts` with `gpu_count` derives nothing. A failure injected
      after the host upsert and before the derivation commits leaves neither.
      **Done 2026-09-21:**
      `tests/integration/test_host_capacity_derivation_api.py`, 4 tests through
      `ProvisioningClient` and `SiteCapacityAdminClient`, including a reimport
      with changed `gpus=` leaving the declaration. The injected failure
      surfaces as the raised exception because the in-process transport
      re-raises; the assertions are on the state left.

## 3. Ordered migration

- [x] 3.1 Add the migration that runs the Section 2 derivation, ordered in the
      provisioning chain and applied before the application serves requests per
      `deployment-state`'s service-owned migration history requirement.
      **Done 2026-09-21:** `20260921_004_legacy_host_capacity_declarations`,
      running `LegacyHostCapacityDerivation` imported at module level (no cycle,
      verified), with the ledger composed as the service composes it.
      **Amended 2026-09-21:** frozen as migration-local SQL by 7b.4.
- [x] 3.2 Keep the migration to the derivation only — no column drop, no host-row
      mutation. Freeze-then-redirect, matching the POOLS campaign's additive-only
      convention. **Amended 2026-09-21:** Section 4b's schema migration is a separate
      ordered entry that runs before this one; this entry stays derivation-only.
      File: `provisioning/compute/service/src/compute_provisioning_service/db/migrations.py`,
      appended to `MIGRATIONS` so `check_schema_version` requires it.
      **Done 2026-09-21:** Adds declarations only; host rows are compared
      unchanged by test.
- [x] 3.3 Validate migration behavior the way `TESTING.md` requires for this
      repository: fresh bootstrap, idempotent rerun, and drift detection.
      **Done 2026-09-21:** `tests/unit/test_legacy_host_capacity_migration.py`
      from the previous-schema fixture, where a declaration named its host by
      `vm_host`: derived set, host rows unchanged (the entry rerun in
      isolation), idempotent rerun with no new events. The generic drift guard
      deletes `MIGRATIONS[-1]`, now this entry; `test_database.py`'s list and
      count are updated.
- [x] 3.4 Confirm rollback within the freeze window leaves derived rows harmless to a
      restored reader, and document that rolling back past this change is a code
      rollback rather than a configuration change.
      **Done 2026-09-21:** Safe by construction: a derived row is an ordinary
      declaration the pre-change code already writes and reads through `PUT
      /api/v1/capacity/resources`. Derived declarations remain reservable after
      a rollback; 6.3/6.4's operator documentation records that and that rolling
      back past this change is a code rollback.

## 4. Projection cutover

The behavioral heart of the change. Depends on Sections 2 and 3 having populated the
authority.

- [x] 4.1 Redirect `capacity_inventory._project_host` to read both `capacity` and
      `attributes` from the declared capacity resource, removing the host-derived
      capacity fallback. **Amended 2026-09-21:** a host no declaration correlates to is
      not projected (`design.md`, "A host with no declaration is not projected"). The
      loop remains host-driven; inverting it is
      `project-capacity-resources-without-hosts`'s scope. Correlation is
      `declaration.host_id == host.host_id` (gate resolved 2026-09-21).
      **Done 2026-09-21:** `_project_host` reads capacity, availability, and
      attributes from the declaration only; a host no declaration names is
      skipped.
- [x] 4.2 Fix the divergence in the same edit: `attributes` currently derives from
      the host unconditionally while `capacity` prefers the resource, so a
      declaration disagreeing with a host row projects contradictory values in one
      row. Both must come from one record. **Amended 2026-09-21 (gate resolved):**
      copy every declaration attribute except `bare_metal_publication`; write the
      host's `public_host` last; remove `attributes.gpu_count`. Per `design.md`'s
      "Projected attributes are the declaration's, plus host connection fields".
      **Done 2026-09-21:** `host_id` and `public_host` are written after the
      declared attributes.
- [x] 4.3 Confirm the bare-metal publication view survives the cutover. It reads
      `resource.attributes[bare_metal_publication]` together with `capacity` through
      `_whole_resource_available`, and the cutover changes where `capacity` comes
      from. Cover with a focused test rather than reasoning about it. **Amended
      2026-09-21:** after `unify-host-identity` the view also reads the declaration's
      top-level `physical_host_id` and `allocation_mode`; the test uses that shape.
      File: `provisioning/compute/service/tests/unit/services/test_capacity_inventory.py`.
      **Done 2026-09-21:**
      `test_the_bare_metal_view_reads_the_declaration_the_projection_reads`: the
      view and the resource share the declaration's capacity, a held GPU makes
      the machine unavailable, and the publication configuration is absent from
      attributes.
- [x] 4.4 Handle the `available`-key semantics change explicitly. `_project_host`
      currently omits `available` when no capacity resource exists; after derivation,
      hosts that previously projected no `available` will project one, and the VM
      reconciler distinguishes an absent projection from a loaded empty one under its
      "ignorance is not zero" rule. Add storefront-side coverage, not only
      provisioning-side — this is the highest-risk item in the change.
      **Amended 2026-09-21:** files —
      `domains/vms/storefront/tests/unit/test_reconciler.py` for
      `_projected_resource_usage` with `available` present on every derived row, and
      `provisioning/compute/service/tests/integration/test_capacity_api.py` for the
      resource-pool projection read through the typed client.
      **Done 2026-09-21:** `available` is projected only when the declaration
      reports it, so an unreported one is never an empty map read as zero
      (`design.md`). Storefront side:
      `test_a_derived_declarations_projection_is_read_as_live_availability` in
      `domains/vms/storefront/tests/unit/test_reconciler.py`, built through
      `kit/site`'s own `resource_pool_projection`. Provisioning side:
      `test_the_resource_pool_projection_publishes_declarations_not_hosts` in
      `test_capacity_api.py`, through `ProvisioningClient` and
      `SiteCapacityClient.resource_pool_projection`.
- [x] 4.5 Run the VM e2e scenarios that depend on projected capacity shape, and the
      `kit/site` ledger and router suites.
      **Partly done 2026-09-21:** `kit/site` passes (221). The VM e2e scenarios
      run with the pipeline in 8.9.
      **Done 2026-09-21:** The owner's end-to-end pipeline passed (8.9).
- [x] 4.6 **Unit.** A host with no correlated declaration yields no projected entry;
      update `tests/unit/services/test_capacity_inventory.py`'s host-only cases, which
      currently assert the fallback.
      **Done 2026-09-21:** `test_capacity_inventory.py`'s three fallback tests
      are replaced: an undeclared host is not projected; a declared host
      projects the declaration where the host row disagrees; a stored
      `host_id`/`public_host` attribute cannot override the host; no `gpu_model`
      or `gpu_count` unless declared; a disabled host projects disabled;
      unreported availability is not projected.

## 4b. Composition-supplied mirror dimension

`design.md`'s "The primary-dimension fallback writes a GPU name into every domain"
accepted this fix; it previously had no task, so an implementer would have had to
invent the semantics while coding. Retiring the scalar mirror entirely remains
deferred — this is the smaller half that the domain-neutral declaration contract
depends on.

- [x] 4b.1 Make the dimension the legacy scalar mirror tracks composition-supplied,
      the way `unit_claim_keys` already is, rather than the module-level
      `PRIMARY_DIMENSION = "gpu_count"` in `kit/site/ledger.py`. **Amended
      2026-09-21:** every site listed under `design.md`'s "What changed since the
      investigation" reads the supplied name, including the module-level helpers
      (`_requested_dimensions`, `_resource_capacity`, `_reservation_dimensions`,
      `dict_resource_satisfies_claim`, `resource_feasibility_view`), which take it as
      a parameter. Update their callers in `kit/fulfillment/src/market_fulfillment/`
      and any storefront caller found by search.
      **Reopened and finished 2026-09-21.** It was checked with
      `resource_feasibility_view` still writing the unit total into every
      domain's match facts under `gpu_count`. Where a composition's unit claim
      keys exclude `gpu_count` (the kit defaults, API credits), a claim naming
      it was an attribute requirement matched against that total, so a neutral
      ledger admitted `{"gpu_count": 3}` against a 3-unit quota. The view now
      takes `mirror_dimension` (default the module default) and keys the total
      under it; `dict_resource_satisfies_claim` and the ledger's own builder pass
      theirs. Nothing in `kit/fulfillment` or the storefronts reads the fact.
      Tests: `test_dict_resource_satisfies_claim.py` and `test_ledger.py`, each
      failing against the previous ledger. Suites: `kit/site` 202,
      `kit/site-client` 36, `kit/fulfillment` 165, `core/storefront` 158 + 2
      skipped, provisioning service 888, API-credits service 63 and storefront
      79, VM storefront 1169 + the 2 pre-existing `test_alkahest` failures.
- [x] 4b.2 Stop writing a mirror dimension into a caller's explicit capacity map.
      `register_resource` currently injects it when absent and then reads it back for
      `mirrored_units`; both sites need the supplied name and the explicit-declaration
      case.
- [x] 4b.3 Make `total_units` optional and absent where the declaration names no
      mirror dimension. Files: `kit/site/src/market_site/http_models.py`,
      `kit/site/src/market_site/db.py` (`CapacityBucket.total_units` nullable),
      `kit/site-client/src/market_site_client/models.py` and `client.py`. A request
      carrying neither `total_units` nor `capacity`, or both disagreeing, is rejected. **Decided 2026-09-09** rather than left as a gate: the
      existing consistency check compares the scalar against its mirrored dimension
      when both are present, so absence keeps that check meaningful while a
      substituted zero would make it assert a false equality. Retiring the scalar
      entirely remains deferred.
- [x] 4b.4 Wire the VM composition to its existing mirror dimension so no behaviour
      changes there.
- [x] 4b.5 Wire the API-credit composition to its own dimension, matching how it
      already overrides `unit_claim_keys` to `("units",)`.
      **Amended 2026-09-21:** the dimension is `units`, in
      `domains/apicredits/service/src/container.py`. No migration and no
      compatibility reader — the domain is unlaunched and its databases are
      recreated; say so in the service's migration module docstring only if a reader
      would otherwise expect one.
- [x] 4b.6 Confirm legacy rows whose scalar mirror was written under the old constant
      still read correctly, and record how a row written before this change is
      interpreted after it. **Amended 2026-09-21:** scoped to the compute domain,
      whose mirror name does not change; API-credit rows are out of scope per 4b.5.
      **Amended 2026-09-21 (method):** a unit test in
      `provisioning/compute/service/tests/unit/` seeds a declaration row as the
      previous code stored it (from the previous-schema fixture: `total_units` set,
      `capacity` naming `gpu_count`, and a row with `capacity` empty). After the chain
      runs, it asserts the payload's `capacity`, `total_units`, and
      `available_gpu_count` equal what the previous code reported. Record the
      interpretation here.
      **Done 2026-09-21:** Verified by
      `test_rows_stored_under_the_previous_default_read_as_they_did` in
      `test_capacity_declaration_contract_migration.py`: a row naming
      `gpu_count` and a row with an empty capacity map both read as `capacity`,
      `value`, `available_units` and `available` of the stored total, as the
      previous code reported. Listings carry no `available_<mirror>` alias;
      `design.md` is corrected.
- [x] 4b.7 **Unit.** An explicit multidimensional declaration with no compute
      dimension is stored as declared, with no manufactured GPU dimension, and its
      scalar unit total is absent rather than zero.
- [x] 4b.8 **Unit.** The VM composition's legacy scalar fallback maps to its
      configured mirror dimension; the API-credit composition's does not become
      `gpu_count`.
- [x] 4b.9 **Integration.** One typed-client case registering a resource whose
      declaration names no compute dimension.
      **Review 2026-09-21:** no such typed-client test exists; the declaration
      naming no compute dimension is covered only at ledger level
      (`test_ledger.py`). Added by 7b.3.
- [x] 4b.10 Require `pool_id` on registration: required field on
      `ResourceRegisterRequest` and `ResourceRegistration`, required argument on
      `register_resource`. Update every caller —
      `domains/apicredits/storefront/src/apicredits_storefront/startup.py` passes the
      default pool explicitly, and the test fixtures in `kit/site`, `kit/fulfillment`,
      provisioning, VM storefront, and API-credits suites that register without one.
- [x] 4b.11 Add `CapacityLedgerService.register_resource_in_session(db, ...)`, neither
      opening a session nor committing, with `register_resource` delegating to it
      under the ledger lock.
- [x] 4b.12 Compute migration, ordered before Section 3's: make
      `capacity_buckets.total_units` nullable (SQLite table rebuild through the
      existing helper) and backfill `NULL` `pool_id` to `DEFAULT_POOL_ID`. Cover fresh
      bootstrap, idempotent rerun, and a populated database.
- [x] 4b.13 **Rejection-path integration.** A `PUT` without `pool_id` returns 422;
      status-code-only assertion, commented as a rejection-path test per
      `TESTING.md`.
- [x] 4b.14 Bump distribution versions and lower bounds: `arkhai-kit-site`,
      `arkhai-kit-site-client`, the compute provisioning service, the API-credits
      service and storefront, and every `pyproject.toml` that depends on the first
      two. No versioned envelope is affected (`design.md`, "Wire and distribution
      versioning"); if implementation finds one, raise its version and record it
      there.
      **Disposition 2026-09-21:** covered by the minor bumps this branch already
      carries for `unify-host-identity` (`kit-site` 0.4.0, `kit-site-client` 0.3.0,
      the provisioning service 0.3.0, API-credits service and storefront 0.3.0), all
      unpublished and merged together. The one package this change needs further
      is `compute-provisioning`, in 5.12.

## 4c. Pool reassignment drain rule

- [x] 4c.1 Refuse reassignment of a capacity resource that holds a live capacity
      obligation — hold, reservation, assignment, or workload — resolved through its
      pool. `register_resource` currently writes `bucket.pool_id = effective_pool_id`
      unconditionally on update, and `backing_pool_id_in_session` resolves a
      reservation's pool through the resource's *current* `pool_id`, so reassignment
      rewrites the authority under an existing reservation.
- [x] 4c.2 Leave the resource in its current pool when a reassignment is refused. A
      partial move is worse than a refused one. **Amended 2026-09-21:** "live
      obligation" is a held-state reservation debited against the resource or whose
      `settlement_resource_id` names it; compare pools after reading `NULL` as the
      default pool. The route maps the refusal to 409.
- [x] 4c.3 **Integration, real DB transaction.** A resource holding a live reservation
      cannot cross a pool boundary; the same resource can once its obligations are
      drained. Cover both in one test so the refusal is not mistaken for a resource
      that could never move. Keep the coverage generic: this change does not depend on
      `pool-declared-advertisement-and-backing`, so a backed-to-unbacked case would
      exercise terminology that may not exist yet when this lands. That
      specialization belongs to the Goal 7 change that introduces it.
      **Review 2026-09-21:** the test calls the ledger directly, so it is a
      component test, not an integration test. The integration case is added by
      7b.3.
- [x] 4c.4 Confirm no existing fixture, bulk import, or e2e setup reassigns a resource
      under a live obligation. If one does, drain it rather than exempting it.
      **Amended 2026-09-21 (method):**
      - Enumerate every `register_resource` and `register_resource_in_session` call
        site in tests, e2e scenarios (`e2e-tests/tests/e2e/roles/scenarios/`), and
        the API-credits startup, and read each for a re-registration under a
        different `pool_id` after a reserve.
      - Run the VM e2e scenarios' pool setup (`host_registry.py`) against the rule.
      - Record the call sites examined.
      **Done 2026-09-21:** Call sites examined: every in-process suite (which
      runs against the rule and passes), `host_registry.py`'s
      `declare_e2e_capacity` and each scenario calling `provision_e2e_executor`,
      `hosted/network.py`, and the API-credits startup. Each e2e resource id is
      unique and bound to one pool; the hosted network uses per-run ids; API
      credits always registers into `default`. None reassigns.
      `E2E_NON_ERC20_POOL_ID` in `host_registry.py` is defined and unused.

## 5. Startup import

- [x] 5.1 Add `capacity_definitions_path` to `settings.toml` and its
      `resolved_capacity_definitions_path` property in `config.py`, mirroring
      `pool_definitions_path` exactly, including empty-string-means-unset.
      **Done 2026-09-21:** The same edit corrects the `inventory_ini` and
      `pool_definitions_path` comments, 6.1's `settings.toml` part.
- [x] 5.2 Add the import step through the existing `DefinitionDocumentImporter`
      rather than a second reconciliation path: gate on the recorded document digest,
      reconcile a new or edited document, do nothing for an unchanged one, reconcile
      regardless of digest on an explicit import, and commit the digest in the same
      transaction as the apply. Raise on a configured path that does not exist.
      **Corrected 2026-09-09:** this task previously said "runs on every startup",
      which was the pool import's behaviour when this change was written.
      `DEPLOYMENT_AND_CONFIG.md` has since established that a process start is not a
      submission and that reapplying an unchanged document reverts administration
      performed since; capacity resources have an API administration surface, so this
      change would have introduced exactly that regression.
      **Amended 2026-09-21:** the applier calls kit/site's
      `reconcile_capacity_definitions_in_session` (1.2) inside the importer's
      transaction, with `pool_exists` answered from the resource-pool tables in the
      same session. It owns no reconciliation logic of its own.
      **Done 2026-09-21:** Capacity is the importer's third kind. The applier
      raises `CapacityDefinitionsRejected` on any problem, which rolls back the
      apply and the digest together. `reconcile_capacity_document` binds
      `pool_exists` to the resource-pool table and is shared with 5.9's
      controller.
- [x] 5.3 Register the step in `startup_steps()` **after** `import-pool-definitions`,
      since a declaration may reference a pool. **Amended 2026-09-21:** also after
      `seed-inventory`, giving relays → pools → hosts → capacity → job queue.
      Files: `app_runtime.py`, `services/definition_documents.py`
      (`import_capacity_definitions` and its applier).
      **Done 2026-09-21:** Order asserted by
      `test_runtime_imports_capacity_after_the_pools_and_hosts_it_names` in
      `tests/unit/test_worker.py`.
- [x] 5.4 ~~Run the Section 2 derivation as part of startup for hosts with legacy data
      and no declaration, so an INI-only deployment retains published capacity once
      the fallback is gone.~~ **Superseded 2026-09-21** by tasks 2.5 and 3.1:
      derivation runs where INI data is applied and once at upgrade, never as a
      recurring startup scan.
      **Disposition:** Superseded as recorded above; nothing to do.
- [x] 5.5 **Integration.** Definitions applied on a restart after an edit;
      configured-but-missing path fails startup; unconfigured path proceeds;
      declaration referencing a pool resolves.
      **Done 2026-09-21:** In
      `tests/unit/services/test_capacity_definitions_startup.py`, following the
      relay restart-safety precedent: a real database file, migrations, and
      `app_runtime.import_capacity_definitions_if_configured` across simulated
      restarts. The first start declares; an edit applies at the next start; a
      declaration may name a pre-existing pool; a missing configured path fails;
      an unconfigured one is skipped.
      **Review 2026-09-21:** these call the startup entry point directly rather
      than booting the app, so they are component tests, as the relay tests they
      follow are.
- [x] 5.6 **Integration.** An unchanged document at restart does not overwrite
      capacity administered through the API since the last import. This is the
      regression the digest gate exists to prevent and the happy-path cases above do
      not cover it.
      **Done 2026-09-21:** Same file: a declaration disabled through the ledger
      stays disabled across three restarts with the document unchanged.
      **Review 2026-09-21:** component level, as 5.5.
- [x] 5.7 **Integration.** An explicit import reconciles a document whose digest
      matches the recorded one.
      **Done 2026-09-21:** Covered by 5.11's reimport through the API
      (reconciled, reported unchanged); the startup digest is untouched (5.10).
- [x] 5.8 Confirm the digest and the reconciliation commit in one transaction,
      reusing the failure pattern the existing definition-document coverage uses. A
      digest committed after an already-committed apply is indistinguishable at the
      next startup from one recorded before a crash.
      **Done 2026-09-21:** Same file: a refused document applies nothing and
      leaves no digest.
- [x] 5.9 Add `POST /api/v1/capacity/definitions/import` in a new
      `controllers/capacity_definitions_controller.py`, taking the document the way
      `POST /api/v1/hosts/import` takes its INI and authenticated as that route is.
      It always reconciles and records no digest. Register it in the provisioning
      route contract (`provisioning/compute/src/compute_provisioning/client.py`) and
      add a typed client method so integration tests obey the "no raw calls" rule.
      **Amended 2026-09-21:** the request carries `yaml_text` and `validate_only`
      (default false). The response carries `applied`, the plan's diff, and the
      problems. A document with problems is 422 carrying them; validate-only
      returns 200 with them. Files:
      - `provisioning/compute/src/compute_provisioning/__init__.py`: re-export 1.2's
        wire models.
      - `provisioning/compute/src/compute_provisioning/client.py`: the route
        contract, with the same role as `provisioning_hosts_import`.
      - `domains/vms/provisioning/client/src/vm_provisioning_operator/client.py`:
        `import_capacity_definitions(yaml_text, *, validate_only=False)` on both
        `ProvisioningClient` and its sync variant.
      - `provisioning/compute/service/tests/unit/test_provisioning_client_contract.py`
        (parity) and
        `provisioning/compute/service/tests/integration/test_provisioning_client_endpoint_coverage.py`
        cover the new method and route.
      **Done 2026-09-21:** `controllers/capacity_definitions_controller.py`,
      mounted in `main.py`. A refused applying import is 422 with the response
      as `detail`; `ProvisioningError` carries it in its message, so
      `validate_only` is how a caller gets structured problems. Route contract
      `provisioning_capacity_definitions_import`, admin-only. The async and sync
      client methods satisfy the existing parity guard.
      `test_provisioning_client_endpoint_coverage.py` covers only endpoints not
      exercised elsewhere, and 5.10–5.11 exercise this one, so it has no entry.
      `compute-provisioning`'s reachability guard gains a passing case.
- [x] 5.10 **Integration.** A document omitting a previously imported, derived, or
      API-registered declaration leaves it unchanged; a document naming an unknown
      pool fails naming it, applies nothing, and records no digest; an explicit
      import leaves the recorded startup digest unchanged.
      **Amended 2026-09-21:** all through `ProvisioningClient.import_capacity_definitions`,
      in a new `provisioning/compute/service/tests/integration/test_capacity_definitions_api.py`.
      **Done 2026-09-21:** `tests/integration/test_capacity_definitions_api.py`,
      through `ProvisioningClient.import_capacity_definitions`, reading back
      through the site clients: unnamed and API-disabled declarations retained;
      an explicit import records no startup digest; the unknown-pool refusal is
      in 5.11's combined case.
- [x] 5.11 **Integration**, same file:
      - reimporting an unchanged document writes nothing and leaves the capacity
        event feed unchanged (read through `SiteCapacityClient.events_after`);
      - a document whose later entry moves a held resource to another pool reports
        the 409-class refusal and leaves earlier entries unapplied;
      - a document with several validation problems returns them all;
      - `validate_only` returns the diff and applies nothing;
      - a startup import whose document is refused records no digest (the
        `DefinitionDocumentImporter` failure pattern).
      **Done 2026-09-21:** Same file: reimport emits no event (version
      unchanged); one refused document reports a structural problem, an unknown
      pool, and a pool move under a live obligation, applying none of its
      entries; `validate_only` reports the plan and a host conflict, applying
      nothing. The startup case is 5.8's.
      **Correction 2026-09-21:** the structural problem was sent as a second
      request, and a structurally invalid document is not evaluated against
      stored state (`design.md`, "Review corrections"). The combined case
      described above does not exist; 7b.3 adds the structural-first case.
- [x] 5.12 Bump `compute-provisioning` to 0.7.0 (`design.md`, "Versions"):
      - `provisioning/compute/pyproject.toml`;
      - its bound to `>=0.7.0` in `domains/vms/provisioning/client/pyproject.toml`
        and `provisioning/compute/service/pyproject.toml` only;
      - regenerate every consumer's `uv.lock` with only that package upgraded;
      - update any `==` image pin.
      `test_every_image_pins_the_version_its_package_declares` guards the pins.
      The VM storefront's lock needs the `torch` index; if the implementation
      environment cannot reach it, the owner's `make test` regenerates it, as
      before.
      **Done 2026-09-21:** 0.7.0; bounds moved only in the operator client and
      the service. Relocked with only `kit-site`, `compute-provisioning` and the
      operator client upgraded (their metadata changed): API-credits service,
      bare-metal adapter and storefront, VM adapter, operator client, e2e-tests,
      `kit/fulfillment`, `kit/site`, `provisioning/compute`, and the service.
      Each lock's changed entries are exactly those packages, plus the service
      where the bare-metal adapter locks it. No `==` pin exists. **The VM
      storefront lock is owed:** it needs the `torch` index; the owner's `make
      test` regenerates it.
      **Amended 2026-09-21:** the e2e run failed at stack build:
      `dev-env/generate_state.py` runs under the VM storefront lock, still
      pinning `arkhai-compute-provisioning==0.6.1`, which the wheelhouse no
      longer builds. The owner's passing `make test` regenerates that lock
      locally; it must be committed.

## 6. Operator surface and deployment wiring

- [x] 6.1 Add Helm and compose wiring for `capacity_definitions_path`, following the
      mounted-file convention in `DEPLOYMENT_AND_CONFIG.md` — configuration travels
      through mounted files, never individual pod env entries. **Amended
      2026-09-21:** Helm only, per `design.md`'s "Deployment wiring follows the relay
      idiom": `definitions.capacity` in `helm/charts/provisioning/values.yaml`, the
      derived path and rendered document in `templates/configmap.yaml`, the
      conditional `subPath` mount in `templates/deployment.yaml`, and
      `config.capacity_definitions_path` forbidden in `values.schema.json`. No Compose
      wiring. `settings.toml` gains the setting, and its stale `pool_definitions_path`
      and `inventory_ini` comments are corrected. **Amended 2026-09-21 (gate
      resolved):** `definitions.pools` is wired the same way in the same four files —
      rendered as `pool-definitions.yaml`, `pool_definitions_path` set only when
      non-empty, `config.pool_definitions_path` forbidden — and the `values.yaml`
      comment explaining why pools were unwired is replaced.
      **Done 2026-09-21:** Helm: `definitions.pools` and `definitions.capacity`
      (empty by default) in `values.yaml`, whose header now states each
      document's retention rule and shows both documents; derived paths and
      rendered documents in `templates/configmap.yaml`; conditional `subPath`
      mounts in `templates/deployment.yaml`; `config.pool_definitions_path` and
      `config.capacity_definitions_path` refused with the schema's existing
      `false` idiom, and `definitions` typed. The chart's `config` comment
      explaining the unwired pool path is replaced. The relay idiom never
      forbade `config.relay_definitions_path`; that gap is left as found. The
      `settings.toml` part was done with 5.1.
- [x] 6.2 ~~Add CLI coverage for declaring and inspecting capacity, so registration is a
      documented workflow rather than a raw HTTP call.~~ **Superseded 2026-09-21:**
      no CLI. Site administrators configure through values files, configuration
      files, and the REST API; task 6.3 documents those.
      **Disposition:** Superseded as recorded above; no CLI.
- [x] 6.3 Update `docs/seller-quickstart.md` and the configuration reference with the
      capacity declaration workflow, including that a declaration wins over any
      derivable legacy host value — the intuition may run the other way. **Amended
      2026-09-21:** cover the document format, the startup digest rule, the REST
      import, retention of unnamed declarations, the `pool_id` requirement, the Helm
      values (`definitions.capacity` and `definitions.pools`), and that everything in
      a declaration's attributes is published to storefronts. **Amended 2026-09-21:**
      also the document fields and their reserved attribute keys; that an entry
      replaces the whole declaration (restate `host_id` when adopting a derived
      declaration; an omitted `enabled` re-enables); that unchanged entries write
      nothing; `validate_only`; and that exchanging hosts between declarations
      takes two imports. Add a "Capacity definitions" subsection to
      `docs/development/DEPLOYMENT_AND_CONFIG.md`'s "Definition documents", stating
      how its retention rule differs from pools and matches relays.
      **Done 2026-09-21:** `docs/seller-quickstart.md`: section 3's authority
      statement corrected and a "Declaring capacity" subsection added (the three
      routes, whole-declaration replacement, retention, public attributes, a
      declaration winning over the host's GPU count).
      `docs/development/DEPLOYMENT_AND_CONFIG.md`: "Definition documents" names
      all three documents and their import order, the retention rule becomes
      three-way, and a "Capacity definitions" subsection covers the document's
      rules and the import API.
- [x] 6.4 State the INI's `gpus=`/`gpu_model=` disposition in operator documentation:
      still parsed, still written to frozen host columns, no longer reaching the
      projection except through derivation, and slated for removal with the later
      column drop. Include that INI values stop affecting capacity once a declaration
      correlates to the host.
      **Done 2026-09-21:** In the quickstart's inventory step, with 3.4's note:
      `gpus=`/`gpu_model=` derive a declaration once, later values are stored
      but inert, `POST /api/v1/hosts` never derives, the values are slated for
      removal, and rolling back past the upgrade is a code rollback that leaves
      derived declarations reservable.
- [x] 6.5 **Helm render test.** For each of `definitions.capacity` and
      `definitions.pools`: empty renders no document, no mount, and no path; non-empty
      renders all three; setting the corresponding `config.*_definitions_path` fails
      schema validation. A render with both supplies both paths.
      **Done 2026-09-21:** `helm/charts/provisioning/tests/test_render.py`
      (standard library only), run by `helm/scripts/test-render.sh` so `make
      test-deployment-packaging` covers it. Removing the capacity mount fails
      it. A document rendered by the chart parses with no problems through
      `parse_capacity_definitions`, checked once by hand. Rendered with Helm
      3.10.1 from the npm package `helm-binary-linux`, an unverified
      redistribution (the official download host is unreachable here); the
      umbrella's pre-existing "compute filter specification declares
      vms.compute" failure is unchanged against the upload.
      **Amended 2026-09-21 (owner request):** the repository had no written
      guidance for render tests; the only deployment check had been deploying to
      the dev cluster. `docs/development/TESTING.md` gains "Chart Render Tests"
      (scope, location, how to write one, obtaining Helm where its download host
      is unreachable), and "Test File Layout" points to it.
      `helm/scripts/test-render.sh` now runs every
      `helm/charts/*/tests/test_render.py`, so the bare-metal storefront chart's
      existing test, previously reachable only through its own Makefile, runs
      there too; it passes.
      **Deployment status (2026-09-21):** the chart changes are validated by
      render tests only. The owner's deployment to the development cluster is
      blocked by pre-existing issues in that environment, unrelated to this
      change, and was not made a condition of archival; a deployed mount of
      either document is unexercised.

## 7. Validation

- [x] 7.1 Run the provisioning unit and integration suites, `kit/site`'s suites, and
      the affected VM e2e scenarios. Disclose any suite not run.
      **Amended 2026-09-21:** also `kit/site-client`, `kit/fulfillment`,
      `core/storefront`, `provisioning/compute`, the VM provisioning operator
      client, the VM storefront, the API-credits service and storefront, and
      e2e unit, since 1.6, 1.7 and 5.12 reach each.
      **Partly done 2026-09-21:** every in-process suite ran against the final
      wheels — `kit/site` 241, provisioning service 931, `provisioning/compute`
      130 plus its known `relay_create` failure, `kit/site-client` 36,
      `kit/fulfillment` 165, `core/storefront` 158, API-credits service 63 and
      storefront 79, bare-metal storefront 126, domain 75 and adapter 2, the VM
      adapter's target 38, e2e unit 237 plus its known failure, and the VM
      storefront 1170 plus its two known `test_alkahest` failures (run in its
      existing environment, since its lock needs the `torch` index). The VM e2e
      scenarios run with the pipeline in 8.9.
      **Done 2026-09-21:** The end-to-end half passed on the owner's pipeline
      run (8.9).
- [x] 7.2 Run `openspec validate --all --strict` and confirm no regression against the
      baseline current at implementation time.
      **Done 2026-09-21:** The failing items are identical to the upload's.
- [x] 7.3 Verify package and import boundaries are unchanged: `kit/site` must not
      acquire a provisioning dependency, and generic compute service modules must not
      import concrete VM or bare-metal models, per `physical-provisioning`'s
      dependency-isolation requirements. **Added 2026-09-21:** the VM provisioning
      adapter reaches derivation only through the injected port, not by importing the
      provisioning service's derivation module.
      **Done 2026-09-21:** `kit/site` imports no provisioning module (one
      pre-existing comment names a provisioning file) and gains only `pyyaml`;
      `kit-site-client` stays a test-only dev dependency. The VM adapter names
      its own `HostCapacityDerivation` port and never imports
      `capacity_derivation`. The new service modules import no domain model.

## 7b. Review corrections (planned and done 2026-09-21)

From the review after Section 7; decisions in `design.md`'s "Review corrections".
Versions: every package touched here already carries an unpublished minor bump on
this branch (`kit-site` 0.4.0, the VM adapter 0.3.0, the provisioning service 0.3.0),
so none moves.

- [x] 7b.1 **Serialization boundary.** In `kit/site/src/market_site/ledger.py`: add
      `CapacityLedgerService.serialized()`, a context manager acquiring the existing
      `RLock` and recording the holding thread; make every public operation that
      takes the lock take it through `serialized()`; make
      `register_resource_in_session` and `register_declaration_in_session` raise
      `RuntimeError` when the calling thread does not hold it. Callers hold it around
      their whole transaction through its commit:
      - `provisioning/compute/service/src/compute_provisioning_service/services/definition_documents.py`:
        the capacity kind's `_import` runs inside `serialized()`;
      - `.../controllers/capacity_definitions_controller.py`: around its session;
      - `domains/vms/provisioning/adapter/src/vm_provisioning_adapter/services/host_service.py`:
        `HostCapacityDerivation` gains `serialized()`, and `seed_from_ini` holds it
        around its session;
      - `.../services/capacity_derivation.py`: implements it through the ledger.
      Tests (`kit/site/tests/unit/test_ledger.py`, component level): an in-session
      mutator outside `serialized()` raises; with a reconciliation paused just after
      its obligation check, another thread's non-blocking acquire of the ledger lock
      fails (deterministic, no timing); on a file-backed SQLite database with
      independent sessions, a reserve racing a pool move never commits a live
      reservation against a resource that has moved. The older `kit/fulfillment`
      in-session methods are not changed (`design.md`).
      **Done 2026-09-21:** `serialized()` records the holding thread in a
      thread-local depth, so it stays re-entrant; all 21 of the ledger's lock
      sites use it. Tests in `test_ledger.py`: the mutator refuses outside it;
      the deterministic lock-held test; the race test, which gives the reserve a
      bounded wait inside the paused move so that, unserialized, the violation
      is actually produced (the assertion itself does not depend on the wait).
      With `serialized()` changed to take no lock, both the deterministic and
      the race tests fail on each of three runs; restored, both pass. The
      migration no longer calls the ledger (7b.4), so it needs no lock.
- [x] 7b.2 **The ledger refuses an unknown pool.** In `kit/site/src/market_site/ledger.py`:
      `UnknownPoolError(ValueError)`, raised by `register_declaration_in_session` when
      `ResourcePool` has no row for the declaration's pool. In
      `kit/site/src/market_site/capacity_definitions.py`: map it to `unknown_pool` and
      remove `pool_exists` from `reconcile_capacity_definitions_in_session`; remove it
      from `reconcile_capacity_document` in `definition_documents.py`. Declare the
      pools four `kit/site` tests register into without creating
      (`test_ledger.py`'s `test_registered_resource_carries_the_real_pool_id` and
      `test_re_registering_updates_pool_id`; `test_projection_router.py`'s two
      projection tests), and any the provisioning and downstream suites reveal.
      **Integration** (`provisioning/compute/service/tests/integration/test_capacity_api.py`):
      a `PUT` naming an unknown pool through `SiteCapacityAdminClient` is 422 and
      writes nothing.
      **Done 2026-09-21:** `UnknownPoolError` in `ledger.py`, exported from
      `market_site`. Beyond the four `kit/site` tests, two provisioning
      integration tests registered into pools they never created
      (`version-pool`, `hetzner-eu`); they now create them through
      `ProvisioningClient.create_pool` (`_create_pool` in
      `test_capacity_api.py`).
      `test_a_declaration_naming_an_unknown_pool_is_refused` (unit) and
      `test_a_registration_naming_an_unknown_pool_is_refused` (integration).
- [x] 7b.3 **Test evidence.**
      - 4b.9: add the typed-client case it claimed —
        `SiteCapacityAdminClient` registers a declaration naming only `ram_gb` and reads
        it back with `value` and `available_units` absent (`test_capacity_api.py`).
      - 4c.3: relabel as a component test; add the integration case — a `PUT` moving a
        resource with a live reservation to another pool is 409 through
        `SiteCapacityAdminClient`, and succeeds after release (`test_capacity_api.py`).
      - 5.5 and 5.6: relabel as component tests, as the relay restart-safety tests they
        follow are.
      - 5.11: correct its note (the structural problem was a second request) and add
        the structural-first case to `test_capacity_definitions_api.py`: an unknown field
        beside an unknown pool reports only the unknown field.
      - `docs/development/DEPLOYMENT_AND_CONFIG.md`'s "Capacity definitions": state
        structural-first validation.
      **Done 2026-09-21:**
      `test_a_declaration_naming_no_compute_dimension_is_stored_as_declared` and
      `test_a_held_resource_moves_pools_only_once_released` in
      `test_capacity_api.py`;
      `test_a_structurally_invalid_document_is_not_checked_against_stored_state`
      in `test_capacity_definitions_api.py`. Relabels and the 5.11 correction
      are in those tasks' notes. `DEPLOYMENT_AND_CONFIG.md` describes the two
      stages.
- [x] 7b.4 **Freeze the upgrade migration.** In
      `provisioning/compute/service/src/compute_provisioning_service/db/migrations.py`,
      `_migrate_legacy_host_capacity_declarations` derives in migration-local SQL —
      the same selection (GPUs, no declaration naming the host, resource id not taken),
      the same declaration row, and the same `released` capacity event registration
      appends — and the module no longer imports the derivation or the ledger.
      Tests (`tests/unit/test_legacy_host_capacity_migration.py`): the existing three,
      plus a parity test deriving the same hosts once through the migration and once
      through `LegacyHostCapacityDerivation`, comparing declarations and events.
      **Done 2026-09-21:** `_migrate_legacy_host_capacity_declarations` is SQL,
      planning every row before writing; `migrations.py` no longer imports the
      ledger or the derivation, and the two imports added for them are removed.
      `test_the_migration_derives_what_the_runtime_derivation_derives` compares
      declarations and events; making the migration drop `gpu_model`, or record
      `capacity_changed` instead of `released`, fails it.
- [x] 7b.5 **Records.** `design.md` done with this plan. Amend task notes 2.1, 3.1,
      4b.9, 4c.3, 5.5, 5.6, 5.11, 5.12 as each correction lands.
      **Done 2026-09-21:** Task notes amended when this section was planned;
      each correction's evidence is in its 7b note.
- [x] 7b.6 **Validation.** Rebuild the changed wheels and rerun `kit/site`, the
      provisioning service, `kit/site-client`, `kit/fulfillment`, `core/storefront`,
      API-credits service and storefront, bare-metal storefront and adapter, the VM
      adapter's target, e2e unit, and the VM storefront.
      **Done 2026-09-21:** `kit/site` 245, provisioning service 936,
      `kit/site-client` 36, `kit/fulfillment` 165, `core/storefront` 158,
      API-credits service 63 and storefront 79, bare-metal storefront 126 and
      adapter 2, the VM adapter's target 38, e2e unit 237 plus its known
      failure, VM storefront 1170 plus its two known `test_alkahest` failures
      (in its existing environment).

## 7c. Second review corrections (planned and done 2026-09-21)

From the review after closeout; `design.md`'s "Review corrections" records the
corrected serialization rule. `kit-site` 0.4.0 and `kit-fulfillment` 0.3.0 are
unpublished minor bumps on this branch and cover these changes.

- [x] 7c.1 **Settlement assignment serializes with pool moves.**
      `kit/site/src/market_site/ledger.py`: `assign_settlement_resource_in_session`
      requires `serialized()`. `kit/fulfillment/src/market_fulfillment/scheduling_persistence.py`:
      `SqlAlchemySchedulingUnitOfWork.transaction` takes `capacity_ledger.serialized()`
      before opening its session (ledger lock, then database, as everywhere else).
      `kit/site/tests/unit/test_settlement_assignment.py`'s two direct callers hold it.
      Tests (component, `kit/site/tests/unit/test_ledger.py`): the assignment writer
      refuses outside the lock; on a file-backed database with independent sessions,
      a pool move paused after its obligation check races a settlement assignment onto
      the resource, and no committed state has a held reservation debited to or
      assigned to the moved resource. Break `serialized()` to confirm the race test
      fails, as for 7b.1.
      **Done 2026-09-21:** `kit/site/tests/unit/test_ledger.py`'s
      `test_a_settlement_assignment_outside_the_serialized_region_is_refused`;
      the race test is in `kit/fulfillment/tests/unit/test_scheduler.py`
      (`test_a_settlement_assignment_racing_a_pool_move_never_survives_on_the_moved_resource`),
      so it drives the real scheduling unit of work. It asserts the commit
      order, because an assignment committed after the move, onto the resource
      in its new pool, is not what the rule forbids. With neither the writer's
      requirement nor the unit of work's lock (the pre-fix state), it fails on
      each of three runs; with only the unit of work's lock removed, six
      scheduler tests fail at once on the writer's refusal. The existing
      cross-thread scheduling test still passes.
- [x] 7c.2 **Stale docstring.** `provisioning/compute/service/tests/integration/test_capacity_definitions_api.py`'s
      `test_a_refused_import_reports_every_problem_and_applies_nothing` describes the
      two requests it makes.
      **Done 2026-09-21:** The docstring now describes the two imports the test
      makes.
- [x] 7c.3 **`kit/site` → `kit/resource-pools` layering.** `ARCHITECTURE.md` allows
      authority capabilities to depend on foundation capabilities only; `kit/site`
      declares `kit-resource-pools` and reads `ResourcePool` for pool existence
      (added here) and deliverable modes (pre-existing). Disposition per the owner's
      decision; `design.md`'s "The ledger refuses an unknown pool" is corrected either
      way, since "the dependency already exists" does not answer the layering rule.
      **Disposition 2026-09-21:** not resolved here; the owner declined to add
      scope this late. Recorded as an open question in
      `openspec/changes/pool-declared-advertisement-and-backing/design.md`,
      whose pool declarations are what the site authority reads. `design.md`'s
      "The ledger refuses an unknown pool" no longer justifies the dependency.
- [x] 7c.4 **Image publication tag.** `Makefile`'s `push-images` retags the local
      `arkhai:compute-provisioning-<sha>` the service build produces as the remote
      `arkhai:provisioning-<sha>`; it named a local `arkhai:provisioning-<sha>` that no
      build makes. `scripts/tests/test_image_publication_contract.py` asserts exactly
      this and runs under `make test-release-tooling`, not `make test`.
      **Done 2026-09-21:** one argument changed; both targets dry-run to the strings
      the contract test asserts. The test itself needs `git rev-parse`, unavailable in
      the implementation snapshot, so its first run is the owner's. Pre-existing and
      unrelated to capacity; fixed here at the owner's request.
- [x] 7c.5 **Validation.** Rebuild `kit-site` and `kit-fulfillment`; rerun `kit/site`,
      `kit/fulfillment`, the provisioning service, and every suite 7b.6 ran.
      **Done 2026-09-21:** `kit/site` 246, `kit/fulfillment` 166, provisioning
      service 936, `kit/site-client` 36, `core/storefront` 158, API-credits
      service 63 and storefront 79, bare-metal storefront 126 and adapter 2, the
      VM adapter's target 38, e2e unit 237 plus its known failure, VM storefront
      1170 plus its two known `test_alkahest` failures.

## 8. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [x] 8.1 **Comment hygiene.** Run `make check-comment-hygiene` and resolve every
      match. Read the touched docstrings directly as well — several of them
      (`_project_host`, the capacity registration route, the two seeding steps)
      currently describe the arrangement this change replaces, and a stale docstring
      is what made this gap invisible in the first place.
      **Done 2026-09-21:** `make check-comment-hygiene` passes. Read directly:
      `_project_host`'s and `load_capacity_resource_inventory`'s docstrings
      describe the cutover; the capacity registration route's docstring now
      names the unknown-pool refusal; `seed_inventory_if_empty`'s comment now
      says seeding also declares capacity.
- [x] 8.2 **Import placement.** Review imports this change adds or touches; move
      function-level imports to module level where no genuine circular import or
      documented lazy-load reason applies, verified against the real suite.
      **Done 2026-09-21:** Every import this change added is at module level.
      Moved: `LegacyHostCapacityDerivation` in the integration `conftest.py`
      (the fixture's other imports stay local by its established pattern) and
      `HostCreate` in `test_capacity_api.py`; earlier moves are in 4b.6 and 4.4.
      The service suite passes (936).
- [x] 8.3 **Documentation compliance.** Re-check accepted decisions against
      `openspec/README.md`'s placement rules; confirm the capability-boundary
      rationale landed in `site-capacity/architecture.md` and the authority statements
      in the two `spec.md` files rather than only in this change.
      **Done 2026-09-21:** Normative rules are in
      `openspec/specs/site-capacity/spec.md` and
      `physical-provisioning/spec.md`; rationale in
      `site-capacity/architecture.md`; the repository-wide authority row and
      vocabulary in `ARCHITECTURE.md`; operator configuration in
      `DEPLOYMENT_AND_CONFIG.md` and `docs/seller-quickstart.md`; test guidance
      in `TESTING.md`. Nothing durable is left only in this directory; the rows
      marked temporary below are change history by decision.
- [x] 8.4 **Narrative compression.** Compress completed-task notes to final behavior,
      validation evidence, and promotion destinations; keep the rejected-alternatives
      analysis in `design.md`.
      **Done 2026-09-21:** The history paragraphs at the top of this file (pause
      notes, planning-pass notes, resume notes) are replaced by one status
      paragraph; each fact they held is in a task note or `design.md`. Task
      notes are kept: each records final behaviour, its evidence, or a
      correction the review required.
- [x] 8.5 **Roadmap currency.** Update the affected goal's current-state description
      and gap mapping in `docs/development/ROADMAP.md`. **Amended 2026-09-21:** the
      roadmap exists; the owed updates are Goal 1's gap row naming this change (remove
      it and absorb the result into Goal 1's current state), Goal 4's note that the
      compute-dimension leak rides with this change (state it fixed), and Goal 7's
      prerequisite mention. Record each in the promotion record.
      **Done 2026-09-21:** Goal 1: its gap row naming this change is removed and
      its current-state paragraph states the result. Goal 4: the
      compute-dimension note states the leak fixed. Goal 7: no change owed; it
      names no dependency on this change, and its row for declarations without a
      host remains true.
- [x] 8.6 **Promotion.** Complete the design-promotion record below. Performed last,
      after 8.7–8.9, per `openspec/README.md`'s closeout order; numbering is kept for
      stability.
      **Done 2026-09-21:** Every accepted decision has a permanent destination
      or a recorded temporary disposition below; the specs were synced from this
      change's deltas, each requirement verbatim and exactly once, and both
      validate strictly.
- [x] 8.7 **Campaign index currency** (part seven, added when
      `openspec/README.md#plan-closeout-requirements` was extended from six parts to seven).
      Appended rather than folded into an existing task, per `AGENTS.md`'s rule to amend
      rather than replace implementation history. Update this change's row, and its
      campaign's dependency graph, in `openspec/changes/README.md` to match its state at
      completion, or record the disposition here if its status and campaign placement are
      both unchanged.
      **Done 2026-09-21:** This change's row reads complete and ready to
      archive; `pools-9-retire-local-physical-authority` and
      `project-capacity-resources-without-hosts` record the dependency as
      complete; the Goal 7 prerequisite paragraph states what was delivered. The
      dependency graphs are unchanged until archival.

- [x] 8.8 **Documentation citations.** Run
      `make check-doc-citations CHANGE=capacity-resource-administration` and resolve every match.
      An unresolvable citation is a blocking defect under `AGENTS.md`'s
      cross-reference rule, and the target also rejects a citation whose
      target is a *tombstone*: a tombstoned file still exists on disk while
      its content is gone, so a plain existence test cannot fail on a
      rename-to-tombstone.
      **Done 2026-09-21:** `make check-doc-citations
      CHANGE=capacity-resource-administration` passes. The repository-wide count
      is 17, unchanged from the upload.
- [x] 8.9 **End-to-end pipeline.** Confirm the end-to-end pipeline passes and
      record the evidence: the run, its result, and the scenarios that
      exercise this change's behaviour. Green unit and integration suites do
      not substitute -- this is the tier that catches a wire contract whose
      two sides disagree, a service that starts cleanly and cannot settle,
      and a configuration gap no in-process test can see. If the pipeline
      cannot run for a reason unrelated to this change, record that as an
      explicit blocker naming the cause and the change that owns it, and
      treat the validations it gates as unrun rather than passed.
      **Done 2026-09-21:** The owner reported `make test` and the end-to-end
      pipeline green on 2026-09-21, after committing the VM storefront lock the
      earlier failed run lacked (5.12); no run identifier was supplied. The VM
      scenarios declare capacity through `SiteCapacityAdminClient` and publish
      through the declaration-driven projection, so they exercise the cutover
      and the registration contract; the capacity-definitions document and INI
      derivation are not exercised end to end, since Compose wires no document
      and the scenarios declare through the API by design.
      **Amended 2026-09-21:** after 7c changed the scheduling unit of work, the
      owner reran `make test` and the end-to-end pipeline on the final fileset;
      both passed. That run is the evidence for the final code.
## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Capacity resources are authoritative for the declared sellable shape and quantity across every dimension; admission authority is resolved separately | `openspec/specs/site-capacity/spec.md` — "Operator-administered capacity declarations" |
| A capacity declaration names no mandatory dimension; the legacy mirror's dimension is composition-supplied and its scalar total is absent where there is no mirror dimension | `openspec/specs/site-capacity/spec.md` |
| A capacity resource does not move pools under live capacity obligations | `openspec/specs/site-capacity/spec.md` |
| Capacity definitions reconcile on a document digest at startup; REST import always reconciles, records no digest, and retains unnamed declarations | `openspec/specs/physical-provisioning/spec.md` — "Capacity definitions are imported from a mounted document"; `docs/development/DEPLOYMENT_AND_CONFIG.md` — "Definition documents" |
| Registration requires `pool_id`; `NULL` pool ids read as the default pool | `openspec/specs/site-capacity/spec.md` — "Operator-administered capacity declarations" |
| Derivation runs where INI data is applied and once at upgrade, using the projection's correlation rule | `openspec/specs/physical-provisioning/spec.md` — "Legacy host capacity is derived into declarations" |
| A declaration names its host through `host_id`; correlation is that field alone | `openspec/specs/physical-provisioning/spec.md` — "Legacy host capacity is derived into declarations" |
| Projected attributes are the declaration's minus `bare_metal_publication`, plus host connection fields written last | `openspec/specs/site-capacity/spec.md` — "Projected inventory is internally consistent" |
| A host with no declaration is not projected | `openspec/specs/physical-provisioning/spec.md` — "Host inventory is connection identity" |
| Capacity and pool document wiring follow the relay idiom; both are opt-in Helm values | `docs/development/DEPLOYMENT_AND_CONFIG.md` — "Definition documents" |
| Wire changes are versioned by distribution, not envelope | Temporary; change history only |
| Projected attributes must not contradict projected capacity | `openspec/specs/site-capacity/spec.md` — "Projected inventory is internally consistent" |
| Host inventory is connection identity, not capacity authority | `openspec/specs/physical-provisioning/spec.md` — "Host inventory is connection identity"; `docs/development/ARCHITECTURE.md` authority-boundaries table and "Capacity Declaration" vocabulary entry |
| Legacy host capacity is derived into declarations rather than retained as a fallback tier | `openspec/specs/physical-provisioning/spec.md` — "Legacy host capacity is derived into declarations" |
| Capacity definitions import is digest-gated, after pool definitions and host seeding | `openspec/specs/physical-provisioning/spec.md` — "Capacity definitions are imported from a mounted document" |
| Why capacity declaration is separate from host inventory, and why splitting dimensions across both was rejected | `openspec/specs/site-capacity/architecture.md` — "Declared capacity and connection identity" |
| A capacity-definitions entry uses the registration fields, replaces the whole declaration, and is refused with every problem reported; unchanged entries write nothing; refusals come from registration's own rules and leave the import unapplied; the import API has a validate-only mode | `openspec/specs/physical-provisioning/spec.md` — "Capacity definitions are imported from a mounted document"; `docs/development/DEPLOYMENT_AND_CONFIG.md` — "Definition documents" |
| A declaration's attributes cannot restate its identity, and declaration fields win over attributes in matching | `openspec/specs/site-capacity/spec.md` — "A declaration's attributes cannot restate its identity" |
| The unit total is a match fact only under the composition's mirror dimension | `openspec/specs/site-capacity/spec.md` — "A capacity declaration names no mandatory dimension" |
| How chart render tests are written and run | `docs/development/TESTING.md` — "Chart Render Tests" (written directly as current guidance) |
| A capacity declaration is one type, shared by registration, documents, the ledger, and derivation | Code: `kit/site/src/market_site/declarations.py` module docstring; temporary otherwise |
| Administration holds the ledger's serialization lock through its caller's commit | `openspec/specs/site-capacity/architecture.md` — "Declared capacity and connection identity" |
| A declaration naming an unknown pool is refused by registration itself, for every entry point | `openspec/specs/site-capacity/spec.md` — "Operator-administered capacity declarations" |
| Structural validation completes before stored state is consulted | `openspec/specs/physical-provisioning/spec.md` — "Capacity definitions are imported from a mounted document" |
| Legacy single-quantity claims translate to the composition's mirror dimension; a bucket's host link is its `host_id` | `openspec/specs/site-capacity/spec.md` — "Multidimensional capacity accounting" and "Site identity ownership boundary" (modified) |
| The upgrade migration's derivation is frozen SQL, held equal to the runtime derivation by a parity test until it ships | Temporary; change history only (the migration's docstring states what it does) |
| Test levels are stated as `TESTING.md` defines them | Temporary; change history only |
| `kit/site`'s dependency on `kit/resource-pools` contradicts the kit layers | Open question in `openspec/changes/pool-declared-advertisement-and-backing/design.md` — not resolved by this change |
| Stored reserved attribute keys are removed by migration, not promoted | Temporary; change history only (the migration's docstring states the rule it enforces) |
| Capacity-definitions wire models live in `kit/site`, re-exported by `compute_provisioning` | Code: `kit/site/src/market_site/capacity_definitions.py` module docstring; `ARCHITECTURE.md`'s layers name no model ownership |
