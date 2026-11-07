# Tasks — API-credit end-to-end lane

Design phase; not planned. Loop holding follows `bare-metal-mock-provisioned-deal`,
which builds the API-credit lane; the integration tests have no blocking dependency.

## 1. Design

- [x] 1.1 **Decision gate.** Decide whether API credits runs in its own lane. Decided:
      its own pipeline job, not inside the VM lane. Building it migrated to
      `bare-metal-mock-provisioned-deal` on 2026-10-01.
- [x] 1.2 **Decision gate.** Decide what an API-credit storefront integration test
      runs. Decided: the production application through its lifespan, with a real
      database and the canonical typed client.
- [ ] 1.3 **Decision gate.** Resolve the open questions in `design.md`.
- [ ] 1.4 Plan the implementation.

## 2. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [ ] 2.1 **Comment hygiene — confirm.** Run `make check-comment-hygiene`, and read
      the comments this change added for any that narrate the review or migration that
      introduced them. Do not edit code here: anything to rewrite returns the change to
      implementation.
- [ ] 2.2 **Import placement — confirm.** Check the imports this change added for any
      still local without a recorded reason. One that should move returns the change to
      implementation.
- [ ] 2.3 **Documentation compliance.** Re-check this change's accepted decisions
      against `openspec/README.md`'s placement rules, and the permanent documents
      against the code they describe.
- [ ] 2.4 **Narrative compression.** Compress completed-task notes to final behavior,
      material validation evidence, unresolved or deferred work, and
      permanent-documentation destinations, moving durable rationale into `design.md`
      first.
- [ ] 2.5 **Roadmap currency.** Update the affected goal's current state and gap
      mapping in `docs/development/ROADMAP.md`, or record that no goal is affected.
- [ ] 2.6 **Campaign index currency.** Update this change's row, and its campaign's
      dependency graph, in `openspec/changes/README.md`, or record that both are
      unchanged. Other rows' `Depends on` are left alone: archive cleanup releases
      dependents after the closeout gate.
- [ ] 2.7 **Packaging.** Run `make check-packaging` and resolve every failure it
      reports (a failure needing a code or lock change returns the change to
      implementation).
- [ ] 2.8 **End-to-end pipeline.** Record the passing run the latest validation names,
      its result, and the scenarios that exercise this change, or an explicit blocker
      naming its cause and the change that owns it, with the validations it gates
      treated as unrun.
- [ ] 2.9 **Promotion.** Write the permanent documents this change owes — named when
      this change is planned — and complete the design-promotion record. The
      `test-compatibility` `spec.md`, which the deltas cover, is written by the archive
      in 2.11, not by hand; the record names it all the same.
- [ ] 2.10 **Documentation citations.** After promotion, run
      `make check-doc-citations CHANGE=apicredits-end-to-end-lane` and resolve every match, then
      `openspec validate apicredits-end-to-end-lane --strict`.
- [ ] 2.11 **Archival.** Last, once every other part is checked: `openspec archive
      apicredits-end-to-end-lane -y` merges the deltas into `openspec/specs/` and moves the
      change under `openspec/changes/archive/`; point the index row at the archived
      directory, and run `openspec validate --specs --strict`.
