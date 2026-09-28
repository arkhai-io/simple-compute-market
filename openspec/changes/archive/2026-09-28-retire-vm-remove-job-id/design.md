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

The mirror is not a copy on every stored row. Migration `20260707_001` added
`release_job_id` without backfilling it, so a reservation that already carried
`vm_remove_job_id` then holds its handle only in the mirror; the fallback
readers are what kept such a row's release pollable.

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
allowed to break, no consumer in the repository reads or sends the field, no
external compatibility commitment exists for it, and the alias would keep the
wrong name — it last stored a fulfillment id, not a
VM-removal job id — on a table bare-metal pools share.

The packages are published, so the repository cannot show that no outside
consumer reads the field; the removal rests on the absence of any commitment to
one, not on the absence of readers.

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

Before dropping, the migration reconciles the two columns row by row, because
the fallback readers are removed in the same release:

- **Mirror only** (`release_job_id` NULL, mirror set): the mirror's value
  becomes `release_job_id`. Every reader already treated the row that way, so
  this keeps the handle rather than choosing one; without it, a releasing row of
  this kind would stop being polled and be marked `release_failed` at the end of
  its grace period with its capacity still held.
- **Divergent** (both set, different values): the migration raises
  `SchemaDriftError` naming the reservations and changes nothing. Picking a
  winner is an operator decision; the error says how to resolve it.

The alternative, refusing on both cases, was rejected because a mirror-only
row has one unambiguous handle.

The migration exists because VM site databases are deployed, and it serves bare
metal too: bare-metal pools share the compute provisioning database, so no
bare-metal migration is needed. API credits needs none either. Its reservations
are never VM-mode, so its column has only ever held NULL; an existing API-credits
database keeps that column unmapped and unread, and databases it creates from
now on do not have it.

The drop takes its own migration ID rather than being folded into
`_migrate_capacity_model_cutover`, where the `vm_host`/`vm_target` drops sit.
That folding was justified because nothing built on the cutover had been
deployed, so no database could be in an intermediate state. Databases past the
cutover are deployed, so this state change is recorded as its own step.

### The drop is an approved exception to expand/contract

`docs/development/ARCHITECTURE.md` makes schema changes additive by default and
requires a non-additive change to use expand/contract across releases, and
`openspec/specs/deployment-state/architecture.md` asks for a plan naming the
period in which old and new readers coexist. Dropping the column in the same
release that stops writing it has no such period. This change takes that
exception deliberately, at the maintainer's direction.

The alternative, recorded because it is the rule's default, was to stop mapping
and writing the column now and drop it in a later change after one deployment
cycle, as `docs/development/ROADMAP.md` records for the VM storefront's frozen
columns. Rejected in favour of retiring the mirror in one step.

**What the exception costs.** The compute provisioning chart deploys with the
`Recreate` strategy and runs migrations in an init container. Rolling the image
back past this migration leaves the prior release's model mapping a column the
database no longer has: its schema-version check passes, because an extra
recorded migration is ignored, and its first reservation query fails.

**Recovery.** The column is nullable and every prior reader takes
`release_job_id` first, so the prior release needs only the column to exist. An
operator rolling back re-adds it empty before starting the prior image:

```sql
ALTER TABLE capacity_reservations ADD COLUMN vm_remove_job_id VARCHAR;
```

No backup restore is needed. The prior release then writes the mirror again as
it always did. Returning to this release afterwards leaves the re-added column
in place, unmapped and unread, because the drop is already recorded as applied;
it can be removed by the same helper whenever convenient.

### Every changed wheel takes a version bump

Every package whose wheel contents change takes a version bump. PyPI is
write-once, and publishing different bytes under an existing version is refused
by the publication gate, so an unbumped changed wheel cannot be released.

Before 1.0, an incompatible change takes a minor bump and an internal change a
patch. `docs/development/RELEASING.md` does not yet say so: read literally, its
policy sends any incompatible change to a major version, which would announce a
1.0 no one has decided on. The minor-bump convention is established practice:
`settle-listing-vocabulary`, `capacity-resource-administration`, and
`bare-metal-publication-reads-pool-declarations` each took a minor bump for a
0.x break. This change writes the convention into `RELEASING.md`'s versioning
policy rather than relying on it silently.

