# Design

## Context

`CapacityLedgerService._sync_release_job_fields` writes `vm_remove_job_id`
only when `offering_mode` is the VM mode and always to the value
`release_job_id` already holds. Four ledger methods accept the name as an alias
that collapses to `release_job_id or vm_remove_job_id`: `begin_releasing`,
`update_lease_fields`, `update_lease_fields_in_session`, and
`update_reservation_state`. (`attach_lease`, named in an earlier draft of the
proposal, takes no such argument.) Three readers fall back to the payload key
(`compute_provisioning/lease_lifecycle.py`, the VM adapter's
`leases_controller.py`, the bare-metal adapter's
`bare_metal_leases_controller.py`); each reads `release_job_id` first.

The name also appears on three wire models:

- `vm_provisioning_operator.models.LeaseResponse`, published by the VM
  adapter's lease routes beside `release_job_id`.
- `vm_provisioning_operator.models.LeaseUpdate`, the lease PATCH body. It has no
  `release_job_id` field: the adapter maps `body.vm_remove_job_id` onto the
  generic `ExecutorLeaseUpdate.release_job_id`, so this is the only way to set
  the handle through PATCH.
- `market_storefront`'s `ReleaseStartedEventRequest`, the body of the admin
  `release-started` fulfillment event. This is not a lease contract. The
  controller forwards the value into `_apply_fulfillment_event`'s `**_extra`,
  where it is discarded, and nothing in the repository sends the event.

That spread is why the first attempt (in `fix-vm-fulfillment-capacity-boundary`,
task 10.5) was withdrawn: it was a public-model change, not a column drop.

Two services build `capacity_reservations` from the `market_site` model. The
compute provisioning service owns a versioned migration chain for it, and VM
site databases built on that chain are deployed. The API-credits service
creates the table through `create_all` from the same model; its reservations are
never VM-mode, so its mirror column has only ever held NULL.

On a fresh compute provisioning database, `create_all` builds
`capacity_reservations` from the model before migrations run. No historical
migration writes the mirror: the legacy lease backfill reads the retired
`vm_leases` table's column of the same name and writes only fulfillment rows.
Dropping the column from the model therefore breaks no earlier migration.

## Decisions

### Outright removal with a version bump

The field is removed from `LeaseResponse` and `ReleaseStartedEventRequest`, and
renamed on `LeaseUpdate`, in one step.

The alternative is a one-way alias, as the deprecated `listing_mode`
cardinality name has: accept the old field for a window while publishing only
the new one. Rejected because every API in the repository is pre-1.0 and is
allowed to break, no consumer outside the repository reads the field, and the
alias would keep the wrong name — it last stored a fulfillment id, not a
VM-removal job id — on a table bare-metal pools share.

**Revisit trigger:** a consumer outside the repository reporting that it reads
`vm_remove_job_id` from a lease. That reopens an alias, applied to the response
only.

### The PATCH body names the handle `release_job_id`

`LeaseUpdate.vm_remove_job_id` becomes `LeaseUpdate.release_job_id`, mapped to
`ExecutorLeaseUpdate.release_job_id` unchanged. An operator keeps the ability to
correct a lease's release handle, under the name every lease response and the
generic executor lease service already use.

The alternative was to remove the field without a replacement. The lifecycle
writes the handle itself and nothing in the repository sends it through PATCH,
so nothing would break. Rejected because it removes an operator repair path as
a side effect of a rename.

### The retired name is not refused

A lease PATCH still carrying `vm_remove_job_id` is treated exactly as one
carrying any other unknown field: `LeaseUpdate` ignores it, as it does today for
every field it does not define. The contract behaves as though the field never
existed.

The alternative was an explicit refusal naming `release_job_id`, so a stale
caller learns at the boundary rather than through a silent no-op. Rejected
because there is no compatibility commitment to outdated clients before a major
version release, and a refusal would be the only field-specific rule on a model
whose unknown-field policy is otherwise uniform. Refusing unknown fields across
the lease models (`extra="forbid"`) was also considered and is out of scope: it
changes the contract for every field, not this one.

