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
comply, and declare an exception to shared guidance only as
[`docs/guidance/engineering/rules.md`](docs/guidance/engineering/rules.md) says. The
testing levels, for instance, change only by changing
`docs/guidance/engineering/test-levels.md`.

## Documentation ownership

OpenSpec's documentation model — specifications, their companions, changes, and
promotion — is the workflow's
([`docs/guidance/workflow/openspec-documentation.md`](docs/guidance/workflow/openspec-documentation.md)),
and what any permanent document says, where provenance lives, and that its citations
resolve is the engineering guidance's
([`docs/guidance/engineering/documentation.md`](docs/guidance/engineering/documentation.md)).
This repository's documents beside it:

- `docs/development/ARCHITECTURE.md` is the repository-wide architecture reference: system shape, dependency layers, authority boundaries, shared vocabulary, major flows, deployment topology, packaging rules, and testing philosophy.
- `docs/development/DEPLOYMENT_AND_CONFIG.md` holds configuration resolution and deployment conventions; `docs/operator-handbook.md` holds what an operator needs to run a deployment: document formats, procedures, and upgrade and recovery steps. Neither replaces a specification's normative requirements.

## Comments

Comments and docstrings describe the current system
([`docs/guidance/engineering/comments.md`](docs/guidance/engineering/comments.md)),
and code names no change, its tasks, or its documents
([`docs/guidance/workflow/change-references.md`](docs/guidance/workflow/change-references.md)).
`make check-comment-hygiene` enforces the second on `.py`, `.toml`, `.yml` and
`.yaml`: it rejects task-number and `tasks.md` references, and separately
rejects any comment naming an OpenSpec change directory, landed or not. `docs/`
is exempt, because naming the change that owns a gap is the roadmap's job. A
comment's stable heading here is in `openspec/specs` or `ARCHITECTURE.md`, as in:

```python
# Fulfillment may depend on site and resource-pool authorities; those lower
# layers must not import fulfillment, including under TYPE_CHECKING.
# See openspec/specs/fulfillment/spec.md#dependency-boundary.
```

## Diagrams

Diagrams follow
[`docs/guidance/engineering/diagrams.md`](docs/guidance/engineering/diagrams.md),
drawn in draw.io: a diagram's `.drawio` source sits beside its `.svg` export. A
diagram drawing a structured source by hand, such as the change workflow's graph
drawn from its graph table, may be compared with that source until a deterministic
layout reads as well as the hand-laid one.

## Package and dependency discipline

Dependencies follow
[`docs/guidance/engineering/dependencies.md`](docs/guidance/engineering/dependencies.md)
and, in Python,
[`dependencies-python.md`](docs/guidance/engineering/dependencies-python.md): any
import is a dependency, a package declares what it imports, and an import a change
adds goes at module level unless a verified reason, recorded beside it, keeps it
local; closeout confirms the last (`docs/guidance/workflow/closeout.md`, "Import
placement"). Here:

- Follow the package layers, scope, and kind rules in `ARCHITECTURE.md#package-and-dependency-layers` and the relevant subsystem specification; review answers ownership, the third of the questions that place a package.
- Place a new package where `ARCHITECTURE.md` says its scope puts it.
- `make check-architecture` enforces the layer, scope, and kind rules over every package, in CI and in `make check-packaging`; a per-package boundary test exists only for what it cannot express, and review answers ownership. A known divergence is an exception row in `docs/development/ARCHITECTURE.toml` naming its owning change — never a comment at the import — and a declaration kept without an import gives its runtime reason in the declaring package's `pyproject.toml`, under `[tool.arkhai.architecture.runtime-dependencies]`, beside the dependency it explains.

## Tests and diagnostics

How tests are placed and written is the engineering guidance: [`docs/guidance/engineering/testing.md`](docs/guidance/engineering/testing.md), the levels in [`test-levels.md`](docs/guidance/engineering/test-levels.md), and the files beside them. This repository's tests apply it as `docs/development/TESTING.md` describes. Here:

- Run `make check-comment-hygiene` before implementation is considered complete; closeout confirms it (`docs/guidance/workflow/closeout.md`, "Comment hygiene").
- Once the tests covering a change pass, run `make check-packaging` and the typing checks, and resolve every failure they report before the work is committed: passing tests prove nothing about the next rebuild ([`docs/guidance/engineering/packaging.md`](docs/guidance/engineering/packaging.md)).

## Public repository discipline

This repository is public: what enters it follows the public case of
[`docs/guidance/engineering/repository-content.md`](docs/guidance/engineering/repository-content.md),
which holds for everything here — code, comments, documentation, specifications,
change documents, fixtures, test data, commit messages, and pull request
descriptions. A change's documents are as public as its code
([`docs/guidance/workflow/changes.md`](docs/guidance/workflow/changes.md#a-changes-documents-are-as-public-as-its-code)).

Some work here is paired with work in separate private repositories. That
pairing never appears here.

### Test fixtures and local development configuration

Local development configuration in this repository is public by design and must
stay obviously so, its development values marked as fixtures
([`repository-content.md`, "Fixtures are obviously fixtures"](docs/guidance/engineering/repository-content.md#fixtures-are-obviously-fixtures)).

### Cross-references must resolve

Every `openspec/`, `docs/`, `tools/`, `scripts/`, `e2e-tests/`, and `.agents/`
path cited by a permanent document must exist on the branch that cites it
([`docs/guidance/engineering/documentation.md`, "Citations resolve"](docs/guidance/engineering/documentation.md#citations-resolve)).
Closeout applies this at promotion and checks it before the archive
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

Terms follow
[`docs/guidance/engineering/terms.md`](docs/guidance/engineering/terms.md): use the
established term from its home, never a synonym `ARCHITECTURE.md`'s "One name per
concept" rules out.
