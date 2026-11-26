## ADDED Requirements

### Requirement: A deal with a filing of its own outstanding is not listed ended

The seller's list MUST NOT show a deal `ended` while a `delivery_end` filing its own end journal requires has no answer from the dispute authority: a filing not yet sent, a filing waiting for the Agreement's start, or a filing whose outcome is pending or unknown. Such a deal MUST be listed `ending`. A filing is answered once the authority accepts or rejects it; a rejected filing shows repair required, as "The seller half lists deals" states.

#### Scenario: A filing waits for the Agreement's start

- **GIVEN** a once-only deal ended as a seller failure before its Agreement's start, with nothing dispatched, whose `delivery_end` filing waits for that start, and a saved read of its dispute authority showing no case
- **WHEN** the seller lists its deals before the start
- **THEN** the deal is `ending`, never `ended`
- **AND** once the filing is accepted and its case closes, the deal is `ended`

#### Scenario: A filing's answer was lost

- **GIVEN** a released deal whose `delivery_end` filing was sent and whose answer was lost
- **WHEN** the seller lists its deals
- **THEN** the deal is `ending` until the filing's outcome is resolved under its operation key