The alternative of following the written policy literally, with major bumps to
1.0.0, was rejected for the reason above.

| Package | Bump | Why |
|---|---|---|
| `arkhai-kit-site` | 0.5.0 → 0.6.0 | Model column, ledger keyword aliases, and payload key removed |
| `arkhai-vms-provisioning-operator-client` | 0.4.0 → 0.5.0 | `LeaseResponse` field removed; `LeaseUpdate` field renamed |
| `arkhai-vms-provisioning-adapter` | 0.3.0 → 0.4.0 | Served lease contract changes |
| `arkhai-compute-provisioning` | 0.7.0 → 0.7.1 | Reader drops a fallback |
| `arkhai-compute-provisioning-service` | 0.4.0 → 0.4.1 | New migration |
| `arkhai-bare-metal-provisioning-adapter` | 0.2.0 → 0.2.1 | Reader drops a fallback |
| `arkhai-vms-storefront` | 0.7.0 → 0.7.1 | An always-ignored event field is removed; behaviour is unchanged |

Three lower bounds rise because a consumer depends on the new version:

- `arkhai-compute-provisioning-service` requires `arkhai-kit-site>=0.6.0`. Its
  migration drops a column the older model still maps, so the pair must move
  together.
- `arkhai-vms-provisioning-adapter` requires
  `arkhai-vms-provisioning-operator-client>=0.5.0`. It reads
  `LeaseUpdate.release_job_id`, which older clients do not define.
- `arkhai-compute-provisioning-service` requires
  `arkhai-vms-provisioning-adapter>=0.4.0` in its `adapters` extra and its dev
  group. Adapter 0.3.0 reads `LeaseUpdate.vm_remove_job_id` and accepts client
  0.5.0, which no longer defines it, so the older bound admitted a pair that
  fails on every lease PATCH. The bare-metal adapter's bound stays: its older
  release only falls back to a payload key that is now absent.

Every `uv.lock` recording a bumped package is regenerated. Each project's
`reinit` target already upgrades and reinstalls its internal wheels, so the
regeneration is mechanical. Two Dockerfiles pin exact internal versions and move
with the bumps: `domains/vms/storefront/Dockerfile` pins
`arkhai-vms-storefront`, and `provisioning/compute/service/Dockerfile` pins the
service and both provisioning adapters.

### Model contracts are proved at unit level

`TESTING.md` assigns request and response model validation rules to unit tests
and the client-to-API contract to integration tests. Tests that exercise a real
database are integration tests: the migration test is created in the compute
provisioning service's `tests/integration`, and `kit/site`'s ledger tests, which
this change touches, move from its `tests/unit` to `tests/integration` as
`TESTING.md` requires of a library test when next touched. The operator client's lease
methods send and return plain dictionaries, so an integration test through the
client proves the route but never builds the client's models itself. The field
sets of `LeaseUpdate`, `LeaseResponse` and `ReleaseStartedEventRequest`, and the
deliberate decision to ignore the retired name rather than refuse it, are
therefore asserted by unit tests. The operator client has no test suite of its
own, and `TESTING.md` places client-contract guardrails with the service that
owns the contract, so its models are tested in the compute provisioning
service's unit suite; the storefront's event model is tested in the storefront's.

## Migration

The column is dropped through `_drop_columns_via_table_rebuild` in its own
compute-provisioning migration. Verified against a database that has the column
and one that does not, since the rebuild runs on both. The drop is irreversible
by the migration chain; rollback past it follows the recovery in "The drop is an
approved exception to expand/contract".

## Out of scope, recorded

- The storefront's own `compute_allocations.vm_remove_job_id` column stays.
  `remove-dead-storefront-physical-surfaces` freezes that ledger rather than
  dropping it.
- The retired `vm_leases` column's name remains in historical migrations, the
  legacy backfill, and the tests that build pre-migration schemas, because those
  exist to read databases that still hold it.
