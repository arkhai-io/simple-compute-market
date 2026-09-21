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

**Dependency.** Sections 2 and 4 consume the declaration's `host_id` and the renamed
host registry from `unify-host-identity`, which lands first. Every decision gate in
this file was resolved on 2026-09-21.

## 1. Capacity declaration carrier and administration surface

- [x] 1.1 Confirm by inspection, before writing anything, that the findings in
      `design.md`'s "Context" still hold: the startup step list, the absence of any
      capacity-resource seeding, `_project_host`'s fallback shape, and `Host`'s
      column set. Record any drift in `design.md` rather than working around it.
      Done 2026-09-21 during design review; drift recorded under `design.md`'s
      "What changed since the investigation". Re-run the same checks at the start of
      implementation if other changes have landed since.
- [ ] 1.2 Define the capacity-definitions document shape (a declaration per Physical
      Resource carrying `resource_id`, a required `pool_id`, `resource_type`,
      optional `resource_subtype`, capacity dimensions, categorical attributes, and
      `enabled`), mirroring the pool-definitions document's structure and validation
      posture: duplicate ids and malformed dimensions are validation problems reported
      together, not first-failure exceptions. New module
      `kit/site/src/market_site/capacity_definitions.py`, parallel to
      `kit/resource-pools/src/market_resource_pools/service.py`'s document handling.
- [ ] 1.3 Promote `PUT /api/v1/capacity/resources/{resource_id}` from a compatibility
      endpoint to a documented operator administration surface: correct the route
      docstring in `kit/site/src/market_site/router.py`, which currently describes it
      as a compatibility path for domains registering logical capacity, and state the
      multidimensional contract and full-replacement semantics.
- [ ] 1.4 Verify `ResourceRegisterRequest` already expresses everything a declaration
      needs and add nothing that is not required; `capacity` and `attributes` are
      already free-form maps. If a client method is added, add it to both the async
      and sync variants in the same change and cover it with the parity contract test
      `TESTING.md` requires. **Amended 2026-09-21:** the two field changes this change
      does make (`pool_id` required, `total_units` optional) are Section 4b's.
      `SiteCapacityAdminClient` has no sync variant, so parity does not apply to it.
- [ ] 1.5 Focused tests: declaration accepted with several dimensions, declaration
      accepted with a single dimension, omitted dimensions treated as undeclared.

## 2. Derivation from legacy host capacity

- [ ] 2.1 Implement the host-to-declaration derivation as one reusable unit consumed
      by both the migration (Section 3) and INI host application (task 2.5) — one
      implementation, two callers, not two code paths that can drift. **Amended
      2026-09-21:** the second caller was a startup step; see `design.md`'s "Legacy
      host capacity is derived at seed time and once at upgrade". Pure planning
      function in a new
      `provisioning/compute/service/src/compute_provisioning_service/services/capacity_derivation.py`,
      writing through `CapacityLedgerService.register_resource_in_session`.
- [ ] 2.2 Derive only for hosts with `gpu_count > 0` and no correlated declaration.
      Never overwrite, never merge. Report the derived set at INFO, matching how both
      existing seeding steps report theirs. **Amended 2026-09-21 (gate resolved):**
      "correlated" means some declaration carries this host's `host_id`, per
      `design.md`'s "A declaration names its host through `host_id`". Derived shape
      per `design.md`'s table.
- [ ] 2.3 Carry `gpu_model` into the declaration's attributes rather than dropping
      it — categorical, matched by equality, so it belongs in attributes and not in
      the capacity map.
- [ ] 2.4 Focused tests: derivation for a host with legacy data; no derivation when a
      declaration exists; operator declaration retained unchanged when it disagrees
      with the legacy value; idempotent across repeated runs. **Added 2026-09-21:**
      no derivation when a declaration's `resource_id` differs from its `host_id`
      (the e2e shape);
      none for a zero-GPU host; a derived declaration's pool and enabled state follow
      the host.
- [ ] 2.5 Wire derivation into `HostService.seed_from_ini`
      (`domains/vms/provisioning/adapter/src/vm_provisioning_adapter/services/host_service.py`)
      through an injected derivation port supplied by
      `provisioning/compute/service/src/compute_provisioning_service/container.py`,
      running inside the host upsert's session and transaction. Do not wire it into
      `create_host`/`update_host`. Both callers of `seed_from_ini` — the
      `seed-inventory` startup step and `POST /api/v1/hosts/import` — gain derivation
      through this one change.
