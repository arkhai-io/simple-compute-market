---
tags: [repository]
---

# Repository Engineering Guidance

The entry for every agent working in this repository: that it works its changes
through the change workflow, what every session reads, where each layer of its
guidance lives and where its tags are, the exceptions to shared guidance that span
its systems, and the rules for any agent's actions here, whatever the task. It holds
only what can be nowhere else: a topic's repository rules are in its file under
`docs/guidance/repository/`, its description in `docs/development/`, and a check's
scope sits beside the check.

## The change workflow

This repository works its changes through the change workflow. What the workflow
does is `change-workflow`'s specification and companion
([`openspec/specs/change-workflow/`](openspec/specs/change-workflow/README.md)); how
the owner operates it is the
[change workflow handbook](docs/change-workflow-handbook.md). Its skills are under
`.agents/skills/`, and its configuration is `.agents/workflow.toml`.

## What every session reads

Every session reads these before changing code or specifications, whether or not it
runs a step of the workflow; a step loads the same documents through `load.common`
in `.agents/workflow.toml`.

| Path | What it holds |
|---|---|
| `AGENTS.md` | This entry |
| [`docs/guidance/engineering/`](docs/guidance/engineering/README.md) | Every Markdown file beneath it: the engineering guidance |
| [`docs/guidance/workflow/`](docs/guidance/workflow/README.md) | Every Markdown file beneath it: the change workflow's guidance |
| [`docs/guidance/repository/`](docs/guidance/repository/README.md) | Every Markdown file beneath it: this repository's rules spanning its systems |
| [`openspec/README.md`](openspec/README.md) | This repository's OpenSpec guide: where each document goes, its closeout parts and their checks |
| [`docs/development/ARCHITECTURE.md`](docs/development/ARCHITECTURE.md) | The description of the system: its shape, package layers, authorities, vocabulary, and flows |
| [`docs/development/TESTING.md`](docs/development/TESTING.md) | The description of its tests: where they run, its lanes, its canonical deal, and its doubles |
| [`docs/development/DEPLOYMENT_AND_CONFIG.md`](docs/development/DEPLOYMENT_AND_CONFIG.md) | The description of how its services are configured and deployed: its stacks, charts, releases, and migrations |

A session working on a capability reads, beside its specification and companion,
every other Markdown file in its directory under `openspec/specs/` but its
`index.md`: the capability's own guidance.

## Where the guidance lives

