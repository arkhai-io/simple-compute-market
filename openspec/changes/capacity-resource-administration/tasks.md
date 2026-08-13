# Implementation Tasks

Sections are sized to land independently in roughly a day each and are ordered so the
authority is populated before the fallback that currently stands in for it is
removed. Sections 1–3 are additive and safe to deploy on their own; Section 4 is the
cutover.

## 1. Capacity declaration carrier and administration surface

- [ ] 1.1 Confirm by inspection, before writing anything, that the findings in
      `design.md`'s "Context" still hold: the startup step list, the absence of any
      capacity-resource seeding, `_project_host`'s fallback shape, and `Host`'s
      column set. Record any drift in `design.md` rather than working around it.
- [ ] 1.2 Define the capacity-definitions document shape (a declaration per Physical
      Resource carrying `pool_id`, capacity dimensions, and categorical attributes),
      mirroring the pool-definitions document's structure and validation posture.
- [ ] 1.3 Promote `PUT /api/v1/capacity/resources/{resource_id}` from a compatibility
      endpoint to a documented operator administration surface: correct the route
      docstring, which currently describes it as a compatibility path for domains
      registering logical capacity, and state the multidimensional contract.
- [ ] 1.4 Verify `ResourceRegisterRequest` already expresses everything a declaration
      needs and add nothing that is not required; `capacity` and `attributes` are
      already free-form maps. If a client method is added, add it to both the async
      and sync variants in the same change and cover it with the parity contract test
      `TESTING.md` requires.
- [ ] 1.5 Focused tests: declaration accepted with several dimensions, declaration
      accepted with a single dimension, omitted dimensions treated as undeclared.

## 2. Derivation from legacy host capacity

- [ ] 2.1 Implement the host-to-declaration derivation as one reusable unit consumed
      by both the migration (Section 3) and the startup step (Section 4) — one
      implementation, two callers, not two code paths that can drift.
- [ ] 2.2 Derive only for hosts carrying legacy capacity data with no existing
      declaration. Never overwrite, never merge. Report the derived set at INFO,
      matching how both existing seeding steps report theirs.
- [ ] 2.3 Carry `gpu_model` into the declaration's attributes rather than dropping
      it — categorical, matched by equality, so it belongs in attributes and not in
      the capacity map.
- [ ] 2.4 Focused tests: derivation for a host with legacy data; no derivation when a
      declaration exists; operator declaration retained unchanged when it disagrees
      with the legacy value; idempotent across repeated runs.

## 3. Ordered migration

- [ ] 3.1 Add the migration that runs the Section 2 derivation, ordered in the
      provisioning chain and applied before the application serves requests per
      `deployment-state`'s service-owned migration history requirement.
- [ ] 3.2 Keep the migration to the derivation only — no column drop, no host-row
      mutation. Freeze-then-redirect, matching the POOLS campaign's additive-only
      convention.
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
      capacity fallback.
- [ ] 4.2 Fix the divergence in the same edit: `attributes` currently derives from the
      host unconditionally while `capacity` prefers the resource, so a declaration
      disagreeing with a host row projects contradictory values in one row. Both must
      come from one record.
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

## 4b. Executor-correlated pool membership and one declaration per executor

Added 2026-08-11 from an e2e capacity trace; see `design.md`'s "Pool membership is
executor-derived, and one-per-executor is enforced on write". Sequenced immediately after
the cutover because both defects are about the projection and admission agreeing on one
record, which is what Section 4 makes true for capacity and attributes.

- [ ] 4b.1 Add an injected executor-correlation provider to `make_capacity_router` in
      `kit/site/src/market_site/router.py`, alongside the existing
      `get_resource_inventory`/`get_pool_directory` providers. It answers "which pool does
      the executor backing this declaration belong to", returning `None` for a declaration
      that names no executor. `kit/site` gains no knowledge of hosts.
- [ ] 4b.2 Supply it from `provisioning/compute/service/src/compute_provisioning_service/main.py`
      beside the two providers already defined there, resolving the `Host` row by the
      declaration's executor attribute and falling back to the declaration id.
- [ ] 4b.3 On registration, take the executor's pool when one is resolved. Refuse with a
      409 when the declaration names a different pool rather than silently overriding
      either value — the error must name both pools and say which to change.
- [ ] 4b.4 Reject `attributes["pool_id"]` outright, naming the field to use instead. Do not
      hoist it into `pool_id`: hoisting leaves two spellings working forever, which is the
      ambiguity this task exists to remove.
- [ ] 4b.5 Compose the executor-identity attribute name into `CapacityLedgerService` the
      way `unit_claim_keys` already is, and route `ledger.py`'s two existing direct reads
      of `attributes["vm_host"]` (`_executor_ref_for_resource` and the executor-kind
      branch in `reserve`) through it. This removes a pre-existing domain leak rather than
      adding a third instance of it.
- [ ] 4b.6 Enforce one declaration per executor at registration, inside
      `register_resource`'s existing transaction: refuse when another declaration already
      claims the same executor identity. Raise the ledger's own conflict error so the
      route maps it to a 409.
- [ ] 4b.7 Degrade `load_capacity_resource_inventory`'s duplicate-correlation `ValueError`
      to a logged warning that omits the ambiguous correlation. State locally why: a read
      path that raises makes one bad row indistinguishable from an unreachable site and
      takes every pool at that site down with it, and 4b.6 is what now prevents the row
      from being written.
