## Why

Architecture, planned work, deferred ideas, operational warnings, and implementation checklists are currently mixed across a 3,800-line architecture reference, a 900-line TODO file, two ad hoc design/migration plans, and inline notes. This makes current behavior hard to distinguish from proposed behavior and allows status, acceptance criteria, and design decisions to drift between duplicate documents.

## What Changes

- Establish OpenSpec as the source of truth for product and architecture requirements, active changes, implementation tasks, and archived decisions.
- Convert stable, code-verified behavior from `docs/development/ARCHITECTURE.md` into capability specs organized by durable system responsibility rather than repository package.
- Convert actionable work from `docs/development/TODO.md`, `design-remaining-work.md`, `provisioning-migration-plan.md`, and explicitly marked ad hoc TODO/FIXME notes into independently reviewable OpenSpec changes.
- Classify non-actionable operational warnings as retained documentation or new requirements with concrete scenarios; do not silently turn every warning into planned work.
- Preserve provenance from each migrated requirement/change back to its source heading and record ambiguous, stale, duplicate, implemented, deferred, conditional, and externally blocked items explicitly.
- Update `openspec/config.yaml` with concise project context and artifact rules so future proposals use the repository's architectural vocabulary and verification conventions.
- Retire planning content from the legacy documents only after coverage and link checks prove that no requirement, decision, task, or warning was lost. Keep a small architecture overview for human orientation if it does not duplicate normative requirements.
- **BREAKING (contributor workflow):** after cutover, new planned work and normative architecture changes are recorded through OpenSpec rather than appended to `docs/development/TODO.md` or ad hoc planning files.

## Capabilities

### New Capabilities
- `planning-governance`: Defines source-of-truth boundaries, migration classification, provenance, lifecycle, validation, and contributor rules for OpenSpec-backed planning.

### Modified Capabilities

None. `openspec/specs/` is currently empty.

## Impact

- Planning artifacts: `openspec/config.yaml`, `openspec/specs/**`, `openspec/changes/**`, and `openspec/changes/archive/**`.
- Legacy documentation: `docs/development/ARCHITECTURE.md`, `TODO.md`, `design-remaining-work.md`, and `provisioning-migration-plan.md`.
- Ad hoc notes: tracked source files containing actionable TODO/FIXME markers; generated, vendored, lock, archive, and migration-history files are excluded unless a note is repository-owned and still actionable.
- Contributor workflow and AI session context change; runtime services, APIs, wire formats, databases, and deployment behavior do not change as part of this migration.
