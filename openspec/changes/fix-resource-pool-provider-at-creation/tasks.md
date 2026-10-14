# Tasks

Section 0 keeps the numbering it has in `pools-9-retire-local-physical-authority`,
which points here.

## 0. Fix a pool's executor at creation

- [ ] 0.1 Reject a differing provider in `ResourcePoolService.replace_pool` and the
      patch path, instead of deleting the old handler's configuration and
      reassigning `pool.provider`. Rejection must not delete the existing
      configuration on its way out — a refused request leaves the pool exactly as it
      was. Follow `_require_backing_unchanged`'s placement: refuse before any write.
- [ ] 0.2 Leave provider configuration replaceable and patchable within the declared
      provider. This forbids changing which executor a pool routes to, not how that
      executor is configured.
- [ ] 0.3 **Unit.** Replace with a differing provider is rejected and the existing
      configuration survives; replace with the same provider and new configuration
      succeeds; patch with a differing provider is rejected; patch with the same
      provider is a no-op for the provider field.
- [ ] 0.4 **Integration.** The same cases through the real pool administration
      API and its canonical client, since the deletion this removes happens inside a
      transaction a service-level test can miss.
- [ ] 0.5 Confirm no fixture, bulk import path, definition-document import, or e2e
      setup relies on an in-place provider swap. If one does, migrate it to the
      two-pool path rather than exempting it.
- [ ] 0.6 Confirm `capacity-resource-administration`'s drain invariant covers the
      migration path this section makes the only one, and have the refusal name
      that path.
- [ ] 0.7 **Comment hygiene and import placement, before the pre-closeout review.** Run
      `make check-comment-hygiene` and read the comments this change added for any that
      narrate the review or migration that introduced them; move each import the change
      added to module level unless a verified circular import or a recorded lazy-load
      reason keeps it local. Closeout only confirms both.

## 1. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [ ] 1.1 **Comment hygiene — confirm.** Run `make check-comment-hygiene`, and read
      the comments this change added for any that narrate the review or migration that
      introduced them. Do not edit code here: anything to rewrite returns the change to
      implementation.
- [ ] 1.2 **Import placement — confirm.** Check the imports this change added for any
      still local without a recorded reason. One that should move returns the change to
      implementation.
- [ ] 1.3 **Documentation compliance.** Re-check this change's accepted decisions
      against `openspec/README.md`'s placement rules, and the permanent documents
      against the code they describe. The decision belongs in
      `resource-pool-management`, which owns provider configuration.
- [ ] 1.4 **Narrative compression.** Compress completed-task notes to final behavior,
      material validation evidence, unresolved or deferred work, and
      permanent-documentation destinations, moving durable rationale into `design.md`
      first.
- [ ] 1.5 **Roadmap currency.** Update the affected goal's current state and gap
      mapping in `docs/development/ROADMAP.md`, or record that no goal is affected. No
      roadmap gap row names this change; record that disposition, and remove the
      provider-swap sentence from Goal 1's current-state text if one was added.
- [ ] 1.6 **Campaign index currency.** Update this change's row in the Goal 1
      campaign, and that campaign's dependency graph, in `openspec/changes/README.md`,
      or record that both are unchanged. Other rows' `Depends on` are left alone:
      archive cleanup releases dependents after the closeout gate.
- [ ] 1.7 **Packaging.** Run `make check-packaging` and resolve every failure it
      reports (a failure needing a code or lock change returns the change to
      implementation).
- [ ] 1.8 **End-to-end pipeline.** Record the passing run the latest validation names,
      its result, and the scenarios that exercise this change, or an explicit blocker
      naming its cause and the change that owns it, with the validations it gates
      treated as unrun.
- [ ] 1.9 **Promotion.** Write the permanent documents this change owes — none beyond
      the `resource-pool-management` specification — and complete the design-promotion
      record below. A `spec.md` the deltas cover
      (`openspec/specs/resource-pool-management/spec.md`) is written by the archive in
      1.11, not by hand; the record names it all the same.
- [ ] 1.10 **Documentation citations.** After promotion, run
      `make check-doc-citations CHANGE=fix-resource-pool-provider-at-creation` and resolve every
      match, then `openspec validate fix-resource-pool-provider-at-creation --strict`.
- [ ] 1.11 **Archival.** Last, once every other part is checked: `openspec archive
      fix-resource-pool-provider-at-creation -y` merges the deltas into `openspec/specs/` and
      moves the change under `openspec/changes/archive/`; point the index row at the
      archived directory, and run `openspec validate --specs --strict`.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| A pool's provider is fixed at creation; replace and patch refuse a differing provider without deleting existing configuration | `openspec/specs/resource-pool-management/spec.md` — "A pool's executor is fixed at creation" |
| Inventory moves executors through a second pool and member migration, safe under the drain invariant | `openspec/specs/resource-pool-management/spec.md` — same requirement |
