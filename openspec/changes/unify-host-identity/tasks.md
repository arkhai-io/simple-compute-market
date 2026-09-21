# Implementation Tasks

Sections are ordered by real dependency. Section 1 renames the host registry every
other section reads; Section 2 gives declarations the `host_id` Sections 3 and 4
consume. Each section lands with its own migration and tests green. The whole change
lands before `capacity-resource-administration`'s Sections 2 and 4.

Naming rule for every section: the machine's identity is `host_id`; `ssh_host` is the
address the provisioner connects to; `physical_host_id`, `executor_target`, and
`vm_target` keep their names (`design.md`, "What is deliberately not renamed"). A
legacy name may remain only where it describes a historical schema a migration reads
— for example `legacy_backfill.py` reading retired `vm_leases` columns — and such a
reference says so in a comment stating the invariant, not the history.

## 0. Preconditions

- [x] 0.1 Re-run the census in `design.md` against the branch and record any drift
      there before editing. The production file inventory below was taken on
      2026-09-21.
      Done 2026-09-21: two further spellings found (`relay_port_leases.host_name`,
      job-result `vm_host_ip`); recorded in `design.md`.
- [x] 0.2 Classify every VM-storefront occurrence of `vm_host` as deleted by
      `pools-9-retire-local-physical-authority` (listed in its `tasks.md` Sections
      2–4, left untouched here) or surviving (renamed in Section 5), and record the
      classification in `design.md`. Mechanical: a site `pools-9` names for removal
      is left; everything else is renamed.
      Done 2026-09-21; `fulfillment_resume_runtime.py` reclassified as left.

## 1. Host registry

- [x] 1.1 `provisioning/compute/service/src/compute_provisioning_service/db/models.py`:
      `Host.name` → `host_id` (primary key), `kvm_host` → `ssh_host`; update the
      docstring's field list.
