## ADDED Requirements

### Requirement: Physical quarantine excludes a host from admission

The site authority MUST support a quarantine eligibility state for a physical host whose release failed or whose physical state is uncertain. While a host is quarantined, admission MUST refuse every resource and offering-mode alias of that physical host, including VM and bare-metal modes. Accounting force-release and automatic teardown retries MUST NOT clear quarantine. Only an authenticated, audited administrator recovery may clear it, and that recovery MUST require verification evidence newer than the quarantine record. Historical allocation records MUST be retained, and availability MUST follow from the authority's own calculation, not from deleting history.

#### Scenario: VM claim targets a quarantined bare-metal host

- **WHEN** a VM slice reservation targets a physical host quarantined after a failed bare-metal release
- **THEN** the site authority refuses the reservation

#### Scenario: Operator force-releases accounting

- **WHEN** an operator force-releases the allocation of a quarantined host
- **THEN** capacity accounting records the override, and the host remains ineligible for admission

#### Scenario: Recovery evidence predates the quarantine

- **WHEN** an administrator requests recovery with verification evidence gathered before the quarantine was recorded
- **THEN** the recovery is refused, and the host stays quarantined
