# Tasks — bare-metal publication reads pool declarations

Unblocked. On Goal 7's critical path. This task list is a baseline carried from the
design phase; planning names the exact files each decision touches.

## 1. Design

- [ ] 1.1 **Decision gate.** Decide how listings bound before the common key included
      the pool are reconciled — fail forward once with seller state carried over, or a
      read-only fallback to the legacy key (`design.md`, "Open questions") — and record
      the decision and its reasoning in `design.md` before Section 3.

## 2. Candidates from the projection

- [ ] 2.1 Fetch each trusted site's resource-pool projection directly from that site's
      client in the publication command, with `arkhai-kit-resource-pools` as a
      storefront dependency. A site whose fetch fails is unknown for the run.
- [ ] 2.2 Derive one publication candidate per Physical Resource carrying a
      `bare_metal.v2` publication view, from that view. Remove the command's
      capacity-snapshot read and its own view construction and availability check.
- [ ] 2.3 Resolve every candidate's pool through `read_site_declarations`: no candidate
      from a pool that does not advertise `bare_metal` or is disabled; hold the listings
      of an unresolvable pool; refuse an unbacked pool with an operator notice naming it.
- [ ] 2.4 Hold every listing of an unknown site — neither closed nor refreshed — and
      report the site in the run's result.

## 3. Publication through the kit runtime

- [ ] 3.1 Publish, reconcile, and converge through `kit/capacity-publication`'s
      `PublicationRuntime`, with `arkhai-kit-capacity-publication` as a storefront
      dependency, the core `MultiRegistryClient` for registry fan-out, and a
      `binding_for_listing` hook built from the common listing binding.
- [ ] 3.2 Track listings by the common binding's derivation key through
      `load_listing_binding_by_derivation`, applying the 1.1 decision to listings bound
      before the key included the pool. Stop reading and writing
      `derived_bare_metal_listings`, including in `count_open_bare_metal_resources`.
- [ ] 3.3 Close a listing whose source was withdrawn, disabled, or moved to another pool
      as a withdrawn source, and a listing whose machine is unavailable as an availability
      close, through distinct plan entries.
- [ ] 3.4 Converge every configured registry on each listing's local status on every run.
- [ ] 3.5 Check each trusted site's projection in the storefront's health check and
      report each site's result.

## 4. Validation

- [ ] 4.1 **Unit.** Candidate derivation from a projection: an advertising, enabled,
      backed pool yields candidates; a non-advertising, disabled, or unbacked pool yields
      none and the unbacked pool is reported; an unresolvable pool holds.
- [ ] 4.2 **Integration.** Through the real storefront database and a site client over
      `ASGITransport`: a pool that stops advertising `bare_metal` closes its listing; a
      held pool's listing is neither closed nor refreshed; a site whose projection fetch
      fails keeps its listings open while another site reconciles.
- [ ] 4.3 **Integration.** Ordering and convergence: a new listing whose local record
      fails reaches no registry; a registry that misses a close and one left closed by a
      failed reopen are each repaired by the next run alone.
- [ ] 4.4 **Integration.** A Physical Resource moved to another pool closes its listing
      and publishes a successor under the new pool's binding; listings bound before the
      key included the pool behave as 1.1 decides.
- [ ] 4.5 **Integration.** A leased machine's listing closes as an availability close and
      reopens when the machine is free; the health check reports a down site.
- [ ] 4.6 `make test-bare-metal` and `make check-reinit`.

## 5. Closeout

- [ ] 5.1 **Comment hygiene.** Run `make check-comment-hygiene` and resolve every match.
      The local rationale to keep is why candidates come from the projection's view rather
      than a storefront-built one, why an unreachable site holds its listings, and why a
      listing is persisted before any registry is told.
- [ ] 5.2 **Import placement.** Review imports this change added or touched and migrate
      function-level ones to module level where no genuine circular import or documented
      lazy-load reason exists — the bare-metal domain package is installed without its
      storefront extra, which is such a reason. Verify against the real test suite.
- [ ] 5.3 **Documentation compliance.** Re-check accepted decisions against
      `openspec/README.md`'s placement table.
- [ ] 5.4 **Narrative compression.** Shorten completed-task notes to final behaviour,
      material validation evidence, deferred work, and permanent-documentation
      destinations.
- [ ] 5.5 **Roadmap currency.** Remove this change's row from Goal 7's gap table in
      `docs/development/ROADMAP.md` and update the current-state sentence that says
      bare-metal publication reads no pool declaration.
- [ ] 5.6 **Campaign index currency.** Update this change's row and Goal 7's dependency
      graph in `openspec/changes/README.md`, and record the unowned drop of
      `derived_bare_metal_listings`.
- [ ] 5.7 **Documentation citations.** Run
      `make check-doc-citations CHANGE=bare-metal-publication-reads-pool-declarations` and
      resolve every match.
- [ ] 5.8 **End-to-end pipeline.** Confirm the end-to-end pipeline passes and record the
      evidence: the run, its result, and the bare-metal scenarios that exercise this
      change's behaviour. If the pipeline cannot run for a reason unrelated to this
      change, record that as an explicit blocker naming the cause and the change that owns
      it, and treat the validations it gates as unrun rather than passed.
- [ ] 5.9 **Promotion.** Complete the design-promotion record below, including the
      `openspec/specs/storefront-publication/architecture.md` rationale.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| A listing advertises only a mode its pool authorizes, bare metal included | `openspec/specs/storefront-publication/spec.md` |
| An unbacked pool yields no bare-metal listing | `openspec/specs/storefront-publication/spec.md` |
| A held site holds bare-metal listings | `openspec/specs/storefront-publication/spec.md` |
| Registry convergence covers bare metal; a new listing is recorded locally before any registry is told | `openspec/specs/storefront-publication/spec.md` |
| Bare metal derives from the projection, not the capacity snapshot; listings are tracked by the common binding | `openspec/specs/storefront-publication/architecture.md` |
| "Publication candidate" has one name | `docs/development/ARCHITECTURE.md` (added during design) |
