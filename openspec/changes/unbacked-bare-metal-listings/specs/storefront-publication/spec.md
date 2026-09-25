## ADDED Requirements

### Requirement: Bare-metal publication derives unbacked listings

Bare-metal publication MUST derive a listing from a Physical Resource whose pool
advertises `bare_metal` and declares itself unbacked, bind it as unbacked, and publish
its backing as `unbacked`. It MUST use the same declaration reader, publication
runtime, and reconciliation rules as every other compute-family domain. An unbacked
bare-metal listing MUST never be reserved, held, scheduled, or fulfilled, and MUST
publish only settlement options bare metal does not fulfil through capacity.

#### Scenario: An unbacked pool advertises bare metal

- **WHEN** a pool advertising `bare_metal` declares itself unbacked
- **THEN** bare-metal publication derives a listing for each of its Physical Resources
  and publishes each with `capacity_backing: unbacked`

#### Scenario: An unbacked bare-metal listing is accepted

- **WHEN** a negotiation against an unbacked bare-metal listing is accepted
- **THEN** no capacity is reserved and the deal settles by introduction, revealing the
  contact of the listing's origin seller