The guidance has three layers — engineering, the change workflow's, and this
repository's — as
[`docs/guidance/workflow/README.md`, "The layers of guidance"](docs/guidance/workflow/README.md#the-layers-of-guidance)
defines them. Each layer's directory under `docs/guidance/` has a README describing
the layer, how its files are organized, and its tag table; its files sit beside it,
each named by its subject and carrying its tags in its frontmatter. This repository's
guidance is this file, `openspec/README.md`, the rules spanning its systems under
`docs/guidance/repository/`, the description documents under `docs/development/`,
and, beside each capability, the guidance files in its directory under
`openspec/specs/` other than its `spec.md`, its companion, and its `index.md`. What
the owner or an operator does is in the handbooks, outside the guidance: the
[operator handbook](docs/operator-handbook.md), the
[release handbook](docs/release-handbook.md), and the change workflow handbook.

| Layer | Guidance |
|---|---|
| engineering | [`docs/guidance/engineering/`](docs/guidance/engineering/README.md) |
| workflow | [`docs/guidance/workflow/`](docs/guidance/workflow/README.md) |
| repository | `AGENTS.md` |
| repository | [`docs/guidance/repository/`](docs/guidance/repository/README.md) |
| repository | [`openspec/README.md`](openspec/README.md) |
| repository | [`docs/development/ARCHITECTURE.md`](docs/development/ARCHITECTURE.md) |
| repository | [`docs/development/TESTING.md`](docs/development/TESTING.md) |
| repository | [`docs/development/DEPLOYMENT_AND_CONFIG.md`](docs/development/DEPLOYMENT_AND_CONFIG.md) |

What each repository document holds is
[`openspec/README.md`, "Documentation placement"](openspec/README.md#documentation-placement).

Three of the roles the workflow's guidance names, found from here; the capability
index and the cross-system documents are named in `openspec/README.md`:

| Role | Here |
|---|---|
| The repository's own closeout parts, run after campaign index currency | [`openspec/README.md`, "This repository's closeout parts"](openspec/README.md#this-repositorys-closeout-parts) |
| The checks the workflow's closeout parts run | [`openspec/README.md`, "The checks the workflow's parts run here"](openspec/README.md#the-checks-the-workflows-parts-run-here) |
| The repository's roadmap | [`docs/development/ROADMAP.md`](docs/development/ROADMAP.md) |

This repository's tags are the table in
[`docs/guidance/repository/README.md`, "Tags"](docs/guidance/repository/README.md#tags),
beside the shared layers' tables.

## Exceptions to shared guidance

Written rules are kept as [`rules.md`](docs/guidance/engineering/rules.md) says. The
exceptions this repository declares to shared guidance across several of its
systems, as
[`rules.md`, "When an exception is expected"](docs/guidance/engineering/rules.md#when-an-exception-is-expected)
admits them, are the rows below; an exception that applies to one capability is a
row of the table in a guidance file beside it. Here, work that does not meet a shared
rule is no exception: it is deferred work, recorded where "Deferred work" below says.

| Shared rule | Kind | Here | Reason |
|---|---|---|---|
| [`repository-content.md`, "In a public repository"](docs/guidance/engineering/repository-content.md#in-a-public-repository) | selects | This repository is public, its local development configuration included, which is public by design | It is published openly, and what enters it stays readable after a later edit removes it |
| [`configuration.md`, "Secrets travel in a secret profile or overlay file"](docs/guidance/engineering/configuration.md#secrets-travel-in-a-secret-profile-or-overlay-file) | overrides | The storefronts and the provisioning service take their signing credential, `ARKHAI_IDENTITY_CREDENTIAL`, from an environment variable sourced from a Secret; the registries read theirs from a mounted file their profile names, as the rule asks | The [identity specification](openspec/specs/marketplace-identity/spec.md) keeps the credential from the configuration loader |
| [`repository-content.md`, "In a public repository"](docs/guidance/engineering/repository-content.md#in-a-public-repository), its run artifacts | overrides | One run artifact is admitted: a marketplace release's bill of materials, committed at the cut as `manifests/release-bom.cdx.json` on its release branch ([`ARCHITECTURE.md`, "The bill of materials"](docs/development/ARCHITECTURE.md#the-bill-of-materials)). It holds content identities only — versions, digests, the source revision and the public repository link — and names no registry host, project or path, and `make check-release-record` refuses any field or URL its layout does not admit ([`published-packages.md`, "The release record"](docs/guidance/repository/published-packages.md#the-release-record)) | A release is recorded in the repository it was built from, and the record is enforced to hold nothing the public case refuses rather than promised to |

## Rules for every agent here

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

### Deferred work

Deferred work goes where
[`working-model.md`, "Deferred work"](docs/guidance/workflow/working-model.md#deferred-work)
says: here, an unowned gap is a row in `openspec/changes/README.md` or the roadmap.
This repository does not use GitHub Issues for its own work; the issue-discovery
harness files its own issues (`docs/development/ISSUE_DISCOVERY.md`).

### Domain docs

Terms live where [`docs/guidance/workflow/terms.md`](docs/guidance/workflow/terms.md)
says, and follow [`docs/guidance/engineering/terms.md`](docs/guidance/engineering/terms.md).
Here the market's cross-subsystem terms live in
[`docs/development/ARCHITECTURE.md`, "Shared vocabulary and identities"](docs/development/ARCHITECTURE.md#shared-vocabulary-and-identities),
whose "One name per concept" names the synonyms ruled out.
