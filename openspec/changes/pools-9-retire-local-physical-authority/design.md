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
  without recording it when a table is absent (decided: "Freeze, do not
  `DROP`; retained data is extraction input").
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
  that only the importers use have no caller left, and two models describing
  the retired physical model already had none (decided: "Code describing the
  retired inventory leaves with it").
- **Local-table wording elsewhere.** "A site whose projection is not held holds
  its listings" and `ARCHITECTURE.md`'s "Storefront capacity boundary" still
  contrast projection derivation with local tables. The statements stay true
  after retirement but describe a mechanism that no longer exists. The delta
  modifies the requirement to drop the local-table clauses, and promotion
  corrects `ARCHITECTURE.md`.

### Re-grounding against `dev` (2026-10-11)

`dev` was merged after D1–D7 were decided. Nothing it delivered reverses a
decision; it changes the following.

- **`remove-dead-storefront-physical-surfaces` is archived (2026-10-08).** It
  froze `compute_allocations`, removed migrations `20260604_001` and
  `20260611_007` from `VM_MIGRATIONS`, and stopped migration `20260604_002`
  creating allocation indexes. It removed the resource administration routes,
  `get_resource`, `apply_resource_set_transition`, `list_hosts`,
  `host_capacity_remaining`, `delete_resource`, and
  `ensure_default_resources`, and narrowed `apply_resource_transition` to the
  one transition `release_reservations`' local loop performs. The `SQLiteClient`
  methods left for this change are `upsert_resource` with
  `_sync_compute_pool_for_resource`, `list_resources`, `upsert_host`,
  `get_host` with `_host_row_to_dict`, `apply_resource_transition`, and the CSV
  upserts. It added `tests/integration/test_resource_transitions.py`, which
  retires with `apply_resource_transition`, and
  `tests/integration/test_compute_allocations_freeze.py`, whose
  release-transition case retires with it while its freeze cases stay.
- **The frozen-table rule is now permanent.** That change promoted to
  `docs/development/DEPLOYMENT_AND_CONFIG.md`'s "Migrations at startup" the
  rule this change's D5 applies: a frozen table is never dropped, and a
  migration whose only effect is on a frozen table leaves the chain with its
  recorded ID inert and never reused. D5 therefore promotes no new mechanism;
  the paragraph's closing sentence names the frozen inventory tables beside
  `compute_allocations`.
- **It deferred one guard here.** `dev` added task 5.7: once the import route
  is gone, an application test asserts no route is mounted under
  `/api/v1/admin/portfolio/resources`. This change's CSV pricing and retired-key
  tasks are renumbered 5.8 and 5.9.
- **The full-deal scenarios share compute deal stages.** VM and bare metal now
  declare common stages from `e2e-tests/tests/e2e/roles/helpers/compute_deal_stages.py`.
  Shared stage `00f1` already seeds supply through provisioning
  (`deal_driver.seed_supply()`), so VM's own stage `00f` CSV import and its
  `resource_count` assertion in both full-deal scenarios are redundant and are
  deleted rather than migrated. The six CSV-dependent files are unchanged.
- **Bare metal still reports `resource_count`.** The health builder moved
  within `runtime.py` and `test_http_system.py` still asserts it; D4's edits
  are unchanged.
- **`ARCHITECTURE.md` gained scope and kind rules.** Nothing this change adds
  creates a new edge. D6's deletion of escrow templates removes Alkahest-shaped
  configuration from `kit/config`, which "Where the current tree diverges" lists
  for carrying mechanism identifiers; the divergence paragraph names no
  escrow-template item, so it needs no edit here.
- **`storefront-publication` gained requirements** (the inventory guard before
  every seller decision and acceptance, bare-metal deal readiness, settlement
  servicing scenarios). None overlaps this change's delta, which still
  validates against the merged baseline.
- **`resolve-compute-family-findings` (proposed)** touches VM storefront
  surfaces this change does not: the literal pool-override route path and the
  unread `[provisioning] mode`.

## Goals / Non-Goals

**Goals:** one listing source; no storefront physical authority; one storefront
override tier; no operator contract that fills retired tables; retained data an
operator can still extract into provisioning.

**Non-Goals:** a per-pool commercial write path (exists); carrying legacy
values forward; dropping schema; the zero-caller surfaces and the provider
rule (own changes); bare-metal publication (only bare metal's status count
retires here).

## Decisions

### Upgrades are fail-forward

Upgrading past this change is one-way. There is no supported downgrade to a
version with the local listing path; a defect after upgrade is fixed forward.
The repository is pre-1.0, and keeping a downgrade path working would mean
keeping the retired schema creatable and its migrations runnable for code
whose only purpose is the path this change removes.

No design choice here is justified by downgrade safety. Operator documentation
states the policy for this change only. Promoting fail-forward to a
repository-wide pre-1.0 rule was considered and deliberately deferred
(2026-10-11); nothing in this change states or implies one.

### Freeze, do not `DROP`; retained data is extraction input

The retired tables are `resources`, `hosts`, `resource_transition_events`,
`compute_capacity_pools`, and `compute_pool_members`. Fresh databases never
create them; upgraded databases keep their schema and rows exactly as they
were. Current storefront code neither reads nor writes them for any purpose,
including startup and status.

The tables are not dropped because their rows may still need to be extracted
into provisioning's inventory: host inventory, pool definitions, and capacity
declarations entered through provisioning's administration surfaces. That is
an operator task, not automatic transfer, and retained rows are historical:
an operator reconciles them against live site state before using them. A
`DROP` is a later change, once operators have had a release to extract what
they need. Commercial values follow the separate override decision below;
retaining mixed rows does not keep their commercial tier active.

Mechanics:

- **Bootstrap.** `_ensure_domain_tables` and `_ensure_domain_indexes` stop
  creating or touching `resources`, `hosts`, `resource_transition_events`,
  their triggers, and their indexes, including the per-startup drop and
  recreation of `trg_resources_updated_at` and the commercial-column `ALTER`s.
- **VM migrations.** The migrations that exist only for the retired tables
  leave `VM_MIGRATIONS` with their functions: `20260604_002` (creates the pool
  tables and backfills them from `resources`), `20260611_006` (pool member
  sites), `20260716_008` (pool table rename), and `20260813_010` (settlement
  columns on `resources` and pools), together with `_backfill_compute_pools`
  and `_resource_attrs`. The runner ignores recorded IDs it no longer ships, so
  an upgraded database keeps its history unchanged and a fresh one never
  records them. A database old enough to have one still pending keeps that
  table as it is, which is what extraction needs.
- **Migration `20260604_003` stays and reads no retired table.** It adds and
  backfills `derived_compute_listings.pool_id`, which the legacy
  listing-binding adapter (`config migrate --scope storefront-domains`)
  requires. Its backfill takes each listing's own `resource_id` as its pool.
  Revised 2026-10-13 after implementation review: it previously recovered the
  pool from `compute_pool_members`, which contradicted the requirement that no
  storefront code reads retired data, including at startup. A bounded
  read-only exception was considered and declined. The cost is borne only by a
  database that never applied `003` (last started before 2026-06-04): a
  fungible-pool listing there binds to its resource rather than its pool, so
  publication closes it and publishes a successor, and its seller's close or
  pause does not carry over.
- **Core `_migrate_listing_resource_timestamps` covers `listings` only.**
  Revised 2026-10-13 after implementation review: as first decided it stayed
  unchanged, but on a database that had not applied it, it added columns to a
  retained `resources` table and ran an `UPDATE` over every row, which fires
  the retained `trg_resources_updated_at` trigger and rewrites `updated_at`.
  Narrowing it also removes a VM table from core. A database that never
  applied it keeps `resources` in whatever shape it had, as the frozen-table
  rule says.

Alternatives:

- *Gate the retired migrations with `required_tables`.* Rejected: a pending
  legacy migration would still rewrite retained rows on upgrade, and code
  reachable only by very old databases would stay.
- *Empty the retired migrations' bodies and keep their IDs.* Rejected: it keeps
  dead entries in the chain and records IDs whose schema was never created.
  `DEPLOYMENT_AND_CONFIG.md`'s frozen-table rule, promoted when
  `compute_allocations` was frozen, now rules it out.
- *Drop the tables now.* Rejected: their rows may still be needed for
  extraction into provisioning.

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
since `compute_allocations` is already frozen. Task 4.5 deletes only the
methods whose remaining callers this change removes: `release_reservations`'
local loop, the status count, the validator, and the importers. The
prerequisite landed on 2026-10-08 (see "Re-grounding against `dev`").

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

### Code describing the retired inventory leaves with it

Code whose only callers this change removes is deleted here, and so is code
that already had no caller but describes the physical model this change
retires.

Dead as a direct result of this change:

- The storage half of the resource adapters in
  `arkhai_vms_listings/resources.py`: `to_domain_resource()` (including its
  `host_row` join) and `from_domain_resource()` on both adapters, the matching
  `ResourceAdapter` protocol methods, and `adapt_db_resource_to_domain_resource()`
  and `adapt_domain_resource_to_db_resource()`. The wire half —
  `from_dict()`/`to_dict()`, the adapter registry, and
  `parse_resource_from_dict()`, used by `listing_service.py` — stays, and
  `_COMPUTE_HOST_CONTEXT_FIELDS` stays only if the wire half still reads it.
- `[escrow_templates]` configuration, whose only consumer was the CSV
  `accepted_escrows` DSL: `ESCROW_TEMPLATES`, `_build_escrow_templates`, and
  `_coerce_templates_table` in the VM storefront's `utils/config.py`, and
  `EscrowTemplate`, `RateSlot`, and `escrow_templates_from_config` in
  `kit/config`. No packaged configuration, chart, or document sets the table.
- `build_storefront_publication_clause_compiler()` in
  `settlement_composition.py`, called only by import and startup seeding.

Already without a caller, and describing the retired model:

- `Host` in `arkhai_vms_listings/models.py`, the schema of the retired `hosts`
  table, whose docstring calls it the source of truth for host hardware —
  false under "Storefront holds no physical-resource authority".
- `ComputeResourcePortfolio`, a local-portfolio capacity check.
- `get_supported_resource_types()`.

Alternatives:

- *Delete only what this change makes dead.* Rejected: `Host`'s docstring would
  contradict the new requirement, and the other two describe the same retired
  model.
- *Keep `[escrow_templates]` in `kit/config` for reuse.* Rejected: a
  configuration surface with no consumer and no planned one.

Consequence: `kit/config`, a repository-wide kit, loses code no other package
imports; no consumer changes.

### Retired configuration keys follow the settlement retirement convention

The retired settings are `resources_csv_path`, `resources_csv_inline`,
`[escrow_templates]`, `capacity.use_site_projection_for_listings`, and the
chart's `secret.resourcesCsvInline` value. The storefront's loader ignores
unknown root keys, so after upgrade they would be silently ignored at runtime.

They are refused where the retired settlement settings are refused, and
nowhere else:

- **At chart render.** Both `helm/charts/storefront/values.schema.json` and
  `helm/values.schema.json` already refuse retired config keys such as
  `HostedSettlement` in any spelling. The retired keys join that list, under
  `capacity` for the flag, and `resourcesCsvInline` is refused under an agent's
  `secret`, as the retired private-key values are. This applies the existing
  rule in `openspec/specs/deployment-state/spec.md` that a retired values shape
  is refused at render, naming the key.
- **At `market-storefront config set`.** Editing a retired key is refused with
  a removal message, as `reject_legacy_settlement_path` refuses a retired
  settlement path. Where the settlement message names a migration command,
  this one names the seller quickstart's upgrade section, because no command
  migrates inventory.

There is no migration command to extend: inventory moves to provisioning by
operator action, and the CSV pricing migration retires. Startup does not
refuse the keys, matching the settlement retirement; a compose or hand-run
deployment that keeps one still starts, and operator guidance names the keys
to remove.

Alternatives:

- *Refuse at startup.* Rejected: it departs from the settlement convention,
  which refuses at render and edit time only.
- *Log a warning at startup.* Rejected for the same reason, and a log line is
  where a silently empty storefront hides.
- *No refusal anywhere.* Rejected: the chart already refuses retired keys, and
  leaving these out would make it pass through configuration the storefront
  ignores, against the deployment-state rule.

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
- **An operator upgrades with CSV configuration** → no inventory, no error at
  runtime, because the storefront's loader ignores unknown keys. Mitigated by
  migration guidance that names the provisioning-side declaration path, by the
  chart refusing the retired keys at render, and by `config set` refusing to
  write them (see "Retired configuration keys follow the settlement retirement
  convention"). A compose or hand-run deployment that keeps a key still
  starts.
- **Retained inventory is mistaken for current supply** → an unsafe
  provisioning seed. Guidance requires checking current site state before
  using the historical records; current storefront code never consults them.
- **A defect surfaces after upgrade** → no downgrade path; it is fixed forward
  (see "Upgrades are fail-forward").
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
   leaves. Done 2026-10-11; see "Re-grounding against `dev`".
3. Prepare provisioning-seeded tests and operator guidance together with
   retirement of local derivation, the flag, legacy overrides, CSV import and
   its pricing migration, startup seeding, deployment and CLI wiring, the
   status count, and local cleanup.
4. Apply the fresh-schema freeze in the same coordinated cutover, preserving
   existing historical data. No partial retirement is an independently
   deployable outcome.
5. Validate fresh and populated databases, the affected suites, packaging,
   and the end-to-end pipeline; complete the planned closeout.

The upgrade is fail-forward. Retained tables stay in upgraded databases for
operator extraction into provisioning; no `DROP` has happened.

## Open Questions

The resource-count diagnostic decision is resolved above: status reports no
resource count.

The repository work order is decided: the separate multi-storefront repair
(done), then `remove-dead-storefront-physical-surfaces`, then the coordinated
retirement. Each self-hosting operator still selects their deployment time
after preparing site inventory and commercial overrides; there is no
fleet-wide rollout signal to wait for.

The decisions raised by the 2026-10-08 re-grounding (D1–D6) and the
retired-key handling it surfaced (D7) are all recorded above.
