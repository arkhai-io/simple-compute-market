## Why

A registry acknowledges listing content it then discards: publication and reads
select six named carriers even though the configured listing schema admits other
terms. Buyers need a listing's resolved rates to price another shape, without
confusing commercial terms with the advertised capacity description, and need
a listing's listing-level prices in one place. Registry-only response signatures do
not prove what the seller published.

## What Changes

- Persist and serve the complete accepted publication document; whole-document
  republication replaces commercial terms rather than merging (D1).
- Authenticate and validate the whole configured listing shape at publication.
  Refuse reserved registry metadata names; never acknowledge and discard a
  field. `PUT` refuses keys other than status and oracle address (D1).
- Rebuild existing rows from their carrier columns on read until republication;
  expose absent seller evidence honestly, without invented backfills (D1).
- Retain exact publication body bytes and the authenticated v2 envelope; keep
  lifecycle/oracle update proofs distinct from the publication proof (D2).
- Move a listing's listing-level prices into one top-level `pricing` object
  holding `asking_rate` and the optional family `rate_structure`, written by
  every in-repository publisher through an opaque extra-term transport, and
  refuse a price at its earlier location; settlement-option prices stay with
  their options (D3).
- Supply the carrier and seller-authority answer to resize gate 2.1a; its buyer
  accessor and pricing behavior remain downstream work (D4).
- Repair registries by republishing each domain's publication candidate, and
  correct the API-credit schema's settlement option shape, which full validation
  now enforces (D6).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `registry-discovery`: retained opaque documents, replacement, schema admission,
  reserved names, legacy rebuild, verifiable seller publication/update evidence,
  and the `pricing` object's filters.
- `storefront-publication`: publish listing pricing in the top-level `pricing`
  object; repair registries through the domain's candidate.
- `resource-pool-management`: an asking rate a pool or override declares is
  published in the listing's `pricing.asking_rate`; the pool kits name no
  published layout.

## Non-Goals

- No new filter operators, indexes, database engine, or migration entry points.
- No domain imports or rate interpretation in the registry engine.
- No shape negotiation, open-ended or spot behavior.
- No storefront startup migration changes.
- No change to the registry's write admission or a request-body size limit;
  that is the registry write hardening gap.

## Impact

- `core/registry`: additive Alembic revision, document/evidence columns,
  publication, update, serialization and validation routes; the compute filter
  specification's `pricing` object.
- `core/registry-client`: opaque additional listing terms; evidence remains in the
  already-preserved response extras.
- `core/storefront`, VM listing models and VM storefront: carry publication terms
  across create, refresh, reopen and repair.
- Bare-metal domain and storefront: write the asking rate to
  `pricing.asking_rate`. `resource-pools`, `resource-pools-contracts` and
  `pool-overrides` resolve and store the rate but never place it in a listing,
  so they need no change.
- `kit/capacity-publication`: the required `publication_candidate` hook every
  composing domain implements; registry repair republishes it.
- `domains/apicredits/registry`: the settlement option shape the market uses.
- Wire behavior: schema-invalid complete publications now fail rather than being
  stored; partial republication is not a patch. Unknown admitted terms survive.
  A version 8 publisher's `listing_resource.asking_rate` is refused, naming
  `pricing.asking_rate`.
  New response evidence fields are additive; legacy rows have null evidence and
  drop out of asking-rate filters until republished.
- Persistence: additive columns, no backfill, no recovered discarded content.
  The revision's downgrade refuses; rollback is restoring the pre-upgrade
  backup, and an older image refuses the migrated database as ahead.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — no principle is promoted; closeout
  corrects "Discovery and negotiation", which says resolved family rates never
  reach a registry.
- [x] Existing specifications and companions — registry discovery, storefront
  publication, resource-pool management.
- [ ] New subsystem specification — none.

### Knowledge to promote

- D1 retained documents, replacement, reserved names, schema admission, legacy
  rebuild and filter semantics — `openspec/specs/registry-discovery/spec.md` and
  `architecture.md`.
- D2 seller evidence wire contract and trust anchor —
  `openspec/specs/registry-discovery/spec.md` and `architecture.md`.
- D3 listing pricing object — `openspec/specs/registry-discovery/spec.md`,
  `openspec/specs/storefront-publication/spec.md` and `architecture.md`,
  `openspec/specs/resource-pool-management/spec.md`.
- D4 verified carrier for resize — registry architecture; the downstream gate
  records the consumption contract when resize work starts.
- D5 migration ordering — sequencing only, no permanent destination unless
  closeout finds a line for registry architecture.
- D6 repair through the domain candidate —
  `openspec/specs/storefront-publication/spec.md` and `architecture.md`.

## Dependencies and Related Changes

- `add-database-migration-commands` is archived. The publication revision follows
  its packaged registry baseline; D5 records the migration boundary.
- Prefer landing before `migrate-registry-to-postgres` so its chain inherits the
  additive revision. No new migration command is introduced.
- `index-registry-filters` remains deferred; future indexes project from the
  document and prove parity for rebuilt legacy rows rather than assuming carriers.
- This supplies the registry carrier needed by `negotiation-driven-capacity-resize`
  §2 and the later open-ended/spot chain. It does not implement their behavior.
