## ADDED Requirements

### Requirement: Active-change index status vocabulary

Every change row in the active-change index at `openspec/changes/README.md` MUST
state its status as exactly one of `proposed`, `active`, `implementing`, `blocked`,
`deferred`, `complete`, or `archived`, in a column holding nothing else. Any
explanation of that status — what a blocked change waits on, which sections are
done, what a deferred change's activation condition is — MUST be carried in a
separate column. A `blocked` or `deferred` status MUST be accompanied by that
explanation.

#### Scenario: A reader or agent asks what may start

- **WHEN** a contributor or an agent reads the index to find work that may begin
- **THEN** it can select rows by status value alone, without interpreting prose

#### Scenario: A change is blocked

- **WHEN** a change's row records the status `blocked`
- **THEN** the same row names what it is blocked on in its explanation column

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
before archival.

#### Scenario: A review finding changes the design

- **WHEN** a review finding leads to an accepted design decision
- **THEN** the decision is recorded in the change's `design.md` and promoted at
  closeout, and nothing permanent cites the review file

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
