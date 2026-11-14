---
tags: [repository, openspec]
---

# Arkhai OpenSpec Guide

How this repository uses OpenSpec. OpenSpec's documentation model — specifications,
their companions, changes, the archive, and what the capability index and the roadmap
are for — and the workflow's rules for a change's documents and its closeout are the
change workflow's guidance:
[`docs/guidance/workflow/openspec-documentation.md`](../docs/guidance/workflow/openspec-documentation.md),
[`changes.md`](../docs/guidance/workflow/changes.md), and
[`closeout.md`](../docs/guidance/workflow/closeout.md). This guide holds what is this
repository's.

Use `bunx @fission-ai/openspec@1.14.0 list` to inspect active changes, `show <name>` to read one, and `validate --all --strict` before review. The validator is pinned to 1.14.0: 1.14.1 adds a strict-mode failure for requirement text over 500 characters, which most permanent specs do not yet meet, and [`shorten-long-requirements`](changes/shorten-long-requirements/) restructures them and moves the pin forward.

## Documentation placement

The workflow's placement table
([`openspec-documentation.md`, "Documentation placement"](../docs/guidance/workflow/openspec-documentation.md#documentation-placement))
names the homes of a capability's specification, companion, and index, and of a
change's documents. This repository's documents beside them:

| Knowledge | Permanent home |
|---|---|
| That this repository works its changes through the change workflow, what every session reads, where each layer of the guidance lives, this repository's tags, its exceptions to shared guidance across several systems, and its rules for any agent's actions here | `AGENTS.md` |
| Guidance that holds in any repository, and the change workflow's guidance | `docs/guidance/engineering/` and `docs/guidance/workflow/` |
| Guidance pertaining to one capability, and an exception to shared guidance that applies to it alone | a guidance file in `openspec/specs/<capability>/`, beside its `spec.md`, carrying `tags` frontmatter |
| The system's shape, repository-wide dependency layers, authority boundaries, common vocabulary, major flows, and deployment topology, and this repository's own rules spanning its systems | `docs/development/ARCHITECTURE.md` |
| This repository's tests at each level, its end-to-end lanes and doubles, and its validation conventions | `docs/development/TESTING.md` |
| How this repository's services resolve configuration, and its Kubernetes deployment conventions | `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| Operating a deployment: document formats, procedures, upgrade and recovery steps | `docs/operator-handbook.md` |
| Build, packaging, environment, lock, and image conventions, and the checks enforcing them | `docs/development/BUILD_AND_PACKAGING.md` |
| Publishing this repository's packages, its published set, and where its other artifacts are pushed | `docs/development/RELEASING.md` |
| The roadmap: directional goals, the value each delivers, current state per goal, and which change owns each open gap | `docs/development/ROADMAP.md` |
| Change provenance and review discussion | Git history and pull requests ([`documentation.md`, "Provenance lives in version control"](../docs/guidance/engineering/documentation.md#provenance-lives-in-version-control)) |

`ARCHITECTURE.md` is a current-state cross-system map. It should link to detailed subsystem specifications rather than duplicate every endpoint and state transition. It is the cross-system document the workflow's guidance means where it says a change promotes cross-system knowledge. Neither it, `DEPLOYMENT_AND_CONFIG.md`, nor the operator handbook replaces a specification's normative requirements.

Diagrams follow [`diagrams.md`](../docs/guidance/engineering/diagrams.md). Here they
are drawn in draw.io: a diagram's `.drawio` source sits beside its `.svg` export.

## The index check

A capability organized by an index
([`openspec-documentation.md`, "A capability organized by an index"](../docs/guidance/workflow/openspec-documentation.md#a-capability-organized-by-an-index))
is held to its index by `make check-spec-index [CHANGE=<change>]` (`scripts/check_spec_index.py`), which `make check-change` runs with the change named. It fails in a capability with an `index.md`, naming each, on: an `index.md` that declares no prefix, which leaves nothing else in that capability checked; a requirement whose name begins with no id; two requirements sharing an id; an id `index.md` omits or lists twice; a listed id in neither `spec.md` nor the named change's own deltas; a retired id in use; a link in `index.md` that does not resolve; and an entry whose link is not to its own id's heading in `spec.md`. With a change named, its deltas count as the archive will leave them, so closeout can write `index.md` before the archive merges a requirement into `spec.md`. A capability with no `index.md` is not checked.

## This repository's closeout parts

The workflow's closeout parts, and their order, are
[`docs/guidance/workflow/closeout.md`](../docs/guidance/workflow/closeout.md). This
repository adds two, packaging and end-to-end pipeline evidence, run in this order
after campaign index currency and before promotion.

### The checks the workflow's parts run here

The workflow's parts name the checks they run by role. Here they are:

| Part | Check |
|---|---|
| Comment hygiene | `make check-comment-hygiene` |
| Campaign index currency | `make check-change-index`, which runs the workflow's `scripts/change-workflow check index` |
| Promotion | the index check, `make check-spec-index CHANGE=<change-name>` ([above](#the-index-check)) |
| Guidance placement | the guidance check, `make check-guidance` |
| Documentation citations | `make check-doc-citations CHANGE=<change-name>` |

### Packaging

This repository's closeout runs `make check-packaging` and resolves every failure it reports; then `make check-architecture-change CHANGE=<change-name>`, which refuses a change that still owns an architecture exception or override row, so each is deleted with its edge or reassigned to the open change that owns the divergence; and `make check-agent-skills` when the change touched `.agents/`, `.claude/`, or `.codex/`. What each packaging check enforces is [`docs/development/BUILD_AND_PACKAGING.md`, "Checks"](../docs/development/BUILD_AND_PACKAGING.md#checks), and why they run though the suites pass is [`packaging.md`, "Packaging checks run before a commit"](../docs/guidance/engineering/packaging.md#packaging-checks-run-before-a-commit).

### End-to-end pipeline

This repository's closeout records the end-to-end pipeline's run at the closeout's code — dispatched by `make run-e2e` and collected by `make fetch-e2e-logs` — its result, and the scenarios that exercise the change's behaviour; a failed run returns the change to implementation, and a run that could not be made is recorded as unrun, naming its cause and the change that owns it ([`docs/guidance/engineering/testing.md`, "Work is not complete because its own tests pass"](../docs/guidance/engineering/testing.md#work-is-not-complete-because-its-own-tests-pass); [`docs/guidance/workflow/working-model.md`, "Implement"](../docs/guidance/workflow/working-model.md#implement)).

## Current capability documentation

This repository's capability index, whose role is
[`openspec-documentation.md`, "The capability index and the roadmap"](../docs/guidance/workflow/openspec-documentation.md#the-capability-index-and-the-roadmap),
is [`openspec/specs/README.md`](specs/README.md): every normative contract and architecture companion. `make check-capability-index` holds it complete: every capability with a `spec.md` has a row, and every row links one.
