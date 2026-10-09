# Design

## Context

Verified against the tree at planning time and re-grounded on 2026-10-08
(task 1.1, recorded under "Re-grounding" below); re-verify before
implementing.

**Two listing sources exist.** `available_compute_slices` in
`domains/vms/listings/src/arkhai_vms_listings/reconciler.py` reads the site
projection when its `site_pool_projection` argument is a mapping and
`_pool_rows_from_local_tables` when it is `None`. The storefront chooses that
argument in one place, `listing_source_projection()` in
`services/capacity_client.py`, which returns `None` while
`use_site_projection_for_listings` is `false`; `_projection_enabled()` in
`services/listing_sources.py` reads the flag separately for listing backing.
Every derivation caller — the publication loop, the listing-source check,
failure actions, two admin routes, capacity-change reconciliation, and the
pool-override service's status source — goes through that selector, so
retiring the local path retires it for all of them.

**The local tables mix physical and commercial columns.**

| Table | Physical columns | Commercial columns |
|---|---|---|
| `resources` | `resource_type`, `resource_subtype`, `unit`, `value`, `state`, `attributes` | `min_price`, `token`, `max_duration_seconds`, `accepted_escrows` — read only by a legacy-resources fallback that is reachable only when `compute_capacity_pools` and `compute_pool_members` are absent, a state no migrated deployment is in |
| `hosts` | all | none; its marketing columns (`cpu_type`, `motherboard`, `host_ram_gb`, `datacenter_grade`, network fields) are unread by publication |
| `compute_pool_members` | all | none |
| `compute_capacity_pools` | `total_gpu_count` | `gpu_model`, `region`, `sla`, `min_price`, `token`, `accepted_escrows`, `settlements`, `max_duration_seconds`, `seller_id`, policy ids |
| `resource_transition_events` | all (audit trail of `resources` mutations) | n/a; existing rows are history and are not deleted |

**The only writer of the local tables is CSV import.**
`SQLiteClient.upsert_resource` → `_sync_compute_pool_for_resource` issues the
one `INSERT … ON CONFLICT` that fills `compute_capacity_pools`, physical and
commercial columns alike. It is reached from
`POST /api/v1/admin/portfolio/resources/import`, the `portfolio import-csv`
command, and startup seeding (`_seed_resources_if_empty` →
`SystemService.seed_resources_if_empty`, sourced from `resources_csv_inline`,
`resources_csv_path`, or `/app/resources.csv`). Helm (`_helpers.tpl`,
`secrets.yaml`, `values.yaml`), compose (`compose/seller.yml`,
`domains/vms/compose.yml`), and the seller quickstart carry that contract.
Seeding silently skips when it finds no source, so an upgraded deployment
with CSV configuration would start with no inventory and no error.

**Two storefront override tiers exist.** The site-scoped store
(`kit/pool-overrides`, keyed by `(site_id, pool_id, offering_mode)`, with
authenticated routes, typed clients, and `market-storefront pool-override
set/show/list/delete`) is the top tier. Beneath it `_tier()` falls back to the
home-site legacy record: `compute_capacity_pools`' commercial columns, read by
`_local_pool_pricing`, keyed by `pool_id` alone. Each field a pool takes from
the legacy record is reported in `legacy_overrides_in_effect` and on system
status. Two legacy fields have no site-scoped equivalent: `region` (the store
forbids it as a physical fact; the pool hint declares it) and
`accepted_escrows` (superseded by `settlements` clauses). The `inactive`
override state exists only for local-table derivation.

**Region, SLA, and pricing have projection equivalents.**
`kit/resource-pools/hints.py` defines the region, SLA, and pricing policy tags,
projected through a pool's `policy_tags` and resolved as a tier by
`_projected_pool_rows`. The legacy record is not filling a projection gap; it
is a second override tier with no write path once the import is gone.

**No deployed storefront depends on the local path any more.** The
multi-storefront repair gave Alice her own provisioning authority and removed
her `use_site_projection_for_listings = false` opt-out. Both seller TOMLs
still set `resources_csv_path`, and compose still mounts the bundled CSV for
both storefronts, so both still seed local tables at startup that the
projection path reads only through the legacy override tier.

**Multi-dimensional capacity is declarable at the site.** The registration API
and capacity-definition documents accept every dimension a resource names, so
the CSV path is not the only expression of it.

