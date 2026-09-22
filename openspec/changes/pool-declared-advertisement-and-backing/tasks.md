# Tasks — a pool declares what it advertises and whether it can be admitted against

No blocking dependency. Prerequisite for `unbacked-listing-publication`.

This change is observable to operators and to nothing else: no listing behaviour
changes until the storefront reads these tags. Its acceptance boundary is that both
declarations exist, are required and validated on every write path, every existing
pool carries both, and one shared resolver exists for consumers to read them
through. Which change wires that resolver into storefront projection ingestion is
decided during planning, and no task below prescribes it.

Validation levels below are named deliberately. Per `docs/development/TESTING.md`,
integration means the real app, a real database, a wired DI container, and the
service's canonical typed client over `ASGITransport`.

## 1. Declarations

- [ ] 1.1 Add `advertisable_modes` to the shared resource-pool capability's
      policy-tag validation and typed resolution, matching how `deliverable_modes`
      is validated: a JSON-compatible set of unique, non-empty strings.
- [ ] 1.2 Make an empty advertisable declaration authorize no mode, never widened
      by a default.
- [ ] 1.3 Add `capacity_backing` with values `backed` and `unbacked`. Reject any
      other value. Do not resolve a malformed or absent discriminator to a default —
      that is the one behaviour that would let a listing claim an admission
      authority it does not have.
- [ ] 1.3a Fix `capacity_backing` at creation: a replace, patch, or document entry
      for an existing pool supplying a differing value is rejected and the pool is
      unchanged. For document import the check compares against stored state, so it
      is evaluated while reconciliation is planned and reported as a structured
      problem on the validate-only path too.
- [ ] 1.3b Require both tags explicitly on every pool write: create, replace, patch
      whenever it supplies `policy_tags`, and every definition-document entry. An
      omission is a validation problem naming the missing tag. Do not default,
      preserve, or merge either tag from stored state — the map a write supplies is
      the map stored.
- [ ] 1.3c Put shape, presence, the backed subset rule, and the unbacked
      empty-deliverable rule in one shared validation used identically by the typed
      administration models and by document validation and import.
- [ ] 1.3d Emit both tags for every pool in canonical export, so an unedited
      exported document imports as unchanged.
- [ ] 1.4 Carry both tags through create, replace, patch, bulk import, projection,
      and canonical export on the existing policy-tag channel.
- [ ] 1.5 Leave `deliverable_modes` untouched — meaning, derivation, migration, and
      every execution recheck at reservation, scheduling, and provider dispatch. A
      diff touching those paths means this change has exceeded its boundary.

## 2. Cross-tag rules and shared resolution

- [ ] 2.1 Enforce on write that a pool declaring `capacity_backing: backed` has an
      advertisable set that is a subset of its deliverable set, rejecting a write
      that breaks the relation from either side — widening advertisable or narrowing
      deliverable — without rewriting the other declaration.
- [ ] 2.2 Expose one domain-neutral resolver from policy tags to typed advertisable
      modes and backing, sharing its implementation with 1.3c. It fails on malformed
      values, the backed subset violation, and an unbacked pool with a non-empty
      deliverable set, and reports an absent tag distinctly from a malformed one.
      Do not apply a producer-version rule inside it; that is the consumer's.
- [ ] 2.3 Leave an `unbacked` pool's advertisable set independent of its deliverable
      set. Do not require a deliverable proof anywhere in that path — removing that
      requirement is what this change exists to do.
- [ ] 2.4 Enforce on write, and in the resolver, that a pool declaring
      `capacity_backing: unbacked` has an empty deliverable set. Add no site-side
      pool read: the existing execution rechecks already refuse a pool delivering
      nothing.

## 3. Migration, seeding, and complete emission

- [ ] 3.1 Migrate every existing provisioning Resource Pool: overwrite
      `advertisable_modes` with its proved deliverable set and `capacity_backing`
      with `backed`, clobbering any value previously stored under either key, and
      report each derived value at INFO.
- [ ] 3.1a Do the same for the API-credits service's own pool storage, and make its
      `default` pool seed write both tags.
- [ ] 3.1b Update every in-repository pool writer to carry both tags: test
      fixtures, seeds, chart values, and definition documents.
- [ ] 3.2 Refuse service start, naming the pool and problem, when a seeded pool —
      from a changed definition document or a bootstrap seed — or a stored pool does
      not carry valid declarations.
- [ ] 3.3 Confirm no existing deployment's advertising surface or admission
      behaviour changes on upgrade. Verify by comparing resolved values before and
      after migration across a fixture covering the system-owned `default` pool, a
      proved single-mode pool, a pool proving nothing, and a pool holding opaque
      values under the new keys.

