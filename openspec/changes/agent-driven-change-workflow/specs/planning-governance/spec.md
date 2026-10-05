## ADDED Requirements

### Requirement: Active-change index status vocabulary

Every change row in the active-change index at `openspec/changes/README.md` MUST
state its status in a column holding nothing else, as exactly one of: `ready for
<phase>`, `in <phase>`, or `blocked in <phase>`, where `<phase>` is one of
`design`, `planning`, `implementation`, or `closeout`; or `ready for archival`,
`deferred`, or `archived`. A `blocked in <phase>` status MUST be used only for a
reason that is not another change, and that reason, and a deferred change's
activation condition, MUST be stated in a separate explanatory column.

Each row MUST list, in a `Depends on` column, every other change that must reach
`ready for archival` or `archived` before it may begin implementation. A dependency
on another change MUST NOT be expressed through the status. When a change reaches
`ready for archival`, its closeout MUST remove it from every dependent's
`Depends on` and MUST set each dependent that has not begun implementation to
`ready for design`, so that its design is reverified against the codebase the
dependency left before it is implemented.

#### Scenario: A reader or agent asks what may start

- **WHEN** a contributor or an agent reads the index to find work that may begin
- **THEN** it selects rows whose status begins `ready for`, excluding a `ready for
  implementation` row with any listed dependency, without interpreting prose

#### Scenario: A dependency lands

- **WHEN** a change that another row depends on completes closeout, and that
  dependent has a reviewed design and a plan but has not begun implementation
- **THEN** the completing change removes itself from the dependent's `Depends on`
  and sets the dependent to `ready for design`, and the dependent's design is
  reviewed again before it is planned or implemented

#### Scenario: Local work waits on an external input

- **WHEN** a change cannot finish implementation until an input outside the
  repository is available
- **THEN** its status is `blocked in implementation` and its explanatory column
  names the input

### Requirement: Campaign priority order

The active-change index MUST carry one ordered list of its campaigns — roadmap
goals, lesser goals, and the independent active changes taken as one entry — whose
order is the priority in which campaigns are worked. Priority MUST NOT be assigned
to individual changes; order within a campaign follows its dependency graph. The
directional roadmap MUST NOT carry this order.

#### Scenario: Choosing the next change

- **WHEN** a contributor or an agent selects the next change to work
- **THEN** it takes the first campaign in priority order with a change whose status
  permits work, and within it the first such change its dependency graph allows

### Requirement: Transient review records

Reviews, review triage, and validation reports produced while a change is worked
MUST be written under that change's `reviews/` directory, MUST NOT be tracked by
version control, and MUST NOT be cited by permanent documentation. Anything durable
in them MUST reach permanent documentation through the ordinary promotion path
before archival. A change's intervention ledger is not a review record: it is
tracked, stays in the change directory, and is archived with the change.

#### Scenario: A review finding changes the design

- **WHEN** a review finding leads to an accepted design decision
- **THEN** the decision is recorded in the change's `design.md` and promoted at
  closeout, and nothing permanent cites the review file

#### Scenario: A change is archived after reviews

- **WHEN** a change that was reviewed is archived
- **THEN** its `reviews/` directory is gone and its intervention ledger is in the
  archived change directory

### Requirement: Harness-neutral agent skills

Each agent skill committed to the repository MUST have exactly one source, and MUST
be loadable by every supported agent harness from that source. A skill MUST NOT be
maintained as separate copies for different harnesses, and every harness entry for
a skill MUST resolve.

#### Scenario: A skill is edited

- **WHEN** a contributor edits a committed skill
- **THEN** every harness loads the edited skill, with no second copy to update

#### Scenario: A harness entry does not resolve

- **WHEN** a harness skill entry points at a source that does not exist
- **THEN** the repository's skill check fails
