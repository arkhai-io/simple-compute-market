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
| Testing methodology, test-level jurisdiction, and validation conventions | `docs/development/TESTING.md` |
| Configuration resolution and Kubernetes deployment conventions | `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| Directional goals, the value each delivers, current state per goal, and which change owns each open gap | `docs/development/ROADMAP.md` |
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

## Open questions and prescribed tasks

An item may not appear under a change's `## Open questions` while a non-decision
task prescribes it. A design that calls a question open while its task list
instructs an implementer to answer it one way has not deferred the decision — it
has made it somewhere a reviewer will not look, and an implementer reading only
`tasks.md` will reasonably assume authority they were never given.

Either move the item into the design's decisions with its revisit trigger
stated, or make the task an explicit decision gate. A task that says "decide X
and record the reasoning" is a gate; a task that says "do X" is not, whether or
not it cites the open question.

## Plan closeout requirements

Every `tasks.md` for a change or a major section within one must end with a closeout task before implementation is considered planned, not invented after a review round asks for it. The closeout task has seven parts:

1. **Comment hygiene.** Run `make check-comment-hygiene` and resolve every match before the task is marked done. The target catches change IDs, section numbers, and task numbers mechanically; it does not catch fuzzier violations of `AGENTS.md`'s "Python comments and docstrings" rule (references to which review or migration introduced the code), which still need a direct read.
2. **Import placement.** Migrate local (function-level) imports to module level wherever safe. Not a blanket move: check each import actually added or touched by the section for a real reason to stay local first — a genuine circular import (verify by attempting the move and reading the actual failure, not by assuming) or a documented, deliberate lazy-load reason (e.g. avoiding import cost for a rarely-exercised code path) — before relocating it. Cross-reference against the section's own diff rather than auditing every pre-existing local import in a touched file; this step is about what the section added, not a general-purpose repo cleanup. Verify each candidate move against the real test suite, not just a syntax check, since a passing import at definition time does not guarantee no circular dependency exists at call time.
3. **Documentation compliance.** Re-check the change's own accepted decisions against this document's placement rules directly — do not defer this to an external reviewer noticing it first.
4. **Narrative compression.** Shorten completed-task notes to final behavior, material validation evidence, unresolved or deferred work, and permanent-documentation destinations. Move detailed alternatives, debugging narratives, and review rationale into `design.md` first if they are not already there — this step deletes duplication, not information.
5. **Roadmap currency.** Update the affected goal's current-state description and gap-to-change mapping in [`docs/development/ROADMAP.md`](../docs/development/ROADMAP.md), and name that update in the design-promotion record. Currency is owed at change *completion*, not at archival, so a completed-but-unarchived change is already reflected. Most changes owe nothing here; a change with no roadmap impact records that disposition explicitly rather than omitting the step, so an absent roadmap edit is a deliberate finding rather than an unanswered question at review.
6. **Campaign index currency.** Update the change's row, and its campaign's dependency graph, in [`changes/README.md`](changes/README.md) so the recorded status matches what is now true, and name that update in the design-promotion record. Like roadmap currency this is owed at change *completion* rather than at archival, because the index answers what a reader may start next and a stale row misdirects that decision. A change whose status and campaign placement are both unchanged records that disposition explicitly rather than omitting the step. A change that creates, renames, supersedes, or removes a change directory reconciles the index's links in the same step: a link to a directory that does not exist is a blocking defect under `AGENTS.md`'s cross-reference rule, not a stale link to fix later.
7. **Promotion.** Complete the design-promotion record (see below).

If a plan's closeout task is growing unusually large on its own, that is a signal the change may have scope-crept past its original boundary — worth a deliberate decision about whether to split it into a new change, not something to notice only once the section is already difficult to review.

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
- [ ] Production code contains no references to `openspec/changes`, task IDs, previous file locations, or migration provenance — `make check-comment-hygiene` passes.
- [ ] Non-obvious comments communicate local rationale and invariants.
- [ ] The active change contains a design-promotion record.
- [ ] Every file requiring deletion is present at its original path with its content replaced by a single-line tombstone comment — no separate manifest, no suffixed copy, no silent omission.
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
