## MODIFIED Requirements

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

<!-- Provenance: documentation-gap migration and removal of the mixed-audience KNOWN_ISSUES.md. -->