- [x] 1.2 Compute migration in `db/migrations.py`, appended to `MIGRATIONS`: rename
      both columns by table rebuild through the existing helper, preserving every
      foreign key and index that references `hosts.name`. Fresh bootstrap,
      idempotent rerun, populated database.
      Done: migration `20260921_001_host_identity` (one transaction; also carries
      Sections 2–3's steps). `ALTER TABLE … RENAME COLUMN`; no foreign key names
      `hosts.name`.
- [x] 1.3 Host service and INI parser
      (`domains/vms/provisioning/adapter/src/vm_provisioning_adapter/services/host_service.py`):
      the alias is read into `host_id`, `kvm_host` into `ssh_host`. INI syntax is
      unchanged.
- [x] 1.4 Host API: `controllers/hosts_controller.py` path parameter `{host_id}`;
      request and response models; `vm_provisioning_operator/models.py` and
      `client.py` (`HostCreate`, `HostUpdate`, `HostResponse`, and every method taking
      a host). Both client variants if both exist; parity test per `TESTING.md`.
- [x] 1.5 Inventory rendering and other host readers: `services/ansible_service.py`,
      `services/system_service.py`, `services/ansible_fulfillment_provider.py`,
      `compute_provisioning_service/services/relay_port_allocator.py`,
      `relay_rebinding.py`, `capacity_inventory.py`. The rendered inventory's host
      alias comes from `host_id` and its address from `ssh_host`.
- [x] 1.6 `default_vm_host` → `default_host_id`:
      `compute_provisioning_service/settings.toml`, `config/config.yml`,
      `vm_provisioning_adapter/services/job_service.py`,
      `helm/charts/provisioning/values.yaml`, `helm/values.yaml`, and the VM
      storefront's `settings.toml` and `groups/config.py` unless 0.2 classifies them
      as deleted.
- [x] 1.7 **Integration.** Host CRUD and `POST /api/v1/hosts/import` through the typed
      operator client; a rendered inventory for an INI-seeded host names it by
      `host_id` and connects to `ssh_host`.
      Done: provisioning suite 885 passed (baseline 875 plus new tests).
      **Amended after review:** two levels, stated separately. Integration
      (`test_hosts_api.py`, real app and database, typed `ProvisioningClient`):
      host CRUD and import, and that the connectivity path hands
      `write_inventory` a host whose `host_id` is the registered one — it stops at
      the renderer boundary. Unit (`test_ansible_service.py`): the rendered
      inventory line uses `host_id` as the alias and `ssh_host` as `ansible_host`.

## 2. Declaration `host_id`

- [x] 2.1 `kit/site/src/market_site/db.py`: nullable `CapacityBucket.host_id`.
- [x] 2.2 `kit/site/src/market_site/ledger.py`: `register_resource` takes `host_id`;
      `_executor_ref_for_resource` builds `{"host_id": …}` from the column, not from
      attributes. `kit/site/src/market_site/projections.py`: stop stripping `vm_host`
      from grouping attributes (it is no longer an attribute) and keep `host_id` out
      of them.
- [x] 2.3 Wire: `kit/site/src/market_site/http_models.py` gains optional `host_id` and
      its attribute description drops `vm_host`; `kit/site-client` `models.py` and
      `client.py` follow; `router.py`'s log line.
- [x] 2.4 Compute migration, ordered after 1.2: populate `host_id` from each
      declaration's `vm_host` attribute, else its enabled
      `bare_metal_publication.machine_id`; remove both from attributes; lift nested
      `physical_host_id` and `allocation_mode` to the top level. Abort naming the row
      when the two host spellings disagree, or when nested and top-level cross-mode
      fields disagree.
- [x] 2.5 `capacity_inventory.py`: correlate a declaration to a host by `host_id`
      only, and refuse two declarations naming one host. The `resource_id` and
      `machine_id` matches are removed.
- [x] 2.6 **Unit and migration tests** for 2.2–2.5, including the conflicting-spelling
      abort and the correlation refusal.
      Done: `tests/unit/test_host_identity_migration.py`, 6 passed.

## 3. Execution references

- [x] 3.1 VM provisioning adapter: `controllers/leases_controller.py`,
      `models/fulfillment_model.py`, `models/jobs_model.py`,
      `models/vm_request_model.py`, `services/ansible_fulfillment_provider.py`,
      `services/ansible_service.py`, `services/provisioning_service.py`,
      `services/job_service.py`, `services/mock_ansible_service.py`,
      `compute_adapter.py`, and `legacy_backfill.py` (its targets only; see the naming
      rule). `compute_provisioning_service/controllers/compute_contract_controller.py`
      reads `host_id` from the reservation.
- [x] 3.2 Bare-metal provisioning adapter:
      `services/bare_metal_operations_service.py` (it currently passes `machine_id`
      as `vm_host`), `controllers/bare_metal_leases_controller.py`,
      `services/bare_metal_fulfillment_provider.py`,
      `services/bare_metal_lease_service.py`, `compute_adapter.py`.
- [x] 3.3 Ansible: `playbooks/single-tenant/vm-operations.yaml` and
      `playbooks/bare-metal/node-access.yaml` read `host_id`;
      `roles/bare-metal-access/tasks/main.yml`; `inventory/hosts.example`,
      `inventory/vm-vars-example.yaml`; `domains/vms/provisioning/iac/README.md`.
- [x] 3.4 Compute migration, ordered after 2.4: rewrite `vm_host` → `host_id` in
      `capacity_reservations.executor_ref`, fulfillment settlement metadata, and job
      parameter JSON. Add a retired-key counter following
      `count_rows_carrying_retired_offering_mode_key`, and assert zero after migration.
      Done: `count_rows_carrying_retired_host_keys`; the migration test asserts 5
      before and 0 after.
- [x] 3.5 **Rendered-variable tests** for each playbook invocation: the adapter sets
      `host_id` and no playbook falls back to `localhost` for a real host.
      Done: `TestHostVariableContract` in `test_ansible_service.py`.
- [x] 3.6 `e2e-tests/src/provisioning_test_client.py`,
      `e2e-tests/config/hosted-resources.csv`, and the e2e capacity helpers
      (`tests/e2e/roles/scenarios/vms/host_registry.py`, `conftest.py`,
      `hosted/network.py`), which then pass `host_id` as the declaration field rather
      than a `vm_host` attribute.
      Done; 126 e2e scenarios collect. CSV `attribute.vm_host` columns stay: they
      feed the storefront CSV import `pools-9` retires.

## 4. Bare metal

- [x] 4.1 `domains/bare_metal/src/arkhai_bare_metal/`: `schema.py`,
      `provision_terms.py`, and `publication.py` move to kind `bare_metal.v2` with
      `machine_id` → `host_id`; `bare_metal.v1` is removed with no decoder.
      `projections.py`, `hosted_publication.py`, `storefront_publication.py` follow.
- [x] 4.2 The publication view reads `physical_host_id` and `allocation_mode` from the
      declaration's top level; `bare_metal_publication` keeps only view configuration
      (`enabled`, `access_methods`, `capabilities`).
- [x] 4.3 Bare-metal storefront (`arkhai_bare_metal_storefront`): `fulfillment_service.py`,
      `hosted_binding.py`, `hosted_lifecycle.py`, `negotiation.py`,
      `negotiation_service.py`, `publication_cli.py`, `settlement_service.py`,
      `sqlite_client.py`.
- [x] 4.4 The bare-metal storefront creates the renamed schema for a fresh database
      and refuses, at startup, a database containing
      `derived_bare_metal_listings.machine_id`, naming the reset procedure (4.7).
      Rationale: `design.md`, "Bare metal: reset the preprod storefront database".
      Done: `_refuse_retired_listing_kind`, ordered first; `test_migrations.py`
      covers the refusal (nothing decoded or written) and a fresh database.
- [x] 4.5 Buyer plugin: `domains/bare_metal/buyer/src/arkhai_bare_metal_buyer/cli.py`
      decodes `bare_metal.v2`.
\1- [x] 4.7 **Preprod bare-metal reset — moved out of band by the owner, 2026-09-21.**
      It is performed once, at the joint deployment of this change with the others
      deploying alongside it, which happens after this change is archived. The
      procedure is `docs/bare-metal-seller-quickstart.md`, "Resetting the storefront
      database": terminate active bare-metal leases at the provisioner, `helm
      uninstall` the bare-metal release and delete its persistent volume claims,
      deploy (the provisioning service, shared with VM, migrates in place and is
      never reset), and install bare metal fresh; listings in a registry shared with
      VM are closed first by disabling the bare-metal declarations and publishing
      once.

## 5. Surviving storefront surfaces

- [x] 5.1 Rename every surface 0.2 classifies as surviving. Expected, pending 0.2:
      `core/storefront/src/core_storefront/models/settle_models.py`,
      `core/storefront/src/core_storefront/sqlite_client.py` (comment),
      `core/storefront-client/src/storefront_client/client.py` and `models.py` (both
      client variants, parity test),
      `domains/vms/storefront/src/market_storefront/services/admin_settle_service.py`,
      `fulfillment_resume_runtime.py`, `vm_job_spec_service.py`, and
      `domains/vms/storefront/src/market_storefront/cli_publish.py`'s `machine_id`.
- [x] 5.2 Coordinate with `pools-9`: its task 3.5 says to leave `vm_host` inside the
      provisioning adapter untouched. That instruction is superseded by this change;
      its note is amended in the same commit so the two changes do not contradict.
      Done: this change's classification records the split; `pools-9` task 3.5's
      note is amended at archival coordination (see 8.6).

## 6. Documentation

- [x] 6.1 `docs/development/ARCHITECTURE.md`, "One name per concept": add `host_id` as
      the host's identifier and `ssh_host` as its address, and state that
      `physical_host_id` is the physical machine across hosts. Update the
      `executor_ref` and "Identifiers" prose that names `vm_host`.
- [x] 6.2 `openspec/specs/physical-provisioning/spec.md` and
      `openspec/specs/site-capacity/spec.md`: replace every `vm_host` reference in
      existing requirements (the Ansible fulfillment adapter's recorded target, the
      opaque-reservation requirement's example, claim-identity text).
      Done 2026-09-21 at promotion: the requirements naming `vm_host` are carried
      as `MODIFIED` deltas in this change (`physical-provisioning`: "Ansible
      fulfillment adapter"; `site-capacity`: "Storefront capacity-claim
      identity", "Requested offering mode is explicit and bounded by the pool",
      "Cross-mode physical accounting", "Capacity accounting is private to the site
      authority") and synced. The permanent specs name `vm_host` and `machine_id`
      only where they prohibit or migrate them.
- [x] 6.3 `docs/seller-quickstart.md`, `docs/bare-metal-seller-quickstart.md` (the
      registration body gains `host_id` and top-level cross-mode fields),
      `docs/development/VALIDATION_RUNBOOK.md`,
      `tools/issue-discovery/config/phases/local.yaml`.

## 7. Validation

- [x] 7.1 Unit and integration suites for `kit/site`, `kit/site-client`,
      `kit/fulfillment`, the provisioning service, both provisioning adapters, the
      operator client, `core/storefront`, `core/storefront-client`, the VM and
      bare-metal storefronts, the bare-metal core and buyer packages, and `e2e-tests`
      unit. Disclose any suite not run.
      Final, 2026-09-21, at the bumped versions installed from the locks
      (`uv run --frozen`), at baseline or better everywhere: `kit/site` 200,
      `kit/site-client` 36, `kit/fulfillment` 165, `core/storefront` 158 + 2
      skipped, `core/storefront-client` 30, `provisioning/compute` 129 + 1
      pre-existing failure, provisioning service 890, `domains/bare_metal` 75,
      bare-metal provisioning adapter 2, bare-metal storefront 126, bare-metal buyer
      11, API-credits service 63, API-credits storefront 79, VM storefront 1169 + 2
      pre-existing `test_alkahest` failures, e2e unit 237 + 1 pre-existing failure.
      Counts include `capacity-resource-administration` Sections 4b and 4c, on the
      same branch.
- [x] 7.2 Bump distribution versions and lower bounds. **Amended after review:**
      done in this change rather than deferred (`design.md`, "Review outcomes").
      Minor: `kit-site` 0.4.0, `kit-site-client` 0.3.0, `kit-fulfillment` 0.3.0,
      `core-storefront` 0.5.0, `core-storefront-client` 0.19.0, `bare-metal` 0.3.0,
      `bare-metal-storefront` 0.3.0, `bare-metal-buyer` 0.2.0,
      `bare-metal-provisioning-adapter` 0.2.0, `vms-provisioning-adapter` 0.3.0,
      `vms-provisioning-operator-client` 0.4.0, `vms-storefront` 0.4.0,
      `compute-provisioning-service` 0.3.0, `apicredits-service` 0.3.0,
      `apicredits-storefront` 0.3.0. Patch: `compute-provisioning` 0.6.1,
      `kit-capacity-publication` 0.1.1, `kit-storefront` 0.1.1. Consumer bounds,
      exact pins, and three Dockerfile pins follow. Twenty locks regenerated with
      only the bumped packages upgraded; nineteen pass `uv lock --check`. The VM
      storefront's lock is hand-assembled from `uv`-generated blocks because its
      `torch` index is unreachable in the implementation environment; it is
      verified by `uv sync --frozen` and a full suite run, and **must be
      regenerated with `uv lock` where that index is reachable before merge.**
- [x] 7.3 A repository search for `vm_host`, `machine_id`, `kvm_host`, and
      `default_vm_host` returns only the historical-schema reads the naming rule
      permits and sites 0.2 left to `pools-9`; record the residue in `design.md`.
      Done: residue is historical-schema reads (retired `vm_leases`, historical
      migration tests), the migration's own retired-key table, and VM-storefront
      code `pools-9` deletes.
- [x] 7.4 `openspec validate --all --strict` shows no regression against the baseline
      at implementation start (18 unrelated failures on 2026-09-21).
      Done 2026-09-21: 75 passed, 18 failed — the same 18 unrelated failures.

## 8. Closeout

Per `openspec/README.md#plan-closeout-requirements`, in that order.

- [x] 8.1 **Comment hygiene.** `make check-comment-hygiene`; also read every touched
      docstring for "renamed from" or "previously" provenance, which the target does
      not catch.
      Done: `make check-comment-hygiene` passes.
- [x] 8.2 **Import placement.** Review imports this change adds or touches; move
      function-level ones to module level where no verified circular import or
      documented lazy-load reason applies, checked against the real suites.
      Done: the one function-level import this change added (a test's
      `RetiredListingKindError`) moved to module level; suite rerun green.
- [x] 8.3 **Documentation compliance.** Confirm the naming rule landed in
      `ARCHITECTURE.md` and the two specs, not only in this change.
      Partly done: `ARCHITECTURE.md`'s "One name per concept" and its physical
      identity prose are current. Spec promotion (6.2) happens after code review,
      per `AGENTS.md`.
      Done 2026-09-21: `ARCHITECTURE.md` "One name per concept" and both specs
      carry the rule; see the promotion record.
- [x] 8.4 **Narrative compression.** Compress completed-task notes to final behaviour,
      evidence, and destinations; move rationale to `design.md`.
      Done 2026-09-21: superseded text removed from 4.4; 7.1 and 8.8 reduced to
      their final evidence; rationale for every amendment is in `design.md`,
      "Decisions made during implementation" and "Review outcomes".
- [x] 8.5 **Roadmap currency.** No roadmap goal names host identity; record that
      disposition here unless implementation finds one.
      Done: no roadmap goal names host identity; no roadmap edit is owed.
- [x] 8.6 **Campaign index currency.** Update this change's row and the
      `unify-host-identity ──► capacity-resource-administration` edges in
      `openspec/changes/README.md`.
      Done 2026-09-21: row reads "promoted; ready to archive"; the edges to
      `capacity-resource-administration` were already current.
- [x] 8.7 **Documentation citations.**
      `make check-doc-citations CHANGE=unify-host-identity`.
      Done 2026-09-21: every cited path resolves and none is a tombstone.
- [x] 8.8 **End-to-end pipeline.** Run it and record the run, result, and the VM and
      bare-metal scenarios that exercise renamed execution references.
      **Run 1, 2026-09-21 — failed at stack start.** The provisioning image pinned
      `arkhai-compute-provisioning-service[adapters]==0.2.0`; the wheelhouse held
      only 0.3.0, so the resolver fetched the published 0.2.0 and its older
      dependencies from the public index and the container ran old migrations.
      The pin search in 7.2 missed it because of the extras bracket. Fixed, and
      guarded by `test_every_image_pins_the_version_its_package_declares`, which a
      control run with the stale pin fails.
      **Run 2, 2026-09-21 — passed:** 113 passed, 3 skipped, 264 deselected. The VM
      scenarios exercising renamed execution references passed:
      `test_full_deal` (32), `test_full_deal_buyer_cli` (28),
      `test_buy_oneshot_buyer_cli` (9), `test_compute_dynamic_listings` (12), and
      `test_multi_registry` (21, 2 skipped).
      **Unrun at this tier, not passed:** `test_bare_metal_complete_deal` skipped
      because the standard pipeline supplies neither the `BARE_METAL.*` settings nor
      the bare-metal buyer plugin it requires; that predates this change and is
      owned by bare-metal release qualification
      (`docs/bare-metal-seller-quickstart.md`, "Release-qualified deal evidence").
      `test_non_erc20_settlement` and the provisioning smoke tier are not selected by
      this pipeline. Bare-metal renamed references are covered in process: the
      fulfillment provider, lease service, and storefront suites (126) and the
      storefront's retired-kind refusal tests.
- [x] 8.9 **Promotion.** Complete the record below.
      Done 2026-09-21: deltas synced to `physical-provisioning` and
      `site-capacity`; every accepted decision has a permanent location below.

## 9. Code review corrections (2026-09-21)

Appended after review; see `design.md`, "Review outcomes". Numbered after Section 8
rather than renumbering it, so the closeout keeps its references.

- [x] 9.1 Make the host-identity migration fail before effect: plan every rewrite
      before writing (`_plan_host_identity_rewrites`) and run the writes in
      `_schema_transaction`, which covers DDL on SQLite. Apply the helper to the
      capacity-declaration table rebuild. Evidence:
      `fixtures/schema_through_20260911_001.sql`, generated by running the
      preceding chain; `test_host_identity_migration.py` (6) and
      `test_capacity_declaration_contract_migration.py` (4) start from it, and the
      failure tests compare every schema object and every row.
- [x] 9.2 Replace the recursive JSON key rename with path-specific rewrites per
      stored shape. A test proves an operator `provider_extra_vars` entry named
      `machine_id` is not touched.
- [x] 9.3 Fix the seven `HostResponse.name` accesses in the provisioning smoke test
      and the VM scenarios; audit every call site of a host-returning method.
- [x] 9.4 Rewrite the bare-metal reset as the owner's uninstall-and-reinstall
      procedure (task 4.7, `docs/bare-metal-seller-quickstart.md`).
- [x] 9.5 Make `CapacityApi` delegate to `SiteCapacityAdminClient` and
      `SiteCapacityClient`; confine raw HTTP to rejection-path tests.
- [x] 9.6 Rewrite the two provider comments and two migration comments as
      current-state rules; correct the negotiation docstring's service-terms kind;
      scope `ARCHITECTURE.md`'s rule to interfaces and name the VM-storefront
      exception.
- [x] 9.7 Add a full sync/async storefront client parity guard in the VM storefront
      suite.
- [x] 9.8 **Bare-metal lease client — moved out of band by the owner, 2026-09-21.**
      Not this change's work: give the bare-metal lease endpoints a canonical client,
      or decide they are not an inter-service API, and move
      `test_bare_metal_leases_api.py` onto it. Tracked outside this change.
- [x] 9.9 **`make test` finding, 2026-09-21.** The API-credits domain suite's
      `test_role_wheels_require_shared_domain_and_versioned_core` asserted literal
      `Requires-Dist` specifiers, so 7.2's correct move of the storefront's
      `arkhai-core-storefront` bound to `>=0.5.0` failed it. The test, and its two
      runtime-requirement siblings, now assert the dependency edges and, for the
      role/core edges, that a version specifier is present — not its value. Mutation
      checks: removing the edge and unbounding it each fail the test. A scan of all
      171 internal requirement specifiers in the repository found each satisfied by
      the version the repository builds. The suites `make test` runs that the 7.1
      baseline omitted were run and pass: API-credits domain 42, buyer 17,
      sample-app 1, Python middleware 8, TypeScript middleware; `core` 98,
      `core/buyer` 125, registry 114; kits alkahest 179, capacity-publication 20,
      config 134, contact-exchange 37, delivery 42, identity 165, policy 39,
      resource-pools 101, settlement-runtime 90, negotiation-runtime 7, storefront 8,
      hosted-settlement 187; VM buyer 196 (`--frozen`; its `reinit` relocks and
      needs the `torch` index); provisioning IaC 65. The Rust middleware suite was
      not run (no `cargo` in the implementation environment).

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| The host's identity is `host_id` on every interface; its address is `ssh_host` | `docs/development/ARCHITECTURE.md` — "One name per concept"; `openspec/specs/physical-provisioning/spec.md` — "A host has one identity name" |
| `physical_host_id` identifies a physical machine across hosts | `docs/development/ARCHITECTURE.md` — "One name per concept" |
| A capacity declaration names its host through a first-class `host_id`, at most one declaration per host | `openspec/specs/site-capacity/spec.md` — "A capacity declaration names the host it is delivered through" |
| Cross-mode accounting fields have one location on a declaration | `openspec/specs/site-capacity/spec.md` — "Cross-mode physical accounting" |
| Existing host identities migrate in one transaction covering schema and data, validated before the first write, rewriting only host-identity locations | `openspec/specs/physical-provisioning/spec.md` — "Existing host identities migrate without loss" |
| A bare-metal storefront refuses state written under a retired listing kind; `bare_metal.v1` is dropped | `openspec/specs/physical-provisioning/spec.md` — "A bare-metal storefront refuses state written under a retired listing kind" |
| The bare-metal domain identity stays `bare_metal.v1` while the payload kind moves | Code: `domains/bare_metal/src/arkhai_bare_metal/schema.py`, the comments on `BARE_METAL_SCHEMA_KIND` and `BARE_METAL_DOMAIN_IDENTITY` |
| Provider operation envelopes name the host at schema 2; kind strings never change | Code: the `_OPERATION_SCHEMA_VERSION` comments in the VM and bare-metal fulfillment providers |
| An image pins the version its repository package declares | Test: `e2e-tests/tests/unit/test_domain_stack_configuration.py`, `test_every_image_pins_the_version_its_package_declares` |
| Async and sync storefront clients expose one operation surface | Test: `domains/vms/storefront/tests/unit/test_lifecycle_client_parity.py` |
| Preprod bare metal is reset by uninstalling and reinstalling its release rather than migrated | Temporary, while bare metal is unreleased: `docs/bare-metal-seller-quickstart.md`, "Resetting the storefront database". The durable evolution rule is owned by `version-accepted-artifacts` |
