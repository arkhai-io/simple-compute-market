## ADDED Requirements

### Requirement: Seller notice uses lifecycle submit and authority-hosted stop
The seller half MUST admit a negotiation-keyed notice command only under the accepted payee entitlement. It MUST use the existing seller-authenticated lifecycle submit contract and journal seam, submit stop immediately through the payment adapter, and return authority status rather than claim a locally scheduled payment end.

#### Scenario: A seller preempts an accepted spot deal
- **GIVEN** an authenticated seller and an accepted payee notice entitlement
- **WHEN** the seller submits notice with a stable operation key
- **THEN** the seller half journals the command and cooperative started-period correction obligation
- **AND** the adapter submits explicit affected-part stops to the payment authority
- **AND** read/list expose the verified pending stop and its effective time

#### Scenario: The notice response is lost
- **WHEN** the authority accepted stop but its response was lost
- **THEN** lifecycle reports unknown and resolves by read or identical-key retry
- **AND** no local due-time payment-stop task is created

#### Scenario: A buyer stops earlier during notice
- **GIVEN** a seller pending stop and an earlier authority-recorded buyer stop
- **WHEN** lifecycle reads the authority
- **THEN** it exposes the earlier effective stop for end service
- **AND** a repeated seller command cannot postpone that stop

#### Scenario: On-demand cannot be dressed as preemption
- **GIVEN** an accepted option without payee entitlement
- **WHEN** the seller submits notice
- **THEN** the command is refused before sending a payment event
- **AND** the response identifies exceptional_end as the dispute path for a seller-caused failure

### Requirement: Compute operator preemption delegates through the typed lifecycle client
Both compute storefront operator CLIs MUST provide deals preempt by negotiation ID, using the lifecycle client's notice method and seller authentication. The command MUST preserve its operation key and optional at and display the authority's status and effective time without claiming a local timestamp is authoritative.

#### Scenario: An operator requests a future stop
- **WHEN** the operator invokes deals preempt with negotiation ID, operation key and at
- **THEN** the CLI delegates the same command through lifecycle submit
- **AND** displays pending, unknown or accepted authority state without bypassing notice

#### Scenario: An unauthenticated caller submits notice
- **WHEN** a caller without the seller route's administrator-principal authentication invokes submit
- **THEN** the route refuses before any adapter event or correction is issued