## 4. Validation

- [ ] 4.1 **Unit.** Exhaustive declaration and resolver cases for both tags: valid,
      absent, empty, malformed, duplicate entries, the backed subset rule broken
      from each side, and an unbacked pool with a non-empty deliverable set — each
      asserted identically for the typed models and for document validation.
- [ ] 4.2 **Integration.** An operator creates an unbacked pool declaring an
      advertisable mode, an empty deliverable set, and a configuration-free provider,
      through the real pool administration API and its canonical client. The claim is
      not that a model accepts the value — it is that the real administration path
      does not demand fake execution configuration.
- [ ] 4.3 **Integration.** Through the canonical pool client: create, replace, patch,
      and bulk import each round-trip explicit declarations; and each **omitting**
      either tag is refused with a problem naming it and leaves the pool unchanged.
- [ ] 4.3a **Integration.** A document predating the declarations fails validation
      per entry and imports nothing; canonical export emits both tags for every pool
      and re-imports as unchanged.
- [ ] 4.4 **Integration.** A backed pool's widened advertisable declaration, and a
      narrowing of its deliverable set below it, are each rejected on write.
- [ ] 4.5 **Integration.** A malformed backing value is rejected on write, and an
      unbacked pool with a non-empty deliverable set is rejected on write.
- [ ] 4.5a **Integration.** A replace, patch, or imported entry changing an existing
      pool's backing is rejected, the pool's backing survives, and validate-only
      reports the problem.
- [ ] 4.6 **Integration.** Migration derives both values on a database written by
      the previous version, including the API-credits service's, and the resolved
      values are unchanged from before.
- [ ] 4.6a **Integration.** Startup refuses a changed definition document and a
      stored pool without declarations, naming the pool; an unchanged document
      still starts.
- [ ] 4.7 **Integration.** A projection from the migrated producer carries both tags
      on every pool it projects, and each resolves through the shared resolver — the
      property `unbacked-listing-publication`'s skew rule depends on and cannot
      verify from its own side.
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
      behaviour, the derivation results from 3.1 and 3.1a, and the revisit trigger
      for refusing an unbacked pool with a non-empty deliverable set.
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

- [ ] 5.8 **Documentation citations.** Run
      `make check-doc-citations CHANGE=pool-declared-advertisement-and-backing` and resolve every match.
      An unresolvable citation is a blocking defect under `AGENTS.md`'s
      cross-reference rule, and the target also rejects a citation whose
      target is a *tombstone*: a tombstoned file still exists on disk while
      its content is gone, so a plain existence test cannot fail on a
      rename-to-tombstone.
- [ ] 5.9 **End-to-end pipeline.** Confirm the end-to-end pipeline passes and
      record the evidence: the run, its result, and the scenarios that
      exercise this change's behaviour. Green unit and integration suites do
      not substitute -- this is the tier that catches a wire contract whose
      two sides disagree, a service that starts cleanly and cannot settle,
      and a configuration gap no in-process test can see. If the pipeline
      cannot run for a reason unrelated to this change, record that as an
      explicit blocker naming the cause and the change that owns it, and
      treat the validations it gates as unrun rather than passed.
## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| `capacity-backed` / `unbacked` defined; backing means an admission authority exists, not that hardware does | `docs/development/ARCHITECTURE.md#terms` |
| Advertisement authorization and delivery authorization are separate declarations | `openspec/specs/resource-pool-management/spec.md` |
| A backed pool's advertisable set is a subset of its deliverable set; an unbacked pool's is independent | `openspec/specs/resource-pool-management/spec.md` |
| A malformed backing value fails closed and never resolves to a default | `openspec/specs/resource-pool-management/spec.md` |
| An unbacked pool's deliverable set is empty, keeping it out of every capacity path without a site-side backing read | `openspec/specs/resource-pool-management/spec.md` |
| Both declarations are required on every write; nothing is defaulted, preserved, or merged | `openspec/specs/resource-pool-management/spec.md` |
| Seeded or stored pools lacking valid declarations stop service load | `openspec/specs/resource-pool-management/spec.md` |
| Readers of projected declarations resolve them through one shared resolver | `openspec/specs/resource-pool-management/spec.md` |
| Backing is fixed at pool creation; moving between backed and unbacked supply is a second pool with migrated resources | `openspec/specs/resource-pool-management/spec.md` |
| A producer emitting these tags emits them on every pool it projects | `openspec/specs/resource-pool-management/spec.md` |
| Existing pools are migrated to an advertisable set equal to their proved deliverable set and `backed` backing, overwriting any prior value | `openspec/specs/resource-pool-management/spec.md` |
