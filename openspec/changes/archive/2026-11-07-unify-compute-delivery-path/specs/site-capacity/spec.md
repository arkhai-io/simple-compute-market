## ADDED Requirements

### Requirement: Reserve replay is keyed by the deal's placement

A reserve MAY carry `deal_ref.placement_key`, naming the deal and the purpose of the placement as `<negotiation_id>:<placement>`. The site MUST treat it as an idempotency key beside `escrow_uid`: an exact replay under a recorded key MUST return the recorded reservation in its current state, held, committed or released, and MUST NOT admit new capacity; a replay under the key that changes the claim, pool, site, offering mode or lease window MUST be refused with nothing written. A reserve without the key MUST behave as before.

#### Scenario: A lost reserve acknowledgement is replayed

- **WHEN** a storefront repeats a reserve under `neg-4c1e:settlement` after the first answer was lost
- **THEN** the site returns the reservation the first call created, and admits nothing new

#### Scenario: A replay changes the request

- **WHEN** a reserve under a recorded placement key asks for a different lease window
- **THEN** the site refuses it and writes nothing

#### Scenario: A lapsed hold is replaced by another placement

- **WHEN** the reservation recorded under `neg-4c1e:hold` has expired and a reserve under `neg-4c1e:settlement` arrives
- **THEN** the site admits the settlement placement as a new reservation, and a replay under `neg-4c1e:hold` still returns the expired one
