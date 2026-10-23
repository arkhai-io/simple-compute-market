## ADDED Requirements

### Requirement: Lifecycle terms and evidence retention are published per listing

A listing MUST publish lifecycle terms only inside its settlement options, and MUST publish the storefront's evidence dispute window. The VM admin interrupt route MUST identify an Alkahest interruptible deal by its accepted option's release condition, not by a listing field.

#### Scenario: An administrator interrupts an Alkahest deal

- **WHEN** an administrator interrupts a deal whose accepted Alkahest option uses the splitter release condition
- **THEN** the route accepts it, without reading a listing-level marker

#### Scenario: A buyer reads the dispute window

- **WHEN** a buyer selects a listing
- **THEN** the listing states the dispute window for which the storefront keeps evidence