**Local inventory still has diagnostics and cleanup consumers.**
`SystemService.get_health` reports `resource_count` through both health models.
The "Operator-visible acceptance state" requirement in
`openspec/specs/storefront-publication/spec.md` prescribes it, and the smoke
test, both VM full-deal scenarios, `docs/seller-quickstart.md`, and
`docs/development/VALIDATION_RUNBOOK.md` use it to diagnose CSV seeding.
`release_reservations` normalizes local held resource rows beside its
authoritative site-ledger release operation, and e2e cleanup calls that route.
Those consumers retire with this change's local-inventory cutover.

### Re-grounding (2026-10-08)

Confirmed unchanged: the legacy-resources fallback is unreachable, because
migration `20260604_002` creates both `compute_capacity_pools` and
`compute_pool_members` on every database. The legacy tier (`_tier()`, the region
fallback, `legacy_overrides_in_effect`) is as described above. The projection
count semantics the earlier count design relied on hold against
`kit/site/src/market_site/projections.py` (capacity groups count enabled
declarations, including exhausted ones; resource-pool members include disabled
declarations), though status no longer reports a count.

Drift from the earlier plan:

- **Paths.** The listings package is
  `domains/vms/listings/src/arkhai_vms_listings/`.
- **Source selection is an argument.** Beyond the flag, every derivation entry
  point treats `site_pool_projection=None` as "use local tables", and the
  storefront wrappers (`close_stale_compute_listings_after_capacity_change`,
  `reopen_available_compute_listings_after_capacity_change`) default it to
  `None`. Retirement makes the projection a required argument. The derivation's
  `home_site` parameter is now used only to scope the legacy tier and the local
  path, so it becomes removable too.
- **`inactive` is defined in `kit/pool-overrides`.** `OVERRIDE_INACTIVE`, the
  `ProjectionSource` type that admits `None`, `override_state()`, the package
  exports, and the kit's status unit test carry it. Bare metal's projection
  source never returns `None`. The earlier claim that `kit/pool-overrides` is
  unaffected was wrong (decided: "The pool-override kit loses `inactive`").
- **A CSV pricing migration exists.** `market-storefront config migrate --scope
  publication --inventory <csv>` (`migrate_publication_csv`) rewrites legacy
  prices inside a resource CSV. It is described by the "Publication pricing
  migration is preview-first and atomic" and "Per-resource settlement input
  uses the common clause contract" requirements, by
  `openspec/specs/storefront-publication/architecture.md`, by
  `openspec/specs/settlement-configuration/architecture.md`, by
  `docs/development/DEPLOYMENT_AND_CONFIG.md`, and by the seller quickstart
  (decided: "The CSV pricing migration retires with CSV import").
