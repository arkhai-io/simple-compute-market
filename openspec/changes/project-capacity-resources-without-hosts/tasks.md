# Tasks — project capacity resources that have no host

Depends on `capacity-resource-administration` having landed. Do not begin
Section 2 before it has.

## 1. Baseline evidence

- [ ] 1.1 Freeze representative host-complete fixtures covering fungible and
      specific-resource pools, and assert the projection equals them
      deterministically. Do not make a snapshot of a development deployment the
      contractual regression test: an arbitrary environment's projection is not
      reproducible, and `docs/development/TESTING.md` is explicit that a
      development run is good for reproducing a failure rather than for owning a
      guarantee. A deployment diff remains useful supplementary evidence.
- [ ] 1.2 Enumerate every consumer of per-entry host-correlated fields,
      storefront-side included. A field this change may omit is a field some
      consumer currently assumes present.

## 2. Invert the projection

- [ ] 2.1 Iterate declared capacity resources in the capacity-inventory
      projection and correlate host rows in by their existing identity keys,
      replacing the host-driven loop.
- [ ] 2.2 Preserve the existing correlation keys exactly, including the
      alternate identities a resource may map to. A resource that correlates
      today must correlate after.
- [ ] 2.3 Keep the duplicate-identity guard: several capacity resources mapping to
      one host identity must still be an error rather than a last-write-wins
      merge.
- [ ] 2.4 Omit host-correlated fields on an uncorrelated entry rather than
      emitting empty values, so absence stays distinguishable from a correlated
      host whose identifier failed to populate.

## 3. Fail closed downstream

- [ ] 3.1 **Integration.** Placement and provider dispatch reject an uncorrelated
      resource before any effect. Assert through the real app with the provider
      boundary mocked and verified *never invoked* — this is an
      effect-prevention claim, and a unit test over a transform cannot make it.
- [ ] 3.2 Confirm rendered host inventory excludes uncorrelated resources
      entirely. A blank address in a rendered inventory is a worse failure than an
      omitted entry.
- [ ] 3.3 **Integration.** Storefront-side ingestion accepts an entry with
      host-correlated fields absent, read through the canonical site client against the
      real provisioning app, and its reconciler continues to distinguish absent
      from zero.

## 4. Verification

- [ ] 4.1 Assert the projection equals the Section 1 frozen fixtures exactly.
- [ ] 4.2 **Unit.** Exhaustive correlation cases: resource with host, resource
      without, duplicate identity conflict, omit-versus-empty.
- [ ] 4.3 **Integration.** A hostless capacity resource appears through the real
      provisioning capacity API read via `SiteCapacityClient`, carrying its
      declared capacity and attributes with host-correlated fields omitted.
- [ ] 4.4 Run the end-to-end scenarios that depend on projected capacity shape.
- [ ] 4.5 **Smoke.** Confirm the deployed route is wired. Do not make smoke
      coverage carry any of the semantics above.

## 5. Specification

- [ ] 5.1 State in `openspec/specs/site-capacity/spec.md` that the capacity
      resource is the unit of projection and host correlation is optional
      per-entry metadata rather than a precondition for projecting.
- [ ] 5.4 Confirm `capacity-resource-administration`'s "Operator-administered
      capacity declarations" requirement still carries the shape-versus-admission
      wording this change depends on. That definition lives in the prerequisite
      rather than here, so that one contract exists before either change lands
      and neither carries a delta that cannot validate on the branch reviewing
      it. "A Physical Resource's sellable capacity"
      does not survive a resource with no host, so this wording has to change for
      this change's own sake regardless of what consumes it downstream.
- [ ] 5.2 Add a scenario for a declared resource with no host: it
      projects with declared capacity and omitted host-correlated fields.
- [ ] 5.3 Add a scenario for the fail-closed execution boundary: an uncorrelated
      resource is refused at placement rather than dispatched with an absent
      host connection identity.

## 6. Closeout

- [ ] 6.1 **Comment hygiene.** Run `make check-comment-hygiene` and resolve every
      match. The local rationale worth keeping at the loop is why iteration
      follows the authority model, not which change inverted it.
- [ ] 6.2 **Import placement.** Review imports this change added or touched and
      migrate function-level ones to module level where no genuine circular
      import or documented lazy-load reason exists. Verify each move against the
      real test suite.
- [ ] 6.3 **Documentation compliance.** Re-check accepted decisions against
      `openspec/README.md`'s placement table. The omit-versus-empty rule states
      behavior implementations must satisfy, so confirm it landed as a normative
      requirement rather than only as design prose.
- [ ] 6.4 **Narrative compression.** Shorten completed-task notes to final
      behavior, the diff evidence from 4.1, and the deferred operator-visibility
      question.
- [ ] 6.5 **Roadmap currency.** Remove this change's row from Goal 7's gap table
      in `docs/development/ROADMAP.md` and absorb the result into that goal's
      current-state prose. Also assess Goal 1's current-state description, since
      this change alters what is true about projection-backed derivation, and
      record that disposition either way.
- [ ] 6.6 **Campaign index currency.** Update this change's row and the
      unbacked-listing campaign's dependency graph in
      `openspec/changes/README.md`, including its dependency edge from
      `capacity-resource-administration`.
- [ ] 6.7 **Promotion.** Complete the design-promotion record below.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| The capacity resource is the unit of projection; host correlation is optional metadata | `openspec/specs/site-capacity/spec.md` |
| A hostless entry omits host-correlated fields rather than emptying them | `openspec/specs/site-capacity/spec.md` |
| Execution paths require host correlation and fail closed without it | `openspec/specs/site-capacity/spec.md` |
