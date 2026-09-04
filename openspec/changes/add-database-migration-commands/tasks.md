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

- [ ] 5.1 Promote explicit command/guard/ordering requirements to `openspec/specs/deployment-state/spec.md` and rationale to `architecture.md`.
- [ ] 5.2 Update `docs/development/ARCHITECTURE.md` only if repository-wide migration philosophy changes, record promotion in `design.md`, and run strict validation before archive.

## 6. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [ ] 6.1 **Comment hygiene.** Run `make check-comment-hygiene`, then direct-read the comments and docstrings this change touches for the fuzzier provenance-narration rule the target cannot catch mechanically.
- [ ] 6.2 **Import placement.** Review every import this change adds or touches and move it to module level where safe; retain a local import only against an observed circular import or a documented lazy-load reason, verified against the real suite.
- [ ] 6.3 **Documentation compliance.** Re-check this change's accepted decisions against `openspec/README.md`'s placement rules. It carries delta specs for `deployment-state`; confirm each landed in the owning `openspec/specs/<capability>/spec.md`, and that durable conceptual rationale sits in the companion `architecture.md` rather than only in `design.md`.
- [ ] 6.4 **Narrative compression.** Compress completed-task notes to final behavior, material validation evidence, unresolved or deferred work, and permanent-documentation destinations, moving durable rationale into `design.md` first.
- [ ] 6.5 **Roadmap currency.** This change sits under the lesser goal “Registry productionization”, which has no roadmap goal behind it, so it most likely owes `docs/development/ROADMAP.md` nothing. Confirm that and record the no-impact disposition explicitly rather than omitting the step.
- [ ] 6.6 **Campaign index currency.** Update this change's row, and its campaign's dependency graph, in `openspec/changes/README.md` to match its state at completion, or record the disposition here if its status and campaign placement are both unchanged.
- [ ] 6.7 **Promotion.** Add a design-promotion record, mapping every accepted decision to its exact permanent heading, and verify no production source references `openspec/changes/add-database-migration-commands`.
