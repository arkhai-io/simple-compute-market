## ADDED Requirements

### Requirement: Mediation case recovery preserves protection outcomes

Recovery of an existing mediation case MUST distinguish accepted case protection
from pending protection. An accepted answer MUST match the requested case,
Agreement and transaction; a pending answer MUST match the requested case.
Neither outcome alone replaces verified signed filing evidence or authorizes a
duplicate filing.

#### Scenario: Accepted case recovery

- **WHEN** an existing delivery-end filing is recovered and the authority returns an accepted case envelope
- **THEN** recovery verifies its bindings and adopts the original signed filing without creating another case

#### Scenario: Protection is still pending

- **WHEN** the authority reports pending protection for the requested case
- **THEN** recovery remains pending and sends no duplicate filing

#### Scenario: Response names another case or deal

- **WHEN** a case answer names a different case, Agreement or transaction
- **THEN** recovery rejects the response without adopting evidence or sending another filing
