## 1. Reconcile the Upstream Slice

- [x] 1.1 Rebase only PR #134's two POOLS-1 implementation commits onto the current OpenSpec branch.
- [x] 1.2 Exclude the PR branch's unrelated package, planning, generated, and repository-wide changes.
- [x] 1.3 Preserve the current compute-contract, site-authority, and service-composition architecture while resolving conflicts.

## 2. Define Pool Contracts and Persistence

- [x] 2.1 Add provider-neutral pool request, response, validation, and reconciliation models to `compute_provisioning`.
- [x] 2.2 Add the generic provider configuration handler protocol and Ansible handler implementation.
- [x] 2.3 Add resource-pool and Ansible-configuration persistence with stable IDs and relationships.
- [x] 2.4 Move VM operator client pool operations onto compute-owned models without recreating `provisioning_client`.

## 3. Implement Pool and Host Behavior

- [x] 3.1 Implement create, list, detail, full replace, partial update, enable, and disable behavior.
- [x] 3.2 Keep the `default` pool present and enabled across every mutation path.
- [x] 3.3 Add host pool assignment, defaulting, validation, response fields, and reassignment behavior.
- [x] 3.4 Register pool services and routes alongside the existing compute-contract and site-authority services.

## 4. Implement Canonical Reconciliation

- [x] 4.1 Implement canonical YAML export with provider configuration included.
- [x] 4.2 Implement strict validation with structured paths, codes, messages, duplicate detection, and unknown-field rejection.
- [x] 4.3 Implement validation-only deterministic diffs without writes.
- [x] 4.4 Implement all-or-nothing authoritative import that disables omitted pools without deleting them.

## 5. Migrate and Package

- [x] 5.1 Order the compute-contract migration before the pool schema migration and seed/backfill `default` safely.
- [x] 5.2 Add a standalone provisioning migration command, startup schema check, and Helm init container.
- [x] 5.3 Advance compute and VM operator client package versions, dependency constraints, build ordering, and lockfiles.
- [x] 5.4 Build the isolated compute and VM operator client wheels and verify their dependency direction.

## 6. Verify Behavior

- [x] 6.1 Cover pool CRUD, full-versus-partial update semantics, provider validation, lifecycle, and host assignment.
- [x] 6.2 Cover strict YAML validation, missing/disabled default pool, duplicate IDs, dry-run, idempotency, and rollback behavior.
- [x] 6.3 Cover ordered migration, legacy host backfill, schema drift rejection, and idempotent migration execution.
- [x] 6.4 Run the complete provisioning unit and integration suite and validate the OpenSpec change strictly.
