## Why

A registry acknowledges listing content it then discards. The compute filter
specification's `listing_shape` admits top-level properties it does not name
(`additionalProperties: true`), and buyers and publishers read that served schema
as the registry's contract. The publish route, the `Listing` table, and the listing
serializer, however, keep exactly six carriers — `listing_resource`,
`accepted_escrows`, `settlement_options`, `demands`, `max_duration_seconds`, and
`oracle_address`. Any other top-level field a publisher sends passes, is answered
with `201`, and is gone. Nothing tells the publisher.

The registry also does not enforce its schema where it stores: the publish boundary
refuses only the retired listing spellings, and full `listing_shape` validation runs
only in the dry-run route.

`registry-discovery`'s "Opaque market payload storage" requirement says the
registry treats domain payloads as opaque except for declarative filter paths and
validation rules. The code instead hard-codes the carrier set into route, table,
and serializer, so the effective listing contract is not the one the filter
specification serves. It is the same invisible skew the v6 filter specification
cites as its reason to refuse retired spellings rather than ignore them.

No listing has lost data to it yet only because every listing-level term added so
far went into `listing_resource` — deliberately, in `asking_rate`'s case. That
workaround pushes every future listing-level term into the capacity description,
where the storefront's listing comparison must classify each one as identity or
term of sale.

## What Changes

The registry stops acknowledging content it does not keep. Two shapes are under
design review, and the review chooses one (see `design.md`):

- **Keep what the schema admits.** Store each accepted listing document as
  published, so the filter specification, not route code, decides what a listing
  carries; filters keep compiling from specification paths.
- **Admit only what is kept.** Close the served `listing_shape` to the stored
  carriers and enforce the specification at the publish boundary, so a new
  top-level term becomes an explicit filter-specification contract change.

Either way the requirement is the same and is stated in this change's delta: a
field the registry accepts is stored and served, and a field it will not store is
refused at publish.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `registry-discovery`: accepted listing content is retained, never silently
  discarded.

## Non-Goals

- Do not change discovery semantics, filter evaluation, or any filter
  specification's filters.
- Do not add any market's field. Which listing-level terms a market publishes, and
  where, stays with the change that introduces each one.
- Do not move existing terms out of `listing_resource`, including `asking_rate`.
- Do not index filters (`index-registry-filters`) or change the database engine
  (`migrate-registry-to-postgres`).

## Impact

- **Affected code:** `core/registry` (publish and update routes, the listing model,
  the serializer, validation at publish, an Alembic migration), `core/registry-client`
  listing models, and the compute filter specification under either option.
- **Wire compatibility:** under "keep", a registry serves fields it previously
  dropped; under "admit only", a publisher sending an unnamed top-level field is
  refused where it was silently accepted. Either is observable to publishers and
  is called out in `design.md`.
- **Persistence:** a registry migration. It follows the migration-command
  conventions `add-database-migration-commands` establishes, and precedes
  `migrate-registry-to-postgres` so the PostgreSQL chain includes it.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md` — the registry's description as the
      schema-centralizing point for discovery, if the chosen option changes it.
- [x] Existing subsystem specification — `openspec/specs/registry-discovery/spec.md`.
- [ ] New subsystem specification — none.

### Knowledge to promote

- Accepted listing content is retained — `openspec/specs/registry-discovery/spec.md`.
- Which option was chosen, and why — `openspec/specs/registry-discovery/architecture.md`.

## Dependencies and Related Changes

- Sequenced after `add-database-migration-commands` and, by preference rather than
  dependency, before
  `migrate-registry-to-postgres`, in the "Registry productionization" lesser goal.
  No roadmap goal blocks on it.
- Its accepted carrier policy is a decision input — not an implementation
  dependency — for `negotiation-driven-capacity-resize` §2 and
  `billable-capacity-reservations`, each of which decides where a buyer reads a
  rate structure. Either may proceed without it by serving the structure from the
  storefront.
- `capacity-shape-pricing` does not depend on it: its rate structure is a
  storefront term of sale and its registry payload is unchanged.
- `publish-indicative-listing-rates` adds registry engine primitives (exact
  decimals, filter co-requirements) and is independent of it.
