# Design

## Context

Verified against the tree at planning time; task 1.1 re-runs every search
before anything is deleted.

**`compute_allocations` is a dead execution ledger.** `kit/site`'s
`CapacityReservation` is the authoritative allocation record. The storefront's
table has no production `INSERT`; the only production write is the
release-`UPDATE` in `SQLiteClient.apply_resource_transition`, reached through
an attribute-path special case for `$.allocation_id` and
`$.compute_allocation_id`. Its readers, `held_gpu_counts` and
`held_gpu_counts_by_resource`, are exported from `domains/vms/listings` and
called by nothing. The only `INSERT` in the repository is in
`test_cli_publish_helpers.py`.

**Physical identity crosses the service boundary as `None`.** `kit/site`
strips `vm_host` from the reservation it returns, so `reserved.get("vm_host")`
in `vm_fulfillment_service.py` is always `None`. The value is nonetheless
threaded through `register_lease`, `schedule_shutdown`, `provision_vm`,
`_do_provision`, and `_register_vm_lease_with_settings`; the code comment
records that it was kept only to avoid a signature change. The provisioning
adapter's own `vm_host` is the execution target and is unrelated.

**Two admin routes have no caller.** `GET`/`PATCH
/api/v1/admin/portfolio/resources/{resource_id}` and the clients'
`get_resource`/`patch_resource` have no production caller. `PATCH`'s
docstring describes a provisioning-service `LeaseWatchdog` call that does not
exist; the provisioning service's only reverse call is the `capacity_released`
event, which `release_reservations` handles through `_release_site_ledger_holds`.

**`release_reservations` has a legacy half.** Beside the authoritative
`_release_site_ledger_holds`, a loop normalizes local `resources` rows that
the projection no longer feeds. Its docstring describes the storefront as
clearing bookkeeping "via the provisioning service's LeaseWatchdog".

**Four `SQLiteClient` methods have no caller.** `delete_resource` and
`ensure_default_resources` have zero references, tests included.
`host_capacity_remaining` is referenced only by `tests/unit/test_hosts.py`.
`list_hosts` has no production caller; every other `list_hosts` in the
repository belongs to the provisioning adapter's host service or its client.

**`resource_count` counts a retiring table.** `SystemService.get_health`
exposes it on both `HealthResponse` models.

## Decisions

### Freeze `compute_allocations`; do not drop it

The campaign's schema posture is additive-only until a deployment cycle
confirms a freeze never needed rolling back. The table has accumulated no rows
since the ledger moved to `kit/site`, so freezing costs nothing and dropping
gains nothing yet.

### Remove the routes rather than deprecate them

Both admin resource routes are pre-1.0 and have no caller in the repository.
A deprecation window would keep alive a `PATCH` whose docstring describes a
call that does not exist, which is how these surfaces outlived their callers.

### No delta specification

The requirement this work serves is `pools-9-retire-local-physical-authority`'s
and describes the terminal state, which this change reaches only in part. Two
changes adding overlapping requirements to one specification would leave
archival to reconcile them; one owns the requirement and the other removes dead
code toward it.
