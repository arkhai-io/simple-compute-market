# Repository Engineering Guidance

This file defines repository-wide rules for AI-assisted and human implementation work. Read it with `docs/development/ARCHITECTURE.md`, `docs/development/TESTING.md`, `docs/development/DEPLOYMENT_AND_CONFIG.md`, and `openspec/README.md` before changing code or specifications.

## Where the guidance lives

The change workflow's guidance — the working model, closeout, a change's documents,
OpenSpec's documentation model, change references in code, and where terms live — is
under [`docs/guidance/workflow/`](docs/guidance/workflow/README.md). What it leaves
to the repository is named here:

| Guidance | Where |
|---|---|
| The workflow's guidance | [`docs/guidance/workflow/`](docs/guidance/workflow/README.md) |
| This repository's closeout parts, run after campaign index currency | [`openspec/README.md`, "This repository's closeout parts"](openspec/README.md#this-repositorys-closeout-parts) |
| This repository's roadmap | [`docs/development/ROADMAP.md`](docs/development/ROADMAP.md) |

## Amend a rule or comply

When work conflicts with a written rule, amend the rule first or make the work
comply; never record a private exception to it. The testing levels, for instance,
change only by changing `docs/development/TESTING.md`.

## Documentation ownership

OpenSpec's documentation model — specifications, their companions, changes, and
promotion — is the workflow's
([`docs/guidance/workflow/openspec-documentation.md`](docs/guidance/workflow/openspec-documentation.md)).
This repository's documents beside it:

- `docs/development/ARCHITECTURE.md` is the repository-wide architecture reference: system shape, dependency layers, authority boundaries, shared vocabulary, major flows, deployment topology, packaging rules, and testing philosophy.
- `docs/development/DEPLOYMENT_AND_CONFIG.md` holds configuration resolution and deployment conventions; `docs/operator-handbook.md` holds what an operator needs to run a deployment: document formats, procedures, and upgrade and recovery steps. Neither replaces a specification's normative requirements.
- Git history and pull requests contain provenance and change history.

## Python comments and docstrings

Comments and docstrings describe the current system, not the history of a change.

Do not reference:

- previous file locations;
- the feature, migration, or review that introduced the code;
- tombstones or generated-artifact instructions;
- temporary implementation phases as though they were permanent rationale.

Nor does code name a change, its tasks, or its documents
([`docs/guidance/workflow/change-references.md`](docs/guidance/workflow/change-references.md)).
`make check-comment-hygiene` enforces that on `.py`, `.toml`, `.yml` and
`.yaml`: it rejects task-number and `tasks.md` references, and separately
rejects any comment naming an OpenSpec change directory, landed or not. `docs/`
is exempt, because naming the change that owns a gap is the roadmap's job. Say
*why* the current invariant holds instead.

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

A bare documentation pointer is not a substitute for a useful local explanation.

## Diagrams

A diagram is held to code only when it is generated deterministically from a
well-structured source. Otherwise it is documentation, maintained by review like the
prose around it: no check holds its boxes to the modules or files it draws, since
nothing derives one from the other. A diagram drawing a structured source by hand,
such as the change workflow's graph drawn from its graph table, may be compared with
that source until a deterministic layout reads as well as the hand-laid one. Keep a
diagram's `.drawio` source beside its `.svg` export, and embed the export in the
document that explains it.

## Package and dependency discipline

