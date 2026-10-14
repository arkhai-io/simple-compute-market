# Planning Governance Specification

## Purpose

Define source-of-truth boundaries, provenance, lifecycle, and validation for OpenSpec-backed planning.

## Requirements

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

### Requirement: Audience-owned documentation
Current user-facing behavior and troubleshooting MUST live in documentation addressed to the buyer, seller, registry operator, provisioner, or contributor who acts on it. Current normative behavior MUST also be represented by its owning OpenSpec capability specification, and intended changes MUST remain in OpenSpec changes rather than role guides.

#### Scenario: Current operational constraint is verified
- **WHEN** a buyer, seller, registry operator, provisioner, or test contributor can encounter a verified constraint
- **THEN** the relevant role guide explains the symptom and safe action while the owning capability spec records the current contract

#### Scenario: Behavior is intended to change
- **WHEN** the desired outcome differs from current implementation
- **THEN** an active OpenSpec change owns the intended delta and role documentation does not present it as current behavior

#### Scenario: Documentation has no actionable audience
- **WHEN** a legacy issue or documentation placeholder cannot identify a reader and safe action
- **THEN** it is removed, rejected, or retained in the change as unresolved rather than added to a generic known-issues page

### Requirement: Complete migration provenance
Migrated planning material MUST record its source, classification, destination or removal rationale, evidence, and verification state.

#### Scenario: Source item is stale or duplicate
- **WHEN** evidence shows a source item is obsolete or another artifact owns it
- **THEN** provenance records that disposition rather than copying the item

### Requirement: Evidence-based baseline specifications
Current-state requirements MUST be supported by code, focused tests, configuration, or a deployed interface definition and MUST describe observable behavior or durable boundaries.

#### Scenario: Prose conflicts with implementation
- **WHEN** implementation evidence and architecture prose disagree
- **THEN** the prose is not promoted to a baseline requirement until resolved

### Requirement: Independently actionable changes
Pending work MUST be normalized into changes whose requirements share one coherent outcome and can be reviewed, implemented, verified, and archived together.

#### Scenario: Legacy program contains independent outcomes
- **WHEN** a planning section has separate compatibility or acceptance boundaries
- **THEN** each unit becomes a separate OpenSpec change

### Requirement: Explicit non-ready states
Deferred, conditional, externally blocked, and unresolved work MUST retain that state and MUST NOT present implementation tasks as ready. Implemented work MUST NOT remain active backlog.

#### Scenario: Conditional optimization lacks its trigger
- **WHEN** measured demand has not satisfied the activation condition
- **THEN** the change has no implementation checklist

### Requirement: Conservative inline-note conversion
Inline TODO/FIXME markers MUST be reviewed in context; only unresolved observable work becomes a change, implementation-local work attaches to an existing change, and stale markers require evidence.

#### Scenario: Marker is a local implementation step
- **WHEN** it belongs to an existing behavioral change
- **THEN** it maps to that change rather than creating a duplicate backlog item

### Requirement: Lossless cutover
Legacy planning content MUST NOT be removed until provenance is resolved, OpenSpec artifacts validate, links are updated or redirected, and a final marker scan finds no orphan actionable note.

#### Scenario: Cutover checks pass
- **WHEN** provenance, strict validation, link checks, and marker reconciliation pass
- **THEN** duplicate legacy planning content may be reduced to non-normative redirects

### Requirement: Planning artifact quality
Project configuration MUST require proposals to identify capabilities/non-goals, specs to use observable scenarios, designs to address compatibility/migration, and tasks to verify behavior before documentation cleanup.

#### Scenario: New change instructions are generated
- **WHEN** a contributor requests artifact instructions
- **THEN** repository vocabulary, dependency constraints, and verification expectations are available without embedding the legacy architecture document

### Requirement: Permanent capability architecture companions
A capability MAY maintain `architecture.md` beside its normative `spec.md` for durable current-state conceptual models, ownership rationale, trade-offs, limitations, and relationships that do not fit observable requirement scenarios. Normative behavior MUST remain in `spec.md`; proposed decisions MUST remain in an active change until accepted and implemented. Every companion MUST be linked from the canonical capability index, and every material update MUST be named in the implementing change's promotion tasks and design-promotion record because OpenSpec does not synchronize companion files automatically.

#### Scenario: Accepted rationale does not fit a behavioral requirement
- **WHEN** an implemented design decision explains why a capability boundary or trade-off exists without introducing independently testable behavior
- **THEN** the change promotes it to the owning capability's `architecture.md` and links that document from the capability index

#### Scenario: Prose contains an observable invariant
- **WHEN** architecture prose states behavior that implementations must satisfy
- **THEN** the owning `spec.md` also expresses that invariant as a normative requirement with a verifiable scenario

