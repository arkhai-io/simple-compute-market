## Why

The workflow carries a change from its design to its archive when the change was
started inside it. A change can also arrive from outside it. A contributor implements
a change on a branch of their own and opens a pull request, so the workflow has no
records of it here: no log, no reviews, no owner record. Or a change's records are
lost, even though its documents and code survive. The owner then has to rebuild,
before `make orchestrate` can continue the change, what the workflow would have
recorded.

The owner took over four stacked pull requests (#349, #350, #351 and #354) this way.
Each was an OpenSpec change implemented outside the workflow, and none had had a
design review. Each went through the same procedure:

- a survey of where the change stood;
- a clone on a review branch, recording the branch it lands on;
- the owner's review of the decisions taken during implementation;
- the round recorded after the fact, with that review as its owner record;
- orchestration from implementation review to archive;
- a restack of the next change once the one below it landed.

The procedure worked, and it was carried out by hand four times, from instructions
written afresh for each session. It will be needed again whenever someone else's
change has to be continued here.

A change can also predate the workflow. `relay-vm-access-without-a-dashboard` was
implemented and promoted before the workflow existed, so it had no log and no records.
In closeout, the owner returned it to design, and that took hand edits:

- Its index status was set back to `ready for design`, so that the next-step
  computation, reading the status when there is no log, would name design.
- The owner's two course corrections were written into its ledger by hand.

Only then could `make orchestrate` create its clone and start design. This is the same
need from another direction: a change whose state the workflow never recorded has to
be brought to where orchestration can take it over.

## What Changes

- A new skill, `change-intake`, run by the owner in their workspace, outside any
  change's steps. It determines where the previous owner left a change and restores
  what the workflow needs to continue the change from there. For a stack of pull
  requests, it sets up one clone per change and restacks a change once the one below
  it lands. It ends with the change ready for `make orchestrate`, which the owner
  runs separately.
- A new skill, `change-intake-design`, run in the change's clone when the intake finds
  decisions taken without a design review. It holds the owner's review of those
  decisions, edits nothing, and records the round after the fact with the review as
  its owner record.
- A supported engine command that changes the branch a clone records as the one its
  change lands on. Today that takes a hand edit of the clone's marker. A squash merge
  of the change below makes it necessary, since it strands a stacked change on a
  commit the landing branch never receives.

## Capabilities

### Modified Capabilities

Provisional; settled in design.

- `change-workflow`: two skills outside any change's steps, how an outside change
  enters the graph through existing mechanisms, and the clone's landing-branch
  command.

### New Capabilities

None.

## Non-Goals

- A new graph node or review kind. An outside change enters through mechanisms the
  workflow already has: a round recorded after the fact, an owner record, and the
  owner's direction waiving a step.
- Running orchestration. The intake stops once the change is ready; the owner starts
  `make orchestrate`.
- Coordinating changes across repositories. "Coordinator" names the agent above
  orchestrators that does that, and these skills do not take its name.
- Reviewing a pull request that is not an OpenSpec change. The intake takes a change
  in; a branch with no change directory is out of scope until it has one.

## Impact

All of it is `arkhai-change-workflow`'s, the installed change workflow:

- two new skills, `change-intake` and `change-intake-design`, installed with the
  workflow's other skills;
- the engine's `clone` command and its tests: the landing-branch command;
- the workflow's specification, its index and companion, and its handbook;
- the workflow's guidance, if the skills need a rule of presentation or settlement
  the guidance does not yet hold (D7).

### Workflow engine interfaces

- Two new skills, each with its argument form. A compatible addition.
- A new `clone` subcommand or flag for the landing branch. A compatible addition.
- Whether the intake writes a record of its own, a new kind in the record set, is
  open in design. If it does, design judges that addition against `change-workflow`'s
  compatibility requirement (`CW-c2tw`).
- The graph, the step table and the outcome schema are unchanged.

## Dependencies and Related Changes

- None. `extract-change-workflow-repository` will carry these skills with the rest of
  the workflow, which is why they are written to the workflow's abstractions (D5).

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `change-workflow`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

To be determined at design completion. Expected destinations: `change-workflow`'s
`spec.md` and `README.md` for the two skills, the entry an outside change takes, and
the landing-branch command; the workflow's handbook for how the owner takes a change
in; the workflow's guidance for any rule D7 adds.
