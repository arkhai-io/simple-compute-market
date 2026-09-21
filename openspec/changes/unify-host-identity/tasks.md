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

- [ ] 0.1 Re-run the census in `design.md` against the branch and record any drift
      there before editing. The production file inventory below was taken on
      2026-09-21.
- [ ] 0.2 Classify every VM-storefront occurrence of `vm_host` as deleted by
      `pools-9-retire-local-physical-authority` (listed in its `tasks.md` Sections
      2–4, left untouched here) or surviving (renamed in Section 5), and record the
      classification in `design.md`. Mechanical: a site `pools-9` names for removal
      is left; everything else is renamed.

## 1. Host registry

- [ ] 1.1 `provisioning/compute/service/src/compute_provisioning_service/db/models.py`:
      `Host.name` → `host_id` (primary key), `kvm_host` → `ssh_host`; update the
      docstring's field list.
- [ ] 1.2 Compute migration in `db/migrations.py`, appended to `MIGRATIONS`: rename
      both columns by table rebuild through the existing helper, preserving every
      foreign key and index that references `hosts.name`. Fresh bootstrap,
      idempotent rerun, populated database.
- [ ] 1.3 Host service and INI parser
      (`domains/vms/provisioning/adapter/src/vm_provisioning_adapter/services/host_service.py`):
      the alias is read into `host_id`, `kvm_host` into `ssh_host`. INI syntax is
      unchanged.
- [ ] 1.4 Host API: `controllers/hosts_controller.py` path parameter `{host_id}`;
      request and response models; `vm_provisioning_operator/models.py` and
      `client.py` (`HostCreate`, `HostUpdate`, `HostResponse`, and every method taking
      a host). Both client variants if both exist; parity test per `TESTING.md`.
- [ ] 1.5 Inventory rendering and other host readers: `services/ansible_service.py`,
      `services/system_service.py`, `services/ansible_fulfillment_provider.py`,
      `compute_provisioning_service/services/relay_port_allocator.py`,
      `relay_rebinding.py`, `capacity_inventory.py`. The rendered inventory's host
      alias comes from `host_id` and its address from `ssh_host`.
- [ ] 1.6 `default_vm_host` → `default_host_id`:
      `compute_provisioning_service/settings.toml`, `config/config.yml`,
      `vm_provisioning_adapter/services/job_service.py`,
      `helm/charts/provisioning/values.yaml`, `helm/values.yaml`, and the VM
      storefront's `settings.toml` and `groups/config.py` unless 0.2 classifies them
      as deleted.
- [ ] 1.7 **Integration.** Host CRUD and `POST /api/v1/hosts/import` through the typed
      operator client; a rendered inventory for an INI-seeded host names it by
      `host_id` and connects to `ssh_host`.

## 2. Declaration `host_id`

- [ ] 2.1 `kit/site/src/market_site/db.py`: nullable `CapacityBucket.host_id`.
- [ ] 2.2 `kit/site/src/market_site/ledger.py`: `register_resource` takes `host_id`;
      `_executor_ref_for_resource` builds `{"host_id": …}` from the column, not from
      attributes. `kit/site/src/market_site/projections.py`: stop stripping `vm_host`
      from grouping attributes (it is no longer an attribute) and keep `host_id` out
      of them.
- [ ] 2.3 Wire: `kit/site/src/market_site/http_models.py` gains optional `host_id` and
      its attribute description drops `vm_host`; `kit/site-client` `models.py` and
      `client.py` follow; `router.py`'s log line.
- [ ] 2.4 Compute migration, ordered after 1.2: populate `host_id` from each
      declaration's `vm_host` attribute, else its enabled
      `bare_metal_publication.machine_id`; remove both from attributes; lift nested
      `physical_host_id` and `allocation_mode` to the top level. Abort naming the row
      when the two host spellings disagree, or when nested and top-level cross-mode
      fields disagree.
- [ ] 2.5 `capacity_inventory.py`: correlate a declaration to a host by `host_id`
      only, and refuse two declarations naming one host. The `resource_id` and
      `machine_id` matches are removed.
- [ ] 2.6 **Unit and migration tests** for 2.2–2.5, including the conflicting-spelling
      abort and the correlation refusal.

## 3. Execution references

- [ ] 3.1 VM provisioning adapter: `controllers/leases_controller.py`,
      `models/fulfillment_model.py`, `models/jobs_model.py`,
      `models/vm_request_model.py`, `services/ansible_fulfillment_provider.py`,
      `services/ansible_service.py`, `services/provisioning_service.py`,
      `services/job_service.py`, `services/mock_ansible_service.py`,
      `compute_adapter.py`, and `legacy_backfill.py` (its targets only; see the naming
      rule). `compute_provisioning_service/controllers/compute_contract_controller.py`
      reads `host_id` from the reservation.
