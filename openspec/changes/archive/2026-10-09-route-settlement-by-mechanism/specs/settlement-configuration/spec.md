## MODIFIED Requirements

### Requirement: Priority orders choices but never changes accepted settlement

Storefront publication MUST emit options in configured priority order for every enabled and ready registration with a valid publication clause and a supported seller-stage entry. Buyer compatibility/selection MUST intersect registration compatibility with supported buyer-stage entries and MAY use priority as policy input. Accepted Terms MUST pin one exact option; configuration, readiness or priority changes MUST NOT switch an accepted or in-flight mechanism.

#### Scenario: One of two enabled mechanisms is unready

- **WHEN** one supported mechanism preflight fails and the other is ready
- **THEN** publication suppresses only the unready mechanism, reports its blocker and advertises the ready mechanism

#### Scenario: No enabled mechanism is ready

- **WHEN** every enabled mechanism fails preflight
- **THEN** publication fails without replacing existing accepted Terms or starting a settlement

#### Scenario: Registration lacks a domain stage

- **WHEN** an installed registration has no supporting entry for the publishing or selecting role
- **THEN** no fresh option for that role is published or selected, even if its configuration and preflight are valid

## ADDED Requirements

### Requirement: Registration and settlement execution are distinct

Registration MUST remain the shared contract for typed configuration, publication, readiness and compatibility. Settlement execution MUST use the domain role table, not a required registration settlement hook. Existing obligation/artifact hooks MUST NOT imply that every mechanism uses the obligation runtime or follows a shared stage convention.

#### Scenario: An Agreement-only mechanism is installed

- **WHEN** a domain composes an Agreement-only stage and its typed registration
- **THEN** publication and compatibility work without conditional-escrow clients, a servicing worker or a universal settle interface

#### Scenario: A mechanism opts out of the convention

- **WHEN** a domain supports a stage with a different actor sequence or fused delivery
- **THEN** it remains a full registered peer and requires no opt-in-convention adapter

### Requirement: Accepted recovery retains supported stage identity

Disabling publication or selection for a mechanism MUST NOT reinterpret accepted work. Recovery MUST retain the domain entry required by the recorded Agreement or report an unavailable accepted stage before effects. It MUST NOT restore eligibility through escrow-shaped fallback or current configuration priority.

#### Scenario: A mechanism is disabled after acceptance

- **WHEN** a previously accepted Agreement is resumed after its registration is disabled for new work
- **THEN** its existing entry resumes that exact mechanism and operation identity without advertising it for fresh work
