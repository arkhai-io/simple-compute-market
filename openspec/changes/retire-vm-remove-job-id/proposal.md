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
withdrew it, because the name is a field on public wire models rather than a
private column.

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
identifier also finds the retired `vm_leases` table's column of the same name.
That table was dropped by migration `20260724_002`; the name survives only in
the historical migrations that create, read, and backfill from it, in
`vm_provisioning_adapter/legacy_backfill.py`, which consumes the legacy row,
and in the tests that build pre-migration schemas. None of them reads or writes
the reservation mirror, so all of them are out of scope. So is
`market_storefront/utils/sqlite_client.py`'s column, which belongs to the
storefront's own database.

## What This Change Covers

Retiring the mirror on `capacity_reservations`, and the name everywhere a lease
contract carries it:

- The column on `market_site.db.CapacityReservation`, and a versioned
  compute-provisioning migration dropping it through
  `_drop_columns_via_table_rebuild`. `vm_host` and `vm_target` were dropped
  from this same table that way, which is the precedent for the helper.
- `CapacityLedgerService`: the `vm_remove_job_id` parameter aliases on
  `begin_releasing`, `update_lease_fields`, `update_lease_fields_in_session`
  and `update_reservation_state`, the mirror write in
  `_sync_release_job_fields`, and the key in `_reservation_payload`.
- The three readers that fall back to it —
  `compute_provisioning/lease_lifecycle.py`,
  `vm_provisioning_adapter/controllers/leases_controller.py`, and
  `bare_metal_provisioning_adapter/controllers/bare_metal_leases_controller.py`
  — which read `release_job_id` alone once the mirror is gone.
- The VM lease contract: `LeaseResponse.vm_remove_job_id` is removed, and the
  lease PATCH body (`LeaseUpdate`) names the handle `release_job_id` instead of
  `vm_remove_job_id`, so an operator can still correct it.
- `market_storefront`'s `ReleaseStartedEventRequest.vm_remove_job_id` and the
  admin controller argument that forwards it. The value has always been
  discarded, and nothing in the repository sends the event.
- A version bump for every package whose wheel contents change, and raised
  lower bounds where a consumer depends on the new behaviour.

## What This Change Does Not Cover

- The retired `vm_leases` table's column of the same name, and the historical
  migration and legacy-backfill code that reads it.
- The storefront's own `vm_remove_job_id` column in
  `market_storefront/utils/sqlite_client.py`, on the frozen
  `compute_allocations` ledger.
- `_reservation_payload`'s derived `vm_host`/`vm_target` keys, which are
  domain-shaped projections beside the generic
  `executor_ref`/`executor_target` rather than duplicated storage, and were
  explicitly left alone under 10.5.
- A migration for API-credits or bare-metal databases. Bare-metal pools share
  the compute provisioning database the VM migration covers, and API-credits
  reservations are never VM-mode, so its column has never held a value; see
  `design.md`.

## Wire Compatibility

Removing `vm_remove_job_id` from `LeaseResponse` is a breaking change for a
consumer that reads it, and renaming the PATCH body field is a breaking change
for one that sends it. `release_job_id` is the replacement on both, and is
already published on both lease endpoints.

The field is removed outright, with a version bump of every package whose wheel
contents change. Every API in this repository is pre-1.0 and may break in this
way. No consumer in the repository reads or sends the field, and no external
compatibility commitment exists for it; the packages are published, so the
change rests on that absence of commitment rather than on a claim that no
outside reader exists. A caller
still sending the old name is treated exactly as a caller sending any other
unknown field: the lease model ignores it. `design.md` records the alternatives
and the revisit trigger.

## Schema Compatibility

Dropping the column in the release that stops writing it is non-additive with
no coexistence period, an exception to the expand/contract rule in
`docs/development/ARCHITECTURE.md` that this change takes deliberately. Rolling
back past the migration requires re-adding the nullable column before starting
the prior image; `design.md` records the exception, its cost, and the recovery.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification — `openspec/specs/site-capacity/spec.md`
- [x] Release policy — `docs/development/RELEASING.md`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- `release_job_id` is the one release handle on a Capacity Reservation and the
  one name for it on every lease contract, published and updatable; no
  domain-prefixed mirror exists — `openspec/specs/site-capacity/spec.md`.
- Before 1.0, an incompatible package change takes a minor version bump —
  `docs/development/RELEASING.md`, "Versioning policy".
