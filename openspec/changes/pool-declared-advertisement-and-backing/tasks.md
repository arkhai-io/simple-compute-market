# Tasks — a pool declares what it advertises and whether it can be admitted against

No blocking dependency. Prerequisite for `unbacked-listing-publication`.

This change is observable to operators and to nothing else: no listing behaviour
changes until the storefront reads these tags. Its acceptance boundary is that both
declarations exist, are validated, and every existing pool carries one.

Validation levels below are named deliberately. Per `docs/development/TESTING.md`,
integration means the real app, a real database, a wired DI container, and the
service's canonical typed client over `ASGITransport`.

## 1. Declarations

- [ ] 1.1 Add `advertisable_modes` to the shared resource-pool capability's
      policy-tag validation and typed resolution, matching how `deliverable_modes`
      is validated: a JSON-compatible set of unique, non-empty strings.
- [ ] 1.2 Make an absent or empty advertisable declaration authorize no mode, never
      widened by a default.
- [ ] 1.3 Add `capacity_backing` with values `backed` and `unbacked`. Reject any
      other value on write; fail the pool closed on ingestion. Do not resolve a
      malformed or absent discriminator to a default — that is the one behaviour
      that would let a listing claim an admission authority it does not have.
- [ ] 1.3a Fix `capacity_backing` at creation: replace and patch reject a differing
      value and leave the pool unchanged. A rejected request must not clear the
      existing value on its way out.
- [ ] 1.3b Preserve a stored backing value on omission, in replace, patch, and
      authoritative import. The general rule resets an omitted optional policy tag to
      the replacement default — `PoolReplace.policy_tags` defaults to `{}` and the
      service assigns `pool.policy_tags = data.policy_tags` wholesale — and applying
      that to an immutable field would change it by omission. Do not reuse the
      secret-provider-field rationale; that exception exists because a caller cannot
      restate an unreadable value, which is not true here.
- [ ] 1.3c Record `backed` explicitly when a create request omits the value. The
      compatibility rule is retained indefinitely rather than given a release count —
      sellers self-host and may lag without bound, so a date would be a number with
      nothing behind it. Do not leave the value absent:
      the preservation rule and the projection's emit-on-every-pool requirement both
      assume every pool carries a value.
- [ ] 1.3d Emit `capacity_backing` explicitly in canonical export, so a round-tripped
      document carries it and re-import is a no-op rather than a reset.
- [ ] 1.4 Carry both tags through create, replace, patch, bulk import, projection,
      and canonical export on the existing policy-tag channel and precedence.
- [ ] 1.5 Leave `deliverable_modes` untouched — meaning, derivation, migration, and
      every execution recheck at reservation, scheduling, and provider dispatch. A
      diff touching those paths means this change has exceeded its boundary.

## 2. Subset rule

- [ ] 2.1 Enforce on write that a pool declaring `capacity_backing: backed` has an
      advertisable set that is a subset of its deliverable set.
- [ ] 2.2 Enforce the same on projection ingestion. The two sides upgrade
      independently, so a write-side-only check would accept from a projection what
      it refuses from an operator.
- [ ] 2.3 Leave an `unbacked` pool's advertisable set independent of its deliverable
      set. Do not require a deliverable proof anywhere in that path — removing that
      requirement is what this change exists to do.

## 3. Migration and complete emission

- [ ] 3.1 Derive each existing pool's advertisable set from its proved deliverable
      set and its backing as `backed`, reporting each derived value at INFO,
      matching how the deliverable sets were themselves derived.
- [ ] 3.2 Make a producer that emits either tag emit it for every Resource Pool it
      projects. This is what lets a consumer distinguish a producer predating the
      tag from a producer that omitted it for one pool; without it, an upgraded site
      holding legacy pools reads as an old producer indefinitely, and the first
      explicitly unbacked pool an operator creates turns every other pool into a
      partially-populated omission.
- [ ] 3.3 Confirm no existing deployment's advertising surface or admission
      behaviour changes on upgrade. Verify by comparing resolved values before and
      after migration across a fixture covering the system-owned `default` pool, a
      proved single-mode pool, and a pool proving nothing.

## 4. Validation

- [ ] 4.1 **Unit.** Exhaustive declaration cases for both tags: valid, absent,
      empty, malformed, duplicate entries, and subset-rule violations in both
      directions.