- [ ] 2.6 **Integration.** `POST /api/v1/hosts/import` of an INI with `gpus=` derives
      declarations visible through `GET /api/v1/capacity/resources` via the typed
      client; `POST /api/v1/hosts` with `gpu_count` derives nothing. A failure injected
      after the host upsert and before the derivation commits leaves neither.

## 3. Ordered migration

- [ ] 3.1 Add the migration that runs the Section 2 derivation, ordered in the
      provisioning chain and applied before the application serves requests per
      `deployment-state`'s service-owned migration history requirement.
- [ ] 3.2 Keep the migration to the derivation only — no column drop, no host-row
      mutation. Freeze-then-redirect, matching the POOLS campaign's additive-only
      convention. **Amended 2026-09-21:** Section 4b's schema migration is a separate
      ordered entry that runs before this one; this entry stays derivation-only.
      File: `provisioning/compute/service/src/compute_provisioning_service/db/migrations.py`,
      appended to `MIGRATIONS` so `check_schema_version` requires it.
- [ ] 3.3 Validate migration behavior the way `TESTING.md` requires for this
      repository: fresh bootstrap, idempotent rerun, and drift detection.
- [ ] 3.4 Confirm rollback within the freeze window leaves derived rows harmless to a
      restored reader, and document that rolling back past this change is a code
      rollback rather than a configuration change.

## 4. Projection cutover

The behavioral heart of the change. Depends on Sections 2 and 3 having populated the
authority.

- [ ] 4.1 Redirect `capacity_inventory._project_host` to read both `capacity` and
      `attributes` from the declared capacity resource, removing the host-derived
      capacity fallback. **Amended 2026-09-21:** a host no declaration correlates to is
      not projected (`design.md`, "A host with no declaration is not projected"). The
      loop remains host-driven; inverting it is
      `project-capacity-resources-without-hosts`'s scope. Correlation is
      `declaration.host_id == host.host_id` (gate resolved 2026-09-21).
- [ ] 4.2 Fix the divergence in the same edit: `attributes` currently derives from
      the host unconditionally while `capacity` prefers the resource, so a
      declaration disagreeing with a host row projects contradictory values in one
      row. Both must come from one record. **Amended 2026-09-21 (gate resolved):**
      copy every declaration attribute except `bare_metal_publication`; write the
      host's `public_host` last; remove `attributes.gpu_count`. Per `design.md`'s
      "Projected attributes are the declaration's, plus host connection fields".
- [ ] 4.3 Confirm the bare-metal publication view survives the cutover. It reads
      `resource.attributes[bare_metal_publication]` together with `capacity` through
      `_whole_resource_available`, and the cutover changes where `capacity` comes
      from. Cover with a focused test rather than reasoning about it.
- [ ] 4.4 Handle the `available`-key semantics change explicitly. `_project_host`
      currently omits `available` when no capacity resource exists; after derivation,
      hosts that previously projected no `available` will project one, and the VM
      reconciler distinguishes an absent projection from a loaded empty one under its
      "ignorance is not zero" rule. Add storefront-side coverage, not only
      provisioning-side — this is the highest-risk item in the change.
- [ ] 4.5 Run the VM e2e scenarios that depend on projected capacity shape, and the
      `kit/site` ledger and router suites.
- [ ] 4.6 **Unit.** A host with no correlated declaration yields no projected entry;
      update `tests/unit/services/test_capacity_inventory.py`'s host-only cases, which
      currently assert the fallback.

## 4b. Composition-supplied mirror dimension

`design.md`'s "The primary-dimension fallback writes a GPU name into every domain"
accepted this fix; it previously had no task, so an implementer would have had to
invent the semantics while coding. Retiring the scalar mirror entirely remains
deferred — this is the smaller half that the domain-neutral declaration contract
depends on.

- [ ] 4b.1 Make the dimension the legacy scalar mirror tracks composition-supplied,
      the way `unit_claim_keys` already is, rather than the module-level
      `PRIMARY_DIMENSION = "gpu_count"` in `kit/site/ledger.py`. **Amended
      2026-09-21:** every site listed under `design.md`'s "What changed since the
      investigation" reads the supplied name, including the module-level helpers
      (`_requested_dimensions`, `_resource_capacity`, `_reservation_dimensions`,
      `dict_resource_satisfies_claim`, `resource_feasibility_view`), which take it as
      a parameter. Update their callers in `kit/fulfillment/src/market_fulfillment/`
      and any storefront caller found by search.
