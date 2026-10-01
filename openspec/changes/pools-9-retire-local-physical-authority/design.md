# Design

## Context

Verified against the tree at planning time; re-verify before implementing.

**Two listing sources exist.** `available_compute_slices` in
`domains/vms/listings/reconciler.py` reads the site projection when
`use_site_projection_for_listings` is `true` (the default) and
`_pool_rows_from_local_tables` otherwise. The flag is read in
`services/capacity_client.py` and `services/listing_sources.py`; the
storefront lifecycle loop derives from the same source selection, so retiring
the local path retires it for the loop too.

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

**One deployed storefront depends on the local path.**
`domains/vms/storefront/storefront.alice.toml` sets
`use_site_projection_for_listings = false` because provisioning trusts one
storefront principal; the second storefront in the two-storefront e2e scenario
can load no projection and derives from local tables, where every source is
capacity-backed.

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

## Goals / Non-Goals

**Goals:** one listing source; no storefront physical authority; one storefront
override tier; no operator contract that fills retired tables; a freeze an
operator can roll back from by reverting code.

**Non-Goals:** a per-pool commercial write path (exists); carrying legacy
values forward; dropping schema; the zero-caller surfaces and the provider
rule (own changes); bare metal.

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

Deleting the local path leaves Alice with no listing source until she has a
working provisioning authority. `repair-multi-storefront-scenario` owns that
prerequisite and uses separate provisioning services for Alice and Bob.
Multiple storefronts per site are explicitly out of scope; this decision
supersedes the earlier shared-authority requirement.

Keep that repair separate and complete it first. Acceptance must prove Alice
derives from provisioning-seeded projections without her local-path opt-out,
both storefronts use their respective authorities, and the two-storefront
stages run and pass. Configuration edits or continued skips do not suffice.

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

### Operator counts belong to each site's projection generation

Replace the storefront-local top-level `resource_count` with
`site_projections[site_id][family].resource_count`, alongside that family's
existing state, revision, digest, last error, and confirmation timestamp.
Counts remain separate for every site and projection family; a storefront-wide
total cannot replace them.

The current site projections already contain the necessary information:

- `resource_pool`: count the projected members across pools. This counts
  capacity declarations, including disabled declarations, not distinct hosts
  or physical machines.
- `capacity_bucket`: sum the groups' existing `resource_count` values. The
  producer groups enabled declarations only, including exhausted ones;
  `available` describes each member's remaining quantities, not a group total.
  Neither the number of groups nor the sum of dimension quantities is a
  resource count. Pool enablement and offering-mode authorization are not
  additional filters for this count.

Compute each summary from the same cached family view whose identity and state
are reported. Do not fetch a new generation just for status or consult local
inventory. A held empty generation reports zero; a family with no generation
held reports `null`; a retained stale generation reports its count with state
`stale`. The two families can differ because their inclusion rules differ and
their generations are independently versioned.

Physical-resource projections also support pools that do not use capacity
buckets; their eventual listing consumers must not make capacity buckets a
universal inventory requirement. Count the current resource-pool projection's
members independently of the capacity-bucket family. The per-site, per-family
structure also accommodates any further physical-resource projection under
its own count semantics when exposed through status. Defining a new projection
protocol or changing which projection creates a listing is outside this
diagnostic decision.

A positive count proves projected inventory exists, not that its pool is
enabled, its shapes are feasible, its provider can execute, or its commercial
terms produce a listing. Publication diagnostics and catalogue checks remain
the evidence for sellable supply. A known-empty generation cannot establish
whether an operator intended it to be empty or an inventory import failed;
import failures are diagnosed at provisioning, which owns the import.

Alternatives:

- *A projection-derived top-level total.* Rejected: the counts per site must
  remain visible, and summing known sites would hide unavailable ones.
- *Adding counts to the site projection protocol.* Unnecessary for the current
  families: grouped capacity already carries multiplicity, and the
  resource-pool projection already enumerates every member.
- *Publication candidate counts as the inventory diagnostic.* Rejected as the
  replacement: a populated projection may yield no candidate for several
  independent reasons. Candidate or listing counts can be separate diagnostics.

This replaces the current operator acceptance requirement's local-row scenario
and its consumers. The response change removes the top-level field and adds
counts beneath the existing projection status; it does not change liveness
health or global negotiation-pause behavior. Permanent homes are
`openspec/specs/storefront-publication/spec.md` for the observable status
contract and its `architecture.md` companion for the interpretation of counts.

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
- **The two-storefront scenario is repaired later than expected** → all local
  inventory retirement waits, including the freeze and CSV removal; design and
  read-only investigation can continue.

## Migration Plan

1. Complete `repair-multi-storefront-scenario` separately, including its
   projection cutover and passing two-storefront evidence.
2. Re-verify the confirming searches against that resulting tree
   (legacy-resources fallback reachability and the remaining CSV consumers).
   Reconcile any files or scenario stages the prerequisite already migrated.
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

The resource-count diagnostic decision is resolved above. Further use of
physical-resource projections for listing creation does not gate these
summaries of existing projections.

The repository work order is decided: complete the separate multi-storefront
repair first, then the coordinated retirement. Each self-hosting operator
still selects their deployment time after preparing site inventory and
commercial overrides; there is no fleet-wide rollout signal to wait for.
