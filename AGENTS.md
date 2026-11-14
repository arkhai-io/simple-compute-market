---
tags: [repository]
---

# Repository Engineering Guidance

The entry to this repository's guidance: where each layer of it lives, the tags and
the exceptions to shared guidance that are this repository's, and its own rules.
Each rule below states what is particular here and links the shared rule it
applies. Read it with `docs/development/ARCHITECTURE.md`, `TESTING.md`,
`DEPLOYMENT_AND_CONFIG.md`, `openspec/README.md`, and the shared guidance under
`docs/guidance/` before changing code or specifications.

## Where the guidance lives

The guidance has three layers — engineering, the change workflow's, and this
repository's — as
[`docs/guidance/workflow/README.md`, "The layers of guidance"](docs/guidance/workflow/README.md#the-layers-of-guidance)
defines them. Each shared layer's README describes the layer and holds its tag table;
its files sit beside it, each named by its subject and carrying its tags in its
frontmatter. This repository's guidance is this file and the documents the table
names, and, beside each capability, the guidance files in its directory under
`openspec/specs/` other than its `spec.md`, its companion, and its `index.md`.

| Layer | Guidance |
|---|---|
| engineering | [`docs/guidance/engineering/`](docs/guidance/engineering/README.md) |
| workflow | [`docs/guidance/workflow/`](docs/guidance/workflow/README.md) |
| repository | `AGENTS.md` |
| repository | [`openspec/README.md`](openspec/README.md) |
| repository | [`docs/development/ARCHITECTURE.md`](docs/development/ARCHITECTURE.md) |
| repository | [`docs/development/TESTING.md`](docs/development/TESTING.md) |
| repository | [`docs/development/DEPLOYMENT_AND_CONFIG.md`](docs/development/DEPLOYMENT_AND_CONFIG.md) |
| repository | [`docs/development/BUILD_AND_PACKAGING.md`](docs/development/BUILD_AND_PACKAGING.md) |
| repository | [`docs/development/RELEASING.md`](docs/development/RELEASING.md) |

What each repository document holds is
[`openspec/README.md`, "Documentation placement"](openspec/README.md#documentation-placement).

Three of the roles the workflow's guidance names, found from here; the capability
index and the cross-system documents are named in `openspec/README.md`:

| Role | Here |
|---|---|
| The repository's own closeout parts, run after campaign index currency | [`openspec/README.md`, "This repository's closeout parts"](openspec/README.md#this-repositorys-closeout-parts) |
| The checks the workflow's closeout parts run | [`openspec/README.md`, "The checks the workflow's parts run here"](openspec/README.md#the-checks-the-workflows-parts-run-here) |
| The repository's roadmap | [`docs/development/ROADMAP.md`](docs/development/ROADMAP.md) |

## Tags

This repository's tags, beside the shared layers' tables. A capability's guidance is
located by its directory, so no capability has a tag.

| Tag | Kind | Description |
|---|---|---|
| `repository` | layer | Names this repository's packages, services, tools, deployment, documents, or make targets |
| `architecture` | topic | This repository's system shape, authorities, and flows |

## Exceptions to shared guidance

The exceptions this repository declares to shared guidance across several of its
systems, as
[`rules.md`, "When an exception is expected"](docs/guidance/engineering/rules.md#when-an-exception-is-expected)
admits them. An exception that applies to one capability sits in a guidance file
beside it.

| Shared rule | Kind | Here | Reason |
|---|---|---|---|
| [`repository-content.md`, "In a public repository"](docs/guidance/engineering/repository-content.md#in-a-public-repository) | selects | This repository is public, its local development configuration included, which is public by design | It is published openly, and what enters it stays readable after a later edit removes it |
| [`testing-python.md`, "A command module's factories are its seam"](docs/guidance/engineering/testing-python.md#a-command-modules-factories-are-its-seam) | overrides | Every CLI's tests but the bare-metal buyer CLI's, and one unit test in the bare-metal buyer package, replace library names and names the module imports | The gap is unowned in [`ROADMAP.md`](docs/development/ROADMAP.md); the exception ends when it closes |
| [`configuration.md`, "Secrets travel in a secret profile or overlay file"](docs/guidance/engineering/configuration.md#secrets-travel-in-a-secret-profile-or-overlay-file) | overrides | The storefronts and the provisioning service take their signing credential, `ARKHAI_IDENTITY_CREDENTIAL`, from an environment variable sourced from a Secret; the registries read theirs from a mounted file their profile names, as the rule asks | The [identity specification](openspec/specs/marketplace-identity/spec.md) keeps the credential from the configuration loader |

## This repository's rules

### Amend a rule or comply

Written rules are kept as
[`rules.md`](docs/guidance/engineering/rules.md) says. Here, an exception to shared
guidance is a row of "Exceptions to shared guidance" above, or of the table beside
the one capability it applies to; and the testing levels, for instance, change only
by changing `docs/guidance/engineering/test-levels.md`.

### Documentation ownership

OpenSpec's documentation model is the workflow's
([`openspec-documentation.md`](docs/guidance/workflow/openspec-documentation.md)),
and what a permanent document says, where provenance lives, and that its citations
resolve are the engineering guidance's
([`documentation.md`](docs/guidance/engineering/documentation.md)). Here, what each
of this repository's permanent documents holds is
[`openspec/README.md`, "Documentation placement"](openspec/README.md#documentation-placement).

### Comments

Comments follow [`comments.md`](docs/guidance/engineering/comments.md) and
[`change-references.md`](docs/guidance/workflow/change-references.md). Here, `make
check-comment-hygiene` holds the second outside `openspec/`: a change id, a section
or task number, or a change document's name in a `.py`, `.yml`, or `.yaml` file, and
a change directory's name in those and `.toml` files outside `docs/`, which holds
the roadmap, and `.claude/`. A comment's stable heading is in `openspec/specs` or
`ARCHITECTURE.md`, as in:

```python
# Fulfillment may depend on site and resource-pool authorities; those lower
# layers must not import fulfillment, including under TYPE_CHECKING.
# See openspec/specs/fulfillment/spec.md#dependency-boundary.
```

### Diagrams

Diagrams follow [`diagrams.md`](docs/guidance/engineering/diagrams.md). Here they
are drawn in draw.io: a diagram's `.drawio` source sits beside its `.svg` export. A
diagram drawing a structured source by hand, such as the change workflow's graph
drawn from its graph table, may be compared with that source until a deterministic
layout reads as well as the hand-laid one.

### Package and dependency discipline

Dependencies follow
[`dependencies.md`](docs/guidance/engineering/dependencies.md) and, in Python,
[`dependencies-python.md`](docs/guidance/engineering/dependencies-python.md). Here a
package's layer, scope, and kind, where a new package goes, how `make
check-architecture` holds them, and how a known divergence is recorded are
[`ARCHITECTURE.md`, "Package and dependency layers"](docs/development/ARCHITECTURE.md#package-and-dependency-layers).

### Tests and diagnostics

Tests follow [`testing.md`](docs/guidance/engineering/testing.md) and the levels in
[`test-levels.md`](docs/guidance/engineering/test-levels.md), as
[`docs/development/TESTING.md`](docs/development/TESTING.md) applies them here.
Here:

- `make check-comment-hygiene` runs before implementation is considered complete;
  closeout confirms it.
- The packaging checks
  ([`packaging.md`, "Packaging checks run before a commit"](docs/guidance/engineering/packaging.md#packaging-checks-run-before-a-commit))
  are `make check-packaging`, run with the typing checks, `make -C <project>
  typecheck` in each project whose Makefile has that target.

### Local deployment

A local development cluster is deployed with `make -C helm deploy-local`, never
`make -C helm deploy` or the root `make deploy`, whether a person or an agent is
deploying;
[`DEPLOYMENT_AND_CONFIG.md`, "Stateful service persistence"](docs/development/DEPLOYMENT_AND_CONFIG.md#stateful-service-persistence)
says why.

### Public repository discipline

What enters a repository follows
[`repository-content.md`](docs/guidance/engineering/repository-content.md), whose
public case this repository selects ("Exceptions to shared guidance" above); a
change's documents are as public as its code
([`docs/guidance/workflow/changes.md`](docs/guidance/workflow/changes.md#a-changes-documents-are-as-public-as-its-code)).
Some work here is paired with work in separate private repositories. That pairing
never appears here.

The public-content checks and the secret scan run in the repository's Git hooks, the
guarded push, and CI
([`market-change-workflow`'s "Public repository content checks"](openspec/specs/market-change-workflow/README.md#public-repository-content-checks)):
an agent pushes through `make push-branch`, and no guard test uses a real
identifier.

#### Cross-references must resolve

A permanent document's citations resolve
([`documentation.md`, "Citations resolve"](docs/guidance/engineering/documentation.md#citations-resolve)).
Here that holds for every `openspec/`, `docs/`, `tools/`, `scripts/`, `e2e-tests/`,
and `.agents/` path a permanent document cites, which `make check-doc-citations`
checks.

### Agent skills

#### Change workflow

Each step of an OpenSpec change is a leaf skill under `.agents/skills/`, started
through `make` or a slash command, or carried from step to step by one
orchestrating session, `make orchestrate CHANGE=<change>`. How the owner starts
each step, orchestrates a change, reads a round, directs, and waives is the
[change workflow handbook](docs/change-workflow-handbook.md); what the workflow
does is `change-workflow`'s specification and companion.

#### Deferred work

Deferred work goes where
[`working-model.md`, "Deferred work"](docs/guidance/workflow/working-model.md#deferred-work)
says: here, an unowned gap is a row in `openspec/changes/README.md` or the roadmap.
This repository does not use GitHub Issues for its own work; the issue-discovery
harness files its own issues (`docs/development/ISSUE_DISCOVERY.md`).

#### Domain docs

Terms live where [`docs/guidance/workflow/terms.md`](docs/guidance/workflow/terms.md)
says, and follow [`docs/guidance/engineering/terms.md`](docs/guidance/engineering/terms.md).
Here the market's cross-subsystem terms live in
[`docs/development/ARCHITECTURE.md`, "Shared vocabulary and identities"](docs/development/ARCHITECTURE.md#shared-vocabulary-and-identities),
whose "One name per concept" names the synonyms ruled out.
