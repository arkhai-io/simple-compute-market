## 1. Verify the provisioning reference

- [ ] 1.1 Add direct CLI exit/logging/idempotency tests for `compute-provisioning-migrate` on blank, current, behind, and incompatible databases.
- [ ] 1.2 Add Helm render assertions for the provisioning migration init container, image/version parity, database path, and startup ordering.

## 2. Separate VM storefront migration

- [ ] 2.1 Inventory core bootstrap, migration metadata, VM domain migrations, and every runtime DDL path in `core/storefront` and `domains/vms/storefront`.
- [ ] 2.2 Define ordered shared/domain revision heads and historical database fixtures before changing construction behavior.
- [ ] 2.3 Implement a packaged VM storefront migration command and idempotent fresh/existing upgrades.
- [ ] 2.4 Make runtime SQLite construction DDL-free and add actionable absent/behind/ahead schema guards.
- [ ] 2.5 Add local Make migration/reinit targets and VM storefront unit/integration/migration tests.

## 3. Separate API-credit migrations

- [ ] 3.1 Inventory API-credit storefront and service `create_all`, table, index, and seed behavior and assign independent database ownership.
- [ ] 3.2 Add packaged idempotent migration commands and runtime guards for each stateful API-credit role.
- [ ] 3.3 Add blank/current/historical/restart tests and preserve quota, grants, keys, balances, and storefront agreement state.

## 4. Deployment and compatibility

- [ ] 4.1 Add migration init phases for VM storefront, API-credit storefront, and API-credit service using the application image/version and database credentials.
- [ ] 4.2 Add render tests proving migration precedes application and disabled roles emit no migration resources.
- [ ] 4.3 Run focused role suites, historical fixture upgrades, packaging/install checks, and rollback compatibility checks.

## 5. Permanent promotion

- [x] 5.1 **Withdrawn** 2026-10-14: closeout does this — 6.9 writes the architecture companion by hand, and the archive in 6.11 writes the `deployment-state` spec its delta covers. As first planned: Promote explicit command/guard/ordering requirements to `openspec/specs/deployment-state/spec.md` and rationale to `architecture.md`.
- [ ] 5.2 Update `docs/development/ARCHITECTURE.md` only if repository-wide migration philosophy changes, record promotion in `design.md`, and run strict validation before archive.
- [ ] 5.3 **Comment hygiene and import placement, before the pre-closeout review.** Run
      `make check-comment-hygiene` and read the comments this change added for any that
      narrate the review or migration that introduced them; move each import the change
      added to module level unless a verified circular import or a recorded lazy-load
      reason keeps it local. Closeout only confirms both.

## 6. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [ ] 6.1 **Comment hygiene — confirm.** Run `make check-comment-hygiene`, and read
      the comments this change added for any that narrate the review or migration that
      introduced them, and confirm no production source references
      `openspec/changes/add-database-migration-commands`. Do not edit code here:
      anything to rewrite returns the change to implementation.
- [ ] 6.2 **Import placement — confirm.** Check the imports this change added for any
      still local without a recorded reason. One that should move returns the change to
      implementation.
- [ ] 6.3 **Documentation compliance.** Re-check this change's accepted decisions
      against `openspec/README.md`'s placement rules, and the permanent documents
      against the code they describe. Durable conceptual rationale for the
      `deployment-state` delta sits in the companion `architecture.md` rather than only
      in `design.md`.
- [ ] 6.4 **Narrative compression.** Compress completed-task notes to final behavior,
      material validation evidence, unresolved or deferred work, and
      permanent-documentation destinations, moving durable rationale into `design.md`
      first.
- [ ] 6.5 **Roadmap currency.** Update the affected goal's current state and gap
      mapping in `docs/development/ROADMAP.md`, or record that no goal is affected.
      This change sits under the lesser goal "Registry productionization", which has no
      roadmap goal behind it, so it most likely owes the roadmap nothing; confirm that
      and record the no-impact disposition.
- [ ] 6.6 **Campaign index currency.** Update this change's row, and its campaign's
      dependency graph, in `openspec/changes/README.md`, or record that both are
      unchanged. Other rows' `Depends on` are left alone: archive cleanup releases
      dependents after the closeout gate.
- [ ] 6.7 **Packaging.** Run `make check-packaging` and resolve every failure it
      reports (a failure needing a code or lock change returns the change to
      implementation).
- [ ] 6.8 **End-to-end pipeline.** Record the passing run the latest validation names,
      its result, and the scenarios that exercise this change, or an explicit blocker
      naming its cause and the change that owns it, with the validations it gates
      treated as unrun.
- [ ] 6.9 **Promotion.** Write the permanent documents this change owes —
      `openspec/specs/deployment-state/architecture.md` (command, guard, and ordering
      rationale), and `docs/development/ARCHITECTURE.md` only if the repository-wide
      migration philosophy changes — and complete the design-promotion record, mapping
      every accepted decision to its exact permanent heading. The `deployment-state`
      `spec.md`, which the deltas cover, is written by the archive in 6.11, not by hand;
      the record names it all the same.
- [ ] 6.10 **Documentation citations.** After promotion, run
      `make check-doc-citations CHANGE=add-database-migration-commands` and resolve every
      match, then `openspec validate add-database-migration-commands --strict`.
- [ ] 6.11 **Archival.** Last, once every other part is checked: `openspec archive
      add-database-migration-commands -y` merges the deltas into `openspec/specs/` and
      moves the change under `openspec/changes/archive/`; point the index row at the
      archived directory, and run `openspec validate --specs --strict`.
