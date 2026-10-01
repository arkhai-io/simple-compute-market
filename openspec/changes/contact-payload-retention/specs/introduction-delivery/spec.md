## MODIFIED Requirements

### Requirement: Delivery fires once per reveal and re-delivery is explicit

Delivery MUST occur on the operation that first reveals an introduction. An
idempotent replay of that operation, or a subsequent read of the durable reveal,
MUST NOT deliver again. Each side MUST offer an explicit operator action that
re-delivers an already-revealed introduction.

An introduction whose contact payloads have been deleted MUST NOT be delivered: an
introduction start answered after deletion MUST NOT deliver, and an operator's
re-delivery request for such an introduction MUST be refused without contacting any
sink. Re-delivery reads the durable reveal rather than reconstructing one, so once the
payloads are gone there is nothing it may send.

#### Scenario: The reveal request is retried

- **WHEN** a buyer retries an introduction start and the retry is served as an exact
  replay
- **THEN** no additional delivery occurs on either side

#### Scenario: Operator re-delivers after a failed send

- **WHEN** an operator explicitly requests re-delivery of a revealed introduction
- **THEN** the configured sinks receive the same introduction again

#### Scenario: Operator re-delivers a deleted introduction

- **WHEN** an operator requests re-delivery of an introduction whose contact payloads
  have been deleted
- **THEN** the request is refused and no configured sink is contacted
