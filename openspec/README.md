# Arkhai OpenSpec Guide

OpenSpec separates the system's durable current contract from the temporary work required to change it.

- `specs/<capability>/spec.md` describes the implemented normative contract: behavior, ownership, invariants, and lifecycle semantics.
- `specs/<capability>/architecture.md` may preserve durable current-state models, motivations, trade-offs, relationships, and limitations in freeform prose.
- `specs/README.md` is the canonical capability documentation index.
- `changes/` describes a transition: proposal, alternatives, unresolved questions, delta requirements, migration concerns, and implementation tasks. [`changes/README.md`](changes/README.md) groups active changes into delivery campaigns without replacing each change's acceptance boundary.
- `changes/archive/` records completed transitions after their durable results have been synchronized into `specs/` and, where repository-wide, `docs/development/ARCHITECTURE.md`.
- `config.yaml` supplies repository context and artifact-quality rules.

Use `bunx @fission-ai/openspec@latest list` to inspect active changes, `show <name>` to read one, and `validate --all --strict` before review.

## Documentation placement

| Knowledge | Permanent home |
|---|---|
| Repository-wide dependency layers, authority boundaries, common vocabulary, and major flows | `docs/development/ARCHITECTURE.md` |
| Subsystem behavior, package ownership, lifecycle, identifiers, and errors | `openspec/specs/<subsystem>/spec.md` |
| Subsystem conceptual models, durable rationale, trade-offs, relationships, and current limits | `openspec/specs/<subsystem>/architecture.md` |
| Proposed behavior and unresolved alternatives | `openspec/changes/<change>/proposal.md` and `design.md` |
| Implementation sequence, files, validation, and manual migration work | `openspec/changes/<change>/tasks.md` |
| Change provenance and review discussion | Git history and pull requests |

`ARCHITECTURE.md` is a current-state cross-system map. It should link to detailed subsystem specifications rather than duplicate every endpoint and state transition. Permanent specs may include short rationale needed to interpret a requirement. Broader explanatory prose belongs in the capability's companion `architecture.md`. Neither document preserves the chronology of how a decision was reached.

## Capability documentation pattern

A subsystem `spec.md` should contain its purpose and normative requirements for responsibilities, authority, dependencies, terminology, lifecycle, errors, retry, idempotency, versioning, and other observable behavior. Every requirement has acceptance scenarios and may point to implementation or test evidence.

A companion `architecture.md` may explain:

1. Conceptual models and major flows.
2. Why an authority or dependency boundary exists.
3. Ownership relationships and explicit non-responsibilities.
4. Alternatives and trade-offs that remain relevant to the current design.
5. Operational consequences and current limitations.
6. Links to adjacent capability contracts.

Both files describe the current system. Avoid wording such as "completed in POOLS-7" or "formerly lived in". Planned and partially implemented behavior remains in a change until it is true. When architecture prose states behavior implementations must satisfy, add the corresponding normative requirement to `spec.md`.

OpenSpec validates and synchronizes `spec.md` but ignores companion architecture files. Every applicable change therefore names companion promotion in `tasks.md` and its design-promotion record.

## Change documentation requirements

Every non-trivial `proposal.md` should identify permanent documentation impact:

```markdown
## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [ ] Existing subsystem specification
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- <material accepted decision and intended permanent destination>
```

Every implementation-ready `tasks.md` should name the exact promotion work rather than using a generic "update docs" task.

During implementation, maintain a promotion record in the active change:

```markdown
## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Fulfillment owns provider-neutral execution contracts | `openspec/specs/fulfillment/spec.md#ownership` |
| Kit dependency layers | `docs/development/ARCHITECTURE.md#package-and-dependency-layers` |
```

The record is change history and remains in the change directory. The destination documents describe only the resulting current state.

## Implementation completion checklist

Before marking implementation complete:

- [ ] Code and tests satisfy the change specification.
- [ ] Existing completed tasks remain preserved; corrections are appended or amended.
- [ ] Every accepted material decision has been classified as permanent, temporary, superseded, or rejected.
- [ ] Subsystem-specific durable knowledge is present in `openspec/specs`.
- [ ] Repository-wide durable knowledge is present in `ARCHITECTURE.md`.
- [ ] Permanent documents describe current state rather than completion history.
- [ ] Production code contains no references to `openspec/changes`, task IDs, previous file locations, or migration provenance.
- [ ] Non-obvious comments communicate local rationale and invariants.
- [ ] The active change contains a design-promotion record.
- [ ] Manual deletions are represented by review tombstones and listed in the delivery summary.
- [ ] Validation evidence and any unrun suites are disclosed.

## Current capability documentation

See the canonical [capability documentation index](specs/README.md) for every normative contract and architecture companion.

## Contributor workflow

1. Read `AGENTS.md`, `docs/development/ARCHITECTURE.md`, the owning permanent specs, and the active change.
2. Audit the proposed delta against current code and focused evidence.
3. Resolve design questions in the active change and identify permanent documentation impact.
4. Preserve completed tasks and create or amend an implementation plan only after the design is ready.
5. Implement code, tests, permanent documentation, and the change's design-promotion record together.
6. Run focused behavioral, package, typing, and integration checks appropriate to the boundary.
7. Synchronize the verified delta, confirm no production code references temporary change documents, and archive the completed change.
