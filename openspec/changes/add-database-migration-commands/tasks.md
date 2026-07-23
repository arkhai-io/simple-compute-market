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
