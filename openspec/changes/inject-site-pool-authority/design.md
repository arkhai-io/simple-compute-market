# Design — the site ledger reads pools through an injected authority

## Context

See `proposal.md` for the four reads and how the edge accumulated. This document
records the decision already taken and the questions this change's discussion
must settle before it is planned.

## Decisions

### Inject a port rather than sanction the edge

Two remedies were considered.

- **Sanction the edge.** Amend `ARCHITECTURE.md` to allow `kit/site → kit/resource-pools`
  as a one-way edge between authority capabilities and forbid the reverse in a
  boundary test. It is acyclic and both tables share one database per site, so
  the design is defensible. But it retires the rule that authority capabilities
  depend on foundation only, and it leaves the API-credits service holding a pool
  table it does not administer.
- **Inject a port.** The ledger receives pool facts from its composition root.
  The rule holds, the diagram stays true, and a service with no pool
  administration need not store pools to run a ledger.

The port is chosen. The deciding consideration is that it removes an
unnecessary dependency rather than documenting one.

### The port is session-scoped

Admission reads pool facts inside the same transaction that creates the
reservation, under the ledger's serialization. Reading them from a separate
session would let a pool's deliverable set narrow between the check and the
reservation. Every port operation therefore takes the caller's session, as the
ledger's current reads do.

### Enforcement is a boundary test

The edge grew because nothing failed when it was added. The change is accepted
only when `kit/site`'s boundary test forbids `market_resource_pools` and
`kit/site/pyproject.toml` no longer declares the pool kit.

## Open questions

- **Port granularity.** One call returning a small value object (exists, enabled,
  deliverable modes, needs host), or one call per fact. A value object reads a
  pool once per decision; separate calls keep each caller's intent visible.
- **API-credits pool storage.** Keep the pool table and pass the real
  implementation, or pass a static single-pool authority and drop the table. The
  second removes storage a service does not administer, but its pool then has no
  row to carry advertisement and backing declarations, so the service would need
  another way to satisfy the rule that every pool carries them.
- **Non-null `pool_id` migration.** Whether any stored capacity row has a null
  `pool_id` in practice, and whether the backfill belongs in each service's
  migration or in a shared helper each calls. The migration-ownership precedent
  in `pool-declared-advertisement-and-backing` keeps migrations service-local.
- **Where `DEFAULT_POOL_ID` lives.** Once the ledger no longer needs it, whether it
  stays in `kit/resource-pools` or moves to a foundation home for the services
  that still seed a default pool.
- **Test construction.** 26 files construct `CapacityLedgerService`. Whether tests
  that do not exercise pool facts receive a permissive test authority, and if so
  how it is kept out of production composition.
- **Finish the split the contracts package started.** *Gates planning.* This design
  predates `kit/resource-pools-contracts` and `kit/resource-pools-client`. The
  contracts package took `hints`, `pools`, and `routes`, but three read-side
  modules stayed with the authority: `asking_rates.py` (imports only
  `market_capability_shape`), `site_declarations.py` (imports only
  `market_resource_pools_contracts.hints`), and `host_requirement.py` (no imports).
  Because they stayed, every reader of pool declarations still installs the
  authority and its SQLAlchemy and PyYAML dependencies — the VM storefront's
  `listing_sources.py`, the bare-metal storefront's `site_reading.py`,
  `arkhai_vms_listings` in three modules, and `kit/site/ledger.py`, which imports
  both distributions. Moving the three modules to the contracts package is
  mechanical and leaves `kit/resource-pools` as `db`, `service`, and
  `pool_config_handler`: the authority alone. After that, the port this design
  defines is the *only* thing `kit/site` needs from pools, and the import is
  deleted rather than injected around.
- **What the authority is, once it is alone.** `db.py`, `service.py`, and
  `pool_config_handler.py` speak provider, playbook, and host. Outside the compute
  family only `apicredits_service` touches them, and only because the site ledger it
  composes reads pool rows: `db/database.py` imports `market_resource_pools.db` to
  create the table the ledger needs. Under
  `ARCHITECTURE.md`'s scope rule a kit may know no family, and under the family-kit
  placement tests the authority fails the third-domain test as a repository-wide
  kit. Decide whether it becomes a compute family-kit distribution
  (`provisioning-pools` beside `hosts/` and `jobs/`, once
  `align-package-paths-with-layers` has placed the family kit) or stays
  repository-wide with that finding recorded in "Where the current tree diverges".
  If it moves, the ledger's pool-facts port is what keeps `kit/site`
  repository-wide, and `apicredits_service` — which imports
  `market_resource_pools.db` directly in `db/database.py` — takes the port's
  implementation by injection or uses the static single-pool authority the
  "API-credits pool storage" question above already contemplates. That question and
  this one are one decision.
- **Where the boundary test lives.** The repository check `enforce-package-layers`
  adds cannot see `kit/site` → `kit/resource-pools` as the tree stands: both are
  kits of empty scope and the edge forms no cycle, so no exception row can excuse
  it and none is seeded. Whether it becomes visible is this design's own decision:
  if the pool authority becomes a compute family-kit distribution, the edge is a
  kit depending on family knowledge and the scope rule fails it; if the authority
  stays repository-wide, the port removes the import and the per-package test this
  design plans (`kit/site` forbids `market_resource_pools`) is added as the guard
  and kept, since it asserts what the repository check cannot. `kit/site` has no
  boundary test of its own today: the repository check subsumed the one it had,
  which forbade only lifecycle, executor, and domain imports. `apicredits_service` →
  `kit/resource-pools` is a composition depending on a kit and is legal until the
  authority is scoped, at which point the same scope rule reports it.
