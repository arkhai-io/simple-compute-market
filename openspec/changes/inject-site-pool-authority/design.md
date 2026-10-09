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
