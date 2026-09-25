# Design

## Context

`CapacityLedgerService._sync_release_job_fields` writes `vm_remove_job_id`
only when `offering_mode` is the VM mode and always to the value
`release_job_id` already holds. Three readers fall back to it
(`compute_provisioning/lease_lifecycle.py`, the VM adapter's
`leases_controller.py`, the bare-metal adapter's
`bare_metal_leases_controller.py`); each reads `release_job_id` first. The
name is also a field on `vm_provisioning_operator.models.LeaseResponse`, on
the VM adapter's lease PATCH body, and on `market_storefront`'s
`capacity_admin_models`, which is why the first attempt (in
`fix-vm-fulfillment-capacity-boundary`, task 10.5) was withdrawn: it was a
public-model change, not a column drop.

Both lease endpoints now publish `release_job_id`, so nothing a caller could
learn from the mirror is unavailable without it. Re-confirmed 2026-09-25: the
ledger still writes the mirror and the three fallbacks are still present.

## Decisions

### Outright removal with a version bump

Decided 2026-09-25. The field is removed from `LeaseResponse`, the lease
PATCH body, and the storefront's admin models in one step, and the packages
whose public models change (`vm_provisioning_operator` at least; the VM
adapter and the storefront if their published models are versioned
separately) take a version bump.

The alternative was the one-way alias `settle-listing-vocabulary` used for
the deprecated `listing_mode` cardinality name: accept the old field for a
window while publishing only the new one. Rejected here because every API in
the repository is pre-1.0 and is allowed to break, no consumer outside the
repository is known to read the field, and the alias would keep the wrong
name — it last stored a fulfillment id, not a VM-removal job id — on a table
bare-metal pools share.

**Revisit trigger:** a consumer outside the repository reporting that it reads
`vm_remove_job_id` from a lease. That reopens the alias, applied to the
response only; the PATCH body would still refuse the field.

### The PATCH body refuses the retired field

A lease PATCH that still carries `vm_remove_job_id` is rejected with a
validation error naming `release_job_id`, rather than silently ignored. A
silent no-op is how a caller keeps sending a field for a year without
noticing.

### Scope stops at the reservation table

`vm_leases.vm_remove_job_id` is the legacy source the backfill reads and is
out of scope, as is the storefront's own sqlite column. Both are named in the
proposal so a reader does not mistake them for the mirror.

## Migration

The column is dropped through `_drop_columns_via_table_rebuild`, the same
path `vm_host` and `vm_target` left this table by. Verified against a
database that has the column and one that does not, since the rebuild runs on
both.
