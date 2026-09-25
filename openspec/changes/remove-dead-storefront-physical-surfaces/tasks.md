# Tasks

Task numbers continue from Sections 2 and 3 of
`pools-9-retire-local-physical-authority`, planned 2026-08-06 and split out
2026-09-25. Section 1 is this change's own re-verification.

## 1. Re-confirm

- [ ] 1.1 Re-run the confirming searches recorded in
      `pools-9-retire-local-physical-authority`'s `design.md`: `compute_allocations`'
      lack of any production `INSERT`, the four zero-caller methods, the two
      admin routes' lack of any production caller, and that `reserved.get("vm_host")`
      is always `None` at the opaque-reservation boundary. Record drift here.

## 2. Retire `compute_allocations`

- [ ] 2.1 Remove `held_gpu_counts`, `held_gpu_counts_by_resource`, and
      `allocation_table_exists` from `domains/vms/listings/reconciler.py` and
      their exports from that package's `__init__.py`.
- [ ] 2.2 Remove the release-`UPDATE` against `compute_allocations` from
      `SQLiteClient.apply_resource_transition`, including the
      `$.allocation_id`/`$.compute_allocation_id` attribute-path special case
      that feeds it.
- [ ] 2.3 Freeze the table: stop creating it in `_ensure_domain_tables`, stop
      creating its trigger and four indexes, and stop adding its columns in
      `migrations.py`. No `DROP`.
- [ ] 2.4 Remove the test-only `INSERT` in `test_cli_publish_helpers.py` and
      any assertion that depends on it; delete `test_compute_allocations.py`
      or reduce it to the freeze's own assertions.
- [ ] 2.5 Run the storefront unit and integration suites.

## 3. Remove dead physical surfaces

All zero-caller. Independent of each other.

- [ ] 3.1 Delete `SQLiteClient.delete_resource`, `ensure_default_resources`,
      `host_capacity_remaining`, and `list_hosts`, plus the
      `host_capacity_remaining` tests in `tests/unit/test_hosts.py`.
- [ ] 3.2 Remove `GET`/`PATCH /api/v1/admin/portfolio/resources/{resource_id}`,
      their request/response models, and `storefront_client`'s `get_resource`
      and `patch_resource` on both client variants.
- [ ] 3.3 Remove the legacy local-row normalization loop from
      `release_reservations`, keeping `_release_site_ledger_holds` unchanged,
      and rewrite the docstring, which currently describes the storefront as
      clearing bookkeeping "via the provisioning service's LeaseWatchdog."
- [ ] 3.4 Remove `resource_count` from `SystemService.get_health` and from
      both `core_storefront`'s and `storefront_client`'s `HealthResponse`.
      Update `storefront-publication`'s Evidence entry, which cites
      resource-count diagnosis.
- [ ] 3.5 Remove the always-`None` `reserved_vm_host` and its threading
      through `register_lease`, `schedule_shutdown`, `provision_vm`,
      `_do_provision`, and `_register_vm_lease_with_settings`. Leave
      `vm_host` inside the provisioning adapter untouched — it is the real
      execution target there.
- [ ] 3.6 Amended 2026-09-25: the collision check with
      `fix-vm-fulfillment-capacity-boundary` is moot; that change is complete.
      Instead, confirm its committed-claim reads in `fulfill_vm_obligation`
      are untouched by 3.5.
- [ ] 3.7 Run the storefront and `core/storefront-client` suites plus the
      client parity contract test.

## 4. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [ ] 4.1 **Comment hygiene.** Run `make check-comment-hygiene`. Read the
      touched docstrings directly as well: `patch_resource`,
      `release_reservations`, and `_register_vm_lease_with_settings` describe
      an arrangement that no longer exists, and stale docstrings are what kept
      these surfaces alive past their callers.
- [ ] 4.2 **Import placement.**
- [ ] 4.3 **Documentation compliance.** Confirm no permanent document
      describes the removed routes or the health field.
- [ ] 4.4 **Narrative compression.**
- [ ] 4.5 **Roadmap currency.** Fold the retired surfaces into Goal 1's
      current-state text in `docs/development/ROADMAP.md` and remove this
      change's gap row.
- [ ] 4.6 **Campaign index currency.** Update this change's row in
      `openspec/changes/README.md`'s Goal 1 campaign.
- [ ] 4.7 **Promotion.** Complete the design-promotion record below.
- [ ] 4.8 **Documentation citations.** Run
      `make check-doc-citations CHANGE=remove-dead-storefront-physical-surfaces`
      and resolve every match.
- [ ] 4.9 **End-to-end pipeline.** Confirm the end-to-end pipeline passes and
      record the evidence; the VM teardown stages exercise
      `release_reservations`. If the pipeline cannot run for a reason unrelated
      to this change, record that as an explicit blocker naming the cause and
      the change that owns it, and treat the validations it gates as unrun.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| The storefront holds no physical-allocation ledger and no physical resource administration surface | Reached in part here; the requirement is `pools-9-retire-local-physical-authority`'s "Storefront holds no physical-resource authority" |
| Why each surface was dead | `pools-9-retire-local-physical-authority`'s `design.md`, "Goal 1 sweep findings (2026-08-06)" |
