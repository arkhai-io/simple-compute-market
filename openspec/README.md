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
| Repository-wide dependency layers, authority boundaries, common vocabulary, and major flows | `docs/development/ARCHITECTURE.md` |
| Testing methodology, test-level jurisdiction, and validation conventions | `docs/development/TESTING.md` |
| Configuration resolution and Kubernetes deployment conventions | `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| Operating a deployment: document formats, procedures, upgrade and recovery steps | `docs/operator-handbook.md` |
| Build, packaging, environment, lock, and image conventions, and the checks enforcing them | `docs/development/BUILD_AND_PACKAGING.md` |
| The roadmap: directional goals, the value each delivers, current state per goal, and which change owns each open gap | `docs/development/ROADMAP.md` |
| Change provenance and review discussion | Git history and pull requests |

`ARCHITECTURE.md` is a current-state cross-system map. It should link to detailed subsystem specifications rather than duplicate every endpoint and state transition. It is the cross-system document the workflow's guidance means where it says a change promotes cross-system knowledge.

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
| Documentation citations | `make check-doc-citations CHANGE=<change-name>` |

### Packaging

Run `make check-packaging` and resolve every failure it reports, then run `make check-architecture-change CHANGE=<change-name>`: a change may not be archived while it owns an architecture exception or override row, so each is deleted with its edge or reassigned to the open change that now owns the divergence. Run `make check-agent-skills` too when the change touched `.agents/`, `.claude/`, or `.codex/`. It builds the wheelhouse, then checks that every environment and image install derives its internal packages from its lock, that every lock is current with its project, the wheels the tree builds, and the repository, that every Python version selection reads the root declaration, and that every package keeps the layer, scope, and kind rules (`make check-architecture`). Passing test suites do not prove this: a suite can pass against an environment a missing or hand-maintained refresh left stale, and the next environment to rebuild then fails instead. [`docs/development/BUILD_AND_PACKAGING.md`](../docs/development/BUILD_AND_PACKAGING.md) says what each check enforces.

### End-to-end pipeline

Confirm the end-to-end pipeline passes, and record the evidence — the run, its result, and the scenarios that exercise this change's behaviour. A change is not complete because its own suites are green: this is the tier that catches a wire contract whose two sides disagree, a service that starts cleanly and cannot settle, and a configuration gap no unit test can see, none of which any in-process test will report. If the pipeline cannot run for a reason unrelated to the change, record that as an explicit blocker naming the cause and the change that owns it, and treat the validations it gates as unrun rather than as passed.

## Current capability documentation

See the canonical [capability documentation index](specs/README.md) for every normative contract and architecture companion. `make check-capability-index` holds it complete: every capability with a `spec.md` has a row, and every row links one.