- [ ] 4.2 **Integration.** An operator creates a pool declaring an advertisable mode
      with no provider configuration proving it, through the real pool
      administration API and its canonical client. The claim is not that a model
      accepts the value — it is that the real administration path does not demand
      fake execution configuration.
- [ ] 4.3 **Integration.** Through the canonical pool client: create, replace, and
      bulk import each round-trip an explicit backing value; and — the case that
      matters more — replace, patch, and import each **omitting** the value preserve
      it rather than resetting. The explicit-value happy path would pass against an
      implementation that resets on omission.
- [ ] 4.3a **Integration.** An old-format authoritative document imported for a
      migrated pool preserves the migrated backing, and canonical export of that pool
      emits it explicitly.
- [ ] 4.4 **Integration.** A backed pool's widened advertisable declaration is
      rejected on write, and the same declaration arriving through an ingested
      projection is rejected there too.
- [ ] 4.5 **Integration.** A malformed backing value is rejected on write, and a
      projection carrying one fails that pool closed.
- [ ] 4.5a **Integration.** A replace or patch changing an existing pool's backing is
      rejected and the pool's backing survives.
- [ ] 4.6 **Integration.** Migration derives both values on a database written by
      the previous version, and the resolved values are unchanged from before.
- [ ] 4.7 **Integration.** A projection from the migrated producer carries both tags
      on every pool it projects — the property `unbacked-listing-publication`'s
      skew rule depends on and cannot verify from its own side.
- [ ] 4.8 Run the pool administration, projection, and offering-mode enforcement
      suites, including `docs/development/TESTING.md`'s pool offering-mode
      enforcement coverage, and confirm no execution-path assertion changes.

## 5. Closeout

- [ ] 5.1 **Comment hygiene.** Run `make check-comment-hygiene` and resolve every
      match. The local rationale to keep is why advertisement does not require a
      delivery proof and why backing fails closed, not which review found the gaps.
- [ ] 5.2 **Import placement.** Review imports this change added or touched and
      migrate function-level ones to module level where no genuine circular import
      or documented lazy-load reason exists. Verify against the real test suite.
- [ ] 5.3 **Documentation compliance.** Re-check accepted decisions against
      `openspec/README.md`'s placement table, and re-read
      `docs/development/ARCHITECTURE.md`'s Resource Pool term and pool-mode
      paragraph to decide whether the second mode declaration belongs in the
      permanent map or is subsystem detail. Record the disposition either way
      rather than leaving the box unchecked.
- [ ] 5.4 **Narrative compression.** Shorten completed-task notes to final
      behaviour, the derivation results from 3.1, and the deferred question about
      an unbacked pool with a non-empty deliverable set.
- [ ] 5.5 **Roadmap currency.** Remove this change's row from Goal 7's gap table in
      `docs/development/ROADMAP.md` and absorb the result into that goal's
      current-state prose.
- [ ] 5.6 **Campaign index currency.** Update this change's row and Goal 7's
      dependency graph in `openspec/changes/README.md`.
- [ ] 5.7 **Promotion.** Promote `capacity-backed` and `unbacked` to
      `docs/development/ARCHITECTURE.md`'s Terms table now that a pool can declare
      backing and the concept is true, and complete the design-promotion record
      below. The listing-level boundary statements stay with
      `unbacked-listing-publication` until that change makes them true.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| `capacity-backed` / `unbacked` defined; backing means an admission authority exists, not that hardware does | `docs/development/ARCHITECTURE.md#terms` |
| Advertisement authorization and delivery authorization are separate declarations | `openspec/specs/resource-pool-management/spec.md` |
| A backed pool's advertisable set is a subset of its deliverable set; an unbacked pool's is independent | `openspec/specs/resource-pool-management/spec.md` |
| A malformed backing value fails closed and never resolves to a default | `openspec/specs/resource-pool-management/spec.md` |
| Backing is fixed at pool creation; moving between backed and unbacked supply is a second pool with migrated resources | `openspec/specs/resource-pool-management/spec.md` |
| A producer emitting these tags emits them on every pool it projects | `openspec/specs/resource-pool-management/spec.md` |
| Existing pools derive an advertisable set from their proved deliverable set and `backed` backing on upgrade | `openspec/specs/resource-pool-management/spec.md` |
