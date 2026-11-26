---
tags: [repository]
---

# This repository's guidance

Guidance that names this repository's own packages, services, tools, deployment,
documents, or make targets and spans its systems: the rules a change here satisfies
beyond the shared layers, and this repository's statement of each shared rule it
applies, as `arkhai-change-workflow`'s guidance, "The layers of guidance", defines
the repository layer. Guidance pertaining to one capability sits beside its
specification, in its directory under `openspec/specs/`. What the system is — its
shape, its tests, its stacks and deployment — is described in
[`ARCHITECTURE.md`](../../development/ARCHITECTURE.md),
[`TESTING.md`](../../development/TESTING.md), and
[`DEPLOYMENT_AND_CONFIG.md`](../../development/DEPLOYMENT_AND_CONFIG.md), which these
files link; what the owner or an operator does is in the handbooks.

## How the files are organized

The files sit flat in this directory, each holding one subject and named by it. The
directory is organization for people navigating the tree and carries no meaning: a
file's frontmatter alone states its layer and tags (`change-workflow`'s CW-n6dm). A
file opens by saying what it holds and states only what is particular here, linking
the shared rule it applies by name rather than restating it.

## Tags

Every file carries YAML frontmatter whose `tags` hold `repository` and tags naming
what the file covers, from this table or a lower layer's: the engineering table in
[`docs/guidance/engineering/README.md`](../engineering/README.md#tags) and the
workflow's in the installed workflow's guidance, its "Tags". Content on another
subject goes in another file. A capability's guidance is located
by its directory, so no capability has a tag.

| Tag | Kind | Description |
|---|---|---|
| `repository` | layer | Names this repository's packages, services, tools, deployment, documents, or make targets |
| `architecture` | topic | This repository's system shape, authorities, and flows |
| `operator-events` | topic | The state changes reported to operators as event kinds: what is one, where the market's kinds are declared, how one is declared and recorded |
