## ADDED Requirements

### Requirement: Canonical planning homes
The repository MUST use OpenSpec main specs as the canonical source for current normative capability behavior, active OpenSpec changes as the canonical source for proposed deltas and implementation tasks, and archived OpenSpec changes as the canonical record of completed changes. Ordinary documentation MAY explain architecture, operations, and workflows, but MUST NOT maintain a competing normative backlog or duplicate requirements without linking to the canonical OpenSpec artifact.

#### Scenario: Contributor proposes behavioral work
- **WHEN** a contributor identifies a new behavior, behavior change, or architecture migration
- **THEN** the work is captured in an OpenSpec change with affected capabilities and requirements before it is added to a flat documentation backlog

#### Scenario: Documentation explains current behavior
- **WHEN** ordinary documentation needs to explain a normative system contract
- **THEN** it links to the owning capability spec and limits its own content to orientation, rationale, examples, or operational guidance

### Requirement: Complete migration inventory
The migration MUST inventory every heading in `docs/development/ARCHITECTURE.md`, `TODO.md`, `design-remaining-work.md`, and `provisioning-migration-plan.md`, plus every in-scope repository-owned actionable TODO/FIXME marker. Each inventory entry MUST record its source, classification, destination or explicit removal rationale, and verification state.

#### Scenario: Source item has a canonical destination
- **WHEN** a source item describes current behavior, proposed work, completed history, or operational guidance
- **THEN** the ledger names the exact spec, change, archive, or retained document that owns it

#### Scenario: Source item is stale or duplicated
- **WHEN** code evidence shows that a source item is stale or another item owns the same contract
- **THEN** the ledger records the evidence and the stale or duplicate item is removed or redirected rather than copied

#### Scenario: Source item is ambiguous
- **WHEN** the available code and documentation do not establish whether an item is current, pending, or obsolete
- **THEN** the item remains explicitly unresolved with its blocker identified and its source text is not silently deleted

### Requirement: Evidence-based baseline specifications
A current-state requirement migrated from architecture prose MUST be supported by repository code, focused tests, configuration, or a deployed interface definition. Requirements MUST describe observable behavior or durable boundaries; package paths and implementation names MAY be cited as evidence but MUST NOT be the only contract.

#### Scenario: Architecture claim matches implementation
- **WHEN** code or focused tests establish the described behavior
- **THEN** the behavior is written as a requirement with at least one verifiable scenario in the owning capability spec

#### Scenario: Architecture claim conflicts with implementation
- **WHEN** the implementation and architecture prose disagree
- **THEN** the migration records the conflict and does not promote the prose to a baseline requirement until the intended contract is resolved

### Requirement: Independently actionable changes
Pending work MUST be normalized into OpenSpec changes whose requirements share one coherent outcome and can be reviewed, implemented, verified, and archived together. A legacy heading MUST be split when it contains independent outcomes and MAY be merged with another heading when both describe the same outcome.

#### Scenario: Legacy program contains independent work
- **WHEN** a TODO section contains changes with separate compatibility risks or acceptance boundaries
- **THEN** each independent unit becomes its own OpenSpec change with explicit dependencies where needed

#### Scenario: Multiple notes describe one outcome
- **WHEN** a TODO section, design note, and inline marker all describe the same desired behavior
- **THEN** one OpenSpec change owns the behavior and the migration ledger maps every source to that change

### Requirement: Explicit non-ready states
Deferred, conditional, externally blocked, and unresolved work MUST retain that state explicitly and MUST NOT be represented as implementation-ready tasks. Implemented work MUST NOT remain in the active backlog.

#### Scenario: Conditional optimization has no trigger
- **WHEN** a proposed optimization is conditional on future measured demand
- **THEN** its change records the activation condition and does not present immediate implementation tasks as ready

#### Scenario: Work is already implemented
- **WHEN** repository evidence satisfies the legacy item's acceptance criteria
- **THEN** the item is represented as baseline behavior or archived history and is removed from active changes

### Requirement: Conservative inline-note conversion
Inline TODO/FIXME markers MUST be reviewed in context. Only markers that describe unresolved observable work become changes; implementation-local steps attach to an existing change, and stale markers may be removed only with evidence. Generated, vendored, lock, migration-history, and archived OpenSpec files MUST be excluded from the marker inventory unless the repository directly owns an actionable marker there.

#### Scenario: Inline marker is an implementation step
- **WHEN** a marker describes a step within an already identified behavioral change
- **THEN** it becomes a task in that change rather than a separate change

#### Scenario: Inline marker is not actionable
- **WHEN** a marker documents a permanent limitation, test fixture, example token, or historical rationale without unresolved work
- **THEN** it remains documentation or is clarified, and no backlog change is created

### Requirement: Lossless cutover gate
Legacy planning content MUST NOT be removed until all inventory entries have resolved dispositions, all generated OpenSpec artifacts validate, internal links to migrated headings have been updated or redirected, and a final source scan finds no orphan actionable planning note.

#### Scenario: Migration has unresolved entries
- **WHEN** any inventory row lacks a verified destination or removal rationale
- **THEN** the legacy source remains available and the migration cannot be declared complete

#### Scenario: Cutover checks pass
- **WHEN** the inventory is complete, OpenSpec validation succeeds, link checks pass, and the final marker scan is reconciled
- **THEN** duplicate legacy planning content is removed or reduced to a non-normative index and OpenSpec becomes the documented contributor workflow

### Requirement: Planning artifact quality rules
The OpenSpec project configuration MUST provide concise repository context and rules that require proposals to identify affected capabilities and non-goals, requirements to use observable scenarios, designs to address compatibility and migration when relevant, and task lists to include focused behavioral verification before documentation cleanup.

#### Scenario: Future change artifacts are generated
- **WHEN** OpenSpec instructions are used for a new repository change
- **THEN** the generated artifact guidance includes the repository's architecture vocabulary, dependency constraints, and verification expectations without embedding the full architecture reference
