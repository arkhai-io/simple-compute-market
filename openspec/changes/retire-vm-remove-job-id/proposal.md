## Why

`capacity_reservations.vm_remove_job_id` is a VM-conditional mirror of
`release_job_id`. `CapacityLedgerService._sync_release_job_fields` writes it
only when `offering_mode` is the VM mode, and always to the value
`release_job_id` already holds, so no reader can learn anything from it that
`release_job_id` does not already say. It is also the one domain-prefixed
column on a reservation table that bare-metal pools share, and the name is
wrong twice over: it last stored a durable *fulfillment* id, not a VM-removal
job id.

`fix-vm-fulfillment-capacity-boundary` task 10.5 recorded the deferral and
named this change as its home. That task attempted the retirement once and
withdrew it, because the name is a field on three packages' public wire
models rather than a private column.

Two things have changed since, and both make this smaller than the withdrawn
attempt:

**The canonical field is now published where it was missing.** The VM
adapter's lease contract (`GET /api/v1/leases/{id}`) previously exposed only
`vm_remove_job_id`, so a caller asking for `release_job_id` — the name the
compute contract endpoint already used — got nothing. `LeaseResponse` now
carries both, filled from the one ledger field. That was the last reason a
caller had to read the mirror, and it removes the wire-compatibility
argument for keeping it.

**The "22 files" estimate conflated two different columns.** A grep for the
identifier finds `vm_leases.vm_remove_job_id` as well — the *legacy* table
the backfill reads from. `db/migrations.py`'s backfill `SELECT`s
`vl.vm_remove_job_id` from `vm_leases` and joins to `capacity_reservations`;
it reads the legacy source and never writes the mirror, and
`vm_provisioning_adapter/legacy_backfill.py` consumes that same legacy row.
Those references are a different column that happens to share a name and are
out of scope here. So is
`market_storefront/utils/sqlite_client.py`'s column, which belongs to the
storefront's own database.

## What This Change Covers

Retiring the mirror on `capacity_reservations` only:

- The column on `market_site.db.CapacityReservation`, dropped through
  `_drop_columns_via_table_rebuild`. `vm_host` and `vm_target` were dropped
  from this same table that way, which is the precedent for the migration.
- `CapacityLedgerService`: the `vm_remove_job_id` parameter aliases on
  `attach_lease`, `begin_releasing`, `update_lease_fields` and
  `update_lease_fields_in_session`, the mirror write in
  `_sync_release_job_fields`, and the key in `_reservation_payload`.
- The three readers that fall back to it —
  `compute_provisioning/lease_lifecycle.py`,
  `vm_provisioning_adapter/controllers/leases_controller.py`, and
  `bare_metal_provisioning_adapter/controllers/bare_metal_leases_controller.py`
  — which can read `release_job_id` alone once the mirror is gone.
- The wire surface: `LeaseResponse.vm_remove_job_id`, the lease PATCH body
  field the adapter and `market_storefront`'s `capacity_admin_models`
  accept, and the storefront admin controller that forwards it.

## What This Change Does Not Cover

- `vm_leases.vm_remove_job_id` and the legacy-backfill path that reads it.
  That column is the historical record the backfill exists to consume;
  dropping it is a separate question about retiring the legacy table.
- The storefront's own `vm_remove_job_id` column in
  `market_storefront/utils/sqlite_client.py`.
- `_reservation_payload`'s derived `vm_host`/`vm_target` keys, which are
  domain-shaped projections beside the generic
  `executor_ref`/`executor_target` rather than duplicated storage, and were
  explicitly left alone under 10.5.

## Wire Compatibility

Removing a field from `LeaseResponse` and from the lease PATCH body is a
breaking change for any consumer outside this repository that reads or sends
`vm_remove_job_id`. `release_job_id` is the replacement and is already
published on both lease endpoints, so a consumer can migrate before the
removal lands. This change owes an explicit decision on whether the removal
ships with a client-wheel version bump or a deprecation window, recorded
before the wire edits are made.
