## MODIFIED Requirements

### Requirement: Reservation lifecycle
Capacity reservation MUST use a hold/commit/release lifecycle keyed by durable allocation identity, support expiry of uncommitted holds, and be idempotent for retries.

`reserve()` is idempotent by its required `placement_key` (see "Reserve replay is keyed by the deal's placement"), not by `deal_ref`'s `escrow_uid`: a caller retrying `reserve()` after a crash — before it durably recorded the first reservation's identity elsewhere — repeats the placement key and does not double-reserve capacity. `escrow_uid` remains bookkeeping recorded on the reservation, and a reserve whose escrow is held by another placement is refused.

#### Scenario: Two buyers reserve the same final unit
- **WHEN** concurrent requests race at one site
- **THEN** the authoritative ledger commits at most one reservation

#### Scenario: Reserve is retried for the same deal before its identity is durably recorded elsewhere
- **WHEN** `reserve()` is called again with the same `placement_key` while the first reservation is still in a held state
- **THEN** the existing reservation is returned and no additional capacity is admitted

#### Scenario: Reserve is retried after the prior hold expired
- **WHEN** `reserve()` is called again with the `placement_key` of a reservation that has since expired or been released
- **THEN** that reservation is returned in its current state and no new capacity is admitted; a new attempt names a new placement key and is admitted as if no prior attempt had occurred

### Requirement: Reserve replay is keyed by the deal's placement

Every reserve MUST carry `placement_key`, a required field of the reserve request beside `claim` and `deal_ref`, naming one placement: `<negotiation_id>:<placement>` for a deal's placements, and a key derived from the administrator's own request for an administrator reserve. A reserve without it MUST be refused as malformed with nothing written. An exact replay under a recorded key MUST return the recorded reservation in its current state, held, committed or released, and MUST NOT admit new capacity; a replay under the key that changes the claim, pool, site, offering mode or lease window MUST be refused with nothing written.

#### Scenario: A lost reserve acknowledgement is replayed

- **WHEN** a storefront repeats a reserve under `neg-4c1e:settlement` after the first answer was lost
- **THEN** the site returns the reservation the first call created, and admits nothing new

#### Scenario: A replay changes the request

- **WHEN** a reserve under a recorded placement key asks for a different lease window
- **THEN** the site refuses it and writes nothing

#### Scenario: A lapsed hold is replaced by another placement

- **WHEN** the reservation recorded under `neg-4c1e:hold` has expired and a reserve under `neg-4c1e:settlement` arrives
- **THEN** the site admits the settlement placement as a new reservation, and a replay under `neg-4c1e:hold` still returns the expired one

#### Scenario: A reserve names no placement

- **WHEN** a reserve request carries no `placement_key`
- **THEN** the site refuses it as malformed and admits nothing

### Requirement: Idempotent release recording
The site authority MUST record release exactly once for an allocation and advance capacity version only when the authoritative allocation transition commits. A release MUST name the `capacity_reservation_id` it releases; a release naming only an escrow MUST be refused as malformed with nothing released.

#### Scenario: Release command is repeated
- **WHEN** the compute lifecycle repeats a successful release command with the same allocation identity
- **THEN** the site authority returns the released state without duplicating capacity or event transitions

#### Scenario: A release names only an escrow
- **WHEN** a release request carries an escrow and no reservation identity
- **THEN** the site refuses it and releases nothing
