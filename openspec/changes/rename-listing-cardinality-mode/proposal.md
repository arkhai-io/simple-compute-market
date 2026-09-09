## Why

The projected pool hint named `listing_mode` answers exactly one question: how
many listing candidates does this pool produce, and how is each identified. Its
domain-owned values are `fungible` (one candidate bounded by what a single member
can currently satisfy) and `specific_resource` (one candidate per currently
enabled member).

The name does not say that. Read cold, `listing_mode` reads as "how is this pool
listed" in the general sense, which invites values describing what the listing
offers or how it settles rather than how many listings there are. That
misreading has already happened during design and produced a proposal to add a
settlement-shaped value to the enum, which would have coupled inventory
declaration to settlement mechanism — a coupling the settlement-registration
design exists to avoid.

Renaming the hint to `listing_cardinality_mode` makes the enum's boundary legible
at the point of use, so a future value that is not a cardinality is visibly out
of place instead of plausibly in scope.

The same read exposes a second, smaller gap. `storefront-publication` requires
that an absent or unrecognized value fall back to the domain's structural default
"with an operator-visible explanation." For a pool with no members that
explanation is not a warning about a misconfiguration; it is unavoidable noise on
every projection refresh, and noise emitted unconditionally trains operators to
ignore the channel.

## What Changes

- Rename the projected pool hint `listing_mode` to `listing_cardinality_mode`
  across the projection producer, the storefront consumers, and
  `openspec/specs/storefront-publication/spec.md`'s "Domain-owned publication and
  hold hints" requirement.
- Accept the previous key as a deprecated alias on ingestion for one release, so
  a projection produced by an unupgraded site is not silently reclassified to the
  structural default. Emit an operator-visible deprecation notice when the alias
  is taken.
- Record in the requirement that the enum's scope is cardinality: how many
  candidates a pool yields and how each is identified. A value describing what is
  offered, how it settles, or whether capacity backs it is out of scope.
- Scope the operator-visible-explanation obligation so that a pool with no
  cardinality question to answer resolves to the structural default silently.
  Absence remains the encoding for "not applicable"; the explanation remains
  required where a value was supplied and not recognized.

## Capabilities

### Modified Capabilities

- `storefront-publication`: the cardinality hint is named for its scope, that
  scope is stated normatively, and the fallback explanation is owed for
  unrecognized values rather than for absence where no cardinality question
  exists.

### New Capabilities

None.

## Non-Goals

- Do not add a value to the enum. Both current values remain, with the same
  semantics.
- Do not introduce, define, or reference a backing property.
  `docs/development/ARCHITECTURE.md` defines the term and
  `unbacked-listing-publication` owns the field. This change must remain
  reviewable as a rename.
- Do not change how a `fungible` pool's publishable range is computed, or how a
  `specific_resource` pool derives one candidate per member.
- Do not rename `offering_mode`, `deliverable_modes`, or
  `offer_resource.virtualization_type`. Those names are separately load-bearing
  and a combined rename would be unreviewable.

## Impact

- Affected code: the resource-pool projection producer in the provisioning
  service, the storefront-side hint consumers, and the domain hint interpretation
  that owns accepted values and the structural default.
- Affected specification: `openspec/specs/storefront-publication/spec.md`'s
  "Domain-owned publication and hold hints" requirement and its listing-mode
  scenario.
- Affected deployment: any operator-supplied pool definitions file carrying the
  old key. The ingestion alias is what makes this a rename rather than a
  deployment-contract break; removing the alias later is a separate decision with
  its own evidence bar.

## Dependencies and Related Changes

- **Prerequisite for `unbacked-listing-publication`**, which adds the backing
  field as a peer of this hint. Landing the rename first is what makes the two
  fields visibly independent instead of looking like one field being widened.
- Coordinate with `capacity-resource-administration` and
  `pools-8-capacity-projection-and-listing-hints`, which own the projection
  producer this rename touches. No ordering dependency either direction, but they
  edit adjacent lines.
- Independently valuable. If the unbacked-listing work is abandoned entirely, the
  rename still removes a live ambiguity.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md` — likely no change; the hint is named in
      subsystem specification rather than in the repository-wide map. Re-confirm
      at implementation time by grepping rather than assuming.
- [x] Existing subsystem specification —
      `openspec/specs/storefront-publication/spec.md`'s "Domain-owned publication
      and hold hints" requirement.
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- The cardinality hint's normative scope, stated so an out-of-scope value is
  visibly out of scope —
  `openspec/specs/storefront-publication/spec.md`.
- Absence encodes "no cardinality question"; the fallback explanation is owed for
  unrecognized values rather than for absence —
  `openspec/specs/storefront-publication/spec.md`.
