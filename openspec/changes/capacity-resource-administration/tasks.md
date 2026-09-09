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

## 4b. Composition-supplied mirror dimension

`design.md`'s "The primary-dimension fallback writes a GPU name into every domain"
accepted this fix; it previously had no task, so an implementer would have had to
invent the semantics while coding. Retiring the scalar mirror entirely remains
deferred — this is the smaller half that the domain-neutral declaration contract
depends on.

- [ ] 4b.1 Make the dimension the legacy scalar mirror tracks composition-supplied,
      the way `unit_claim_keys` already is, rather than the module-level
      `PRIMARY_DIMENSION = "gpu_count"` in `kit/site/ledger.py`.
- [ ] 4b.2 Stop writing a mirror dimension into a caller's explicit capacity map.
      `register_resource` currently injects it when absent and then reads it back for
      `mirrored_units`; both sites need the supplied name and the explicit-declaration
      case.
- [ ] 4b.3 Define `total_units`' behaviour when an explicit capacity map contains no
      mirror dimension, and record the decision. The existing consistency check
      compares them when both are present; what it means when only one is is a
      decision, not a default.
- [ ] 4b.4 Wire the VM composition to its existing mirror dimension so no behaviour
      changes there.
- [ ] 4b.5 Wire the API-credit composition to its own dimension, matching how it
      already overrides `unit_claim_keys` to `("units",)`.
- [ ] 4b.6 Confirm legacy rows whose scalar mirror was written under the old constant
      still read correctly, and record how a row written before this change is
      interpreted after it.
- [ ] 4b.7 **Unit.** An explicit multidimensional declaration with no compute
      dimension is stored as declared, with no manufactured GPU dimension.
- [ ] 4b.8 **Unit.** The VM composition's legacy scalar fallback maps to its
      configured mirror dimension; the API-credit composition's does not become
      `gpu_count`.
- [ ] 4b.9 **Integration.** One typed-client case registering a resource whose
      declaration names no compute dimension.

## 4c. Pool reassignment drain rule

- [ ] 4c.1 Refuse reassignment of a capacity resource that holds a live capacity
      obligation — hold, reservation, assignment, or workload — resolved through its
      pool. `register_resource` currently writes `bucket.pool_id = effective_pool_id`
      unconditionally on update, and `backing_pool_id_in_session` resolves a
      reservation's pool through the resource's *current* `pool_id`, so reassignment
      rewrites the authority under an existing reservation.
- [ ] 4c.2 Leave the resource in its current pool when a reassignment is refused. A
      partial move is worse than a refused one.
- [ ] 4c.3 **Integration, real DB transaction.** A resource holding a live reservation
      cannot cross a pool boundary; the same resource can once its obligations are
      drained. Cover both in one test so the refusal is not mistaken for a resource
      that could never move.
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
      since a declaration may reference a pool.
- [ ] 5.4 Run the Section 2 derivation as part of startup for hosts with legacy data
      and no declaration, so an INI-only deployment retains published capacity once
      the fallback is gone.
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
      and gap mapping in `docs/development/ROADMAP.md`. If `add-development-roadmap`
      has not landed when this change completes, record that disposition explicitly
      rather than skipping the step.
- [ ] 8.6 **Promotion.** Complete the design-promotion record below.
- [ ] 8.7 **Campaign index currency** (part seven, added when
      `openspec/README.md#plan-closeout-requirements` was extended from six parts to seven).
      Appended rather than folded into an existing task, per `AGENTS.md`'s rule to amend
      rather than replace implementation history. Update this change's row, and its
      campaign's dependency graph, in `openspec/changes/README.md` to match its state at
      completion, or record the disposition here if its status and campaign placement are
      both unchanged.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Capacity resources are authoritative for the declared sellable shape and quantity across every dimension; admission authority is resolved separately | `openspec/specs/site-capacity/spec.md` — "Operator-administered capacity declarations" |
| A capacity declaration names no mandatory dimension; the legacy mirror's dimension is composition-supplied | `openspec/specs/site-capacity/spec.md` |
| A capacity resource does not move pools under live capacity obligations | `openspec/specs/site-capacity/spec.md` |
| Capacity definitions reconcile on a document digest, not on process start | `openspec/specs/physical-provisioning/spec.md` |
| Projected attributes must not contradict projected capacity | `openspec/specs/site-capacity/spec.md` — "Projected inventory is internally consistent" |
| Host inventory is executor identity, not capacity authority | `openspec/specs/physical-provisioning/spec.md` — "Host inventory is executor identity"; `docs/development/ARCHITECTURE.md` authority-boundaries table |
| Legacy host capacity is derived into declarations rather than retained as a fallback tier | `openspec/specs/physical-provisioning/spec.md` — "Legacy host capacity is derived into declarations" |
| Capacity definitions import is digest-gated, after pool definitions | `openspec/specs/physical-provisioning/spec.md` — "Capacity definitions import at startup" |
| Why capacity declaration is separate from executor inventory, and why splitting dimensions across both was rejected | `openspec/specs/site-capacity/architecture.md` |
