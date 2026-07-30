## Context

Compute provisioning has a standalone migration entry point, deployment init container, and startup compatibility guard. VM storefront construction still performs core bootstrap and domain-specific `ALTER TABLE` work, while API-credit storefront/service startup creates schema directly. This couples normal startup to write-capable migration and makes rollout failures appear as application failures.

## Goals / Non-Goals

**Goals:** explicit idempotent migration commands; read-only runtime guards; migration-before-app deployment ordering; current database preservation.

**Non-Goals:** business-schema redesign, automatic downgrade, or registry PostgreSQL cutover.

## Decisions

### Use composition-owned migration heads

Shared core storefront owns schema-opaque core migrations; each concrete storefront composition declares and runs its domain migration set and expected head. Runtime client construction opens compatible schema without applying changes. API-credit service owns its ledger migration chain independently from storefront state.

### Preserve fresh and existing database paths

A migration command must build a fresh database and advance representative existing versions to the same expected schema. Existing ad hoc bootstrap behavior is converted into ordered idempotent revisions before removal from runtime construction.

### Fail startup read-only and actionably

Runtime checks migration metadata and required invariants without issuing DDL. Missing, behind, or ahead/incompatible schema exits with the exact migration command and observed/expected head. Empty first-run databases must be migrated by init tooling.

### Run migration as deployment preparation

Local Make targets and deployment init containers run the packaged command with the same database path/credentials and image version as the application. Render tests prove the init phase exists and precedes startup.

## Risks / Trade-offs

- **[Current bootstrap is not reproducible as revisions]** → Test blank and historical fixtures before disabling runtime mutation.
- **[Shared/core and domain heads diverge]** → Let the concrete composition own ordered execution and one expected compatibility result.
- **[Rollback binary sees newer schema]** → Keep changes additive/expand-contract and make ahead-schema policy explicit per role.

## Migration Plan

1. Strengthen provisioning CLI/render evidence without changing its accepted behavior.
2. Extract VM storefront bootstrap/domain changes into an explicit chain and guard.
3. Add API-credit storefront and service chains/guards.
4. Add local/deployment migration phases, then disable runtime mutation.

Rollback uses the prior binary only while schema compatibility permits; data is not automatically downgraded.

## Permanent Documentation Promotion

Accepted commands, startup semantics, and deployment ordering belong in `openspec/specs/deployment-state/spec.md` and `architecture.md`; repository-wide migration philosophy updates belong in `docs/development/ARCHITECTURE.md` only if changed.
