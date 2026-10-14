## ADDED Requirements

### Requirement: Active-change index status vocabulary

Every change row in the active-change index at `openspec/changes/README.md` MUST
state its status in a column holding nothing else, as exactly one of: `ready for
<phase>`, `in <phase>`, or `blocked in <phase>`, where `<phase>` is one of
`design`, `planning`, `implementation`, or `closeout`; or `deferred` or
`archived`. `blocked in <phase>` MUST be used only for a reason that
is not another change, and `blocked in design` means the design cannot proceed
without a decision from the repository owner. That reason, and a deferred change's
activation condition, MUST be stated in a separate explanatory column.

#### Scenario: A reader or agent asks what may start

- **WHEN** a contributor or an agent reads the index to find work that may begin
- **THEN** it selects rows whose status begins `ready for` and none of whose
  listed dependencies gates that phase or an earlier one, without interpreting
  prose

#### Scenario: Local work waits on an external input

- **WHEN** a change cannot finish implementation until an input outside the
  repository is available
- **THEN** its status is `blocked in implementation` and its explanatory column
  names the input

### Requirement: Phase-gating change dependencies

Each change row MUST list, in a `Depends on` column, every other change that must
reach `archived` before it may proceed, each with the phase
it gates. An entry naming no phase gates implementation. A dependency on another
change MUST NOT be expressed through the status. A dependency gating only part of a
change MUST be stated in the explanatory column rather than in `Depends on`.

#### Scenario: A dependency decides whether the dependent exists

- **WHEN** another change's design decides whether a change is superseded,
  narrowed, or folded in
- **THEN** the dependent lists that change in `Depends on` as gating `design`, and
  is not designed until it lands

### Requirement: Design reverification when a dependency lands

When a change's archive is cleaned up, the step that sets it to `archived` MUST remove it from every
dependent's `Depends on`, and MUST set each dependent whose status is `ready for` or
`in` planning or implementation, and which has not begun implementing, to `ready
for design`, so that its design is reverified against the codebase the dependency
left before it is planned or implemented. A dependent whose status is `blocked in`
a phase MUST keep that status, and the completing change MUST record in its
explanatory column that design reverification is owed. Closeout MUST NOT change
a dependent's `Depends on` or status before the closeout review's gate is passed.

#### Scenario: A planned dependent

- **WHEN** a change that another row depends on is archived and cleaned up, and that
  dependent has a reviewed design and a plan but has not begun implementation
- **THEN** the completing change removes itself from the dependent's `Depends on`
  and sets the dependent to `ready for design`, and the dependent's design is
  reviewed again before it is planned or implemented

#### Scenario: A blocked dependent

- **WHEN** a change that another row depends on is archived and cleaned up, and that
  dependent is `blocked in planning` on an external input
- **THEN** the dependent stays `blocked in planning`, and its explanatory column
  records that design reverification is owed once the blocker clears

#### Scenario: A closeout review sends the change back

- **WHEN** a change's closeout review is triaged and its gate is not passed
- **THEN** every row that depends on it keeps its `Depends on` and its status

## MODIFIED Requirements

### Requirement: Canonical planning homes

The repository MUST use OpenSpec main specs as the canonical source for current
normative capability behavior, active OpenSpec changes as the canonical source for
proposed deltas and implementation tasks, and archived OpenSpec changes as the
canonical record of completed changes. A change is completed when its index status
is `archived`, not when its directory is moved: closeout moves the directory under
the archive before its closeout review, and a change archived on disk whose status
is `in closeout` is being closed out, not completed. Ordinary documentation MAY
explain architecture, operations, workflows, and directional goals, but MUST NOT
maintain a competing normative backlog. Documentation maintains a competing backlog
when it carries implementation tasks, acceptance criteria, or readiness status for
work an OpenSpec change owns or should own; stating a goal, the value it delivers,
current behavior, and a link to the owning change does not.

#### Scenario: Contributor proposes behavioral work

- **WHEN** a contributor identifies a behavior or architecture change
- **THEN** it is captured in an OpenSpec change rather than a flat documentation
  backlog

#### Scenario: Documentation states goal-level direction

- **WHEN** documentation explains why a goal exists, what value it delivers, and
  which changes carry it
- **THEN** it is permitted directional context provided it assigns no tasks,
  acceptance criteria, or readiness status

#### Scenario: A change is archived but its closeout review is pending

- **WHEN** a change's directory is under the archive and its index status is
  `in closeout`
- **THEN** it is not a completed change, and nothing depending on it proceeds


### Requirement: Roadmap currency at change closeout

A change whose completion alters what is true about a roadmap goal MUST update that
goal's current-state description and its gap-to-change mapping as part of the
change's own closeout, before implementation is considered complete, and MUST name
that update in the change's design-promotion record. The update MUST be made before
the change is archived, so that the closeout review reads the roadmap as the change
leaves it. A change with no roadmap impact MUST record that disposition explicitly at
closeout rather than omitting the step.

#### Scenario: Completed change closes a mapped gap

- **WHEN** a change completes work the roadmap maps to it as an open gap
- **THEN** the same change updates the goal's current-state description, removes the
  closed gap from the mapping, and records the roadmap update in its
  design-promotion record

#### Scenario: The closeout review reads the roadmap

- **WHEN** a change's closeout review runs
- **THEN** the roadmap already reflects the resulting current state, written before
  the change was archived

#### Scenario: Change has no roadmap impact

- **WHEN** a change completes without altering what is true about any roadmap goal
- **THEN** its closeout records that no roadmap update is owed, rather than silently
  skipping the step