#### Scenario: Change is archived
- **WHEN** a completed change contains accepted capability-level design rationale
- **THEN** archive review verifies its explicit permanent architecture destination even though OpenSpec's delta synchronizer does not process the companion file

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
that update in the change's design-promotion record. The update MUST be made before
the change is archived, so that the closeout review reads the roadmap as the change
leaves it. A change with no roadmap impact MUST record that disposition explicitly at
closeout rather than omitting the step.

#### Scenario: Completed change closes a mapped gap

- **WHEN** a change completes work the roadmap maps to it as an open gap
- **THEN** the same change updates the goal's current-state description, removes the
  closed gap from the mapping, and records the roadmap update in its
  design-promotion record

#### Scenario: Change is complete but not yet archived

- **WHEN** a change's implementation is complete while its change directory remains
  active
- **THEN** its closeout updates the roadmap before archiving it, so the closeout
  review reads the roadmap as the change leaves it

#### Scenario: Change has no roadmap impact

- **WHEN** a change completes without altering what is true about any roadmap goal
- **THEN** its closeout records that no roadmap update is owed, rather than silently
  skipping the step

### Requirement: Packaging check at change closeout

Every change's closeout task MUST run the repository packaging check and resolve every
failure it reports before implementation is considered complete. Passing test suites do
not satisfy it: a suite can pass against an environment a hand-maintained or missing
refresh left stale, and the next environment to rebuild then fails instead. A change
MUST own no architecture exception row when it is archived.

#### Scenario: A change adds an internal dependency

- **WHEN** a change makes a project depend on another repository distribution and its
  closeout runs the packaging check
- **THEN** the check passes only if the project's lock resolves that distribution from
  the wheelhouse at the version the tree builds

#### Scenario: A closeout task omits the packaging check

- **WHEN** a change's plan ends with a closeout task that does not run the packaging
  check
- **THEN** the plan does not satisfy the plan-closeout requirements

#### Scenario: A change owns an architecture exception at closeout

- **WHEN** a change that owns an architecture exception row runs its closeout
- **THEN** the change-scoped architecture check fails until the row is gone, either
  because the change removed its edge and deleted the row, or because the row was
  reassigned to another open change that now owns the divergence

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
dependent's `Depends on`, and MUST set each dependent whose status is `ready for
planning`, `in planning`, or `ready for implementation` to `ready for design`, so that its design is reverified against the codebase the dependency
left before it is planned or implemented. A dependent `in implementation` MUST keep
that status, since its implementation has begun. A dependent whose status is `blocked in`
a phase MUST keep that status, and the completing change MUST record in its
explanatory column that design reverification is owed. Closeout MUST NOT change
a dependent's `Depends on` or status before the closeout review's gate is passed.

#### Scenario: A planned dependent

- **WHEN** a change that another row depends on is archived and cleaned up, and that
  dependent is `ready for planning`, `in planning`, or `ready for implementation`
- **THEN** the completing change removes itself from the dependent's `Depends on`
  and sets the dependent to `ready for design`, and the dependent's design is
  reviewed again before it is planned or implemented

#### Scenario: A dependent in implementation

- **WHEN** a change that another row depends on is archived and cleaned up, and that
  dependent is `in implementation`
- **THEN** the completing change removes itself from the dependent's `Depends on`,
  and the dependent stays `in implementation`

#### Scenario: A blocked dependent

- **WHEN** a change that another row depends on is archived and cleaned up, and that
  dependent is `blocked in planning` on an external input
- **THEN** the dependent stays `blocked in planning`, and its explanatory column
  records that design reverification is owed once the blocker clears

#### Scenario: A closeout review sends the change back

- **WHEN** a change's closeout review is triaged and its gate is not passed
- **THEN** every row that depends on it keeps its `Depends on` and its status

## Evidence

- Canonical contributor workflow and capability index: `openspec/README.md`.
- Artifact-generation context and quality rules: `openspec/config.yaml`.
- Role-owned operational guidance: `docs/buyer-quickstart.md`, `docs/seller-quickstart.md`, `docs/indexer-quickstart.md`, `docs/domain-authoring/README.md`, and `e2e-tests/tests/e2e/roles/README.md`.
- Repository-wide architecture, operational, and directional separation: `docs/development/ARCHITECTURE.md`, `docs/development/ROADMAP.md`, and `openspec/changes/README.md` — the current system, the goals being pursued, and delivery readiness respectively, each naming the other two's jurisdiction.
- The single permitted directional roadmap and its no-tasks/no-acceptance-criteria/no-status constraints: `docs/development/ROADMAP.md`.
- Roadmap currency owed at change completion: `openspec/README.md#plan-closeout-requirements`, part 5.
- Campaign index currency owed at change completion: `openspec/README.md#plan-closeout-requirements`, part 6.
- Packaging check at change closeout: `openspec/README.md#plan-closeout-requirements`, part 7; `make check-packaging`, which runs `make check-architecture`; a change's own exception rows: `make check-architecture-change CHANGE=<name>`.

Strict OpenSpec validation checks artifact structure. Evidence strength, current-versus-proposed classification, coherent change boundaries, and stale inline-note disposition still require code-aware review.
