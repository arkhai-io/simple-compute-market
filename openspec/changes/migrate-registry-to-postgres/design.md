## Context

The registry can construct a PostgreSQL engine and ships a PostgreSQL driver, but startup still invokes ORM `create_all` and migration/stamping in process. Deployment defaults use SQLite, a PVC, and `Recreate`. A blank Alembic audit reaches current revision while omitting the `api_keys` table and `listings.demands` because revisions assume ORM bootstrap created them. There is no packaged migration command, PostgreSQL integration suite, or rehearsed data cutover.

## Goals / Non-Goals

**Goals:** complete migration history; preserved current state; external PostgreSQL deployment; migration-before-rollout; tested rollback/backup.

**Non-Goals:** external infrastructure provisioning, registry API changes, or filter indexing.

## Decisions

### Block implementation on infrastructure and topology readiness

The shared-registry deployment separation lands first. External Cloud SQL/IAM/network/Secret ownership must have a named operator and test environment before implementation tasks are generated. This change remains intentionally taskless while blocked.

### Make Alembic the only production schema authority

Repair the chain so `upgrade head` creates every current table, column, index, constraint, and deterministic invariant from blank and upgrades supported existing schemas. ORM `create_all` is limited to isolated unit fixtures if retained at all; production startup performs a read-only head/invariant guard.

### Preserve registry state

The cutover migrates publishers, listing JSON/demands/status, API keys/scopes, and identity sequences. It verifies row counts, stable public identifiers, key hashes/scopes, representative query equivalence, and sequence continuation. A disposable-state cutover was rejected because registry authority and credentials are operational state.

### Package migration and deploy before rollout

The image includes Alembic configuration and a packaged command. A Helm migration Job uses Secret-backed DSN and the target application image before Deployments roll. PostgreSQL mode disables SQLite PVC and `Recreate`; rollout strategy permits compatible old/new pods only after expand/contract analysis.

### Retain a rehearsed rollback boundary

Before traffic cutover, snapshot SQLite and PostgreSQL and define the write-freeze/data-delta boundary. Rollback cannot safely accept writes independently in both databases; the runbook names the source of truth and restoration point.

## Risks / Trade-offs

- **[Migration history does not match deployed SQLite variants]** → Build representative fixtures and compare ORM/Alembic schemas before cutover.
- **[Data changes during copy]** → Use a bounded write freeze or verified incremental reconciliation.
- **[Secret leaks through values/jobs]** → Use Secret references and redact command/log output.
- **[Old/new binaries disagree on schema]** → Use expand/contract and explicit compatibility matrices.
- **[Cloud SQL is unavailable]** → Keep verified backup and a rehearsed rollback before DNS/config switch.

## Activation Questions

- Which external project owns instance, IAM, network, backups, and credential rotation?
- Which deployed SQLite schema/data fixture is the migration source of record?
- What downtime/write-freeze budget is accepted?
- Which old/new binary versions must coexist during rollout?

## Permanent Documentation Promotion

After implementation, PostgreSQL authority, migration ordering, backup/rollback, and deployment topology belong in `openspec/specs/deployment-state/spec.md` and `architecture.md`; operator procedure belongs in registry deployment documentation.