- [ ] 4b.2 Stop writing a mirror dimension into a caller's explicit capacity map.
      `register_resource` currently injects it when absent and then reads it back for
      `mirrored_units`; both sites need the supplied name and the explicit-declaration
      case.
- [ ] 4b.3 Make `total_units` optional and absent where the declaration names no
      mirror dimension. Files: `kit/site/src/market_site/http_models.py`,
      `kit/site/src/market_site/db.py` (`CapacityBucket.total_units` nullable),
      `kit/site-client/src/market_site_client/models.py` and `client.py`. A request
      carrying neither `total_units` nor `capacity`, or both disagreeing, is rejected. **Decided 2026-09-09** rather than left as a gate: the
      existing consistency check compares the scalar against its mirrored dimension
      when both are present, so absence keeps that check meaningful while a
      substituted zero would make it assert a false equality. Retiring the scalar
      entirely remains deferred.
- [ ] 4b.4 Wire the VM composition to its existing mirror dimension so no behaviour
      changes there.
- [ ] 4b.5 Wire the API-credit composition to its own dimension, matching how it
      already overrides `unit_claim_keys` to `("units",)`.
      **Amended 2026-09-21:** the dimension is `units`, in
      `domains/apicredits/service/src/container.py`. No migration and no
      compatibility reader — the domain is unlaunched and its databases are
      recreated; say so in the service's migration module docstring only if a reader
      would otherwise expect one.
- [ ] 4b.6 Confirm legacy rows whose scalar mirror was written under the old constant
      still read correctly, and record how a row written before this change is
      interpreted after it. **Amended 2026-09-21:** scoped to the compute domain,
      whose mirror name does not change; API-credit rows are out of scope per 4b.5.
- [ ] 4b.7 **Unit.** An explicit multidimensional declaration with no compute
      dimension is stored as declared, with no manufactured GPU dimension, and its
      scalar unit total is absent rather than zero.
- [ ] 4b.8 **Unit.** The VM composition's legacy scalar fallback maps to its
      configured mirror dimension; the API-credit composition's does not become
      `gpu_count`.
- [ ] 4b.9 **Integration.** One typed-client case registering a resource whose
      declaration names no compute dimension.
- [ ] 4b.10 Require `pool_id` on registration: required field on
      `ResourceRegisterRequest` and `ResourceRegistration`, required argument on
      `register_resource`. Update every caller —
      `domains/apicredits/storefront/src/apicredits_storefront/startup.py` passes the
      default pool explicitly, and the test fixtures in `kit/site`, `kit/fulfillment`,
      provisioning, VM storefront, and API-credits suites that register without one.
- [ ] 4b.11 Add `CapacityLedgerService.register_resource_in_session(db, ...)`, neither
      opening a session nor committing, with `register_resource` delegating to it
      under the ledger lock.
- [ ] 4b.12 Compute migration, ordered before Section 3's: make
      `capacity_buckets.total_units` nullable (SQLite table rebuild through the
      existing helper) and backfill `NULL` `pool_id` to `DEFAULT_POOL_ID`. Cover fresh
      bootstrap, idempotent rerun, and a populated database.
- [ ] 4b.13 **Rejection-path integration.** A `PUT` without `pool_id` returns 422;
      status-code-only assertion, commented as a rejection-path test per
      `TESTING.md`.
