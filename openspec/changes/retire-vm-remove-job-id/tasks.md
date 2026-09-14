# Tasks

## 1. Decide the wire disposition first

- [ ] 1.1 Decide and record whether `LeaseResponse.vm_remove_job_id` and the
      lease PATCH body field are removed outright with a client-wheel version
      bump, or deprecated for a window first. Everything in section 3 depends
      on the answer, and making the edits before the decision is what turns a
      contract change into an accident. `release_job_id` is already published
      on both lease endpoints, so no consumer is blocked on the removal
      itself.

## 2. Retire the ledger mirror

- [ ] 2.1 Drop the `vm_remove_job_id` parameter aliases from
      `CapacityLedgerService.attach_lease`, `begin_releasing`,
      `update_lease_fields` and `update_lease_fields_in_session`. Each
      currently collapses to `release_job_id or vm_remove_job_id`; the
      callers all pass `release_job_id`.
- [ ] 2.2 Remove the mirror write from `_sync_release_job_fields` and the
      `vm_remove_job_id` key from `_reservation_payload`. Reading the payload
      back is how the three fallback readers in 2.3 see the field, so this is
      the change that makes them dead.
- [ ] 2.3 Drop the `or reservation.get("vm_remove_job_id")` fallbacks in
      `compute_provisioning/lease_lifecycle.py`,
      `vm_provisioning_adapter/controllers/leases_controller.py` and
      `bare_metal_provisioning_adapter/controllers/bare_metal_leases_controller.py`.
- [ ] 2.4 Drop the column from `market_site.db.CapacityReservation` and add
      the versioned migration through `_drop_columns_via_table_rebuild`,
      following the `vm_host`/`vm_target` drop on this same table. Verify
      against a database that has the column and one that does not, since the
      table-rebuild path runs on both.
- [ ] 2.5 Confirm no test asserts the mirror's *presence* as a contract.
      There are roughly eight test files referencing the identifier; a test
      that asserts `release_job_id == vm_remove_job_id` is asserting the
      mirror exists and should be reduced to the canonical field, not
      mechanically updated to keep both.

## 3. Retire the wire field

- [ ] 3.1 Per 1.1's decision, remove or deprecate
      `LeaseResponse.vm_remove_job_id`, the lease PATCH body field on the VM
      adapter, `market_storefront`'s `capacity_admin_models` equivalent, and
      the storefront admin controller that forwards it.
- [ ] 3.2 Check the e2e scenarios' lease assertions. `DealLease.refresh`
      reads `release_job_id` already, so the expectation is no scenario
      change; record that disposition explicitly rather than omitting it.

## 4. Validation

- [ ] 4.1 `kit/site`, `kit/fulfillment`, `provisioning/compute/service`,
      `domains/vms/storefront` and the bare-metal storefront suites.
      `provisioning/compute/service` and `kit/site` are the two that cover
      the ledger and the lease contract directly.
- [ ] 4.2 One e2e run. The VM teardown stages (10a-11b) are the ones that
      read a releasing lease's handle end to end, and they went green on
      2026-09-14; a regression there is the signal this change broke a
      reader.
- [ ] 4.3 Grep the repository for the identifier afterwards and confirm every
      remaining hit is either `vm_leases`, the storefront's own sqlite
      column, or documentation of this retirement.

## 5. Closeout

- [ ] 5.1 **Comment hygiene.** `make check-comment-hygiene`.
- [ ] 5.2 **Import placement.** Migrate any function-level import this change
      adds to module level where safe, checked against this change's own diff.
- [ ] 5.3 **Documentation compliance.** Re-check this change's accepted
      decisions against `openspec/README.md`'s placement rules.
- [ ] 5.4 **Narrative compression.** Reduce completed-task notes to final
      behavior, validation evidence, and deferred work.
- [ ] 5.5 **Roadmap currency.** Update `docs/development/ROADMAP.md` for the
      affected goal, or record explicitly that this change has no roadmap
      impact.
- [ ] 5.6 **Campaign index currency.** Update this change's row and its
      campaign's dependency graph in `openspec/changes/README.md`.
- [ ] 5.7 **Promotion.** Complete the design-promotion record. The column
      drop and the `release_job_id`-is-canonical rule both want permanent
      destinations: `openspec/specs/site-capacity/spec.md` is the likely home
      for the latter.
