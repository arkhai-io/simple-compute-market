# Planning Governance Specification

## Purpose

Define source-of-truth boundaries, provenance, lifecycle, and validation for OpenSpec-backed planning.

## Requirements

### Requirement: Canonical planning homes
The repository MUST use OpenSpec main specs as the canonical source for current normative capability behavior, active OpenSpec changes as the canonical source for proposed deltas and implementation tasks, and archived OpenSpec changes as the canonical record of completed changes. Ordinary documentation MAY explain architecture, operations, and workflows, but MUST NOT maintain a competing normative backlog.

#### Scenario: Contributor proposes behavioral work
- **WHEN** a contributor identifies a behavior or architecture change
- **THEN** it is captured in an OpenSpec change rather than a flat documentation backlog

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

## Evidence

- Canonical contributor workflow and capability index: `openspec/README.md`.
- Artifact-generation context and quality rules: `openspec/config.yaml`.
- Lossless migration provenance: `openspec/changes/archive/2026-07-13-migrate-planning-to-openspec/migration-ledger.json` and its archived artifacts.
- Role-owned operational guidance: `docs/buyer-quickstart.md`, `docs/seller-quickstart.md`, `docs/indexer-quickstart.md`, `docs/domain-authoring/README.md`, and `e2e-tests/tests/e2e/roles/README.md`.
- Repository-wide architecture, operational, and directional separation: `docs/development/ARCHITECTURE.md`, `docs/development/ROADMAP.md`, and `openspec/changes/README.md` — the current system, the goals being pursued, and delivery readiness respectively, each naming the other two's jurisdiction.
- The single permitted directional roadmap and its no-tasks/no-acceptance-criteria/no-status constraints: `docs/development/ROADMAP.md`.
- Roadmap currency owed at change completion: `openspec/README.md#plan-closeout-requirements`, part 5.
- Campaign index currency owed at change completion: `openspec/README.md#plan-closeout-requirements`, part 6.

Strict OpenSpec validation checks artifact structure. Evidence strength, current-versus-proposed classification, coherent change boundaries, and stale inline-note disposition still require code-aware review.