- [ ] 4b.14 Bump distribution versions and lower bounds: `arkhai-kit-site`,
      `arkhai-kit-site-client`, the compute provisioning service, the API-credits
      service and storefront, and every `pyproject.toml` that depends on the first
      two. No versioned envelope is affected (`design.md`, "Wire and distribution
      versioning"); if implementation finds one, raise its version and record it
      there.

## 4c. Pool reassignment drain rule

- [ ] 4c.1 Refuse reassignment of a capacity resource that holds a live capacity
      obligation — hold, reservation, assignment, or workload — resolved through its
      pool. `register_resource` currently writes `bucket.pool_id = effective_pool_id`
      unconditionally on update, and `backing_pool_id_in_session` resolves a
      reservation's pool through the resource's *current* `pool_id`, so reassignment
      rewrites the authority under an existing reservation.
- [ ] 4c.2 Leave the resource in its current pool when a reassignment is refused. A
      partial move is worse than a refused one. **Amended 2026-09-21:** "live
      obligation" is a held-state reservation debited against the resource or whose
      `settlement_resource_id` names it; compare pools after reading `NULL` as the
      default pool. The route maps the refusal to 409.
- [ ] 4c.3 **Integration, real DB transaction.** A resource holding a live reservation
      cannot cross a pool boundary; the same resource can once its obligations are
      drained. Cover both in one test so the refusal is not mistaken for a resource
      that could never move. Keep the coverage generic: this change does not depend on
      `pool-declared-advertisement-and-backing`, so a backed-to-unbacked case would
      exercise terminology that may not exist yet when this lands. That
      specialization belongs to the Goal 7 change that introduces it.
- [ ] 4c.4 Confirm no existing fixture, bulk import, or e2e setup reassigns a resource
      under a live obligation. If one does, drain it rather than exempting it.

## 5. Startup import

- [ ] 5.1 Add `capacity_definitions_path` to `settings.toml` and its
      `resolved_capacity_definitions_path` property in `config.py`, mirroring
      `pool_definitions_path` exactly, including empty-string-means-unset.
- [ ] 5.2 Add the import step through the existing `DefinitionDocumentImporter`
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
- [ ] 5.3 Register the step in `startup_steps()` **after** `import-pool-definitions`,
      since a declaration may reference a pool. **Amended 2026-09-21:** also after
      `seed-inventory`, giving relays → pools → hosts → capacity → job queue.
      Files: `app_runtime.py`, `services/definition_documents.py`
      (`import_capacity_definitions` and its applier).
- [ ] 5.4 ~~Run the Section 2 derivation as part of startup for hosts with legacy data
      and no declaration, so an INI-only deployment retains published capacity once
      the fallback is gone.~~ **Superseded 2026-09-21** by tasks 2.5 and 3.1:
      derivation runs where INI data is applied and once at upgrade, never as a
      recurring startup scan.
- [ ] 5.5 **Integration.** Definitions applied on a restart after an edit;
      configured-but-missing path fails startup; unconfigured path proceeds;
      declaration referencing a pool resolves.
- [ ] 5.6 **Integration.** An unchanged document at restart does not overwrite
      capacity administered through the API since the last import. This is the
      regression the digest gate exists to prevent and the happy-path cases above do
      not cover it.
- [ ] 5.7 **Integration.** An explicit import reconciles a document whose digest
      matches the recorded one.
- [ ] 5.8 Confirm the digest and the reconciliation commit in one transaction,
      reusing the failure pattern the existing definition-document coverage uses. A
      digest committed after an already-committed apply is indistinguishable at the
      next startup from one recorded before a crash.
- [ ] 5.9 Add `POST /api/v1/capacity/definitions/import` in a new
      `controllers/capacity_definitions_controller.py`, taking the document the way
      `POST /api/v1/hosts/import` takes its INI and authenticated as that route is.
      It always reconciles and records no digest. Register it in the provisioning
      route contract (`provisioning/compute/src/compute_provisioning/client.py`) and
      add a typed client method so integration tests obey the "no raw calls" rule.
- [ ] 5.10 **Integration.** A document omitting a previously imported, derived, or
      API-registered declaration leaves it unchanged; a document naming an unknown
      pool fails naming it, applies nothing, and records no digest; an explicit
      import leaves the recorded startup digest unchanged.

## 6. Operator surface and deployment wiring

- [ ] 6.1 Add Helm and compose wiring for `capacity_definitions_path`, following the
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
- [ ] 6.2 ~~Add CLI coverage for declaring and inspecting capacity, so registration is a
      documented workflow rather than a raw HTTP call.~~ **Superseded 2026-09-21:**
      no CLI. Site administrators configure through values files, configuration
      files, and the REST API; task 6.3 documents those.
- [ ] 6.3 Update `docs/seller-quickstart.md` and the configuration reference with the
      capacity declaration workflow, including that a declaration wins over any
      derivable legacy host value — the intuition may run the other way. **Amended
      2026-09-21:** cover the document format, the startup digest rule, the REST
      import, retention of unnamed declarations, the `pool_id` requirement, the Helm
      values (`definitions.capacity` and `definitions.pools`), and that everything in
      a declaration's attributes is published to storefronts. Add a "Capacity definitions" subsection to
      `docs/development/DEPLOYMENT_AND_CONFIG.md`'s "Definition documents", stating
      how its retention rule differs from pools and matches relays.
- [ ] 6.4 State the INI's `gpus=`/`gpu_model=` disposition in operator documentation:
      still parsed, still written to frozen host columns, no longer reaching the
      projection except through derivation, and slated for removal with the later
      column drop. Include that INI values stop affecting capacity once a declaration
      correlates to the host.
- [ ] 6.5 **Helm render test.** For each of `definitions.capacity` and
      `definitions.pools`: empty renders no document, no mount, and no path; non-empty
      renders all three; setting the corresponding `config.*_definitions_path` fails
      schema validation. A render with both supplies both paths.

## 7. Validation

- [ ] 7.1 Run the provisioning unit and integration suites, `kit/site`'s suites, and
      the affected VM e2e scenarios. Disclose any suite not run.
- [ ] 7.2 Run `openspec validate --all --strict` and confirm no regression against the
      baseline current at implementation time.
- [ ] 7.3 Verify package and import boundaries are unchanged: `kit/site` must not
      acquire a provisioning dependency, and generic compute service modules must not
      import concrete VM or bare-metal models, per `physical-provisioning`'s
      dependency-isolation requirements. **Added 2026-09-21:** the VM provisioning
      adapter reaches derivation only through the injected port, not by importing the
      provisioning service's derivation module.

## 8. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [ ] 8.1 **Comment hygiene.** Run `make check-comment-hygiene` and resolve every
      match. Read the touched docstrings directly as well — several of them
      (`_project_host`, the capacity registration route, the two seeding steps)
      currently describe the arrangement this change replaces, and a stale docstring
      is what made this gap invisible in the first place.
- [ ] 8.2 **Import placement.** Review imports this change adds or touches; move
      function-level imports to module level where no genuine circular import or
      documented lazy-load reason applies, verified against the real suite.
- [ ] 8.3 **Documentation compliance.** Re-check accepted decisions against
      `openspec/README.md`'s placement rules; confirm the capability-boundary
      rationale landed in `site-capacity/architecture.md` and the authority statements
      in the two `spec.md` files rather than only in this change.
- [ ] 8.4 **Narrative compression.** Compress completed-task notes to final behavior,
      validation evidence, and promotion destinations; keep the rejected-alternatives
      analysis in `design.md`.
- [ ] 8.5 **Roadmap currency.** Update the affected goal's current-state description
      and gap mapping in `docs/development/ROADMAP.md`. If `add-development-roadmap`
      has not landed when this change completes, record that disposition explicitly
      rather than skipping the step.
- [ ] 8.6 **Promotion.** Complete the design-promotion record below. Performed last,
      after 8.7–8.9, per `openspec/README.md`'s closeout order; numbering is kept for
      stability.
- [ ] 8.7 **Campaign index currency** (part seven, added when
      `openspec/README.md#plan-closeout-requirements` was extended from six parts to seven).
      Appended rather than folded into an existing task, per `AGENTS.md`'s rule to amend
      rather than replace implementation history. Update this change's row, and its
      campaign's dependency graph, in `openspec/changes/README.md` to match its state at
      completion, or record the disposition here if its status and campaign placement are
      both unchanged.

- [ ] 8.8 **Documentation citations.** Run
      `make check-doc-citations CHANGE=capacity-resource-administration` and resolve every match.
      An unresolvable citation is a blocking defect under `AGENTS.md`'s
      cross-reference rule, and the target also rejects a citation whose
      target is a *tombstone*: a tombstoned file still exists on disk while
      its content is gone, so a plain existence test cannot fail on a
      rename-to-tombstone.
- [ ] 8.9 **End-to-end pipeline.** Confirm the end-to-end pipeline passes and
      record the evidence: the run, its result, and the scenarios that
      exercise this change's behaviour. Green unit and integration suites do
      not substitute -- this is the tier that catches a wire contract whose
      two sides disagree, a service that starts cleanly and cannot settle,
      and a configuration gap no in-process test can see. If the pipeline
      cannot run for a reason unrelated to this change, record that as an
      explicit blocker naming the cause and the change that owns it, and
      treat the validations it gates as unrun rather than passed.
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
| Host inventory is connection identity, not capacity authority | `openspec/specs/physical-provisioning/spec.md` — "Host inventory is connection identity"; `docs/development/ARCHITECTURE.md` authority-boundaries table |
| Legacy host capacity is derived into declarations rather than retained as a fallback tier | `openspec/specs/physical-provisioning/spec.md` — "Legacy host capacity is derived into declarations" |
| Capacity definitions import is digest-gated, after pool definitions and host seeding | `openspec/specs/physical-provisioning/spec.md` — "Capacity definitions are imported from a mounted document" |
| Why capacity declaration is separate from host inventory, and why splitting dimensions across both was rejected | `openspec/specs/site-capacity/architecture.md` |
