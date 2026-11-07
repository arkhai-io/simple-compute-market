## ADDED Requirements

### Requirement: Directional roadmap document

The repository MAY maintain exactly one repository-wide directional roadmap, at
`docs/development/ROADMAP.md`. For each current goal it MUST state the value that
goal delivers and an evidence-based, present-tense description of current behavior,
and it MUST link every identified gap to the OpenSpec change that owns it. It MUST
NOT contain implementation tasks, acceptance criteria, readiness or blocking status,
or delivery sequencing; those remain owned by the changes themselves and by the
active-change index. An identified gap with no owning change MUST result in an
OpenSpec change being opened rather than a roadmap entry standing in for one. A
second directional roadmap MUST NOT be introduced elsewhere in ordinary
documentation.

#### Scenario: Goal-level gap has no owning change

- **WHEN** roadmap review identifies work required by a goal that no active or
  archived OpenSpec change owns
- **THEN** an OpenSpec change is opened for that work and the roadmap links it,
  rather than the roadmap describing the work as a standing item

#### Scenario: Reader needs to know whether work may begin

- **WHEN** a contributor asks whether work toward a roadmap goal is ready, blocked,
  or deferred
- **THEN** the roadmap directs them to the owning change and the active-change index
  rather than stating readiness itself

#### Scenario: Additional planning document is proposed in ordinary documentation

- **WHEN** a contributor proposes a second roadmap, goal list, or directional
  backlog elsewhere under `docs/`
- **THEN** it is rejected or consolidated into the single permitted roadmap

### Requirement: Roadmap currency at change closeout

A change whose completion alters what is true about a roadmap goal MUST update that
goal's current-state description and its gap-to-change mapping as part of the
change's own closeout, before implementation is considered complete, and MUST name
that update in the change's design-promotion record. Roadmap currency MUST be tied
to change completion rather than to archival, so that a completed change is
reflected without waiting for its documents to be archived. A change with no roadmap
impact MUST record that disposition explicitly at closeout rather than omitting the
step.

#### Scenario: Completed change closes a mapped gap

- **WHEN** a change completes work the roadmap maps to it as an open gap
- **THEN** the same change updates the goal's current-state description, removes the
  closed gap from the mapping, and records the roadmap update in its
  design-promotion record

#### Scenario: Change is complete but not yet archived

- **WHEN** a change's implementation is complete while its change directory remains
  active
- **THEN** the roadmap already reflects the resulting current state rather than
  waiting for archival

#### Scenario: Change has no roadmap impact

- **WHEN** a change completes without altering what is true about any roadmap goal
- **THEN** its closeout records that no roadmap update is owed, rather than silently
  skipping the step

## MODIFIED Requirements

### Requirement: Canonical planning homes

The repository MUST use OpenSpec main specs as the canonical source for current
normative capability behavior, active OpenSpec changes as the canonical source for
proposed deltas and implementation tasks, and archived OpenSpec changes as the
canonical record of completed changes. Ordinary documentation MAY explain
architecture, operations, workflows, and directional goals, but MUST NOT maintain a
competing normative backlog. Documentation maintains a competing backlog when it
carries implementation tasks, acceptance criteria, or readiness status for work an
OpenSpec change owns or should own; stating a goal, the value it delivers, current
behavior, and a link to the owning change does not.

#### Scenario: Contributor proposes behavioral work

- **WHEN** a contributor identifies a behavior or architecture change
- **THEN** it is captured in an OpenSpec change rather than a flat documentation
  backlog

#### Scenario: Documentation states goal-level direction

- **WHEN** documentation explains why a goal exists, what value it delivers, and
  which changes carry it
- **THEN** it is permitted directional context provided it assigns no tasks,
  acceptance criteria, or readiness status