- **Bare metal shares the status surface.** The bare-metal storefront reports
  its own top-level `resource_count` (open, unpaused bare-metal listings) and
  builds the shared `ProjectionFamilyStatus` from a version-only fetch that
  holds no generation. Its tests read `resource_count` through the shared
  `core/storefront-client` `HealthResponse` (decided: "Status reports no
  resource count").
- **`remove-dead-storefront-physical-surfaces` is coupled, not independent.**
  Its resource routes, host helpers, and the `compute_allocations` indexes in
  migration `20260604_002` read or build on the tables this change stops
  creating. Decided: that change lands first (see "The zero-caller removal
  lands first").
- **Freeze mechanics.** `_ensure_domain_tables` drops and recreates
  `trg_resources_updated_at` on every startup, so it would change retained
  schema unless it stops touching the retired tables. The migration runner
  already supports `Migration.required_tables`, which skips a migration
  without recording it when a table is absent (open decision D5).
- **More CSV consumers.** `resources_csv_path` in both seller TOMLs and Alice's
  compose mount; `domains/vms/storefront/Makefile` and `helm/Makefile`
  `RESOURCES_CSV_FILE` wiring; `helm/fixtures/eip191-evm-values.yaml` and the
  chart `values.yaml`'s `resources_csv_path`; the administrator route contract
  and multipart signing descriptor in `middleware/admin_identity.py`; both
  `ImportResourcesResponse` models; the bundled inventory CSVs and
  `test_bundled_inventory.py`; `test_accepted_escrows_csv_dsl.py`; and
  `scripts/tests/test_multi_storefront_compose.py`'s flag assertion.
  `_helpers.tpl` now carries one CSV site, not two.
- **E2E consumers.** Six files import CSV; the repair already migrated
  `test_multi_registry.py`. `test_compute_dynamic_listings.py` imports rows
  whose `pool_id` matches its projected pools, so the legacy tier currently
  supplies those pools' SLA and region. The other imports' pool identifiers
  match no projected pool and look vestigial; planning confirms each.
- **Dead models and adapters.** Once import retires, models and adapter code
  that only the importers use may have no caller left (open decision D6).
- **Local-table wording elsewhere.** "A site whose projection is not held holds
  its listings" and `ARCHITECTURE.md`'s "Storefront capacity boundary" still
  contrast projection derivation with local tables. The statements stay true
  after retirement but describe a mechanism that no longer exists. The delta
  modifies the requirement to drop the local-table clauses, and promotion
  corrects `ARCHITECTURE.md`.

## Goals / Non-Goals

**Goals:** one listing source; no storefront physical authority; one storefront
override tier; no operator contract that fills retired tables; a freeze an
operator can roll back from by reverting code.

**Non-Goals:** a per-pool commercial write path (exists); carrying legacy
values forward; dropping schema; the zero-caller surfaces and the provider
rule (own changes); bare-metal publication (only bare metal's status count
retires here).

## Decisions

### Freeze, then redirect; no `DROP`

The migration stops creating and writing the retired tables, columns,
triggers, and indexes and redirects every read to the projection. The schema
stays so a code rollback or an operator seeding provisioning finds its data.
Fresh databases omit the retired schema; upgraded databases preserve existing
tables, columns, triggers, indexes, and rows unchanged. Current storefront code
does not read or write that data for any purpose, including startup and status.
A `DROP` is a later change, after a
deployment cycle shows the freeze never needed reverting. This matches the
additive-only posture of every other schema change in the campaign.

Rollback past this change is a code operation, not a configuration flip;
operator documentation says so explicitly. Retention preserves historical
data, not a current inventory snapshot: once provisioning changes physical
state, an operator must reconcile the retained data against current site state
before resuming an older storefront version or using it to seed provisioning.
Restoring stale inventory alone does not establish safe availability.

Retained rows can inform an operator's provisioning host inventory, pool
definitions, and capacity declarations through the existing provisioning
administration surfaces. This does not add an automatic transfer command or
overwrite live site state. Commercial values still follow the independent
override decision below; retaining mixed historical rows does not keep their
commercial tier active.

The terminal contract prohibits active storefront physical authority, rather
than requiring all historical physical records to be absent. Its fresh-boot
and upgrade scenarios distinguish these database populations explicitly.

### The legacy override tier retires with the import, without carry-over

The legacy record is written only by CSV import and read only by
`_local_pool_pricing`. Retiring the import leaves it write-only-in-the-past,
so it retires with the import. On upgrade a home-site pool that took a field
from it resolves that field from the pool hint, then the configured default.
The operator re-enters any value they want to keep through `pool-override set`
before upgrading; the system-status report already enumerates the pools and
fields.

Alternatives:

- *A gate in the freeze migration*, refusing to run while a legacy row carries
  a non-null commercial column with no site-scoped override for the same pool
  unless acknowledged. Rejected: machinery for a population the status report
  already enumerates; the operator guidance carries the instruction.
- *A preview-first `pool-override import-legacy --site <id>` command* on the
  publication-pricing migration pattern. Rejected: one-shot code, dead after
  it runs, copying a price the operator typed into a CSV once; and two of the
  eight fields cannot be copied — `region` (the store forbids it) and
  `accepted_escrows` (its only conversion is the clause interpretation the
  pricing migration already refuses when ambiguous).
- *Keeping the tier read-only beneath the store.* Rejected: with the write
  path gone the rows can only decay, the physical/commercial mixed table
  survives the change whose purpose is removing it, and `_tier()` keeps two
  levels forever.

Revisit trigger: a seller with many home-site pools reporting that re-entry
through the CLI is impractical. That reopens the import command, not the gate.

Consequences the guidance must state: `region`'s legacy fallback disappears,
so a home-site pool whose region came from the CSV needs `region` declared on
its pool hint before upgrading; `accepted_escrows` has no equivalent other
than a `settlements` clause list.

### The cutover requires both storefronts to consume projections

Deleting the local path would have left Alice with no listing source until she
had a working provisioning authority. `repair-multi-storefront-scenario` owned
that prerequisite and uses separate provisioning services for Alice and Bob.
Multiple storefronts per site are explicitly out of scope; this decision
supersedes the earlier shared-authority requirement.

That repair was kept separate and is complete (archived 2026-10-01): Alice
derives from provisioning-seeded projections without her local-path opt-out,
both storefronts use their respective authorities, and the 21-stage
two-storefront scenario passed with no skips in a full local pipeline run.

### Retire the local inventory contract in one coordinated cutover

Local derivation, CSV import, startup seeding, deployment and CLI wiring,
legacy overrides, local diagnostics and cleanup, and the fresh-schema freeze
form one supported contract until their replacement is ready. Retire them
together after the separate multi-storefront repair is complete. Existing
task section numbers organize the work; they do not define independently
deployable intermediate states.

The prior claim that CSV removal and the freeze can land first is superseded.
While local derivation and its writers remain supported, fresh databases still
need their schema. Removing its creation or its inventory-input contract in
isolation would leave a supported configuration without a working inventory
path. Updating source consumers, test seeding, and diagnostics belongs in the
same cutover before it is offered for deployment.

Alternatives:

- *Fold multi-storefront support into this change.* Rejected: keep its trust
  configuration design and acceptance boundary in the existing separate change.
- *Ship the freeze or CSV removal before local derivation retires.* Rejected:
  that intermediate state does not preserve the supported inventory contract.

Read-only re-grounding, design, and planning can proceed beforehand. Independent
zero-caller cleanup and pool-provider immutability remain separate changes.

### Commercial rows are storefront-owned; the site-scoped store is where they live

`ARCHITECTURE.md`'s authority boundaries assign listing, negotiation, deal,
and seller-policy state to the storefront and pool metadata and provider
configuration to the resource-pool service. Per-pool commercial values are
therefore correctly storefront-owned, and the site-scoped store is the
architecturally right home. This bounds the change: the terminal state is no
*physical* authority in the storefront, not no per-pool rows.

### The contract modification is a replacement, not an amendment

The "Storefront pool overrides are site-scoped and durable" requirement loses
its legacy-record paragraph, its `inactive` state, and two scenarios ("An
override is deleted over a legacy value", "Listings derive from local
tables"). A modified requirement cannot drop scenarios, so the delta removes
it and adds "Storefront pool overrides are the only override tier", carrying
every other paragraph and scenario forward and adding one for a home-site
pool with no override.

### Independent work is not held behind the cutover

The cutover's start trigger is a repository-owner judgment with no fleet-wide
signal to gate on. Work that lands alone — fixing a pool's provider at
creation, and removing the storefront's zero-caller physical surfaces — is
not held behind it; each is its own change.

### The zero-caller removal lands first

`remove-dead-storefront-physical-surfaces` is implemented before this change.
It was recorded as independent in either order, but the freeze here stops
creating `resources` and `hosts` on fresh databases, and that change's
surfaces still read them: the resource `GET`/`PATCH` routes reach
`get_resource` and `apply_resource_transition`, `list_hosts` and
`host_capacity_remaining` read `hosts`, and migration `20260604_002` builds
two indexes on `compute_allocations`. Landing this change first would leave
those surfaces failing on fresh databases, or require this change to absorb
their removal.

Alternatives:

- *Absorb the overlapping removals here when this change lands first.*
  Rejected: this change is already the larger cutover, and the zero-caller
  removal has no dependency on it.
- *Merge the two changes.* Rejected: the zero-caller removal needs no operator
  migration and should not wait on this cutover's operator and test work.

Consequences: this change's freeze covers only the local inventory tables,
since `compute_allocations` is already frozen when it starts. Task 4.5 deletes
only the methods whose remaining callers this change removes:
`release_reservations`' local loop, the status count, the validator, and the
importers.

### The pool-override kit loses `inactive`

`kit/pool-overrides` drops the `inactive` state entirely: `OVERRIDE_INACTIVE`
and its export are deleted, and `ProjectionSource` and `override_state()`'s
`projection` argument stop admitting `None`. The only producer of `None` was
the VM storefront's local-path selection, which this change deletes; bare
metal's source already returns a mapping, `{}` when no generation is
recorded. A storefront holding no projection passes `{}`, and every override
it stores then reads `unknown`, which is true. The kit's states then match the
contract's four exactly.

Alternatives:

- *Keep `None` and treat it as `{}`.* Rejected: it keeps a nullable contract no
  caller uses, and a composition that wires a source returning `None` by
  mistake would report a believable `unknown` instead of failing.
- *Keep `inactive` in the kit and retire it only from the VM contract.*
  Rejected: the kit would define a state the contract does not list, against
  its rule that every override is in exactly one of the listed states, and
  keep a branch nothing exercises.

Consequences: a small breaking change to an internal pre-1.0 wheel. Only the
kit's own status test imports the constant. The VM composition root passes
the projection read that replaces `listing_source_projection()` as the
override service's source.

### The CSV pricing migration retires with CSV import

`market-storefront config migrate --scope publication --inventory <csv>`
(`migrate_publication_csv`) rewrites a resource CSV's legacy `min_price` and
`token` into a `settlements` column. Once CSV import retires nothing reads
that file, so the migration has no consumer. Its one remaining use, preparing
values before an upgrade, runs on the pre-upgrade version, which still ships
it. Its rows are per resource while overrides are per site, pool, and offering
mode, so its output does not map onto override records either; a direct
converter was already rejected (see the legacy-tier decision above).

`--inventory`, `migrate_publication_csv`, and its CSV-only cases retire here.
The TOML publication migration and its shared helpers stay. Two requirements
are modified rather than left describing a retired input:

- "Publication pricing migration is preview-first and atomic" covers TOML
  configuration only. Its conflict list names per-model legacy pricing, which
  the TOML migration refuses, in place of per-row pricing and conflicting
  config and row values, which only CSV rows could produce.
- "Per-resource settlement input uses the common clause contract" is replaced
  by "Settlement input uses the common clause contract", which no longer lists
  imported resource records. Its scenario becomes a storefront pool override's
  clauses replacing the configured defaults for that pool's listings, the
  behaviour the CSV row used to supply. A modified requirement cannot drop
  its only scenario, so this is a replacement under a new name, as with the
  override requirement above.

Alternatives:

- *Keep `--inventory` as a standalone converter.* Rejected: its output has no
  reader, and two requirements would keep describing a retired format.
- *Retire it in a follow-up change.* Rejected: between the two changes the
  contract would describe an input the system no longer supports.

Operator guidance says to run any CSV pricing migration on the current version
before upgrading if its output is wanted as a reference for re-entering
values through `pool-override set`.

### Local diagnostics and cleanup retire with the cutover

The design review of `remove-dead-storefront-physical-surfaces` transferred
`resource_count` removal and the local-row half of `release_reservations`
here. Both remain supported while the local listing path and CSV import
remain supported. Their removal belongs to the same operator and test
migration as their inventory source; the site-ledger release operation
continues to own authoritative cleanup.

Removing them in the independent cleanup change was rejected. The count is
required by a current permanent scenario and read by running e2e checks,
and removing the local cleanup loop while local derivation remains available
would discard an existing recovery operation before its inventory retires.

### Status reports no resource count

No storefront's system status reports a `resource_count`, and none is added
beneath `site_projections`. The VM storefront's top-level field, the core
`HealthResponse` field, bare metal's top-level field, and the shared typed
client's field all retire. Each question the field was used to answer already
has a better signal:

- **Can the storefront see inventory at a site?** Per-site, per-family
  projection state and identity on the status surface and the administrator
  projection refresh route, required by `site-capacity`'s "Per-site projection
  load-state visibility". The VM e2e host-registry helper already asserts on
  those states. What a loaded generation contains is read from the site's own
  projection or provisioning's inventory administration surfaces.
- **Is the storefront selling anything?** The storefront's listings and the
  per-site `publication_derivation` report, which explains why a pool
  publishes nothing.
- **Did an inventory import fail?** Provisioning, which owns import, reports
  it through its import API and status. A storefront cannot tell an
  intentionally empty site from a failed import.

Provenance. The VM field was added in May 2026 to catch one failure: the CSV
importer writing to a different SQLite file than the server read, which left
the storefront answering every negotiation with `no_matching_inventory`. It
counts local `resources` rows. Since projection-backed derivation became the
default, neither publication nor the round-zero inventory guard reads those
rows, so the field no longer tracks whether a storefront can sell; in the e2e
stack it reads 1 only because both storefronts still mount the bundled CSV.
Its failure mode retires with the importer. Bare metal's field was added in
July 2026 for status-shape parity but counts open, unpaused bare-metal
listings, a publication outcome under the same name. The permanent scenario
that requires the field was written in July 2026 to record existing
behaviour, not to choose it. No production code reads either field; its
readers are the smoke test, the two full-deal scenarios' stage 00f, one
bare-metal HTTP test, the validation runbook, and the seller quickstart.

Alternatives:

- *Per-site, per-family projection counts* (the earlier decision in this
  change). Rejected: the e2e readiness checks it would serve already assert
  on projection state, and the projection's content is readable at its
  source. A count would add a second status contract whose zero, null, and
  stale semantics need their own specification and tests, and bare metal,
  which fetches only projection versions from its health probe, could not
  fill it.
- *Unify by meaning:* per-family inventory counts plus a shared open-listing
  count. Rejected: the listings API already answers the publication question,
  and a status counter would duplicate it.
- *Keep the field for bare metal only.* Rejected: one typed client field
  would carry two meanings, and its only reader is a test.

Bare metal is touched only to delete its status field and the listing count
behind it; its publication is unchanged. Liveness health and global
negotiation-pause behavior are unchanged. The permanent home is
`openspec/specs/storefront-publication/spec.md`'s replacement for
"Operator-visible acceptance state".

## Risks / Trade-offs

- **An operator upgrades with legacy values still in effect** → a silent
  commercial change to the hint or configured default. Mitigated by the
  status report and the guidance; accepted rather than gated (see above).
- **An operator upgrades with CSV configuration** → no inventory, no error.
  Mitigated by migration guidance that names the provisioning-side
  declaration path and by the seeding stack's removal making the
  configuration keys unknown.
- **Retained inventory is mistaken for current supply** → an unsafe rollback
  or provisioning seed. Guidance requires checking current site state before
  using the historical records; current storefront code never consults them.
- **The zero-caller removal lands later than expected** → this cutover's
  implementation waits; design and planning continue against the current
  tree, and planning re-grounds the method list after it lands.

## Migration Plan

1. Complete `repair-multi-storefront-scenario` separately, including its
   projection cutover and passing two-storefront evidence. Done (archived
   2026-10-01).
2. Re-verify the confirming searches against that resulting tree
   (legacy-resources fallback reachability and the remaining CSV consumers).
   Reconcile any files or scenario stages the prerequisite already migrated.
   Done 2026-10-08; see "Re-grounding".
2a. Land `remove-dead-storefront-physical-surfaces`, then re-check the
   `SQLiteClient` method list and migration `20260604_002` against the tree it
   leaves.
3. Prepare projection counts, provisioning-seeded tests, and operator guidance
   together with retirement of local derivation, the flag, legacy overrides,
   CSV import, startup seeding, deployment and CLI wiring, and local cleanup.
4. Apply the fresh-schema freeze in the same coordinated cutover, preserving
   existing historical data. No partial retirement is an independently
   deployable outcome.
5. Validate fresh and populated databases, the affected suites, packaging,
   and the end-to-end pipeline; complete the planned closeout.

Rollback requires earlier code and reconciliation of retained historical data
with current site state before trading resumes; no `DROP` has happened.

## Open Questions

The resource-count diagnostic decision is resolved above: status reports no
resource count.

The repository work order is decided: the separate multi-storefront repair
(done), then `remove-dead-storefront-physical-surfaces`, then the coordinated
retirement. Each self-hosting operator still selects their deployment time
after preparing site inventory and commercial overrides; there is no
fleet-wide rollout signal to wait for.

Open decisions raised by the 2026-10-08 re-grounding (D1–D4 are decided
above). Each gates the tasks named; no task prescribes an answer until the
decision is recorded above.

- **D5 — freeze mechanics.** How fresh databases skip the retired tables'
  migrations and bootstrap, and what an upgraded database with a pending
  legacy migration does. Gates tasks 4.4 and 6.1–6.2 and the delta's upgrade
  scenario.
- **D6 — code left without a caller.** Whether models and adapter code that
  only the importers use retire here. Gates task 4.5.
