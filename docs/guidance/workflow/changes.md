---
tags: [workflow, changes]
---

# A change's documents

A change lives in `openspec/changes/<change>/` while it is active: its proposal,
its design, its delta specifications, and its task list
([OpenSpec documentation](openspec-documentation.md)). This file holds what the
workflow requires of those documents and of the change index.

## The change index

The change index, `openspec/changes/README.md`, groups the active changes into
delivery campaigns without replacing each change's acceptance boundary. The
workflow's index check holds it, and closeout keeps it current
([Campaign index currency](closeout.md#campaign-index-currency)).

## Change documentation requirements

Every non-trivial `proposal.md` identifies its permanent documentation impact:

```markdown
## Permanent documentation impact

- [ ] The repository's architecture document
- [ ] Existing subsystem specification
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- <material accepted decision and intended permanent destination>
```

Every implementation-ready `tasks.md` names the exact promotion work rather than a
generic "update docs" task.

A change to the change workflow names, in its proposal, each public interface of the
workflow's engine it changes — a subcommand, a flag, an output field, a skill or its
argument form, a graph node or review kind, the record set's format, or a role an
adopting repository provides — and whether each change is compatible, as
`change-workflow`'s compatibility requirement (`CW-c2tw`) judges it; review checks
it. Where the engine carries no version of its own, the proposal is where an
incompatible change is declared.

## One change per branch

One change is implemented per branch. Recording an open question or a note in
another active change's documents, or writing the proposal of a follow-up change, on
the current branch is not working that change: the edit lands with the current
change. A prerequisite — a change this one must wait for — is proposed apart, since
it must land first (`change-workflow`'s CW-dtpz).

## Open questions and prescribed tasks

An item may not appear under a change's `## Open questions` while a non-decision
task prescribes it. A design that calls a question open while its task list
instructs an implementer to answer it one way has not deferred the decision — it
has made it somewhere a reviewer will not look, and an implementer reading only
`tasks.md` will reasonably assume authority they were never given.

Either move the item into the design's decisions with its revisit trigger
stated, or make the task an explicit decision gate. A task that says "decide X
and record the reasoning" is a gate; a task that says "do X" is not, whether or
not it cites the open question.

## The design-promotion record

During implementation, maintain a promotion record in the active change:

```markdown
## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| One capability owns settlement state | `openspec/specs/<capability>/spec.md#ownership` |
| Service dependency layers | the repository's architecture document, its section on dependency layers |
```

The record is change history and remains in the change directory. The destination
documents describe only the resulting current state. Closeout's promotion completes
it ([Promotion](closeout.md#promotion)).

## Defects found during a change

A defect found while working a change is fixed in that change when its fix is
understood and small beside the change, even where it lies outside the change's
stated scope: a change of its own costs a design, reviews, validation and a
closeout, which a small fix does not repay. A defect that is large, or not
understood well enough to fix without a design of its own, gets its own change, or
an unowned gap where no change owns its area
([Deferred work](working-model.md#deferred-work)). This is a judgement of
proportion, not a rule that changes stay narrow, and growth that unifies behaviour
the architecture wants shared, composed from one component rather than handled
differently in two places
([Composition from one component](../engineering/implementation.md#composition-from-one-component)),
is not scope creep. A defect fixed outside the stated
scope is recorded where the change's reviewers will see it: in the task notes, or in
the triage record.

## A change's documents are as public as its code

A change's documents — its design rationale, its task notes — are as public as the
repository's code: whatever the repository refuses to hold in its code, it refuses
in them. "It is only in the change directory" is not an exception.