**Revisit trigger:** the first major version release, which is when a
compatibility policy for older clients is set; the unknown-field posture of the
lease models belongs to that decision, not to this one.

### The storefront event field is removed, not refused

`ReleaseStartedEventRequest.vm_remove_job_id` and the argument forwarding it are
removed. The value was always discarded, so removing it leaves behaviour
identical: a sender, if one existed, is ignored before and after. The event is
not a lease contract, so the one-release-handle requirement does not govern it.

### One migration, in compute provisioning, under its own ID

The column is dropped from compute provisioning databases by a new versioned
migration appended to `MIGRATIONS`, using `_drop_columns_via_table_rebuild`, the
helper `vm_host` and `vm_target` left this table by. The helper is a no-op where
the column is absent, so a database created from the current model migrates
unchanged.

The migration exists because VM site databases are deployed. Bare-metal pools
share the compute provisioning database but bare metal has never been released,
so it needs nothing of its own. API credits has never been released either: no
migration is added to its chain, and its model change applies to databases it
creates from now on. An existing API-credits development database may be
recreated; this stage permits destructive changes to it.

The drop takes its own migration ID rather than being folded into
`_migrate_capacity_model_cutover`, where the `vm_host`/`vm_target` drops sit.
That folding was justified because nothing built on the cutover had been
deployed, so no database could be in an intermediate state. Databases past the
cutover are deployed, so this state change is recorded as its own step.

### Every changed wheel takes a version bump

Every package whose wheel contents change takes a version bump. PyPI is
write-once, and publishing different bytes under an existing version is refused
by the publication gate, so an unbumped changed wheel cannot be released. Per
`docs/development/RELEASING.md`'s SemVer policy, a pre-1.0 contract break takes a
minor bump and an internal change a patch:

| Package | Bump | Why |
|---|---|---|
| `arkhai-kit-site` | 0.5.0 → 0.6.0 | Model column, ledger keyword aliases, and payload key removed |
| `arkhai-vms-provisioning-operator-client` | 0.4.0 → 0.5.0 | `LeaseResponse` field removed; `LeaseUpdate` field renamed |
| `arkhai-vms-provisioning-adapter` | 0.3.0 → 0.4.0 | Served lease contract changes |
| `arkhai-compute-provisioning` | 0.7.0 → 0.7.1 | Reader drops a fallback |
| `arkhai-compute-provisioning-service` | 0.4.0 → 0.4.1 | New migration |
| `arkhai-bare-metal-provisioning-adapter` | 0.2.0 → 0.2.1 | Reader drops a fallback |
| `arkhai-vms-storefront` | 0.7.0 → 0.7.1 | An always-ignored event field is removed; behaviour is unchanged |

Two lower bounds rise because a consumer depends on the new version:

- `arkhai-compute-provisioning-service` requires `arkhai-kit-site>=0.6.0`. Its
  migration drops a column the older model still maps, so the pair must move
  together.
- `arkhai-vms-provisioning-adapter` requires
  `arkhai-vms-provisioning-operator-client>=0.5.0`. It reads
  `LeaseUpdate.release_job_id`, which older clients do not define.

Every `uv.lock` recording a bumped package is regenerated. Each project's
`reinit` target already upgrades and reinstalls its internal wheels, so the
regeneration is mechanical.

## Migration

The column is dropped through `_drop_columns_via_table_rebuild` in its own
compute-provisioning migration. Verified against a database that has the column
and one that does not, since the rebuild runs on both.

## Out of scope, recorded

- The storefront's own `compute_allocations.vm_remove_job_id` column stays.
  `remove-dead-storefront-physical-surfaces` freezes that ledger rather than
  dropping it.
- The retired `vm_leases` column's name remains in historical migrations, the
  legacy backfill, and the tests that build pre-migration schemas, because those
  exist to read databases that still hold it.
