# Repository Engineering Guidance

This file defines repository-wide rules for AI-assisted and human implementation work. Read it with `docs/development/ARCHITECTURE.md` and `openspec/README.md` before changing code or specifications.

## Working model

Use a discuss → plan → implement workflow for non-trivial changes.

### Discuss

- Inspect current code, permanent specifications, and the active change before proposing a design.
- Record alternatives, unresolved questions, and proposed decisions in `openspec/changes/<change>/design.md`.
- Update `proposal.md` when the intended scope, impact, or acceptance boundary changes.
- Do not treat an active change document as permanent architecture.

### Plan

- Preserve existing completed tasks. Amend or append tasks rather than replacing implementation history.
- Name the files to touch and why.
- Identify the permanent documentation destination for every accepted material design decision.
- Include focused validation and relevant integration suites.

### Implement

Implementation is not complete when code merely passes tests. It is complete when:

- the planned code and tests are implemented;
- accepted subsystem design is present in `openspec/specs/<subsystem>/spec.md`;
- accepted repository-wide architecture is present in `docs/development/ARCHITECTURE.md`;
- permanent documentation describes the current system rather than announcing completion;
- temporary migration and changelog commentary has been removed from production code;
- the active change records where each material decision was promoted;
- the relevant focused, integration, packaging, and typing checks have been run or any unrun checks are disclosed.

## Documentation ownership

- `docs/development/ARCHITECTURE.md` is the repository-wide architecture reference: system shape, dependency layers, authority boundaries, shared vocabulary, major flows, deployment topology, packaging rules, and testing philosophy.
- `openspec/specs/` contains authoritative current subsystem behavior, invariants, ownership, lifecycle semantics, and durable design rationale.
- `openspec/changes/` contains proposed deltas, design exploration, migration notes, implementation tasks, and temporary compatibility concerns.
- Git history and pull requests contain provenance and change history.

Production code must not depend on `openspec/changes` for design context. Before a change is considered implemented, durable knowledge from the change must be promoted to `openspec/specs` or `ARCHITECTURE.md`.

## Python comments and docstrings

Comments and docstrings describe the current system, not the history of a change.

Do not reference:

- OpenSpec change IDs or task numbers;
- `tasks.md`;
- previous file locations;
- the feature, migration, or review that introduced the code;
- tombstones or generated-artifact instructions;
- temporary implementation phases as though they were permanent rationale.

Use comments for:

- non-obvious invariants;
- safety and correctness constraints;
- reasons an apparently simpler implementation is invalid;
- lifecycle or concurrency assumptions;
- behavior that cannot be made clear through naming and structure.

When broader context is needed, state the applicable rule locally and link to a stable heading in `openspec/specs` or `ARCHITECTURE.md`.

Prefer:

```python
# Fulfillment may depend on site and resource-pool authorities; those lower
# layers must not import fulfillment, including under TYPE_CHECKING.
# See openspec/specs/fulfillment/spec.md#dependency-boundary.
```

Avoid:

```python
# Moved here during POOLS-7 task 1.8.
```

A bare documentation pointer is not a substitute for a useful local explanation.

## Package and dependency discipline

- Follow the dependency layers defined in `ARCHITECTURE.md` and the relevant subsystem specification.
- `TYPE_CHECKING` imports count as architectural dependencies.
- Internal Python dependencies are built into `.dist` and installed from wheels. Do not add editable sibling paths merely to make local development work.
- Reinit targets must explicitly upgrade/reinstall changed internal packages from `.dist`.

## Tests and diagnostics

- Put a test at the lowest level that can meaningfully prove the behavior.
- Prefer observable seams, injected dependencies, and deterministic test controls over sleeps or brute-force monkeypatching.
- When a failure cannot be reproduced locally, report useful diagnostic steps and identify any design decision needed before changing behavior.
- A difficult-to-test failure is evidence to consider a testability refactor, not permission to bypass the boundary.

## Generated implementation artifacts

Return only updated files. Copying an archive does not delete files, so paths requiring deletion must be represented by explicit review tombstones and listed as manual actions. Tombstones are review artifacts only: final production code and permanent documentation must not mention them.
