# Planning Governance Specification

## Purpose

Define source-of-truth boundaries, provenance, lifecycle, and validation for OpenSpec-backed planning.

## Requirements

### Requirement: Canonical planning homes
The repository MUST use OpenSpec main specs as the canonical source for current normative capability behavior, active OpenSpec changes as the canonical source for proposed deltas and implementation tasks, and archived OpenSpec changes as the canonical record of completed changes. Ordinary documentation MAY explain architecture, operations, and workflows, but MUST NOT maintain a competing normative backlog.

#### Scenario: Contributor proposes behavioral work
- **WHEN** a contributor identifies a behavior or architecture change
- **THEN** it is captured in an OpenSpec change rather than a flat documentation backlog

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
