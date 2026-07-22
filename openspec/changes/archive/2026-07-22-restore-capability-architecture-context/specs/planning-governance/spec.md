## ADDED Requirements

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
