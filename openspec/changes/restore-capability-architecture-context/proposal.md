## Why

The migration from the former monolithic architecture reference preserved headings and normative summaries but discarded substantial durable rationale, conceptual models, and testing/deployment motivation. Permanent capability documentation needs a supported freeform architecture layer without weakening OpenSpec's proposal → design → tasks → sync/archive lifecycle.

## What Changes

- Establish `openspec/specs/README.md` as the canonical capability table of contents, linking each normative `spec.md` and companion `architecture.md`.
- Add freeform `architecture.md` companions for existing capabilities where verified current design rationale was lost during migration.
- Restore only current, evidence-backed motivations and models; do not restore endpoint inventories, historical plans, obsolete identifiers, or unresolved claims.
- Add a permanent API-credits capability contract and architecture document for the implemented market domain omitted from the migrated baseline.
- Update planning governance, contributor guidance, and the repository-wide architecture map to distinguish normative contracts, durable capability rationale, cross-system architecture, operational documentation, and temporary change artifacts.
- Record unresolved publication, packaging, configuration, FRP, typed-client, and settlement-generalization questions as explicitly deferred rather than presenting them as current architecture.

## Capabilities

### New Capabilities

- `api-credits`: Authority, identity, quota, issuance, and settlement behavior for the implemented API-credits market domain.

### Modified Capabilities

- `planning-governance`: Require durable accepted design rationale to be promoted to capability architecture documents and indexed alongside normative specifications.

## Impact

- Documentation: `openspec/specs/`, `openspec/README.md`, and `docs/development/ARCHITECTURE.md`.
- Contributor workflow: change plans and promotion records must identify both normative and architectural-rationale destinations where applicable.
- Runtime code, APIs, persistence, deployment, and package dependencies are unchanged.
- Deferred verification topics remain outside the current baseline and require separate changes before becoming normative.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specifications
- [x] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- Capability contracts and freeform architecture have distinct permanent roles under one OpenSpec lifecycle.
- The capability index is the canonical entry point for both kinds of permanent documentation.
- Verified rationale from the pre-OpenSpec architecture belongs in owning capability architecture documents.
- API-credits authority and lifecycle behavior belongs in a dedicated permanent capability.
