# Tasks

Paths are relative to the repository root. Production files and the tests that
prove them are named per task; `design.md` carries the rationale for every
decision these tasks implement.

## 1. Decide the wire disposition first

- [x] 1.1 Decide and record whether `LeaseResponse.vm_remove_job_id` and the
      lease PATCH body field are removed outright with a client-wheel version
      bump, or deprecated for a window first. Everything in section 3 depends
      on the answer, and making the edits before the decision is what turns a
      contract change into an accident. `release_job_id` is already published
      on both lease endpoints, so no consumer is blocked on the removal
      itself.
      **Decided: outright removal with a version bump.** Every API here is
      pre-1.0; the PATCH body refuses the retired field rather than ignoring it.
      Alternative and revisit trigger recorded in `design.md`.

      **Amended during design review.** The outright removal stands; the
      refusal does not. The PATCH body names the handle `release_job_id` and
      ignores `vm_remove_job_id` as it ignores any unknown field. `design.md`
      records both decisions ("The PATCH body names the handle
      `release_job_id`", "The retired name is not refused") and the refusal's
      revisit trigger.

## 2. Retire the ledger mirror

- [x] 2.1 Drop the `vm_remove_job_id` keyword aliases from
      `CapacityLedgerService.begin_releasing`, `update_lease_fields`,
      `update_lease_fields_in_session` and `update_reservation_state` in
      `kit/site/src/market_site/ledger.py`. Each collapses to
      `release_job_id or vm_remove_job_id`; every production caller passes
      `release_job_id`. (`attach_lease` takes no such argument.)
- [x] 2.2 In the same file, remove the mirror write from
      `_sync_release_job_fields` and the `vm_remove_job_id` key from
      `_reservation_payload`. Reading the payload back is how the three
      fallback readers in 2.3 see the field, so this is the change that makes
      them dead.
- [x] 2.3 Drop the `or reservation.get("vm_remove_job_id")` fallbacks in
      `provisioning/compute/src/compute_provisioning/lease_lifecycle.py` and
      `domains/bare_metal/provisioning/adapter/src/bare_metal_provisioning_adapter/controllers/bare_metal_leases_controller.py`.
      The VM adapter's reader is rewritten in 3.3.
- [x] 2.4 Drop the column from `kit/site/src/market_site/db.py`'s
      `CapacityReservation`. In
      `provisioning/compute/service/src/compute_provisioning_service/db/migrations.py`,
      add `_migrate_drop_reservation_release_mirror`, which calls
      `_drop_columns_via_table_rebuild(engine, "capacity_reservations",
      ["vm_remove_job_id"])` when the table exists, and append it to
      `MIGRATIONS` as `20260927_001_drop_reservation_release_mirror`. Its
      docstring states the present invariant (a reservation's release handle
      has one name) rather than the change that introduced it, and the
      operational constraint: the drop is irreversible by the chain, and a
      prior release rolled back past it needs the nullable column re-added
      before it starts (`design.md`, "The drop is an approved exception to
      expand/contract"). No migration is added to `domains/apicredits/service`
      or for bare metal (`design.md`, "One migration, in compute provisioning,
      under its own ID"). Add the new ID to the pinned set in
      `provisioning/compute/service/tests/unit/test_database.py`.

      **Done.** The reservation-state docstring in `kit/site/src/market_site/db.py`
      also read "teardown/vm_remove job in flight"; it now names the teardown by
      `release_job_id`, since the table is shared across domains.

- [x] 2.5 Reduce every test asserting the mirror to the canonical field rather
      than keeping both. A `vm_remove_job_id=` keyword becomes
      `release_job_id=`; an equality between the two becomes an assertion on
      `release_job_id` alone; an `is None` on the mirror becomes an assertion
      that the payload has no such key.
      - `kit/site/tests/unit/test_ledger.py`: the `begin_releasing` call and
        its mirror assertion.
      - `provisioning/compute/service/tests/unit/services/test_ledger_lease_lifecycle.py`:
        the four `begin_releasing(..., vm_remove_job_id=...)` calls and the
        three mirror assertions.
      - `provisioning/compute/service/tests/integration/test_leases_api.py`:
        the ledger-level mirror equality, the published-response mirror
        equality and the docstring sentence explaining it, the
        `begin_releasing` keyword, and the retry-release mirror assertion.
      - `provisioning/compute/service/tests/integration/test_bare_metal_leases_api.py`:
        the mirror `is None` assertion.

      Left untouched, because they read or build the retired `vm_leases`
      table's column of the same name:
      `test_legacy_backfill_teardown.py`,
      `test_fulfillment_convergence_after_legacy_backfill.py`,
      `test_legacy_vm_fulfillment_backfill.py`,
      `test_legacy_vm_lease_migration.py`, and `test_database.py`'s
      pre-migration schema. `domains/vms/storefront/tests/unit/test_compute_allocations.py`
      covers the storefront's own column and is also untouched.

      **Done, with one deviation.** A mirror `is None` assertion was deleted
      rather than rewritten as a key-absence check: 2.7 proves absence once at the
      ledger, and each site already asserts `release_job_id` beside the deleted line.
      The integration test publishing the handle asserts the retired key is
      absent (6.5). `test_database.py`'s hard-coded migration count became
      `len(MIGRATIONS)`.

- [x] 2.6 **Unit, migration.** Add
      `provisioning/compute/service/tests/integration/test_reservation_release_mirror_migration.py`
      (created under `unit/`, placed in `integration/` by 6.6),
      following `test_reservation_offering_mode_migration.py`: a current-schema
      database with the column added back and populated loses the column while
      every row keeps its `release_job_id` and other columns; a database
      without the column is unchanged; a rerun is a no-op; and `run_migrations`
      applies the drop to a database whose `schema_migrations` lacks the new ID.

      **Done.** Eight cases, including the rollback recovery (a column re-added
      after the drop is recorded survives a later migration run) and the two
      reconciliation cases 6.2 added.

- [x] 2.7 **Ledger.** In `kit/site/tests/integration/test_ledger.py` (moved
      from `tests/unit/` by 6.6), a VM-mode
      reservation moved to releasing carries `release_job_id` and a payload
      with no `vm_remove_job_id` key, and the model defines no such column.

      **Done.** Asserts the retired key on the payload and the model (6.5).

## 3. Retire the wire field

- [x] 3.1 In `domains/vms/provisioning/client/src/vm_provisioning_operator/models.py`,
      remove `LeaseResponse.vm_remove_job_id` and the comment describing it as
      a retained mirror; keep a comment on `release_job_id` stating what the
      handle is. Rename `LeaseUpdate.vm_remove_job_id` to `release_job_id`,
      describing it as the reservation's release handle (for a VM, the durable
      teardown `fulfillment_id`). Add no validator for the old name and leave
      the model's unknown-field policy unchanged (`design.md`, "The retired name
      is not refused").
- [x] 3.2 Check the e2e scenarios' lease assertions. **Answered during
      design:** `DealLease` in `e2e-tests/tests/e2e/roles/scenarios/vms/conftest.py`
      reads `release_job_id` and nothing else, so no scenario changes.
- [x] 3.3 In `domains/vms/provisioning/adapter/src/vm_provisioning_adapter/controllers/leases_controller.py`,
      `_lease_view` stops setting `vm_remove_job_id` and loses the
      wire-compatibility comment, and `update_lease` maps
      `body.release_job_id` onto `ExecutorLeaseUpdate.release_job_id`.
- [x] 3.4 Remove `ReleaseStartedEventRequest.vm_remove_job_id` from
      `domains/vms/storefront/src/market_storefront/models/capacity_admin_models.py`
      and the argument forwarding it from `release_started` in
      `domains/vms/storefront/src/market_storefront/controllers/admin_controller.py`.
      The value was discarded, so behaviour is unchanged (`design.md`, "The
      storefront event field is removed, not refused").
- [x] 3.5 **Integration.** In
      `provisioning/compute/service/tests/integration/test_leases_api.py`,
      through the operator client: a PATCH supplying `release_job_id` replaces
      the reservation's release handle and the returned lease publishes it; a
      releasing lease's response carries `release_job_id` and no
      `vm_remove_job_id` key.
- [x] 3.6 **Unit, operator client models.** Add
      `provisioning/compute/service/tests/unit/test_lease_models.py`:
      `LeaseUpdate` defines `release_job_id` and not `vm_remove_job_id`;
      a `LeaseUpdate` built from a body carrying only `vm_remove_job_id`
      leaves `release_job_id` unset, pinning the decision to ignore rather
      than refuse the retired name; and `LeaseResponse` defines no
      `vm_remove_job_id`. The client has no suite of its own; `design.md`,
      "Model contracts are proved at unit level", places these here.
- [x] 3.7 **Unit, storefront event model.** Add
      `domains/vms/storefront/tests/unit/test_capacity_admin_models.py`:
      `ReleaseStartedEventRequest` defines no `vm_remove_job_id`.

      **Done.** Asserts the field is undefined and that an event carrying it is
      accepted with the value dropped (6.5).

## 3b. Versions and locks

- [x] 3b.1 Bump each changed package's `version` in its `pyproject.toml`, per
      `design.md`'s table: `kit/site` 0.6.0,
      `domains/vms/provisioning/client` 0.5.0,
      `domains/vms/provisioning/adapter` 0.4.0, `provisioning/compute` 0.7.1,
      `provisioning/compute/service` 0.4.1,
      `domains/bare_metal/provisioning/adapter` 0.2.1, and
      `domains/vms/storefront` 0.7.1.
- [x] 3b.2 Raise two lower bounds: `arkhai-kit-site>=0.6.0` in
      `provisioning/compute/service/pyproject.toml`, and
      `arkhai-vms-provisioning-operator-client>=0.5.0` in
      `domains/vms/provisioning/adapter/pyproject.toml`.
- [x] 3b.3 Build the changed wheels into `.dist`, then regenerate every lock
      recording a bumped package: `kit/site`, `kit/fulfillment`,
      `provisioning/compute`, `provisioning/compute/service`,
      `domains/vms/provisioning/adapter`, `domains/vms/provisioning/client`,
      `domains/vms/storefront`, `domains/bare_metal/provisioning/adapter`,
      `domains/bare_metal/storefront`, `domains/apicredits/service`, and
      `e2e-tests`. Use each project's own `make reinit`, run from its
      directory so its relative `DIST_DIR` default applies;
      `domains/vms/provisioning/client` has no Makefile and is relocked with
      `uv lock --find-links ../../../../.dist --upgrade-package <n>` for each
      bumped package it records. Each lock diff must touch only the bumped
      packages' versions and specifiers, and no lock may gain an absolute
      path.

      **Done.** Nine locks relocked through `reinit` with version-only diffs. Two
      could not be relocked cleanly and carry hand-applied version edits instead:
      - `domains/bare_metal/storefront`: any relock, including with uv 0.11.17 as
        CI pins, re-serializes every dependency with platform markers; the minimal
        edit passes `uv lock --check` under both 0.11.7 and 0.11.17. Its `reinit`
        rewrites the lock again, so the minimal version was restored after its suite.
      - `domains/vms/storefront`: resolving needs `torch` from
        `download.pytorch.org`, unreachable from the implementation environment, so
        the edit is unverified by uv there; `check-internal-locks` passes.
      `arkhai-kit-hosted-settlement` must be built into `.dist` (`make -C kit
      dist-hosted-settlement`) before relocking consumers of it; `make dist-ci` omits
      it, and the resolver otherwise reaches the uninstallable 0.1.4 on PyPI. No lock
      contains an absolute path.

- [x] 3b.4 Move the exact internal pins in two Dockerfiles with the bumps:
      `domains/vms/storefront/Dockerfile` (`arkhai-vms-storefront==0.7.1`)
      and `provisioning/compute/service/Dockerfile`
      (`arkhai-compute-provisioning-service==0.4.1`,
      `arkhai-vms-provisioning-adapter==0.4.0`,
      `arkhai-bare-metal-provisioning-adapter==0.2.1`). No other Dockerfile
      pins a bumped package.
- [x] 3b.5 `make check-internal-locks` and `make check-reinit` pass.

      **Done.** Both pass, before and after the suites.

## 4. Validation

- [x] 4.1 Suites, each after its `reinit`: `make -C kit/site test`,
      `make -C kit/fulfillment test`, `make -C provisioning/compute test`,
      `make -C provisioning/compute/service test-unit test-integration`,
      `make -C domains/vms/provisioning/adapter test`,
      `make -C domains/bare_metal/provisioning/adapter test`,
      `make -C domains/vms/storefront test`,
      `make -C domains/bare_metal/storefront test`,
      `make -C domains/apicredits/service test`, and the e2e project's unit
      tier, `make -C e2e-tests test PYTEST_ARGS=tests/unit`.
      `provisioning/compute/service` and `kit/site` cover the ledger and the
      lease contract directly; `domains/apicredits/service` proves its fresh
      database builds from the changed model.

      **Done.** Passed after the code-review follow-ups: `kit/site` 256 (105 in
      the moved `integration/test_ledger.py`), `kit/fulfillment` 176,
      `provisioning/compute` 131, `provisioning/compute/service` unit 670 and
      integration 281, VM adapter 39, bare-metal adapter 2, VM storefront unit 1086
      (1 skipped) and integration 250, bare-metal storefront 174, API-credits service
      34, e2e unit 237. The VM storefront ran in a frozen environment without
      `torch`, which none of its sources or tests import.
      
      **Unrun or failing for reasons outside this change:**
      - VM storefront `tests/integration/test_alkahest.py::test_rust` and
        `::test_python`: the Alkahest test-chain runtime could not spawn its node
        process in the implementation environment.
      - e2e unit `test_hosted_public_boundary.py::test_buyer_deployment_mounts_separate_profile_state_and_credential`:
        asserts `compose.vms.yml` and `compose.apicredits.yml` mention
        `XDG_DATA_HOME`; neither file is touched by this change, so it fails on the
        checkpoint tree as well.

- [x] 4.2 The end-to-end run is closeout part 8 (5.8).
- [x] 4.3 Grep the repository for the identifier afterwards and confirm every
      remaining hit is the retired `vm_leases` column in historical
      migrations, the legacy backfill and their tests; the storefront's own
      `compute_allocations` column and its test; the new migration and its
      test (2.4, 2.6); tests asserting the name's absence or that it is ignored
      (2.7, 3.5, 3.6, 3.7); or documentation.

      **Done.** Every remaining hit is in an allowed category; the one
      permanent-document hit, in `ROADMAP.md`, was removed by 5.5.

## 5. Closeout

Per `openspec/README.md#plan-closeout-requirements`, in its order.

- [x] 5.1 **Comment hygiene.** Run `make check-comment-hygiene` and resolve
      every match. Then directly read the comments and docstrings this change
      touches: the new migration's docstring, the `release_job_id` comment in
      `vm_provisioning_operator/models.py`, `LeaseUpdate.release_job_id`'s
      description, and `_lease_view` in the VM adapter. None may narrate the
      retirement ("no longer", "formerly", "retained for compatibility").

      **Done.** The target passes, and no added production line narrates the
      retirement.

- [x] 5.2 **Import placement.** Review every import this change adds or
      touches, including those in the new migration test, and move any
      function-level import to module level where safe, verified against the
      real suite.

      **Done.** Every added import is module-level; none was local. Ruff
      reports no new findings in touched files (208 before and after, all
      pre-existing).

- [x] 5.3 **Documentation compliance.** Re-check the accepted decisions against
      `openspec/README.md`'s placement rules. The one-release-handle rule
      belongs in `site-capacity`, and the pre-1.0 minor-bump convention in
      `docs/development/RELEASING.md`. The wire disposition, the unrefused old
      name, the per-domain migration scope, the expand/contract exception and
      its recovery, and the version table are change history and stay in
      `design.md`.

      **Done.** Placement is as `design.md` records.

- [x] 5.4 **Narrative compression.** Reduce completed-task notes to final
      behaviour, validation evidence, deferred work, and permanent-documentation
      destinations.

      **Done.**

- [x] 5.5 **Roadmap currency.** In `docs/development/ROADMAP.md`'s Goal 1
      current-state text, remove the sentence recording
      `capacity_reservations.vm_remove_job_id` as the outstanding cleanup. No
      gap row in that goal names this change. Record the update in the
      promotion record.

      **Done.** Goal 1's current state now states the one-name rule in place of
      the outstanding-cleanup sentence.

- [x] 5.6 **Campaign index currency.** In `openspec/changes/README.md`, set
      this change's Goal 1 row to complete, and correct
      `fix-vm-fulfillment-capacity-boundary`'s row, which names this change as
      the owner of its one deferral. Record the update in the promotion record.

      **Done.** This change's row reads "complete; ready to archive", and
      `fix-vm-fulfillment-capacity-boundary`'s row says its deferral is complete
      here. The dependency edge stays until archive.

- [x] 5.7 **Documentation citations.** Run
      `make check-doc-citations CHANGE=retire-vm-remove-job-id` and resolve every match.
      An unresolvable citation is a blocking defect under `AGENTS.md`'s
      cross-reference rule, and the target also rejects a citation whose
      target is a *tombstone*: a tombstoned file still exists on disk while
      its content is gone, so a plain existence test cannot fail on a
      rename-to-tombstone.

      **Done.** Passes.

- [x] 5.8 **End-to-end pipeline.** Confirm the end-to-end pipeline passes and
      record the evidence: the run, its result, and the scenarios that
      exercise this change's behaviour — the VM lane's teardown stages
      (10a–11b), which read a releasing lease's handle end to end, and the
      bare-metal lane, whose provisioning database runs the new migration.
      Green unit and integration suites do not substitute -- this is the tier
      that catches a wire contract whose two sides disagree, a service that
      starts cleanly and cannot settle, and a configuration gap no in-process
      test can see. If the pipeline cannot run for a reason unrelated to this
      change, record that as an explicit blocker naming the cause and the
      change that owns it, and treat the validations it gates as unrun rather
      than passed.

      **Done.** GitHub Actions run 36390260302, at commit
      `994f6cbcb47fcb8b8f36ef495705102edd6a7f24` (the code-review follow-ups), built every
      bumped wheel (`arkhai-kit-site` 0.6.0, operator client 0.5.0, VM
      adapter 0.4.0, compute provisioning 0.7.1 and service 0.4.1, bare-metal
      adapter 0.2.1, VM storefront 0.7.1).
      - VM lane: 126 passed, 2 skipped. The skips are
        `test_multi_registry.py` stages 06b and 06c, multi-registry
        negotiation, which this change does not reach. Teardown stages 10a,
        10b, 11a and 11b passed in both `test_full_deal.py` and
        `test_full_deal_buyer_cli.py`; 10b reads the releasing lease's
        `release_job_id` as the teardown `fulfillment_id`.
      - Bare-metal lane: 8 passed.
      - Both lanes' provisioning services applied
        `20260927_001_drop_reservation_release_mirror` at startup, on fresh
        databases where it has no column to reconcile, and the API-credits
        service started from a database created by the changed model.
      - Neither lane's service logs contain a traceback, a 5xx response, or
        the retired field name.

- [x] 5.9 **Promotion.** After code review, add "A reservation's release
      handle has one name" and its five scenarios to
      `openspec/specs/site-capacity/spec.md`, with an evidence line naming 2.6,
      2.7, 3.5 and 3.6's tests, and confirm they match what landed. Add the
      pre-1.0 rule to `docs/development/RELEASING.md`'s "Versioning policy":
      before 1.0, an incompatible change takes a minor bump. Complete the
      design-promotion record below.

      **Done.** The requirement and its five scenarios are in
      `openspec/specs/site-capacity/spec.md`, taken verbatim from the delta, and
      the central evidence list names the ledger, VM and bare-metal lease,
      model, migration and end-to-end tests. Each scenario was checked against
      the landed code and the test that proves it; the bare-metal lease read
      is proved at its route by 7.1. `docs/development/RELEASING.md`'s versioning
      policy states the pre-1.0 rule; it covers incompatible changes only and
      leaves the other bump rules as they were. Both files were verified
      changed.

## 6. Code review follow-ups

Findings from the implementation review, each accepted as recorded here.

- [x] 6.1 **Service admits the old VM adapter.** Raise
      `arkhai-vms-provisioning-adapter` to `>=0.4.0` in both the `adapters`
      extra and the dev group of `provisioning/compute/service/pyproject.toml`,
      and relock. Adapter 0.3.0 reads `LeaseUpdate.vm_remove_job_id` and
      accepts client 0.5.0, which does not define it.

      **Done.** The service lock changed in exactly those two specifiers. The
      bare-metal adapter's bound stays (`design.md`).
- [x] 6.2 **Reconcile before the drop.** `release_job_id` was added by
      `20260707_001` without a backfill, so the mirror can hold a row's only
      handle. The migration copies a mirror-only value into `release_job_id`,
      and raises `SchemaDriftError` naming the reservations, changing nothing,
      when the two columns disagree (`design.md`). Two cases added to the
      migration test.

      **Done.** The divergent case also proves the guard runs before the
      backfill.
- [x] 6.3 **Name the helper for what it does.** `_sync_release_job_fields` in
      `kit/site/src/market_site/ledger.py` sets one field and is renamed
      `_set_release_job_id`.
- [x] 6.4 **Spec follows the reconciliation.** The delta's upgrade scenario
      states the mirror-only backfill, and a fifth scenario states the refusal
      on disagreement.
- [x] 6.5 **Assert the requirement, not a broader rule.** The ledger, lease
      integration, and storefront event tests asserted that no other `*_job_id`
      field exists, which would forbid unrelated future job identifiers. Each
      now asserts the retired key specifically; the storefront event test also
      proves the retired name is accepted and dropped, as `LeaseUpdate`'s does.
- [x] 6.6 **Test tiers.** Tests exercising a real database are integration
      tests (`docs/development/TESTING.md`). `kit/site/tests/unit/test_ledger.py`
      moves whole to `kit/site/tests/integration/test_ledger.py`, and the
      migration test lives only in the compute provisioning service's
      `tests/integration` (7.2). `openspec/specs/site-capacity/spec.md`'s
      evidence citations follow the ledger file.

      Recorded, not moved: `test_ledger_lease_lifecycle.py` and
      `test_database.py`, also touched here, run in-memory SQLite under the
      service's `tests/unit`. `TESTING.md`'s move-when-touched rule is stated for
      library packages, and the service keeps many database-backed tests there;
      re-tiering them is a separate decision.

      Not covered as a client contract: `test_bare_metal_leases_api.py` drives
      the real application through its own HTTP helper rather than a public
      client, so it proves the application path, not a client contract. This is
      pre-existing and unchanged here.

## 7. Promotion review follow-ups

- [x] 7.1 **Bare-metal handle proved at its route.** The promoted requirement
      says a lease read through either adapter publishes the handle as
      `release_job_id`. `test_generic_market_lease_terminate_dispatches_bare_metal_reclaim`
      in `provisioning/compute/service/tests/integration/test_bare_metal_leases_api.py`
      now reads the releasing bare-metal lease back and asserts its populated
      `release_job_id` and the absence of the retired key; the permanent
      evidence line cites it.
- [x] 7.2 **Migration test in one tier only.** The copy under
      `provisioning/compute/service/tests/unit/` is removed, leaving the
      eight-case test under `tests/integration`. Service suites rerun: unit 670,
      integration 281, with no migration test collected from `unit/`.
- [x] 7.3 **Current-state spec wording.** The upgrade scenario says the mirror
      column is removed without losing any reservation's release handle or
      other data, in place of its provenance in an earlier table rebuild, in
      both the delta and `openspec/specs/site-capacity/spec.md`.
- [x] 7.4 **Record accuracy.** 5.6's campaign-status note, 5.8's commit (the
      runner image's build commit had been recorded in place of the
      repository's), and 6.6's wording now describe the final tree.
- [x] 7.5 **Every decision classified.** The promotion record names each
      change-history decision as not promoted, including the storefront event
      field.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| A reservation's release handle has one name, `release_job_id`, with no domain-prefixed mirror; every lease contract publishes and accepts it under that name; an upgrade keeps a mirror-only handle and stops on disagreement | `openspec/specs/site-capacity/spec.md` — "A reservation's release handle has one name" (promoted, 5.9) |
| Outright removal rather than a deprecation window, and why | Change history in this change's `design.md`; not promoted |
| Before 1.0, an incompatible package change takes a minor bump | `docs/development/RELEASING.md` — "Versioning policy" (promoted, 5.9) |
| The column drop is an approved exception to expand/contract, with its rollback recovery | Change history in this change's `design.md`; not promoted, because it is a one-release exception rather than a rule |
| The PATCH body renames the field; the old name is ignored rather than refused until a major release sets a compatibility policy | Change history in this change's `design.md`; not promoted. The name `release_job_id` on a lease update is promoted as part of the site-capacity requirement |
| One compute-provisioning migration, reconciling mirror-only and divergent rows before the drop; none for bare-metal or API-credits databases | Change history in this change's `design.md`; not promoted. The upgrade's observable outcome is promoted as the site-capacity requirement's upgrade scenarios |
| Version bumps and raised lower bounds | Each package's `pyproject.toml`; rationale is change history in this change's `design.md`, not promoted |
| `ReleaseStartedEventRequest.vm_remove_job_id` is removed, and stale input remains accepted and discarded | Change history in this change's `design.md`; not promoted, because observable event behaviour is unchanged |
| Model contracts are proved at unit level; real-database tests are integration tests | Change history in this change's `design.md`; not promoted, because it applies rules `docs/development/TESTING.md` already states |
| Roadmap currency | `docs/development/ROADMAP.md` — Goal 1 current state (5.5) |
| Campaign index currency | `openspec/changes/README.md` — Goal 1 table (5.6) |
