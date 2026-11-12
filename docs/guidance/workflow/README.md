---
tags: [workflow]
---

# The workflow's guidance

Guidance that holds in any repository adopting the change workflow, OpenSpec
included, and names nothing of one repository: how a change is discussed, planned,
implemented, and closed out, how its documents and the permanent specifications
divide what they record, and how a change is kept out of the code it produces. The
workflow's steps, its engine, and its records are described in the workflow's guide,
[`docs/agents/change-workflow.md`](../../agents/change-workflow.md), which is
workflow guidance too.

## The layers of guidance

A repository adopting the workflow divides its guidance into three layers, each
piece of guidance belonging to one:

- **Engineering** holds in a repository that uses neither the change workflow nor
  OpenSpec: how comments are written, what a test at each level may prove, that a
  permanent document describes the current system.
- **Workflow** holds in any repository adopting the workflow, OpenSpec included, and
  names nothing of one repository: the working model, the closeout parts, how a
  change's documents relate to the specifications.
- **Repository** names the adopting repository's own packages, services, tools,
  deployment, documents, or targets.

The test is what a piece of guidance depends on. A rule that would hold without the
workflow is engineering, even when it is written today with one repository's
example; it moves with a neutral example, and the repository's statement stays as
its instance. A rule that presupposes changes, steps, or OpenSpec's documents is the
workflow's. A rule that names something only one repository has is that
repository's.

A lower layer never links to a higher one: engineering guidance links only to
engineering guidance, workflow guidance to workflow or engineering guidance, and
repository guidance to any. Where workflow guidance needs something a repository
supplies — a check, a path, a document — it names it by its role ("the repository's
citation check", "the repository's roadmap"), and the repository's guidance names
the command or the path. This keeps each layer movable on its own: lifting the
workflow's guidance out of a repository takes its files, and rewrites none.

Every guidance file carries YAML frontmatter whose `tags` hold exactly one layer
tag, `engineering`, `workflow`, or `repository`, and otherwise only tags from its
layer's vocabulary table or a lower layer's. A file carries the tags its whole
content needs and no more, so content needing other tags goes in another file. The
layer model is `change-workflow`'s requirements CW-g7lt, on the layer tag, and
CW-d2rw, on the link direction.

## How the files are organized

The workflow's guidance files sit flat in this directory, each named by its subject.
The directory is organization for people navigating the tree, and carries no
meaning: the frontmatter alone states a file's layer and tags, so a file tagged
`workflow` is the workflow's wherever it sits, and moving it changes nothing the
workflow does with it (`change-workflow`'s CW-n6dm). Directories may nest once the
files grow too many to navigate, named for their organization rather than after the
tags of the files within.

## Tags

| Tag | Kind | Description |
|---|---|---|
| `workflow` | layer | Holds in any repository adopting the workflow, and names nothing of one |
| `openspec` | topic | OpenSpec's documentation model: specifications, companions, indexes, promotion |
| `changes` | topic | A change's documents and the change index |
| `closeout` | topic | The closeout task and its parts |
