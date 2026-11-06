## Why

A registry acknowledges listing content it then discards: publication and reads
select six named carriers even though the configured listing schema admits other
terms. Buyers need a listing's resolved rates to price another shape, without
confusing commercial terms with the advertised capacity description. Registry-only
response signatures do not prove what the seller published.

## What Changes

- Choose Option A: persist and serve the complete accepted publication document;
  whole-document republication replaces commercial terms rather than merging.
- Authenticate and validate the configured listing shape at publication. Reserve
  registry metadata names explicitly; never acknowledge and discard a field.
- Synthesize existing rows from retained carriers until republication; expose
  absent seller evidence honestly, without invented backfills.
- Retain exact publication body bytes and the authenticated v2 envelope/signature.
  Keep lifecycle/oracle update proofs distinct from the publication proof.
- Publish the VM storefront's `rate_structure` as a top-level listing term through
  an opaque extra-term transport. Keep `asking_rate` in `listing_resource`.
- Supply the carrier and seller-authority answer to resize gate 2.1a; its buyer
  accessor and pricing behavior remain downstream work.

D-a through D-e in `design.md` were decided by webapp owner 2026-11-06, pending
maintainer review. The PR calls these out before its implementation summary.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `registry-discovery`: retained opaque documents, replacement, schema admission,
  legacy synthesis and verifiable seller publication/update evidence.
- `storefront-publication`: publish resolved rate structures at listing level.

## Non-Goals

- No new filter operators, indexes, database engine, or migration entry points.
- No domain imports or rate interpretation in the registry engine.
- No asking-rate relocation, shape negotiation, open-ended or spot behavior.
- No storefront startup migration changes.

## Impact

- `core/registry`: additive Alembic revision, document/evidence columns, publication,
  update, serialization and validation routes.
- `core/registry-client`: opaque additional listing terms; evidence remains in the
  already-preserved response extras.
- `core/storefront`, VM listing models and VM storefront: carry publication terms
  across create, refresh and reopen; compute schema declares top-level rates.
- Wire behavior: schema-invalid complete publications now fail rather than being
  stored; partial republication is not a patch. Unknown admitted terms survive.
  New response evidence fields are additive; legacy rows have null evidence.
- Persistence: additive columns, no backfill, no recovered discarded content.
  Downgrade loses documents/evidence and must not be used as data-preserving rollback.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md` — assess at closeout; authority detail
  currently belongs to the owning subsystem companions.
- [x] Existing specifications and companions — registry discovery and storefront publication.
- [ ] New subsystem specification — none.

### Knowledge to promote

- D-a document replacement, legacy synthesis and filter semantics —
  `openspec/specs/registry-discovery/spec.md` and `architecture.md`.
- D-b listing-level rates — `openspec/specs/storefront-publication/spec.md` and
  `architecture.md`.
- D-c seller proof and registry metadata boundaries —
  `openspec/specs/registry-discovery/spec.md` and `architecture.md`.
- D-d verified carrier for resize — registry architecture; downstream gate records
  the consumption contract when resize work starts.
- D-e dependency correction is temporary sequencing rationale in this change and
  `openspec/changes/README.md`, not permanent architecture.

## Dependencies and Related Changes

- `add-database-migration-commands` is not a dependency: its scope is VM/API-credit
  roles, not registry Alembic. D-e records the owner-approved correction.
- Prefer landing before `migrate-registry-to-postgres` so its chain inherits the
  additive revision. No new migration command is introduced.
- `index-registry-filters` remains deferred; future indexes project from the opaque
  document and prove parity for legacy synthesis rather than assuming carriers.
- This supplies the registry carrier needed by `negotiation-driven-capacity-resize`
  §2 and the later open-ended/spot chain. It does not implement their behavior.