- [ ] 3.2 Bare-metal provisioning adapter:
      `services/bare_metal_operations_service.py` (it currently passes `machine_id`
      as `vm_host`), `controllers/bare_metal_leases_controller.py`,
      `services/bare_metal_fulfillment_provider.py`,
      `services/bare_metal_lease_service.py`, `compute_adapter.py`.
- [ ] 3.3 Ansible: `playbooks/single-tenant/vm-operations.yaml` and
      `playbooks/bare-metal/node-access.yaml` read `host_id`;
      `roles/bare-metal-access/tasks/main.yml`; `inventory/hosts.example`,
      `inventory/vm-vars-example.yaml`; `domains/vms/provisioning/iac/README.md`.
- [ ] 3.4 Compute migration, ordered after 2.4: rewrite `vm_host` → `host_id` in
      `capacity_reservations.executor_ref`, fulfillment settlement metadata, and job
      parameter JSON. Add a retired-key counter following
      `count_rows_carrying_retired_offering_mode_key`, and assert zero after migration.
- [ ] 3.5 **Rendered-variable tests** for each playbook invocation: the adapter sets
      `host_id` and no playbook falls back to `localhost` for a real host.
- [ ] 3.6 `e2e-tests/src/provisioning_test_client.py`,
      `e2e-tests/config/hosted-resources.csv`, and the e2e capacity helpers
      (`tests/e2e/roles/scenarios/vms/host_registry.py`, `conftest.py`,
      `hosted/network.py`), which then pass `host_id` as the declaration field rather
      than a `vm_host` attribute.

## 4. Bare metal

- [ ] 4.1 `domains/bare_metal/src/arkhai_bare_metal/`: `schema.py`,
      `provision_terms.py`, and `publication.py` move to kind `bare_metal.v2` with
      `machine_id` → `host_id`; `bare_metal.v1` is removed with no decoder.
      `projections.py`, `hosted_publication.py`, `storefront_publication.py` follow.
- [ ] 4.2 The publication view reads `physical_host_id` and `allocation_mode` from the
      declaration's top level; `bare_metal_publication` keeps only view configuration
      (`enabled`, `access_methods`, `capabilities`).
- [ ] 4.3 Bare-metal storefront (`arkhai_bare_metal_storefront`): `fulfillment_service.py`,
      `hosted_binding.py`, `hosted_lifecycle.py`, `negotiation.py`,
      `negotiation_service.py`, `publication_cli.py`, `settlement_service.py`,
      `sqlite_client.py`.
- [ ] 4.4 ~~Bare-metal storefront migration behind a drain guard.~~ **Superseded
      2026-09-21** by `design.md`'s "Bare metal: reset the preprod storefront
      database and drop `bare_metal.v1`". Instead: the bare-metal storefront's
      `migrations.py` creates the renamed schema for a fresh database, and startup
      refuses a database containing `derived_bare_metal_listings.machine_id`, naming
      the reset procedure in 4.7. Test both, and that the refusal decodes and writes
      nothing.
- [ ] 4.5 Buyer plugin: `domains/bare_metal/buyer/src/arkhai_bare_metal_buyer/cli.py`
      decodes `bare_metal.v2`.
\1- [ ] 4.7 **Manual migration — preprod bare-metal reset**, performed once when this
      change is deployed to preprod, and recorded here with the date and result:
      1. Before upgrading, list active bare-metal leases at the compute provisioner
         and terminate each through the lease API; force-release any whose teardown
         cannot complete, after verifying the node externally. Otherwise the reset
         orphans them at the provisioner.
      2. Stop the bare-metal storefront and delete its database volume.
      3. Deploy; the compute provisioner applies Sections 1–3's migrations.
      4. Start the bare-metal storefront on the empty volume; confirm it republishes
         and that the registry's previous `bare_metal.v1` listings are replaced or
         closed rather than left discoverable.
      5. Discard preprod bare-metal buyer run logs; they reference `v1` deals no
         decoder can recover.

## 5. Surviving storefront surfaces

- [ ] 5.1 Rename every surface 0.2 classifies as surviving. Expected, pending 0.2:
      `core/storefront/src/core_storefront/models/settle_models.py`,
      `core/storefront/src/core_storefront/sqlite_client.py` (comment),
      `core/storefront-client/src/storefront_client/client.py` and `models.py` (both
      client variants, parity test),
      `domains/vms/storefront/src/market_storefront/services/admin_settle_service.py`,
      `fulfillment_resume_runtime.py`, `vm_job_spec_service.py`, and
      `domains/vms/storefront/src/market_storefront/cli_publish.py`'s `machine_id`.
- [ ] 5.2 Coordinate with `pools-9`: its task 3.5 says to leave `vm_host` inside the
      provisioning adapter untouched. That instruction is superseded by this change;
      its note is amended in the same commit so the two changes do not contradict.

