## ADDED Requirements

### Requirement: Seller notice uses lifecycle submit and authority-hosted stop
The seller half MUST admit a negotiation-keyed notice command only under the accepted payee entitlement. It MUST use the foundation's lifecycle submit command contract, submit stop immediately through the payment adapter, and return authority status rather than claim a locally scheduled payment end.

#### Scenario: A seller preempts an accepted spot deal
- **GIVEN** an authenticated seller and an accepted payee notice entitlement
- **WHEN** the seller submits notice with a stable operation key
- **THEN** the seller half preserves the command identity without a correction obligation
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

### Requirement: Canonical rate buyer end preserves service during notice
The buyer half MUST normally submit rate stop at the payment authority and send hint, allowing delivery until effective stop reaches end service through watch. It MUST reserve end_delivery for explicit immediate surrender or the foundation's unreachable-payment-authority buyer_end(at) path. Immediate surrender MUST disclose that paid notice may outlast service.

#### Scenario: A payer has nonzero notice
- **GIVEN** an accepted rate option with payer notice 300 seconds
- **WHEN** the buyer invokes normal end and stop is accepted pending
- **THEN** the buyer sends hint, not end_delivery, and service continues until the effective authority stop
- **AND** losing the hint does not cancel or postpone that stop

#### Scenario: The buyer explicitly gives up remaining notice service
- **WHEN** the buyer chooses end-now-regardless
- **THEN** the buyer half submits stop and sends end_delivery with the immediate-surrender disclosure

#### Scenario: The payment authority cannot be reached
- **WHEN** the buyer invokes end but payment stop is unknown or unavailable
- **THEN** the foundation's signed end_delivery and buyer_end(at) evidence/retry path is used
