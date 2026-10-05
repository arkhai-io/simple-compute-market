## ADDED Requirements

### Requirement: Active-change index status vocabulary

Every change row in the active-change index at `openspec/changes/README.md` MUST
state its status in a column holding nothing else, as exactly one of: `ready for
<phase>`, `in <phase>`, or `blocked in <phase>`, where `<phase>` is one of
`design`, `planning`, `implementation`, or `closeout`; or `ready for archival`,
`deferred`, or `archived`. `blocked in <phase>` MUST be used only for a reason that
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
reach `ready for archival` or `archived` before it may proceed, each with the phase
it gates. An entry naming no phase gates implementation. A dependency on another
change MUST NOT be expressed through the status. A dependency gating only part of a
change MUST be stated in the explanatory column rather than in `Depends on`.

#### Scenario: A dependency decides whether the dependent exists

- **WHEN** another change's design decides whether a change is superseded,
  narrowed, or folded in
- **THEN** the dependent lists that change in `Depends on` as gating `design`, and
  is not designed until it lands

### Requirement: Design reverification when a dependency lands

When a change reaches `ready for archival`, its closeout MUST remove it from every
dependent's `Depends on`, and MUST set each dependent whose status is `ready for` or
`in` planning or implementation, and which has not begun implementing, to `ready
for design`, so that its design is reverified against the codebase the dependency
left before it is planned or implemented. A dependent whose status is `blocked in`
a phase MUST keep that status, and the completing change MUST record in its
explanatory column that design reverification is owed.

#### Scenario: A planned dependent

- **WHEN** a change that another row depends on completes closeout, and that
  dependent has a reviewed design and a plan but has not begun implementation
- **THEN** the completing change removes itself from the dependent's `Depends on`
  and sets the dependent to `ready for design`, and the dependent's design is
  reviewed again before it is planned or implemented

#### Scenario: A blocked dependent

- **WHEN** a change that another row depends on completes closeout, and that
  dependent is `blocked in planning` on an external input
- **THEN** the dependent stays `blocked in planning`, and its explanatory column
  records that design reverification is owed once the blocker clears