## 6. Documentation

- [ ] 6.1 `docs/development/ARCHITECTURE.md`, "One name per concept": add `host_id` as
      the host's identifier and `ssh_host` as its address, and state that
      `physical_host_id` is the physical machine across hosts. Update the
      `executor_ref` and "Identifiers" prose that names `vm_host`.
- [ ] 6.2 `openspec/specs/physical-provisioning/spec.md` and
      `openspec/specs/site-capacity/spec.md`: replace every `vm_host` reference in
      existing requirements (the Ansible fulfillment adapter's recorded target, the
      opaque-reservation requirement's example, claim-identity text).
- [ ] 6.3 `docs/seller-quickstart.md`, `docs/bare-metal-seller-quickstart.md` (the
      registration body gains `host_id` and top-level cross-mode fields),
      `docs/development/VALIDATION_RUNBOOK.md`,
      `tools/issue-discovery/config/phases/local.yaml`.

## 7. Validation

- [ ] 7.1 Unit and integration suites for `kit/site`, `kit/site-client`,
      `kit/fulfillment`, the provisioning service, both provisioning adapters, the
      operator client, `core/storefront`, `core/storefront-client`, the VM and
      bare-metal storefronts, the bare-metal core and buyer packages, and `e2e-tests`
      unit. Disclose any suite not run.
- [ ] 7.2 Bump distribution versions and consumer lower bounds for every package whose
      public model or wire changed: `arkhai-kit-site`, `arkhai-kit-site-client`, the
      provisioning service, both provisioning adapters, the operator client,
      `arkhai-bare-metal` and its storefront and buyer, `core/storefront` and its
      client. The one versioned envelope is the bare-metal kind (4.1).
- [ ] 7.3 A repository search for `vm_host`, `machine_id`, `kvm_host`, and
      `default_vm_host` returns only the historical-schema reads the naming rule
      permits and sites 0.2 left to `pools-9`; record the residue in `design.md`.
- [ ] 7.4 `openspec validate --all --strict` shows no regression against the baseline
      at implementation start (18 unrelated failures on 2026-09-21).

## 8. Closeout

Per `openspec/README.md#plan-closeout-requirements`, in that order.

- [ ] 8.1 **Comment hygiene.** `make check-comment-hygiene`; also read every touched
      docstring for "renamed from" or "previously" provenance, which the target does
      not catch.
- [ ] 8.2 **Import placement.** Review imports this change adds or touches; move
      function-level ones to module level where no verified circular import or
      documented lazy-load reason applies, checked against the real suites.
- [ ] 8.3 **Documentation compliance.** Confirm the naming rule landed in
      `ARCHITECTURE.md` and the two specs, not only in this change.
- [ ] 8.4 **Narrative compression.** Compress completed-task notes to final behaviour,
      evidence, and destinations; move rationale to `design.md`.
- [ ] 8.5 **Roadmap currency.** No roadmap goal names host identity; record that
      disposition here unless implementation finds one.
- [ ] 8.6 **Campaign index currency.** Update this change's row and the
      `unify-host-identity ──► capacity-resource-administration` edges in
      `openspec/changes/README.md`.
- [ ] 8.7 **Documentation citations.**
      `make check-doc-citations CHANGE=unify-host-identity`.
- [ ] 8.8 **End-to-end pipeline.** Run it and record the run, result, and the VM and
      bare-metal scenarios that exercise renamed execution references. A blocker
      unrelated to this change is recorded with its cause and owner, and what it gates
      is treated as unrun.
- [ ] 8.9 **Promotion.** Complete the record below.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| The host's identity is `host_id` on every surface; its address is `ssh_host` | `docs/development/ARCHITECTURE.md` — "One name per concept"; `openspec/specs/physical-provisioning/spec.md` — "A host has one identity name" |
| `physical_host_id` identifies a physical machine across hosts | `docs/development/ARCHITECTURE.md` — "One name per concept" |
| A capacity declaration names its host through a first-class `host_id` | `openspec/specs/site-capacity/spec.md` |
| Cross-mode accounting fields have one location on a declaration | `openspec/specs/site-capacity/spec.md` — "Cross-mode physical accounting" |
| Existing host identities migrate in one transaction and fail closed | `openspec/specs/physical-provisioning/spec.md` — "Existing host identities migrate without loss" |
| A bare-metal storefront refuses state written under a retired listing kind; `bare_metal.v1` is dropped | `openspec/specs/physical-provisioning/spec.md` — "A bare-metal storefront refuses state written under a retired listing kind" |
| Preprod bare-metal storefront is reset rather than migrated | Temporary; change history only. The durable evolution rule is owned by `version-accepted-artifacts` |