- [ ] 4b.8 Confirm `resource_feasibility_view`'s `pool_id or resource_id` fallback is left
      intact and document why at the call site — a declaration with no pool is its own
      single-member pool, which the structural listing-mode default depends on.
- [ ] 4b.9 Focused tests: declaration inherits its executor's pool; conflicting declared
      pool refused; `attributes["pool_id"]` refused; second declaration on one executor
      refused; declaration with no executor keeps its declared pool (API-credits shape);
      a pre-existing duplicate correlation warns and still serves a projection for every
      other pool.
- [ ] 4b.10 Integration test through the real router: register an executor into a pool,
      declare capacity for it, and assert the resource-pool projection, the capacity-bucket
      projection, and a pool-scoped `reserve` all report the same pool identity. This is
      the assertion that would have caught the three-identity divergence.

## 5. Startup import

- [ ] 5.1 Add `capacity_definitions_path` to `settings.toml` and its
      `resolved_capacity_definitions_path` property in `config.py`, mirroring
      `pool_definitions_path` exactly, including empty-string-means-unset.
- [ ] 5.2 Add the import step: diff-based, idempotent, runs on every startup, raises
      on a configured path that does not exist. Document at the step why it is
      unconditional rather than skip-if-empty, since the adjacent host seeding uses
      the opposite idiom and a reader will ask.
- [ ] 5.3 Register the step in `startup_steps()` **after** `import-pool-definitions`,
      since a declaration may reference a pool.
- [ ] 5.4 Run the Section 2 derivation as part of startup for hosts with legacy data
      and no declaration, so an INI-only deployment retains published capacity once
      the fallback is gone.
- [ ] 5.5 Integration tests: definitions applied on a restart after an edit;
      configured-but-missing path fails startup; unconfigured path proceeds;
      declaration referencing a pool resolves.

## 6. Operator surface and deployment wiring

- [ ] 6.1 Add Helm and compose wiring for `capacity_definitions_path`, following the
      mounted-file convention in `DEPLOYMENT_AND_CONFIG.md` — configuration travels
      through mounted files, never individual pod env entries.
- [ ] 6.2 Add CLI coverage for declaring and inspecting capacity, so registration is a
      documented workflow rather than a raw HTTP call.
- [ ] 6.3 Update `docs/seller-quickstart.md` and the configuration reference with the
      capacity declaration workflow, including that a declaration wins over any
      derivable legacy host value — the intuition may run the other way.
- [ ] 6.4 State the INI's `gpus=`/`gpu_model=` disposition in operator documentation:
      still parsed, still written to frozen host columns, no longer reaching the
      projection except through derivation, and slated for removal with the later
      column drop.

## 7. Validation

- [ ] 7.1 Run the provisioning unit and integration suites, `kit/site`'s suites, and
      the affected VM e2e scenarios. Disclose any suite not run.
- [ ] 7.2 Run `openspec validate --all --strict` and confirm no regression against the
      baseline current at implementation time.
- [ ] 7.3 Verify package and import boundaries are unchanged: `kit/site` must not
      acquire a provisioning dependency, and generic compute service modules must not
      import concrete VM or bare-metal models, per `physical-provisioning`'s
      dependency-isolation requirements.

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
      and gap mapping in `docs/development/ROADMAP.md`. The conditional this task
      originally carried is resolved: `add-development-roadmap` landed and was archived
      2026-08-13, so the roadmap exists and the step is owed unconditionally.
- [ ] 8.6 **Promotion.** Complete the design-promotion record below.
- [ ] 8.7 **Section 4b hygiene.** Read the docstrings 4b touches directly:
      `_match_payload`'s pool/member comment, `load_capacity_resource_inventory`'s
      correlation docstring, and `CapacityLedgerService.__init__`'s parameter block all
      describe the arrangement 4b replaces. A stale docstring asserting an authority the
      code no longer holds is a defect in this change, not a wording preference.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Capacity resources are the authoritative declaration of sellable capacity across every dimension | `openspec/specs/site-capacity/spec.md` — "Operator-administered capacity declarations" |
| Projected attributes must not contradict projected capacity | `openspec/specs/site-capacity/spec.md` — "Projected inventory is internally consistent" |
| Host inventory is executor identity, not capacity authority | `openspec/specs/physical-provisioning/spec.md` — "Host inventory is executor identity"; `docs/development/ARCHITECTURE.md` authority-boundaries table |
| Legacy host capacity is derived into declarations rather than retained as a fallback tier | `openspec/specs/physical-provisioning/spec.md` — "Legacy host capacity is derived into declarations" |
| Capacity definitions import is unconditional-but-idempotent, after pool definitions | `openspec/specs/physical-provisioning/spec.md` — "Capacity definitions import at startup" |
| Why capacity declaration is separate from executor inventory, and why splitting dimensions across both was rejected | `openspec/specs/site-capacity/architecture.md` |
| A declaration correlated to an executor takes that executor's pool membership; a conflicting declared pool is refused | `openspec/specs/site-capacity/spec.md` — "Pool membership follows the executor" |
| One declaration per executor, enforced when the declaration is written rather than when inventory is read | `openspec/specs/site-capacity/spec.md` — "One capacity declaration per executor" |
| Why the invariant is enforced on write, and why a projection read path must not raise on one bad row | `openspec/specs/site-capacity/architecture.md` |
