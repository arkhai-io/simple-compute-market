## ADDED Requirements

### Requirement: Early termination is published per option

A listing MUST publish early-termination terms only inside its settlement options. The VM admin interrupt route MUST identify an Alkahest interruptible deal by its accepted option's release condition, not by a listing field.

#### Scenario: An administrator interrupts an Alkahest deal

- **WHEN** an administrator interrupts a deal whose accepted Alkahest option uses the splitter release condition
- **THEN** the route accepts it, without reading a listing-level marker
