# Design

## Context

Verified against the tree at planning time; task 1.1 re-runs every search
before anything is deleted.

**`compute_allocations` is a dead execution ledger.** `kit/site`'s
`CapacityReservation` is the authoritative allocation record. The storefront's
table has no production `INSERT`; a runtime write remains in the
release-`UPDATE` in `SQLiteClient.apply_resource_transition`, reached through
an attribute-path special case for `$.allocation_id` and
`$.compute_allocation_id`. Its readers, `held_gpu_counts` and
`held_gpu_counts_by_resource`, are exported from `domains/vms/listings` and
called by nothing. Migration code also adds columns and indexes and backfills
pool/member metadata. The previously cited CLI publish test file is absent
from the current tree; its purported test-only insertion is not a current
consumer.

**Physical identity crosses the service boundary as `None`.** `kit/site`
strips `vm_host` from the reservation it returns, so `reserved.get("vm_host")`
in `vm_fulfillment_service.py` is always `None`. The value is nonetheless
threaded through `register_lease`, `schedule_shutdown`, `provision_vm`,
`_do_provision`, and `_register_vm_lease_with_settings`; the code comment
records that it was kept only to avoid a signature change. The provisioning
adapter's own `vm_host` is the execution target and is unrelated.

**Two admin routes have no production or executable e2e caller.** `GET`/`PATCH
/api/v1/admin/portfolio/resources/{resource_id}` and the clients'
`get_resource`/`patch_resource` have no production caller. `PATCH`'s
docstring describes a provisioning-service `LeaseWatchdog` call that does not
exist; the provisioning service's only reverse call is the `capacity_released`
event. The two full-deal e2e files mention the PATCH route only in stale
watchdog-connectivity docstrings. Integration tests, the administrator
authentication mapping, and client signing tests still exercise the route.

**`release_reservations` has a legacy half.** Beside the authoritative
`_release_site_ledger_holds`, a loop normalizes local `resources` rows that
the projection no longer feeds. Local listing derivation remains selectable,
including for the second storefront, so those local rows have not yet lost
their operational role. E2e cleanup calls this endpoint. Its obsolete
watchdog explanation does not prove the local-row loop is unused.

**Four `SQLiteClient` methods have no production caller.** `delete_resource` and
`ensure_default_resources` have zero references, tests included.
`host_capacity_remaining` is referenced only by `tests/unit/test_hosts.py`.
`list_hosts` has no production caller; every other `list_hosts` in the
repository belongs to the provisioning adapter's host service or its client.

**`resource_count` is a live diagnostic contract.** `SystemService.get_health`
exposes it on both `HealthResponse` models. The "Operator-visible acceptance
state" requirement in `openspec/specs/storefront-publication/spec.md` requires
it when local resource rows are absent. The smoke test, both VM full-deal
scenarios, `docs/seller-quickstart.md`, and
`docs/development/VALIDATION_RUNBOOK.md` consume it to diagnose CSV seeding.

**The allocation test file contains surviving coverage.**
`test_compute_allocations.py` contains local listing derivation, member
availability, cross-site identity, and negotiation hold-persistence tests
alongside the allocation schema assertions. Removing the ledger does not
retire those behaviors. `test_hosts.py` likewise exercises `list_hosts` as
well as `host_capacity_remaining`.

## Decisions

### Freeze `compute_allocations`; do not drop it

The campaign's schema posture is additive-only until a deployment cycle
confirms a freeze never needed rolling back. Absence of a current insertion
path does not establish that an operator's historical table is empty. Existing
table contents and schema therefore remain intact; fresh databases stop
creating the table, and current runtime and migration code stop modifying it.

The freeze covers index creation in both the bootstrap and migration paths,
column additions, and the allocation update in `_backfill_compute_pools`.
Historical migration IDs remain stable. A fresh database, a database with an
existing allocation table, and repeated initialization must all satisfy the
freeze without discarding unrelated local-inventory or hold-persistence
coverage. These are acceptance constraints for revising the existing
checklist; this discussion does not establish a new implementation sequence.

### Remove the routes rather than deprecate them

Both routes are pre-1.0 and have no production or executable e2e caller.
The accepted decision is to remove them with their models, client methods,
and route authentication contracts. Route-specific tests retire with the
routes; generic administrator signing and synchronous/asynchronous client
parity coverage must use a supported operation.

Alternatives considered:

- Keep the routes for future e2e state setup. Rejected: modifying a storefront
  resource row does not modify the authoritative site's reservation or
  fulfillment state. Existing site reservation APIs, provisioning lifecycle
  controls, and mock execution gates provide the appropriate scenario seams.
- Deprecate until the local-inventory cutover. Rejected: no running scenario
  relies on either route, and the stale PATCH references are explanatory text
  to correct rather than a compatibility dependency.

Revisit only if a concrete scenario identifies state it must establish that
the authoritative seams cannot express; review that missing seam and its
owner before retaining a local physical-state mutation.

### Retire local cleanup and resource-count diagnosis with local inventory

The user accepted deferring the local-row half of `release_reservations` and
`resource_count` to `pools-9-retire-local-physical-authority`. That change owns
the local listing path, CSV import, scenario seeding, and operator migration.
Their supporting diagnostics and cleanup retire at the same boundary.

Removing both here would require revising the normative resource-count
scenario, smoke and deal assertions, and operator guidance while their local
inventory source still exists. Replacing the diagnostic with projection state
alone would also stop checking whether the CSV importer and storefront use
the same database. Keeping the field but removing cleanup alone would leave
the selectable local path without its existing normalization during cleanup.

The replacement operator diagnostic is a cutover design question for
`pools-9`; this change does not select its response shape or acceptance rule.

### No delta specification

The requirement this work serves is `pools-9-retire-local-physical-authority`'s
and describes the terminal state, which this change reaches only in part. Two
changes adding overlapping requirements to one specification would leave
archival to reconcile them; one owns the requirement and the other removes dead
code toward it. The resource-count requirement and its Evidence entry remain
current until `pools-9` resolves and promotes their replacement.

## Design review disposition

The scope decisions above are settled, and the existing checklist records the
migration, authentication, and test-ownership corrections. Planning and
implementation remain separate next steps.
