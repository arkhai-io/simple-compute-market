# Repository Engineering Guidance

This file defines repository-wide rules for AI-assisted and human implementation work. Read it with `docs/development/ARCHITECTURE.md`, `docs/development/TESTING.md`, `docs/development/DEPLOYMENT_AND_CONFIG.md`, and `openspec/README.md` before changing code or specifications.

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
- End the plan with the closeout task defined in `openspec/README.md#plan-closeout-requirements` — comment hygiene, documentation compliance, and tasks compression. Do not defer this to a later review round. Promotion happens post code-review to reduce file churn.

### Implement

Implementation is not complete when code merely passes tests. It is complete when:

- the planned code and tests are implemented;
- accepted subsystem behavior is present in `openspec/specs/<subsystem>/spec.md`;
- accepted subsystem design rationale is present in `openspec/specs/<subsystem>/architecture.md` when it does not fit normative scenarios;
- accepted repository-wide architecture is present in `docs/development/ARCHITECTURE.md`;
- permanent documentation describes the current system rather than announcing completion;
- temporary migration and changelog commentary has been removed from production code;
- the active change records where each material decision was promoted;
- the relevant focused, integration, packaging, and typing checks have been run or any unrun checks are disclosed.

## Documentation ownership

- `docs/development/ARCHITECTURE.md` is the repository-wide architecture reference: system shape, dependency layers, authority boundaries, shared vocabulary, major flows, deployment topology, packaging rules, and testing philosophy.
- `openspec/specs/<subsystem>/spec.md` contains authoritative current subsystem behavior, invariants, ownership, and lifecycle semantics.
- `openspec/specs/<subsystem>/architecture.md` may contain durable current-state conceptual models, design motivation, trade-offs, relationships, and limitations. It does not replace normative requirements.
- `openspec/specs/README.md` is the canonical capability documentation index.
- `openspec/changes/` contains proposed deltas, design exploration, migration notes, implementation tasks, and temporary compatibility concerns.
- Git history and pull requests contain provenance and change history.

Production code must not depend on `openspec/changes` for design context. Before a change is considered implemented, durable knowledge from the change must be promoted to the owning `spec.md`, companion `architecture.md`, or repository-wide `ARCHITECTURE.md`. OpenSpec does not synchronize companion architecture files automatically, so applicable changes must name that promotion explicitly in tasks and the design-promotion record.

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

- Put a test at the lowest level that can meaningfully prove the behavior. See `docs/development/TESTING.md` for the level definitions, per-level jurisdiction, and coverage boundaries between them.
- Prefer observable seams, injected dependencies, and deterministic test controls over sleeps or brute-force monkeypatching.
- When a failure cannot be reproduced locally, report useful diagnostic steps and identify any design decision needed before changing behavior.
- A difficult-to-test failure is evidence to consider a testability refactor, not permission to bypass the boundary.
- Run `make check-comment-hygiene` before implementation is considered complete; see `openspec/README.md#plan-closeout-requirements`.

## Generated implementation artifacts

Return only updated files. Represent a file requiring deletion by replacing its entire contents with a single-line tombstone comment stating the reason, at the file's original path — never a separate manifest file, a suffixed parallel copy, or a silent omission. Tombstones are review artifacts only: final production code and permanent documentation must not contain one.

```python
# TOMBSTONE: delete this file — replaced by domains/apicredits/settlement/credits_client.py
```

## Public repository discipline

This repository is public. Everything in it — code, comments, documentation,
specifications, change documents, fixtures, test data, commit messages, and pull
request descriptions — is world-readable, permanently, including after a later
edit removes it.

Some work here is paired with work in separate private repositories. That
pairing never appears here.

### Never enters this repository

- Private repository names, branch names, or commit SHAs.
- Cloud project, account, cluster, namespace, or host identifiers.
- Internal endpoints, private URLs, or non-public service addresses.
- Wallet addresses, keys, or credentials of any kind, including expired ones and
  including ones believed to be test-only on a private network.
- Filesystem paths from a private repository or a private working environment.
- Raw logs, evidence bundles, or run artifacts produced by private tooling.
- The names or contents of private planning documents.

A change document, a `design.md` rationale, and a task note are as public as
production code. "It is only in the change directory" is not an exception.

### Test fixtures and local development configuration

Local development configuration in this repository is public by design and must
stay obviously so. Where a fixture needs an address, a key, or a host, use a
well-known deterministic development value and say in a comment that it is one
and must never be used on a public network.

A value that looks plausible and is not obviously a fixture is worse than no
comment, because a later reader cannot tell whether removing it is safe.

### Referring to work that is not here

When a change here exists because of work elsewhere, describe the requirement in
terms of this repository's own behaviour, not in terms of the external
consumer's identity.

Prefer:

```
Exposes a stable invocation target so an external test harness can run the
suite without reproducing the internal command sequence.
```

Avoid:

```
Needed by the harness runner in <private repo>, see <private plan document>.
```

The first is a durable statement about this repository's interface. The second
is a leak, and it also rots the moment the external caller is renamed.

### Cross-references must resolve

Every `openspec/`, `docs/`, `tools/`, `scripts/`, and `e2e-tests/` path cited by
a permanent document must exist on the branch that cites it.

A permanent document describing behaviour this branch does not implement is not
a harmless forward reference — it is how work from another branch or another
plan epoch gets treated as inherited without anyone deciding to inherit it. This
has happened in this repository: a closeout commit promoted a documentation
section describing a subsystem that has never existed on `dev`, citing a
specification requirement that has never existed on `dev`.

Note the shape of that failure, because the usual controls do not catch it. The
commit was inside its author's permitted paths and violated no scope rule; the
content came from a plan epoch the author had no authority over. Path
permissions cannot detect that. A cross-reference check can, in one pass — so
run one before promoting documentation, and treat an unresolvable citation as a
blocking defect rather than a stale link to fix later.

## Agent skills

### Issue tracker

GitHub Issues handle intake and triage through the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the five default triage labels. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context. See `docs/agents/domain.md`.
