---
tags: [workflow, closeout]
---

# Closeout

Every `tasks.md` for a change, or for a major section within one, ends with a
closeout task before implementation is considered planned, not invented after a
review round asks for it. The closeout task works through the parts below, in this
order, archival last. It changes only the repository's inert paths, changes'
records, and the archive's own writes — the change's own documents and their move
into the archive, its index row, and its deltas merged into the specifications: a
part that would change any other path — a comment in code, say — returns the change
to implementation instead (`change-workflow`'s CW-pkug). Why closeout is shaped so is
the workflow companion's
([Closeout and archival](../../../openspec/specs/change-workflow/README.md#closeout-and-archival)).

The workflow's parts are these ten, each under its own heading below, with the
repository's own parts at the seventh position
([The repository's own closeout parts](#the-repositorys-own-closeout-parts)):

1. Comment hygiene
2. Import placement
3. Documentation compliance
4. Narrative compression
5. Roadmap currency
6. Campaign index currency
7. The repository's own closeout parts
8. Promotion
9. Guidance placement
10. Documentation citations
11. Archival

A plan, a skill, or a review cites a part by its heading, never by its number, so a
part added, removed, or reordered, or a repository's own parts, never break a
citation.

If a plan's closeout task grows unusually large on its own, decide deliberately
whether the growth belongs to the change — a found defect fixed in place, or
unification the architecture favours — or is separate work better split, rather
than noticing only once the section is hard to review
([Defects found during a change](changes.md#defects-found-during-a-change)).

## Comment hygiene

Confirm it; do not do it here. Comments are code, so the work belongs to
implementation: the pre-closeout review reads the comments the change added, and its
triage round fixes them. At closeout, run the repository's comment check. It
catches change ids, section numbers, and task numbers mechanically, though not fuzzier
violations of the rules this part confirms — that comments describe the current
system, and that they name no change, task, or change document
([Change references](change-references.md)) — such as a comment naming the review or
migration that introduced the code. If a check reports anything, or a comment the
change added still needs rewriting, closeout stops and the change returns to
implementation for a fix round; closeout never edits code, so its review, which
reads only documentation, covers everything closeout changed.

## Import placement

Confirm it; do not do it here, for the same reason as comment hygiene. During
implementation, before the pre-closeout review, each section places the imports it
added or touched as the repository's guidance on imports says, checking its own diff
rather than every pre-existing local import in a file it touched. At closeout, check
the imports the change added; one that should move returns the change to
implementation.

## Documentation compliance

Re-check the change's own accepted decisions against the workflow's placement rules
([OpenSpec documentation](openspec-documentation.md)) and the repository's placement
table directly — do not defer this to an external reviewer noticing it first.

## Narrative compression

Shorten completed-task notes to final behaviour, material validation evidence,
unresolved or deferred work, and permanent-documentation destinations. Move detailed
alternatives, debugging narratives, and review rationale into `design.md` first if
they are not already there — this step deletes duplication, not information.

## Roadmap currency

Update the affected goal's current-state description and gap-to-change mapping in
the repository's roadmap, and name that update in the design-promotion record. Most
changes owe nothing here; a change with no roadmap impact records that disposition
explicitly rather than omitting the step, so an absent roadmap edit is a deliberate
finding rather than an unanswered question at review.

## Campaign index currency

Update the change's row, and its campaign's dependency graph, in the change index so
the recorded status matches what is now true, and name that update in the
design-promotion record. The index answers what a reader may start next, and a stale
row misdirects that decision. A change whose status and campaign placement are both
unchanged records that disposition explicitly rather than omitting the step. A
change that creates, renames, supersedes, or removes a change directory reconciles
the index's links in the same step: a link to a directory that does not exist is a
blocking defect, as an unresolvable citation always is, not a stale link to fix
later. The workflow's index check, `scripts/change-workflow check index`, holds each
row — its cells, its link, its status, and its dependencies, each listed and not
archived — and that every active change has exactly one (`change-workflow`'s
CW-jyff); an archived change needs no row, since archived rows may be pruned from
the index over time.

Closeout leaves other rows' `Depends on` as they are: a dependency lands when it is
`archived`, which is written only once the closeout review's triage records that the
change advances and the archive is cleaned up. Archive cleanup then removes the
change from every other row's `Depends on`, and returns each dependent whose status
is `ready for planning`, `in planning`, or `ready for implementation` to `ready for
design`: the dependent's design rests on a codebase this change has just altered, so
it is reverified before it is planned or implemented. A dependent `in
implementation` keeps its status, because its implementation has begun. A dependent
that is `blocked in` a phase keeps its status, because that blocker is independent
of this change; archive cleanup records in its `Notes` that design reverification is
owed once the blocker clears.

## The repository's own closeout parts

A repository adds a part for a check or evidence the workflow cannot name: one that
depends on how the repository builds, packages, deploys, or runs its system end to
end. Its root guidance names the section that defines them; there each part has a
heading of its own saying what it confirms, the command it runs, and what a failure
means for the change. They run once the change index is current and before
promotion, so a failure that returns the change to implementation does so before any
permanent document is written.

For example, a repository whose services ship as container images might define:

```markdown
### Image build

Run `make images` and confirm every image builds from the change's lock files.
A failure returns the change to implementation.
```

## Promotion

Write the permanent documents the closeout task names — the capabilities'
companions, the repository's cross-system documents, its capability index, and any
other — and complete the design-promotion record
([The design-promotion record](changes.md#the-design-promotion-record)). A `spec.md`
the change's deltas cover is written by the archive, not by hand; the record names it
all the same. In a capability organized by an index
([A capability organized by an index](openspec-documentation.md#a-capability-organized-by-an-index)),
promotion also writes its `index.md`: an entry, with its link and summary line under
its part and group, for each id the change's deltas add; for each requirement they
rename, its entry's link moved to the new heading; for each they modify, its summary
line revised where it no longer holds; and, for each requirement they remove, its id
moved to the retired ids with where its rule went. The repository's index check
accepts the new ids from the change's deltas, so the entries are written before the
archive merges them.

Promote only what the change's own branch implements. A closeout commit can promote
a section describing a subsystem the branch has never had, citing a requirement the
branch has never had, while staying inside every path its author may edit: the
content comes from another branch or an earlier plan the author had no authority
over, and path permissions cannot detect that. A citation check can, in one pass,
which is why documentation citations check every citation the change wrote, and
treat an unresolvable one as a blocking defect.

## Guidance placement

Read each guidance section the change added, moved, or rewrote since it branched —
promoted text included — against the layer test, adjacency, and exception placement
([The layers of guidance](README.md#the-layers-of-guidance)): a rule that holds
without the workflow is engineering, with a neutral example; repository guidance
that pertains to one system sits beside that system's specification, and guidance
spanning several systems in the repository's cross-system documents; an exception to
shared guidance sits beside the component it applies to, or in the repository's root
guidance when it spans several systems. Move what is misplaced and re-point its
citations within the inert paths — a citation outside them returns the change to
implementation — then run the repository's guidance check. A misplacement that needs a
decision is reported for the closeout review rather than settled here. A change that
touched no guidance records that.

## Documentation citations

Run the repository's citation check, scoped to the change, after promotion, so the
documents it wrote are there to resolve, and resolve every match: a citation whose
target does not resolve is a blocking defect, not a stale link. Then validate the
change strictly, `scripts/change-workflow openspec validate <change> --strict`, the
last check before the archive. A change with no spec deltas records that instead,
since the validator rejects a change with none, and archives with `--skip-specs`.

The check is scoped to the change on purpose. A change owes the citations it wrote,
and gating archival on the whole repository's documentation debt would let one
team's stale runbook block everyone else's, which turns a check into something
people route around. Run it unscoped to see the repository-wide picture.

## Archival

Archive the change as the last step, once every other part is done:
`scripts/change-workflow openspec archive <change> -y` merges its spec deltas into
`openspec/specs/` and moves it to `openspec/changes/archive/<date>-<change>/`; the
change's row in the change index then links to that directory. A change whose
`spec.md` was already edited by hand archives with `--skip-specs`, so the merge is
not applied twice. The closeout review
and its triage then read the archived change and the permanent documents as
archived, and find the change by name under the archive
(`scripts/change-workflow find <change>`).