- Follow the package layers, scope, and kind rules in `ARCHITECTURE.md#package-and-dependency-layers` and the relevant subsystem specification. A change whose edges all point a permitted way has answered the direction and knowledge questions, not the ownership one; that one is review's.
- Any import is an architectural dependency: module-level, function-local, under `TYPE_CHECKING`, or behind `try`/`except`. A "lazy" or "call-path" import does not soften the edge; if the edge is wrong, move the code rather than defer the import.
- Place each import a change adds at module level, wherever safe. Not a blanket move: check each import the change actually added or touched for a real reason to stay local first — a genuine circular import (verify by attempting the move and reading the actual failure, not by assuming) or a documented, deliberate lazy-load reason (e.g. avoiding import cost for a rarely-exercised code path) — and record that reason beside it. Cross-reference against the change's own diff rather than auditing every pre-existing local import in a touched file: this is about what the change added, not a general-purpose cleanup. Verify each move against the real test suite, not just a syntax check, since a passing import at definition time does not guarantee no circular dependency exists at call time. Closeout confirms it (`docs/guidance/workflow/closeout.md`, "Import placement").
- Place a new package where `ARCHITECTURE.md` says its scope puts it, and declare every distribution it imports in its `pyproject.toml`. A declared internal distribution the source never imports is removed or kept for a stated runtime reason.
- `make check-architecture` enforces the layer, scope, and kind rules over every package, in CI and in `make check-packaging`; a per-package boundary test exists only for what it cannot express, and review answers ownership. A known divergence is an exception row in `docs/development/ARCHITECTURE.toml` naming its owning change — never a comment at the import — and a declaration kept without an import gives its runtime reason in the declaring package's `pyproject.toml`, under `[tool.arkhai.architecture.runtime-dependencies]`, beside the dependency it explains.

## Tests and diagnostics

- Put a test at the lowest level that can meaningfully prove the behavior. See `docs/development/TESTING.md` for the level definitions, per-level jurisdiction, and coverage boundaries between them.
- Prefer observable seams, injected dependencies, and deterministic test controls over sleeps or brute-force monkeypatching.
- When a failure cannot be reproduced locally, report useful diagnostic steps and identify any design decision needed before changing behavior.
- A difficult-to-test failure is evidence to consider a testability refactor, not permission to bypass the boundary.
- Run `make check-comment-hygiene` before implementation is considered complete; closeout confirms it (`docs/guidance/workflow/closeout.md`, "Comment hygiene").
- Once the tests covering a change pass, run `make check-packaging` and the typing checks, and resolve every failure they report before the work is committed. Passing tests do not prove it: they may have run against an environment a missing or hand-maintained refresh left stale, and the next environment to rebuild will fail instead.

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

A change's documents are as public as its code
([`docs/guidance/workflow/changes.md`](docs/guidance/workflow/changes.md#a-changes-documents-are-as-public-as-its-code)).

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

Every `openspec/`, `docs/`, `tools/`, `scripts/`, `e2e-tests/`, and `.agents/`
path cited by a permanent document must exist on the branch that cites it.

A permanent document describing behaviour this branch does not implement is not
a harmless forward reference — it is how work from another branch or another
plan epoch gets treated as inherited without anyone deciding to inherit it.
Treat an unresolvable citation as a blocking defect rather than a stale link to
fix later. Closeout applies this at promotion and checks it before the archive
(`docs/guidance/workflow/closeout.md`, "Promotion" and "Documentation
citations").

## Agent skills

### Change workflow

Each step of an OpenSpec change is a leaf skill under `.agents/skills/`, started
through `make` or a slash command, or carried from step to step by one
orchestrating session, `make orchestrate CHANGE=<change>`. How the owner starts
each step, orchestrates a change, reads a round, directs, and waives is the
[change workflow handbook](docs/change-workflow-handbook.md); what the workflow
does is `change-workflow`'s specification and companion.

### Deferred work

Deferred work goes where the workflow's working model says
([`docs/guidance/workflow/working-model.md`](docs/guidance/workflow/working-model.md#deferred-work)):
here, an unowned gap is a row in `openspec/changes/README.md` or
`docs/development/ROADMAP.md`. This repository does not use GitHub Issues for its
own work; the issue-discovery harness files its own issues
(`docs/development/ISSUE_DISCOVERY.md`).

### Domain docs

Where terms live is the workflow's
([`docs/guidance/workflow/terms.md`](docs/guidance/workflow/terms.md)); here, the
market's cross-subsystem terms live in
[`docs/development/ARCHITECTURE.md`, "Shared vocabulary and identities"](docs/development/ARCHITECTURE.md#shared-vocabulary-and-identities).

- Use the established term from its home. Don't drift to a synonym
  `ARCHITECTURE.md`'s "One name per concept" rules out.
- A term new to the reader is defined where it first appears and marked as new.
