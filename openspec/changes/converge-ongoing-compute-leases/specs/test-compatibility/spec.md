## ADDED Requirements

### Requirement: Rate servicing scenarios qualify both compute lanes

VM and bare-metal lanes MUST exercise the nine convergence scenarios against the in-lane payment and mediation doubles, pausing loops and advancing explicit effects. Evidence MUST distinguish proposed-contract qualification, published-contract qualification and live evidence. Each scenario MUST observe physical progress, financial work and kept evidence independently; a double run MUST NOT be labelled live evidence.

#### Scenario: Convergence scenario matrix runs

- **WHEN** rate servicing is qualified in either compute lane
- **THEN** its report covers baseline, payment-outage buyer end, absent-storefront site withdrawal, filing/ruling crash replay, stop/disclosure races, activation expiry, exhaustion, authority-hosted notice and start-without-delivery, recording both completion facts and authority/evidence references

#### Scenario: A stop outlives the storefront

- **WHEN** the lane records a seller notice at the double and pauses the storefront beyond its effective time
- **THEN** the double applies the stop without another seller call, and resumed end service adopts that authority record

#### Scenario: Late evidence follows an uncertain effect

- **WHEN** a filing or correction acknowledgement is lost and earlier site evidence is later received
- **THEN** restart resolves the original operation, appends the new evidence under a stable identity and never applies a duplicate correction
